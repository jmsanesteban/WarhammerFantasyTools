"""
PDF processing service.

Architecture (per page):
  1. Extract text (digital) or OCR (scanned) → for sections and translation.
  2. Extract word-level positions → detect and parse the stat table by row alignment,
     bypassing the flat-text problem that loses table structure.
  3. Extract labeled sections (Skills, Talents, Trappings, Entries, Exits) from text.
  4. Translate to Spanish if needed.
  5. Emit one profession entry per page that looks like a career page
     (has stats AND at least one content section).
"""

import logging
import re
from collections import defaultdict

logger = logging.getLogger(__name__)

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False
    logger.warning("PyMuPDF not available – PDF text extraction disabled.")

try:
    from pdf2image import convert_from_bytes
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False
    logger.warning("pdf2image not available – OCR fallback disabled.")

try:
    import pytesseract
    from PIL import Image  # noqa: F401
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    logger.warning("pytesseract / Pillow not available – OCR disabled.")

from app.services.translation_service import (
    translate_to_spanish, needs_translation, force_translate_to_spanish
)

_MIN_TEXT_LENGTH = 50  # chars per page below which we assume it is a scan


# ---------------------------------------------------------------------------
# Stat table mappings
# ---------------------------------------------------------------------------

_PRIMARY_MAP = {
    'HA': 'ws',  'WS': 'ws',
    'HP': 'bs',  'BS': 'bs',
    'F':  's_char', 'S': 's_char',
    'R':  't_char', 'T': 't_char',
    'AG': 'ag',
    'I':  'int_char', 'INT': 'int_char',
    'V':  'wp',  'WP': 'wp',
    'EM': 'fel', 'FEL': 'fel',
}

_SECONDARY_MAP = {
    'A':   'attacks',
    'H':   'wounds',   'W':   'wounds',
    'BF':  'strength_bonus',  'SB':  'strength_bonus',
    'BR':  'toughness_bonus', 'TB':  'toughness_bonus',
    'M':   'movement',
    'MAG': 'magic',
    'PL':  'insanity_points', 'IP':  'insanity_points',
    'PD':  'fate_points',     'FP':  'fate_points',
}

_ALL_STAT_KEYS = frozenset(_PRIMARY_MAP) | frozenset(_SECONDARY_MAP)

_RE_VALUE   = re.compile(r'[+\-]?\s*\d+')
_RE_DASH    = re.compile(r'^[-—–]+$')

# ---------------------------------------------------------------------------
# Section regexes
# ---------------------------------------------------------------------------

# These patterns anchor at the start of a line (after _normalize_sections runs).
_RE_SECTION = {
    'skills':    re.compile(
        r'^(?:habilidades?|skills?)\s*:',
        re.IGNORECASE | re.MULTILINE),
    'talents':   re.compile(
        r'^(?:talentos?|talents?)\s*:',
        re.IGNORECASE | re.MULTILINE),
    'trappings': re.compile(
        r'^(?:enseres?|adornos?|accesorios?|equipo|trappings?)\s*:',
        re.IGNORECASE | re.MULTILINE),
    'entries':   re.compile(
        r'^(?:accesos?(?:\s+de\s+carrera)?|entradas?\s+de\s+carrera|entradas?|career\s+entr(?:y|ies))\s*:',
        re.IGNORECASE | re.MULTILINE),
    'exits':     re.compile(
        r'^(?:salidas?\s+(?:profesionales?|de\s+carrera)|salidas?|career\s+exits?)\s*:',
        re.IGNORECASE | re.MULTILINE),
}
_SECTION_ORDER = ['skills', 'talents', 'trappings', 'entries', 'exits']

# Marks where the career block ends and the narrative/adventure section begins.
# Everything after this point is description text, not career data.
_RE_NARRATIVE_START = re.compile(
    r'^(?:hechos?\s+poco\s+conocidos?|semillas?\s+de\s+aventura|'
    r'little\s+known\s+facts?|adventure\s+seeds?|trasfondo|background)\b',
    re.IGNORECASE | re.MULTILINE,
)

# Detects any section header appearing mid-line so we can insert \n before it.
_RE_SECTION_INLINE = re.compile(
    r'(?<!\n)'
    r'(\b(?:'
    r'habilidades?|talentos?|enseres?|adornos?|accesorios?|equipo|'
    r'accesos?(?:\s+de\s+carrera)?|entradas?\s+de\s+carrera|entradas?|'
    r'salidas?\s+(?:profesionales?|de\s+carrera)|salidas?|'
    r'career\s+(?:entr(?:y|ies)|exits?)|skills?|talents?|trappings?'
    r')\s*:)',
    re.IGNORECASE,
)

# Junk at the start of OCR-extracted name lines: page numbers, decorations
_RE_LEADING_JUNK = re.compile(r'^[\d.\s\-–—♦•★◆▶▸·]+')

# OCR often splits a capital letter from the rest of its word: "A Nimal" → "Animal"
_RE_SPLIT_LETTER = re.compile(r'\b([A-Z])\s+([A-Z][a-z]{2,})')

# ---------------------------------------------------------------------------
# Spanish scanned format — career title pattern:  — Nombre de la Profesión —
# Allows for OCR noise: dashes, em-dashes, 1-3 delimiters on each side.
# ---------------------------------------------------------------------------

_RE_SPANISH_TITLE = re.compile(
    r'[—\-]{1,3}\s+([A-ZÁÉÍÓÚÜÑ][^—\-\n]{3,50}?)\s+[—\-]{1,3}',
    re.MULTILINE,
)

# "Avanzada / Especial" badge in the scanned Spanish layout
_RE_SPANISH_ADVANCED = re.compile(
    r'\b(?:avan[cz]ada?|especial)\b', re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def process_pdf(file_bytes: bytes, progress_cb=None, format_hint: str = 'auto') -> dict:
    """
    Process a PDF binary.  Returns:
      {
        'pages':       [{'page': int, 'text': str, 'translated': bool}, ...],
        'professions': [profession_dict, ...],
        'errors':      [str, ...],
      }
    progress_cb(percent, stage) is called after each page when provided.

    format_hint:
      'auto'    — detect automatically (digital → English, scanned Spanish → Spanish)
      'english' — Career Compendium format (digital, 1 profession/page, English text)
      'spanish' — Scanned Spanish book (OCR, 1-2 professions/page, Spanish text)
    """
    result = {'pages': [], 'professions': [], 'errors': []}

    if not PYMUPDF_AVAILABLE:
        result['errors'].append("PyMuPDF no está disponible. Instala las dependencias correctamente.")
        return result

    try:
        doc = fitz.open(stream=file_bytes, filetype='pdf')
    except Exception as e:
        result['errors'].append(f"Error al abrir el PDF: {e}")
        return result

    # Detect format if not specified
    fmt = format_hint
    if fmt == 'auto':
        fmt = _detect_format(doc, file_bytes)

    logger.info("PDF format: %s", fmt)

    if fmt == 'spanish':
        return _process_pdf_spanish(doc, file_bytes, result, progress_cb)
    else:
        return _process_pdf_english(doc, file_bytes, result, progress_cb)


def _detect_format(doc, file_bytes: bytes) -> str:
    """
    Heuristic format detection.

    - Digital pages (much text) → English Career Compendium
    - Scanned pages with Spanish keywords → Spanish scanned book
    - Scanned pages with English/no-text detected → English (OCR path)
    """
    sample = min(5, len(doc))
    digital_count = 0
    spanish_signals = 0
    english_signals = 0

    for i in range(sample):
        text = doc[i].get_text("text").strip()
        if len(text) > 150:
            digital_count += 1
            tl = text.lower()
            if 'career entries' in tl or 'career exits' in tl or 'trappings' in tl:
                english_signals += 1
            if 'características' in tl or 'esquema de mejoras' in tl or 'accesos' in tl:
                spanish_signals += 1

    if digital_count >= sample * 0.5:
        # Mostly digital → English Career Compendium
        return 'spanish' if spanish_signals > english_signals else 'english'

    # Scanned — try OCR on first page to detect language
    if PDF2IMAGE_AVAILABLE and TESSERACT_AVAILABLE:
        try:
            text, _ = _ocr_page(file_bytes, 0)
            tl = text.lower()
            if 'características' in tl or 'habilidades' in tl or 'accesos' in tl:
                return 'spanish'
        except Exception:
            pass

    return 'english'  # safe default


def _process_pdf_english(doc, file_bytes: bytes, result: dict, progress_cb) -> dict:
    """Process an English digital PDF (Career Compendium format)."""
    total_pages = len(doc)

    for page_num in range(total_pages):
        page     = doc[page_num]
        raw_text = page.get_text("text").strip()
        is_scan  = len(raw_text) < _MIN_TEXT_LENGTH

        # ---- 1. Text + word-row extraction ----
        if is_scan:
            if progress_cb:
                progress_cb(
                    5 + int(page_num / total_pages * 75),
                    f'OCR página {page_num + 1} de {total_pages}…'
                )
            text, word_rows = _ocr_page(file_bytes, page_num)
            sep_y = None
        else:
            if progress_cb:
                progress_cb(
                    5 + int(page_num / total_pages * 75),
                    f'Extrayendo página {page_num + 1} de {total_pages}…'
                )
            # Detect visual separator line (horizontal rule between career data
            # and narrative section).  This is the most reliable way to know
            # where career data ends in digital PDFs.
            sep_y = _find_separator_y(page)
            if sep_y is not None:
                text      = _text_above_y(page, sep_y)
                word_rows = _digital_word_rows(page, y_cutoff=sep_y)
                logger.debug("Page %d: separator line at y=%.1f", page_num + 1, sep_y)
            else:
                text      = raw_text
                word_rows = _digital_word_rows(page)

        # ---- 2. Translation ----
        original_text = text  # always preserve pre-translation text
        if needs_translation(text):
            if progress_cb:
                progress_cb(
                    5 + int(page_num / total_pages * 75),
                    f'Traduciendo página {page_num + 1} de {total_pages}…'
                )
            text           = translate_to_spanish(text)
            was_translated = True
        else:
            was_translated = False

        result['pages'].append({
            'page':       page_num + 1,
            'text':       text,
            'translated': was_translated,
        })

        # ---- 3. Stat extraction (positional) ----
        stats = _extract_stats(word_rows)

        # ---- 4. Section extraction (text-based) ----
        sections = _parse_sections(text)
        if was_translated:
            # Also extract sections from the original English text so that
            # admin can match skill/talent names against DB name_en, bypassing
            # the Google-Translate ≠ official-Spanish-WFRP2 translation gap.
            en_sects = _parse_sections(original_text)
            sections['skills_raw_en']  = en_sects.get('skills_raw', '')
            sections['talents_raw_en'] = en_sects.get('talents_raw', '')

        # ---- 5. Emit profession entry if this is a career page ----
        if _is_career_page(stats, sections):
            prof_type = (
                'advanced'
                if re.search(r'\bavan[cz]ad[ao]\b|\badvanced\b', text, re.IGNORECASE)
                else 'basic'
            )
            raw_name = _fix_ocr_name(_extract_name(page, text, is_scan))
            if was_translated and raw_name:
                # Page was in English: store English original + translate for Spanish
                name_en = raw_name
                name_es = force_translate_to_spanish(raw_name) or raw_name
            else:
                name_es = raw_name
                name_en = ''

            result['professions'].append({
                'name':        name_es,
                'name_en':     name_en,
                'type':        prof_type,
                'description': '',
                **_empty_stats(),
                **stats,
                **sections,
            })

        if progress_cb:
            progress_cb(
                5 + int((page_num + 1) / total_pages * 75),
                f'Procesada página {page_num + 1} de {total_pages}'
            )

    doc.close()
    return result


# ---------------------------------------------------------------------------
# Spanish scanned format (Sistema 2)
# ---------------------------------------------------------------------------

def _process_pdf_spanish(doc, file_bytes: bytes, result: dict, progress_cb) -> dict:
    """
    Process a Spanish scanned PDF.

    Layout: 1-2 professions per page inside red-bordered boxes.
    Each career block starts with '— Nombre —' and ends before the next title.
    Stat table uses Spanish abbreviations (HA HP F R Ag I V Em / A H BF BR M Mag PL PD).
    No translation is needed — the text is already in Spanish.
    """
    total_pages = len(doc)

    for page_num in range(total_pages):
        if progress_cb:
            progress_cb(
                5 + int(page_num / total_pages * 85),
                f'OCR página {page_num + 1} de {total_pages}…'
            )

        # OCR the page
        text, word_rows = _ocr_page(file_bytes, page_num)
        if not text.strip():
            continue

        result['pages'].append({
            'page':       page_num + 1,
            'text':       text,
            'translated': False,
        })

        # Split text into 1 or 2 career blocks based on '— Name —' titles
        blocks = _split_spanish_page(text)
        if not blocks:
            continue

        # For 2 blocks, split word_rows spatially by finding the y-split point
        if len(blocks) == 2:
            split_name = _extract_spanish_career_name(blocks[1])
            split_idx = _find_title_in_rows(word_rows, split_name) if split_name else None
            if split_idx is None:
                split_idx = len(word_rows) // 2
            rows_per_block = [word_rows[:split_idx], word_rows[split_idx:]]
        else:
            rows_per_block = [word_rows]

        for block_text, block_rows in zip(blocks, rows_per_block):
            name = _extract_spanish_career_name(block_text)
            if not name:
                continue

            sections = _parse_sections(block_text)
            stats    = _extract_stats(block_rows)

            if not _is_career_page(stats, sections):
                continue

            prof_type = 'advanced' if _RE_SPANISH_ADVANCED.search(block_text) else 'basic'

            result['professions'].append({
                'name':        name,
                'name_en':     '',
                'type':        prof_type,
                'description': '',
                **_empty_stats(),
                **stats,
                **sections,
                'skills_raw_en':  '',
                'talents_raw_en': '',
            })

    doc.close()
    return result


def _split_spanish_page(text: str) -> list:
    """
    Find 1-2 career blocks in a Spanish scanned page.
    Each block starts at a '— Name —' title pattern.
    Returns a list with 0, 1, or 2 text strings.
    """
    matches = list(_RE_SPANISH_TITLE.finditer(text))
    if not matches:
        return []
    if len(matches) == 1:
        # Single profession — start from the title
        return [text[matches[0].start():].strip()]
    # Two (or more) — take first two blocks
    return [
        text[matches[0].start(): matches[1].start()].strip(),
        text[matches[1].start():].strip(),
    ]


def _extract_spanish_career_name(block: str) -> str:
    """Return the career name from the first '— Name —' in block, title-cased."""
    m = _RE_SPANISH_TITLE.search(block)
    if not m:
        return ''
    raw = m.group(1).strip()
    # Remove any OCR artefacts that survived the regex
    raw = re.sub(r'[—\-]+', '', raw).strip()
    return raw.title() if raw else ''


def _find_title_in_rows(word_rows: list, title: str) -> int | None:
    """
    Estimate the word_rows index where the given career title starts.
    Uses the first word of the title as a search key (case-insensitive).
    Returns the row index, or None if not found.
    """
    if not title:
        return None
    first_word = title.split()[0].lower()
    for i, row in enumerate(word_rows):
        for w in row:
            if w.lower().startswith(first_word[:4]):  # partial match for OCR noise
                return i
    return None


# ---------------------------------------------------------------------------
# Text / OCR extraction
# ---------------------------------------------------------------------------

def _ocr_page(file_bytes: bytes, page_index: int):
    """Return (text, sorted_word_rows) via a single Tesseract call."""
    if not PDF2IMAGE_AVAILABLE or not TESSERACT_AVAILABLE:
        return '', []
    try:
        images = convert_from_bytes(
            file_bytes, first_page=page_index + 1, last_page=page_index + 1, dpi=300
        )
        if not images:
            return '', []

        from pytesseract import Output
        data = pytesseract.image_to_data(
            images[0], lang='spa+eng', output_type=Output.DICT
        )

        rows_dict  = defaultdict(list)
        text_lines = defaultdict(list)

        for i in range(len(data['text'])):
            word = data['text'][i].strip()
            conf_raw = str(data['conf'][i])
            conf = int(conf_raw) if conf_raw.lstrip('-').isdigit() else -1
            if not word or conf < 20:
                continue
            line_key = (data['block_num'][i], data['par_num'][i], data['line_num'][i])
            text_lines[line_key].append(word)
            y_center = data['top'][i] + data['height'][i] // 2
            rows_dict[round(y_center / 15) * 15].append((data['left'][i], word))

        text = '\n'.join(' '.join(text_lines[k]) for k in sorted(text_lines))
        sorted_rows = [
            [w for _, w in sorted(rows_dict[k])]
            for k in sorted(rows_dict)
        ]
        return text, sorted_rows

    except Exception as e:
        logger.warning("OCR failed on page %d: %s", page_index + 1, e)
        return '', []


def _digital_word_rows(page, y_cutoff: float = None) -> list:
    """Extract word positions from a digital PDF page using PyMuPDF.

    y_cutoff: if provided, ignore all words whose top edge is at or below
              this y-coordinate (i.e. below the visual separator line).
    """
    try:
        words = page.get_text("words")
        # words: (x0, y0, x1, y1, word, block, line, word_idx)
        rows_dict = defaultdict(list)
        for w in words:
            x0, y0, x1, y1, word = w[:5]
            if y_cutoff is not None and y0 >= y_cutoff:
                continue
            word = word.strip()
            if not word:
                continue
            y_center = (y0 + y1) / 2
            rows_dict[round(y_center / 8) * 8].append((x0, word))
        return [
            [w for _, w in sorted(rows_dict[k])]
            for k in sorted(rows_dict)
        ]
    except Exception as e:
        logger.warning("Word extraction failed: %s", e)
        return []


def _find_separator_y(page) -> float | None:
    """
    Detect the y-coordinate of a horizontal separator line (vector graphic)
    that marks the boundary between career data and narrative text.

    Looks for drawing elements that are:
      - wide  (≥ 40 % of page width)
      - thin  (≤ 6 px tall)
      - below the stat-table area (> 25 % of page height)

    Returns the topmost matching y, or None when no clear separator is found.
    """
    pw = page.rect.width
    ph = page.rect.height
    min_w = pw * 0.40
    candidates = []
    try:
        for d in page.get_drawings():
            r = d.get('rect')
            if r is None:
                continue
            if r.width >= min_w and r.height <= 6 and r.y0 > ph * 0.25:
                candidates.append(float(r.y0))
    except Exception as e:
        logger.debug("Drawing extraction failed: %s", e)
    return min(candidates) if candidates else None


def _text_above_y(page, y_cutoff: float) -> str:
    """Return page text, skipping any content whose top edge is at or below y_cutoff."""
    lines_out = []
    try:
        for block in page.get_text("dict").get('blocks', []):
            if block.get('type') != 0:
                continue
            for line in block.get('lines', []):
                if line['bbox'][1] >= y_cutoff:
                    continue
                text = ' '.join(s.get('text', '') for s in line.get('spans', []))
                if text.strip():
                    lines_out.append(text)
    except Exception as e:
        logger.warning("Text-above-y extraction failed: %s", e)
        return page.get_text("text").strip()
    return '\n'.join(lines_out)


# ---------------------------------------------------------------------------
# Stat extraction (positional)
# ---------------------------------------------------------------------------

def _parse_value(token: str):
    """Parse '+25%', '—', '-', '+6' → int or None."""
    token = token.strip()
    if _RE_DASH.match(token) or token == '':
        return None
    m = _RE_VALUE.search(token)
    return int(m.group().replace(' ', '')) if m else None


def _parse_row_pair(header_row: list, value_row: list, mapping: dict) -> dict:
    """Map header[i] → field, value[i] → int, using direct index alignment."""
    result = {}
    for i, header in enumerate(header_row):
        field = mapping.get(header.upper())
        if field and i < len(value_row):
            result[field] = _parse_value(value_row[i])
    return result


def _extract_stats(sorted_rows: list) -> dict:
    """
    Scan word rows for a stat header line (≥3 known abbreviations that make up
    ≥60% of the line's words) then read values from the very next row.
    Works identically for digital-PDF and OCR word rows.
    """
    primary_result   = {}
    secondary_result = {}

    for i, row in enumerate(sorted_rows):
        if i + 1 >= len(sorted_rows) or not row:
            continue

        upper = [w.upper() for w in row]
        n     = len(upper)
        stat_frac    = sum(1 for w in upper if w in _ALL_STAT_KEYS) / n
        primary_hits = sum(1 for w in upper if w in _PRIMARY_MAP)
        sec_hits     = sum(1 for w in upper if w in _SECONDARY_MAP)

        next_row = sorted_rows[i + 1]

        if primary_hits >= 3 and stat_frac >= 0.6 and not primary_result:
            parsed = _parse_row_pair(row, next_row, _PRIMARY_MAP)
            if any(v is not None for v in parsed.values()):
                primary_result = parsed

        if sec_hits >= 3 and stat_frac >= 0.6 and not secondary_result:
            parsed = _parse_row_pair(row, next_row, _SECONDARY_MAP)
            if any(v is not None for v in parsed.values()):
                secondary_result = parsed

    return {**primary_result, **secondary_result}


def _empty_stats() -> dict:
    return {
        'ws': None, 'bs': None, 's_char': None, 't_char': None,
        'ag': None, 'int_char': None, 'wp': None, 'fel': None,
        'attacks': None, 'wounds': None, 'strength_bonus': None,
        'toughness_bonus': None, 'movement': None, 'magic': None,
        'insanity_points': None, 'fate_points': None,
    }


# ---------------------------------------------------------------------------
# Section extraction (text-based — already works well)
# ---------------------------------------------------------------------------

def _normalize_sections(text: str) -> str:
    """Ensure every section header starts on its own line.

    fitz sometimes runs 'Talentos: A, B Adornos: C, D' on one line without
    a newline between sections.  This pre-processing step inserts \\n before
    any mid-line section header so the '^' anchors in _RE_SECTION work.
    """
    return _RE_SECTION_INLINE.sub(r'\n\1', text)


def _parse_sections(text: str) -> dict:
    """Extract Skills, Talents, Trappings, Entries, Exits from page text."""
    text = _normalize_sections(text)
    # Drop everything from the narrative/adventure section onwards —
    # "Hechos poco conocidos", "Semillas de aventura", etc. are not career data.
    m_narr = _RE_NARRATIVE_START.search(text)
    if m_narr:
        text = text[:m_narr.start()]
    sections = {k + '_raw': '' for k in _SECTION_ORDER}
    for idx, key in enumerate(_SECTION_ORDER):
        m = _RE_SECTION[key].search(text)
        if not m:
            continue
        end = len(text)
        for later in _SECTION_ORDER[idx + 1:]:
            nm = _RE_SECTION[later].search(text, m.end())
            if nm and nm.start() < end:
                end = nm.start()
        raw = text[m.end():end].strip().strip(':').strip()
        if key in ('skills', 'talents'):
            # Filter tokens that are description sentences rather than names.
            raw = _filter_items(raw)
        elif key in ('entries', 'exits'):
            # Career entries/exits are short profession names separated by commas.
            # Truncate at the first sentence-like token (contains a period or > 80 chars).
            raw = _filter_career_list(raw)
        sections[key + '_raw'] = raw

    # OCR/translation sometimes garbles the "Enseres/Trappings" header badly
    # enough that _RE_SECTION['trappings'] never matches - since Trappings
    # immediately follows Talents in _SECTION_ORDER, its whole text then gets
    # swallowed into talents_raw instead of being dropped as its own section.
    # Recover it by detecting where equipment-looking items start and moving
    # everything from that point onward into trappings_raw.
    sections['talents_raw'], stray = _split_stray_trappings(sections['talents_raw'])
    if stray:
        sections['trappings_raw'] = ', '.join(
            ([sections['trappings_raw']] if sections['trappings_raw'] else []) + stray
        )

    return sections


# Equipment-ish first words that flag a comma item as a stray trapping rather
# than a talent name. Talent names never start with a bare quantity, and
# essentially never lead with these nouns.
_RE_TRAPPING_QTY = re.compile(r'^\d+\s+\S')
_TRAPPING_KEYWORDS = frozenset({
    'red', 'cuerda', 'cuerdas', 'veneno', 'venenos', 'gancho', 'ganchos',
    'antorcha', 'antorchas', 'mochila', 'saco', 'sacos', 'ballesta', 'ballestas',
    'munición', 'municion', 'municiones', 'daga', 'dagas', 'cuchillo', 'cuchillos',
    'capa', 'capas', 'herramientas', 'linterna', 'brújula', 'brujula', 'mapa', 'mapas',
})


def _looks_like_trapping(item: str) -> bool:
    if _RE_TRAPPING_QTY.match(item):
        return True
    first_word = re.split(r'\s+', item.strip().lower())[0].strip(':') if item.strip() else ''
    return first_word in _TRAPPING_KEYWORDS


def _split_stray_trappings(raw: str) -> tuple:
    """Return (remaining_raw, moved_items). Once one item looks like
    equipment, everything from there onward is treated as leaked trappings
    text — a boundary miss doesn't self-correct partway through a list."""
    items = [p.strip() for p in raw.split(',') if p.strip()]
    for i, item in enumerate(items):
        if _looks_like_trapping(item):
            return ', '.join(items[:i]), items[i:]
    return raw, []


def _filter_items(raw: str) -> str:
    """Remove description-sentence tokens from a comma-separated skill/talent list.

    A token is treated as a name if it is ≤80 chars and contains no period.
    """
    clean = []
    for part in raw.split(','):
        item = part.strip()
        if item and len(item) <= 80 and '.' not in item:
            clean.append(item)
    return ', '.join(clean)


def _filter_career_list(raw: str) -> str:
    """Extract profession names from an entries/exits raw string.

    Profession names are short (≤60 chars, no period).  Any token exceeding
    these bounds is assumed to be description text and terminates the list.
    Splits on both commas and newlines so that e.g. "Scholar\\nLittle Known"
    correctly yields only "Scholar".
    """
    clean = []
    for part in re.split(r'[,\n]+', raw):
        item = part.strip()
        if not item:
            continue
        if len(item) > 60 or '.' in item:
            break
        clean.append(item)
    return ', '.join(clean)


# ---------------------------------------------------------------------------
# Career page detection & name extraction
# ---------------------------------------------------------------------------

def _is_career_page(stats: dict, sections: dict) -> bool:
    """
    Only emit a profession entry when the page has BOTH positional stats AND
    at least one meaningful content section.  This prevents career-summary
    tables (stats but no sections) and lore pages (sections but no stats)
    from generating false entries.
    """
    has_stats = any(v is not None for v in stats.values())
    has_sections = (
        len(sections.get('skills_raw', '').strip()) > 10
        or len(sections.get('talents_raw', '').strip()) > 10
        or len(sections.get('trappings_raw', '').strip()) > 5
    )
    return has_stats and has_sections


def _fix_ocr_name(name: str) -> str:
    """
    Repair OCR-split capital letters: 'A Nimal T Rainer' → 'Animal Trainer'.
    Applied iteratively until stable, then collapses extra spaces.
    """
    prev = None
    while prev != name:
        prev = name
        name = _RE_SPLIT_LETTER.sub(
            lambda m: m.group(1) + m.group(2)[0].lower() + m.group(2)[1:],
            name,
        )
    return re.sub(r'\s{2,}', ' ', name).strip()


def _extract_name(page, text: str, is_scan: bool) -> str:
    """
    For digital PDFs: return the text of the span with the largest font size.
    Fallback for all pages: first ALL-CAPS line with ≥3 real letters.
    """
    if not is_scan:
        try:
            page_dict = page.get_text("dict")
            max_size  = 0
            candidate = ''
            for block in page_dict.get('blocks', []):
                if block.get('type') != 0:
                    continue
                for line in block.get('lines', []):
                    for span in line.get('spans', []):
                        size      = span.get('size', 0)
                        span_text = span.get('text', '').strip()
                        if size > max_size and sum(1 for c in span_text if c.isalpha()) >= 2:
                            max_size  = size
                            candidate = ' '.join(
                                s.get('text', '') for s in line.get('spans', [])
                            ).strip()
            if candidate and sum(1 for c in candidate if c.isalpha()) >= 2:
                return candidate.title()
        except Exception:
            pass

    # Fallback: first ALL-CAPS line of reasonable length
    for line in text.split('\n'):
        cleaned = _RE_LEADING_JUNK.sub('', line.strip()).strip()
        if (cleaned
                and cleaned == cleaned.upper()
                and sum(1 for c in cleaned if c.isalpha()) >= 3
                and len(cleaned.split()) <= 6):
            return cleaned.title()

    return ''


# ---------------------------------------------------------------------------
# Kept for backwards compatibility (no longer called by process_pdf)
# ---------------------------------------------------------------------------

def parse_professions(text: str) -> list:
    return []

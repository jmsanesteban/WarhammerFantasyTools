"""
PDF processing service.

Pipeline:
  1. Try to extract embedded text with PyMuPDF.
  2. If a page looks like a scan (text below threshold), convert to image and run Tesseract OCR.
  3. Detect language; translate to Spanish if needed.
  4. Parse each page's text with a heuristic state-machine to extract profession data.
  5. Return a list of raw parsed-profession dicts ready for admin review.
"""

import io
import logging
import os
import re
import tempfile

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
    from PIL import Image
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    logger.warning("pytesseract / Pillow not available – OCR disabled.")

from app.services.translation_service import translate_to_spanish, needs_translation

_MIN_TEXT_LENGTH = 50  # characters per page below which we assume it's a scan


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def process_pdf(file_bytes: bytes) -> dict:
    """
    Process a PDF binary and return:
      {
        'pages': [{'page': int, 'text': str, 'translated': bool}, ...],
        'professions': [parsed_profession_dict, ...],
        'errors': [str, ...],
      }
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

    full_text_parts = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text").strip()

        if len(text) < _MIN_TEXT_LENGTH:
            # Scanned page – try OCR
            text = _ocr_page(file_bytes, page_num)

        if needs_translation(text):
            translated = translate_to_spanish(text)
            was_translated = True
        else:
            translated = text
            was_translated = False

        result['pages'].append({
            'page': page_num + 1,
            'text': translated,
            'translated': was_translated,
        })
        full_text_parts.append(translated)

    full_text = '\n\n--- PÁGINA ---\n\n'.join(full_text_parts)
    result['professions'] = parse_professions(full_text)

    doc.close()
    return result


def _ocr_page(file_bytes: bytes, page_index: int) -> str:
    """Convert a single PDF page to image and run Tesseract."""
    if not PDF2IMAGE_AVAILABLE or not TESSERACT_AVAILABLE:
        return ''
    try:
        images = convert_from_bytes(file_bytes, first_page=page_index + 1, last_page=page_index + 1, dpi=300)
        if not images:
            return ''
        text = pytesseract.image_to_string(images[0], lang='spa+eng')
        return text.strip()
    except Exception as e:
        logger.warning(f"OCR failed on page {page_index + 1}: {e}")
        return ''


# ---------------------------------------------------------------------------
# Heuristic profession parser
# ---------------------------------------------------------------------------

_RE_SECTION = {
    'main_profile': re.compile(
        r'(perfil\s+principal|main\s+profile|características\s+primarias)',
        re.IGNORECASE
    ),
    'secondary_profile': re.compile(
        r'(perfil\s+secundario|secondary\s+profile|características\s+secundarias)',
        re.IGNORECASE
    ),
    'skills': re.compile(r'^(habilidades?|skills?)\s*:', re.IGNORECASE | re.MULTILINE),
    'talents': re.compile(r'^(talentos?|talents?)\s*:', re.IGNORECASE | re.MULTILINE),
    'trappings': re.compile(r'^(enseres?|trappings?)\s*:', re.IGNORECASE | re.MULTILINE),
    'entries': re.compile(r'^(accesos?|entradas?|career\s+entr(?:y|ies))\s*:', re.IGNORECASE | re.MULTILINE),
    'exits': re.compile(r'^(salidas?|career\s+exits?)\s*:', re.IGNORECASE | re.MULTILINE),
}

# Primary characteristic headers in Spanish abbreviations and common OCR variants
_PRIMARY_HEADERS = ('HA', 'HP', 'F', 'R', 'Ag', 'I', 'V', 'Em',
                    'WS', 'BS', 'S', 'T', 'Int', 'WP', 'Fel')

_SECONDARY_HEADERS = ('A', 'H', 'BF', 'BR', 'M', 'Mag', 'PL', 'PD',
                       'W', 'SB', 'TB', 'IP', 'FP')

# Map Spanish/English abbreviations → internal field names
_PRIMARY_MAP = {
    'HA': 'ws', 'WS': 'ws',
    'HP': 'bs', 'BS': 'bs',
    'F': 's_char', 'S': 's_char',
    'R': 't_char', 'T': 't_char',
    'AG': 'ag',
    'I': 'int_char', 'INT': 'int_char',
    'V': 'wp', 'WP': 'wp',
    'EM': 'fel', 'FEL': 'fel',
}

_SECONDARY_MAP = {
    'A': 'attacks',
    'H': 'wounds', 'W': 'wounds',
    'BF': 'strength_bonus', 'SB': 'strength_bonus',
    'BR': 'toughness_bonus', 'TB': 'toughness_bonus',
    'M': 'movement',
    'MAG': 'magic',
    'PL': 'insanity_points', 'IP': 'insanity_points',
    'PD': 'fate_points', 'FP': 'fate_points',
}

_RE_VALUE = re.compile(r'[+\-]?\s*\d+')
_RE_DASH = re.compile(r'^[-—–]+$')


def _parse_value(token: str):
    """Parse a characteristic value token like '+5', '—', '-', '+10'."""
    token = token.strip()
    if _RE_DASH.match(token) or token == '':
        return None
    m = _RE_VALUE.search(token)
    if m:
        return int(m.group().replace(' ', ''))
    return None


def _extract_section_text(text: str, start_pattern, end_patterns) -> str:
    """Extract text between start_pattern and the first match of any end_pattern."""
    m_start = start_pattern.search(text)
    if not m_start:
        return ''
    start = m_start.end()
    end = len(text)
    for ep in end_patterns:
        m_end = ep.search(text, start)
        if m_end and m_end.start() < end:
            end = m_end.start()
    return text[start:end].strip()


def _parse_characteristic_table(header_line: str, value_line: str, mapping: dict) -> dict:
    """Parse two-line table: headers | values → {field: int_or_None}"""
    headers = [h.strip().upper() for h in re.split(r'\s+', header_line.strip()) if h.strip()]
    values_raw = re.split(r'\s+', value_line.strip())
    result = {}
    for i, header in enumerate(headers):
        field = mapping.get(header)
        if field and i < len(values_raw):
            result[field] = _parse_value(values_raw[i])
    return result


def _parse_list_section(text: str) -> list:
    """Split a comma/semicolon-separated list, preserving 'A o B' groups."""
    items = re.split(r'[,;]', text)
    return [item.strip() for item in items if item.strip()]


def parse_professions(text: str) -> list:
    """
    Very best-effort parser for WFRP2-style profession pages.
    Returns a list of dicts, each representing one profession found in the text.
    Fields may be None/empty when not detected.
    """
    professions = []

    # Split by possible profession delimiters (page breaks, ALL-CAPS lines)
    blocks = _split_into_blocks(text)

    for block in blocks:
        prof = _parse_block(block)
        if prof and prof.get('name'):
            professions.append(prof)

    return professions


def _split_into_blocks(text: str) -> list:
    """Split text into potential per-profession blocks."""
    # Strategy: split on lines that are entirely UPPERCASE (potential profession names)
    lines = text.split('\n')
    blocks = []
    current = []
    for line in lines:
        stripped = line.strip()
        if (stripped
                and stripped == stripped.upper()
                and len(stripped) > 3
                and not any(h in stripped.split() for h in _PRIMARY_HEADERS + _SECONDARY_HEADERS)
                and not stripped.startswith('---')):
            if current:
                blocks.append('\n'.join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append('\n'.join(current))
    return [b for b in blocks if b.strip()]


def _parse_block(block: str) -> dict:
    """Parse a single text block as one profession."""
    lines = [l.rstrip() for l in block.split('\n')]
    if not lines:
        return {}

    prof = {
        'name': '',
        'name_en': '',
        'type': 'basic',
        'description': '',
        'ws': None, 'bs': None, 's_char': None, 't_char': None,
        'ag': None, 'int_char': None, 'wp': None, 'fel': None,
        'attacks': None, 'wounds': None, 'strength_bonus': None,
        'toughness_bonus': None, 'movement': None, 'magic': None,
        'insanity_points': None, 'fate_points': None,
        'skills_raw': '',
        'talents_raw': '',
        'trappings_raw': '',
        'entries_raw': '',
        'exits_raw': '',
    }

    # First non-empty line is the profession name
    for line in lines:
        if line.strip():
            prof['name'] = line.strip().title()
            break

    text = block

    # Determine basic/advanced
    if re.search(r'\bavan[cz]ad[ao]\b|\badvanced\b', text, re.IGNORECASE):
        prof['type'] = 'advanced'

    # Find main profile
    m_main = _RE_SECTION['main_profile'].search(text)
    m_secondary = _RE_SECTION['secondary_profile'].search(text)
    m_skills = _RE_SECTION['skills'].search(text)

    if m_main:
        # Next two non-empty lines after the header: headers row + values row
        segment = text[m_main.end():]
        non_empty = [l.strip() for l in segment.split('\n') if l.strip()][:2]
        if len(non_empty) == 2:
            parsed = _parse_characteristic_table(non_empty[0], non_empty[1], _PRIMARY_MAP)
            prof.update(parsed)

    if m_secondary:
        segment = text[m_secondary.end():]
        non_empty = [l.strip() for l in segment.split('\n') if l.strip()][:2]
        if len(non_empty) == 2:
            parsed = _parse_characteristic_table(non_empty[0], non_empty[1], _SECONDARY_MAP)
            prof.update(parsed)

    # Skills
    m = _RE_SECTION['skills'].search(text)
    if m:
        end = len(text)
        for key in ('talents', 'trappings', 'entries', 'exits'):
            nm = _RE_SECTION[key].search(text, m.end())
            if nm and nm.start() < end:
                end = nm.start()
        prof['skills_raw'] = text[m.end():end].strip().strip(':').strip()

    # Talents
    m = _RE_SECTION['talents'].search(text)
    if m:
        end = len(text)
        for key in ('trappings', 'entries', 'exits'):
            nm = _RE_SECTION[key].search(text, m.end())
            if nm and nm.start() < end:
                end = nm.start()
        prof['talents_raw'] = text[m.end():end].strip().strip(':').strip()

    # Trappings
    m = _RE_SECTION['trappings'].search(text)
    if m:
        end = len(text)
        for key in ('entries', 'exits'):
            nm = _RE_SECTION[key].search(text, m.end())
            if nm and nm.start() < end:
                end = nm.start()
        prof['trappings_raw'] = text[m.end():end].strip().strip(':').strip()

    # Entries
    m = _RE_SECTION['entries'].search(text)
    if m:
        end = len(text)
        nm = _RE_SECTION['exits'].search(text, m.end())
        if nm:
            end = nm.start()
        prof['entries_raw'] = text[m.end():end].strip().strip(':').strip()

    # Exits
    m = _RE_SECTION['exits'].search(text)
    if m:
        prof['exits_raw'] = text[m.end():].strip().strip(':').strip()

    return prof

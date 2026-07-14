"""Admin tooling for the recetas catalog: parsing "Recetas hechas"-style PDFs
(one block per recipe, stats + an embedded photo, matching the book's own
companion document) and syncing recipe photos an admin drops by hand into
uploads/imagenes_comidas/ (filename = recipe nombre).

Uses PyMuPDF (`fitz`) - already a dependency (see pdf_processor.py) - for
both text and image extraction. No OCR/translation: this document's text is
already born-digital and clean, unlike the scanned profession PDFs."""
import os
import re
import unicodedata

import fitz
from flask import current_app
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models.food import CookingMethod, Ingredient, Recipe

_ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
_IMAGENES_COMIDAS_DIR = 'imagenes_comidas'

# One recipe block always starts with an ALL-CAPS name line, then "Vigor : N"
# and "Moral : M" each on their own line (see uploads/Recetas hechas.pdf).
_BLOCK_RE = re.compile(
    r'^(?P<nombre>[A-ZÁÉÍÓÚÑ0-9][A-ZÁÉÍÓÚÑ0-9 /()\-]*?)\s*\n'
    r'Vigor\s*:\s*(?P<vigor>-?\d+)\s*\n'
    r'Moral\s*:\s*(?P<moral>-?\d+)',
    re.MULTILINE,
)
_METODO_RE = re.compile(r'M[eé]todo de cocina/recalentar\s*:\s*(?P<metodo>.+?)\s*/\s*(?P<recalentar>SI|NO)')
_DURACION_DIAS_RE = re.compile(r'Duraci[oó]n\s*:\s*(?P<n>\d+)\s*d[ií]as')
_DURACION_ANOS_RE = re.compile(r'Duraci[oó]n\s*:\s*(?P<n>\d+)\s*a[ñn]os')
_CALIDAD_RE = re.compile(r'Calidad\s*:\s*(?P<calidad>[A-ZÁÉÍÓÚÑ]+)\s*\(\s*(?P<complejidad>\d+)\s*\)')
_INGREDIENTE_RE = {i: re.compile(rf'Ingrediente {i}:\s*(?P<v>[^\n]+)') for i in (1, 2, 3, 4)}
_CONDIMENTO_RE = {i: re.compile(rf'Condimento {i}:\s*(?P<v>[^\n]+)') for i in (1, 2)}
_COSTE_RE = re.compile(
    r'Coste\s*Taberna\s*\nCoste\s*Ingredientes\s*\n\s*(?P<taberna>\d+)\s*p\s*\n(?:\s*\n)?\s*(?P<ingredientes>\d+)\s*p'
)
_NOTAS_ESPECIAL_RE = re.compile(r'Calidad\s*:\s*\*\s*\n(?P<notas>.*?)\nCoste\s*Taberna', re.DOTALL)


def _normalize(text):
    """Accent/case-insensitive comparison key - the source PDF has real
    inconsistencies (e.g. "Almibar" for the book's own "Almíbar"), not just
    terminal-display noise, so exact string matching against the catalog
    would silently fail to link the method/ingredient."""
    stripped = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    return stripped.strip().lower()


def _normalize_filename(text):
    """Like _normalize(), but also drops standalone "de" connectors - some
    photo filenames skip them ("Menestra verduras invernales.jpg" for the
    recipe "Menestra de verduras invernales", "Ración cecina.jpg" for
    "Ración de cecina") even though the recipe's own nombre keeps them."""
    words = [w for w in _normalize(text).split() if w != 'de']
    return ' '.join(words)


def parse_recetas_pdf(file_bytes):
    """Returns a list of dicts, one per recipe block found in the PDF, each
    with every Recipe field needed to create the row plus `image_bytes`/
    `image_ext` (or None) and `existe_ya` (bool, matched by exact nombre).

    The Nth embedded image on a page is paired with the Nth recipe block on
    that same page (assumes PyMuPDF's image order matches the page's visual
    top-to-bottom reading order) - never verified beyond eyeballing it, which
    is exactly why the caller must show this to an admin for visual
    confirmation before saving anything, not commit it blind."""
    doc = fitz.open(stream=file_bytes, filetype='pdf')
    try:
        existing_names = {r.nombre for r in Recipe.query.all()}
        methods_by_norm = {_normalize(m.nombre): m for m in CookingMethod.query.all()}
        ingredients_by_norm = {_normalize(i.nombre): i for i in Ingredient.query.all()}

        results = []
        for page in doc:
            text = page.get_text()
            blocks = list(_BLOCK_RE.finditer(text))
            images = page.get_images(full=True)

            for idx, match in enumerate(blocks):
                start = match.start()
                end = blocks[idx + 1].start() if idx + 1 < len(blocks) else len(text)
                block_text = text[start:end]

                nombre = ' '.join(match.group('nombre').split())
                vigor = int(match.group('vigor'))
                moral_match = re.match(r'-?\d+', match.group('moral'))
                moral = int(moral_match.group()) if moral_match else int(match.group('moral'))

                metodo_match = _METODO_RE.search(block_text)
                metodo_raw = metodo_match.group('metodo').strip() if metodo_match else None
                recalentar = bool(metodo_match) and metodo_match.group('recalentar') == 'SI'
                metodo = None
                if metodo_raw and metodo_raw != '*':
                    metodo = methods_by_norm.get(_normalize(metodo_raw))

                dias_match = _DURACION_DIAS_RE.search(block_text)
                if dias_match:
                    duracion_dias = int(dias_match.group('n'))
                else:
                    anos_match = _DURACION_ANOS_RE.search(block_text)
                    duracion_dias = int(anos_match.group('n')) * Recipe.DIAS_POR_ANO if anos_match else None

                calidad_match = _CALIDAD_RE.search(block_text)
                calidad = calidad_match.group('calidad').capitalize() if calidad_match else None
                complejidad = int(calidad_match.group('complejidad')) if calidad_match else None
                solo_compra = calidad_match is None

                def _resolve_ingrediente(pattern_map, n):
                    m = pattern_map[n].search(block_text)
                    if not m:
                        return None
                    value = m.group('v').strip()
                    if not value or value == 'Nada':
                        return None
                    return ingredients_by_norm.get(_normalize(value))

                ingredientes = [_resolve_ingrediente(_INGREDIENTE_RE, i) for i in (1, 2, 3, 4)]
                condimentos = [_resolve_ingrediente(_CONDIMENTO_RE, i) for i in (1, 2)]

                coste_match = _COSTE_RE.search(block_text)
                precio_compra_peniques = int(coste_match.group('taberna')) if coste_match else None
                coste_creacion_peniques = int(coste_match.group('ingredientes')) if coste_match else None

                notas = None
                if solo_compra:
                    notas_match = _NOTAS_ESPECIAL_RE.search(block_text)
                    if notas_match:
                        notas = ' '.join(notas_match.group('notas').split())

                image_bytes, image_ext = None, None
                if idx < len(images):
                    xref = images[idx][0]
                    base_image = doc.extract_image(xref)
                    image_bytes = base_image['image']
                    image_ext = base_image['ext']

                results.append({
                    'nombre': nombre,
                    'vigor': vigor,
                    'moral': moral,
                    'cooking_method_id': metodo.id if metodo else None,
                    'metodo_nombre': metodo.nombre if metodo else metodo_raw,
                    'calidad': calidad,
                    'complejidad': complejidad,
                    'duracion_dias': duracion_dias,
                    'recalentar': recalentar,
                    'precio_compra_peniques': precio_compra_peniques,
                    'coste_creacion_peniques': coste_creacion_peniques,
                    'solo_compra': solo_compra,
                    'notas': notas,
                    'ingrediente_1_id': ingredientes[0].id if ingredientes[0] else None,
                    'ingrediente_2_id': ingredientes[1].id if ingredientes[1] else None,
                    'ingrediente_3_id': ingredientes[2].id if ingredientes[2] else None,
                    'ingrediente_4_id': ingredientes[3].id if ingredientes[3] else None,
                    'condimento_1_id': condimentos[0].id if condimentos[0] else None,
                    'condimento_2_id': condimentos[1].id if condimentos[1] else None,
                    'ingredientes_nombres': [i.nombre for i in ingredientes if i],
                    'condimentos_nombres': [c.nombre for c in condimentos if c],
                    'image_bytes': image_bytes,
                    'image_ext': image_ext,
                    'existe_ya': nombre in existing_names,
                })
        return results
    finally:
        doc.close()


def save_recipe_image_bytes(nombre, image_bytes, image_ext):
    """Writes PDF-extracted (or any raw) image bytes to uploads/recetas/ and
    returns the image_path to store on the Recipe row - same target
    directory/convention as the community recipe-proposal upload flow."""
    dest_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'recetas')
    os.makedirs(dest_dir, exist_ok=True)
    filename = secure_filename(nombre) + '.' + (image_ext or 'jpg')
    with open(os.path.join(dest_dir, filename), 'wb') as f:
        f.write(image_bytes)
    return os.path.join('recetas', filename)


def sync_recipe_images_from_folder():
    """Scans uploads/imagenes_comidas/ (admin-populated by hand, filename =
    recipe nombre) and links each matching file to its Recipe - only for
    recipes that don't already have a photo, never overwriting one that's
    already set. Returns a summary dict for the admin flash message."""
    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], _IMAGENES_COMIDAS_DIR)
    summary = {'linked': [], 'already_had_photo': [], 'unmatched_files': []}
    if not os.path.isdir(folder):
        return summary

    recipes_by_norm = {_normalize_filename(r.nombre): r for r in Recipe.query.all()}

    for filename in sorted(os.listdir(folder)):
        stem, ext = os.path.splitext(filename)
        if ext.lower().lstrip('.') not in _ALLOWED_IMAGE_EXTENSIONS:
            continue
        recipe = recipes_by_norm.get(_normalize_filename(stem))
        if recipe is None:
            summary['unmatched_files'].append(filename)
            continue
        if recipe.image_path:
            summary['already_had_photo'].append(recipe.nombre)
            continue
        with open(os.path.join(folder, filename), 'rb') as f:
            recipe.image_path = save_recipe_image_bytes(recipe.nombre, f.read(), ext.lower().lstrip('.'))
        summary['linked'].append(recipe.nombre)

    if summary['linked']:
        db.session.commit()
    return summary

"""Shared Untersuchung grado/marca data - used by both Contact (NPCs) and
Character (player characters who are themselves Untersuchung agents). Source:
the user's "untersuchung.pdf" (uploads/) - 8 "con marca" grados are real
agents of the organization, each represented by a physical mark/brand with
its own image; Bazas and Contactos are "sin marca" - external collaborators
who are explicitly NOT members, so they have no mark image and never
auto-flag es_untersuchung. A person can hold up to MAX_GRADOS marks at once
("grados mixtos", e.g. Paloma/Gato) - rare in practice (only 2 players
currently have a 2nd mark), but the book allows it."""

UNTERSUCHUNG_GRADOS_CON_MARCA = [
    'Escudo', 'Estilete', 'Gato', 'Brújula', 'Pluma', 'Corona', 'Carro', 'Paloma',
]
UNTERSUCHUNG_GRADOS_SIN_MARCA = ['Bazas', 'Contactos']
UNTERSUCHUNG_GRADOS = UNTERSUCHUNG_GRADOS_CON_MARCA + UNTERSUCHUNG_GRADOS_SIN_MARCA

MAX_GRADOS = 3

# Filenames the user placed in uploads/imagenes_untersuchung/ - one per
# "con marca" grado. Bazas/Contactos intentionally have no entry here.
_MARCA_IMAGE_FILENAMES = {
    'Escudo': 'escudo.jpg', 'Estilete': 'estilete.jpg', 'Gato': 'gato.jpg',
    'Brújula': 'brujula.jpg', 'Pluma': 'pluma.jpg', 'Corona': 'corona.jpg',
    'Carro': 'carro.jpg', 'Paloma': 'paloma.jpg',
}


def marca_image_path(grado):
    """Path relative to UPLOAD_FOLDER for a grado's mark image, or None for
    grados sin marca (Bazas/Contactos) - they have no physical mark at all."""
    filename = _MARCA_IMAGE_FILENAMES.get(grado)
    return f'imagenes_untersuchung/{filename}' if filename else None


def has_marca(grados):
    """True if any of the given grados is one of the 8 "con marca" ones -
    used to auto-set es_untersuchung=True. Bazas/Contactos alone never do,
    since the source material is explicit that they aren't members."""
    return bool(grados) and any(g in UNTERSUCHUNG_GRADOS_CON_MARCA for g in grados)


def clamp_grados(grados):
    """Keep only recognized values, in the order given, capped at
    MAX_GRADOS. Deliberately does NOT deduplicate - an agent can hold the
    same grado twice (represents a senior/veteran double mark), confirmed
    with the user. Returns None (not []) when nothing's left, matching the
    nullable-JSON-column convention used elsewhere in this app."""
    if not grados:
        return None
    kept = [g for g in grados if g in UNTERSUCHUNG_GRADOS][:MAX_GRADOS]
    return kept or None


def grados_display(grados):
    """Human-readable summary that collapses repeated grados instead of
    printing the same name twice in a row, e.g. ['Gato', 'Gato'] -> 'Gato x2'
    instead of 'Gato, Gato'."""
    if not grados:
        return ''
    counts = {}
    for g in grados:
        counts[g] = counts.get(g, 0) + 1
    seen = []
    parts = []
    for g in grados:
        if g in seen:
            continue
        seen.append(g)
        parts.append(f'{g} x{counts[g]}' if counts[g] > 1 else g)
    return ', '.join(parts)

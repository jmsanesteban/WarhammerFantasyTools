"""Untersuchung grado/marca data - used by Character (player characters who
are themselves Untersuchung agents). Source: the user's "untersuchung.pdf"
(uploads/). Two tiers now (reworked 2026-07-16, replacing the old flat
10-value con-marca/sin-marca split):
- Agente: full members, hold 1-MAX_GRADOS marks, may repeat the same grado
  twice (represents a senior/veteran double mark).
- Adjunto: helpers/assistants of the agents, hold exactly ONE mark, never
  combined with an Agente mark in the same set - Carro and Paloma used to
  live in the same flat list as the 6 Agente grados with no exclusivity at
  all; that's the actual behavior change here.
Contact (NPCs) used to have this same grado/marca system (2026-07-16 through
2026-07-19), but the director asked for it to be dropped from Contacts
entirely - a contact's Untersuchung membership is now just a plain
tipo_relacion='Unter' value on ContactCharacterLink (per-character fact, no
grado/marca), see app/models/contact_character_link.py."""

UNTERSUCHUNG_GRADOS_AGENTE = ['Escudo', 'Estilete', 'Gato', 'Brújula', 'Pluma', 'Corona']
UNTERSUCHUNG_GRADOS_ADJUNTO = ['Carro', 'Paloma']
UNTERSUCHUNG_GRADOS = UNTERSUCHUNG_GRADOS_AGENTE + UNTERSUCHUNG_GRADOS_ADJUNTO
# Alias kept for existing importers/templates: every remaining grado carries
# a physical mark now that Bazas/Contactos are gone, so this is just the
# full list under its old name - avoids touching every call site.
UNTERSUCHUNG_GRADOS_CON_MARCA = UNTERSUCHUNG_GRADOS

MAX_GRADOS = 3

# Filenames the user placed in uploads/imagenes_untersuchung/ - one per grado.
_MARCA_IMAGE_FILENAMES = {
    'Escudo': 'escudo.jpg', 'Estilete': 'estilete.jpg', 'Gato': 'gato.jpg',
    'Brújula': 'brujula.jpg', 'Pluma': 'pluma.jpg', 'Corona': 'corona.jpg',
    'Carro': 'carro.jpg', 'Paloma': 'paloma.jpg',
}


def marca_image_path(grado):
    """Path relative to UPLOAD_FOLDER for a grado's mark image, or None if
    the value isn't a recognized grado at all."""
    filename = _MARCA_IMAGE_FILENAMES.get(grado)
    return f'imagenes_untersuchung/{filename}' if filename else None


def has_marca(grados):
    """True if any grado is set - both remaining tiers carry a physical mark,
    so this is now just "is the list non-empty", kept as a named function
    since callers already depend on it rather than inlining `bool(grados)`."""
    return bool(grados)


def clamp_grados(grados):
    """Keep only recognized values, in the order given, and now tier-
    exclusive: the first recognized grado commits the whole selection to its
    tier (Agente or Adjunto); any value from the other tier is silently
    dropped, matching this function's existing "sanitize, never reject"
    style. Within Agente, up to MAX_GRADOS, duplicates preserved (a repeated
    grado represents a veteran double mark). Within Adjunto, capped at
    exactly 1 - there's no "double mark" concept for an Adjunto. Returns
    None (not []) when nothing's left, matching the nullable-JSON-column
    convention used elsewhere in this app."""
    if not grados:
        return None
    tier = None
    kept = []
    for g in grados:
        if g in UNTERSUCHUNG_GRADOS_AGENTE:
            g_tier = 'agente'
        elif g in UNTERSUCHUNG_GRADOS_ADJUNTO:
            g_tier = 'adjunto'
        else:
            continue
        if tier is None:
            tier = g_tier
        elif g_tier != tier:
            continue
        if tier == 'adjunto' and kept:
            continue
        kept.append(g)
        if len(kept) == MAX_GRADOS:
            break
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

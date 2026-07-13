"""Carrying-capacity rules from "El Imperio y sus viajes" (p.9, "Aclaraciones
sobre la carga"): a character's base carry level is Fuerza + Resistencia (the
raw characteristics, not their /10 bonus), with three worsening tiers on top
of it, each imposing its own movement/fatigue/agility penalty. The talent
Robusto shifts all three tiers by a flat +20 (confirmed with the user: it
does not scale the F+R total before tripling it for "carga pesada")."""

ROBUSTO_BONUS = 20

LEVEL_LABELS = {
    'sin_carga': 'Sin carga',
    'ligera': 'Carga ligera',
    'media': 'Carga media',
    'pesada': 'Carga pesada',
}

# Green -> yellow -> orange -> red progression, background+text chosen for
# readable contrast at every step (used as a CSS class suffix: wh-carga-<level>).
LEVEL_CSS_CLASS = {
    'sin_carga': 'wh-carga-sin_carga',
    'ligera': 'wh-carga-ligera',
    'media': 'wh-carga-media',
    'pesada': 'wh-carga-pesada',
}

# Penalty text split by turno/viaje so the UI can label each one explicitly
# instead of a single blended sentence - always a string (even for
# sin_carga) since the summary line always shows both.
LEVEL_PENALTIES = {
    'sin_carga': {'turno': 'Sin penalización.', 'viaje': 'Sin penalización.'},
    'ligera': {
        'turno': '-1 Movimiento.',
        'viaje': 'Sin penalización.',
    },
    'media': {
        'turno': '-2 Movimiento; al recibir Cansancio, se gana 1 punto adicional; -20% a Agilidad y Atletismo.',
        'viaje': '-1 Movimiento.',
    },
    'pesada': {
        'turno': '-3 Movimiento; al recibir Cansancio, se ganan 3 puntos adicionales; -40% a Agilidad y Atletismo.',
        'viaje': '-2 Movimiento.',
    },
}

# "El Imperio y sus viajes" carga units (U) a mochila/saco can hold before
# it's physically full - independent of whether the character is strong
# enough to carry that weight at all (encumbrance tiers above).
CONTAINER_CAPACITIES = {'mochila': 50.0, 'saco': 80.0}
CONTAINER_LABELS = {'mochila': 'Mochila', 'saco': 'Saco'}

# Comida/bebida weight (confirmed with the user): a ración always weighs the
# same regardless of recipe (2 raciones = 1U - normal is 3 raciones/day).
# A drink's weight depends only on its `recipiente` (serving size), not the
# specific drink - all 61 catalog drinks use one of these 3 recipientes, and
# the book's own examples (1L beer -> 2 pintas, 1 bottle wine -> 4 copas,
# 1 bottle spirits -> 10 chupitos) all work out to the same 1U per container,
# regardless of how many servings that container yields.
RECIPE_PESO_RACION = 0.5
DRINK_RECIPIENTE_PESO = {'Botella': 1.0, 'Pinta': 0.5, 'Chupito': 0.1}


def has_robusto(character):
    return any(
        ct.talent and ct.talent.name_es.strip().lower() == 'robusto'
        for ct in character.talents
    )


def carry_thresholds(character):
    """{'ligera': ..., 'media': ..., 'pesada': ...} - the weight at which
    each tier starts. Below 'ligera' is 'sin_carga' (no penalty)."""
    f = character.s_char or 0
    r = character.t_char or 0
    bonus = ROBUSTO_BONUS if has_robusto(character) else 0
    return {
        'ligera': f + bonus,
        'media': f + r + bonus,
        'pesada': 2 * (f + r) + bonus,
    }


def carry_level(weight, thresholds):
    if weight >= thresholds['pesada']:
        return 'pesada'
    if weight >= thresholds['media']:
        return 'media'
    if weight >= thresholds['ligera']:
        return 'ligera'
    return 'sin_carga'


def unit_weight(inv_item):
    """Weight of a single unit of this inventory line, or None if there's no
    weight data to derive one from (custom items, or an equipment row whose
    catalog peso is unset)."""
    if inv_item.equipment_item:
        return inv_item.equipment_item.peso_for_quality(inv_item.quality)
    if inv_item.drink:
        return DRINK_RECIPIENTE_PESO.get(inv_item.drink.recipiente)
    if inv_item.recipe:
        return RECIPE_PESO_RACION
    return None


def item_weight(inv_item):
    """Weight of one CharacterInventoryItem row (unit_weight * quantity).
    Items with no catalog link (custom_name only) or no known weight don't
    contribute - there's no weight data to derive one from."""
    peso = unit_weight(inv_item)
    return (peso or 0.0) * inv_item.quantity

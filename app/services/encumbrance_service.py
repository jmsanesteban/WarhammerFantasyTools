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

# One line per level, already worded for display; 'sin_carga' has none.
LEVEL_MESSAGES = {
    'ligera': 'Carga ligera: -1 Movimiento por turno.',
    'media': (
        'Carga media: -2 Movimiento por turno (al recibir Cansancio, se gana 1 adicional; '
        '-20% a Agilidad y Atletismo). En viaje: -1 Movimiento.'
    ),
    'pesada': (
        'Carga pesada: -3 Movimiento por turno (al recibir Cansancio, se ganan 3 adicionales; '
        '-40% a Agilidad y Atletismo). En viaje: -2 Movimiento.'
    ),
}


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


def item_weight(inv_item):
    """Weight of one CharacterInventoryItem row (peso_for_quality * quantity).
    Items with no catalog link (custom_name only) or no stored peso don't
    contribute - there's no weight data to derive one from."""
    if not inv_item.equipment_item:
        return 0.0
    peso = inv_item.equipment_item.peso_for_quality(inv_item.quality)
    return (peso or 0.0) * inv_item.quantity

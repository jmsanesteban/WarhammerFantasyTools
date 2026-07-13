"""Tests for the character inventory: moving items between the 5 storage
locations (full stack, partial quantity, merging into an existing stack at
the destination), and the "carga" (carrying capacity) rules from El Imperio
y sus viajes p.9 - weight per location, the 3 worsening tiers, and the
Robusto talent's flat +20 to every tier."""
from app.models.equipment import CharacterInventoryItem
from app.models.character import CharacterTalent
from app.services import encumbrance_service


def _owner_and_char(make_user, make_character, login_as, client, **char_kwargs):
    owner = make_user(username='owner1', password='ownerpass123')
    char = make_character(owner, name='Personaje', **char_kwargs)
    login_as(client, owner, 'ownerpass123')
    return char


def _inv_item(db, char, item, quantity=1, location='equipamiento', quality=None):
    from app.models.equipment import CharacterInventoryItem
    inv = CharacterInventoryItem(character_id=char.id, equipment_item_id=item.id,
                                  quantity=quantity, location=location, quality=quality)
    db.session.add(inv)
    db.session.commit()
    return inv


# ── encumbrance_service unit tests ──────────────────────────────────────────

class _FakeTalentLink:
    def __init__(self, talent):
        self.talent = talent


class _FakeTalent:
    def __init__(self, name_es):
        self.name_es = name_es


class _FakeChar:
    def __init__(self, s_char, t_char, talents=()):
        self.s_char = s_char
        self.t_char = t_char
        self.talents = [_FakeTalentLink(_FakeTalent(n)) for n in talents]


def test_carry_thresholds_without_robusto():
    char = _FakeChar(s_char=30, t_char=40)
    thresholds = encumbrance_service.carry_thresholds(char)
    assert thresholds == {'ligera': 30, 'media': 70, 'pesada': 140}


def test_carry_thresholds_with_robusto_adds_flat_20_to_each_tier():
    char = _FakeChar(s_char=30, t_char=40, talents=['Robusto'])
    thresholds = encumbrance_service.carry_thresholds(char)
    assert thresholds == {'ligera': 50, 'media': 90, 'pesada': 160}


def test_has_robusto_is_case_insensitive():
    assert encumbrance_service.has_robusto(_FakeChar(30, 40, talents=['robusto']))
    assert not encumbrance_service.has_robusto(_FakeChar(30, 40, talents=['Ambidiestro']))


def test_carry_level_tiers():
    thresholds = {'ligera': 30, 'media': 70, 'pesada': 140}
    assert encumbrance_service.carry_level(0, thresholds) == 'sin_carga'
    assert encumbrance_service.carry_level(29, thresholds) == 'sin_carga'
    assert encumbrance_service.carry_level(30, thresholds) == 'ligera'
    assert encumbrance_service.carry_level(69, thresholds) == 'ligera'
    assert encumbrance_service.carry_level(70, thresholds) == 'media'
    assert encumbrance_service.carry_level(139, thresholds) == 'media'
    assert encumbrance_service.carry_level(140, thresholds) == 'pesada'


# ── Inventory route: weights + carga warning ────────────────────────────────

def test_inventario_shows_weight_per_location(db, client, make_user, make_character, make_equipment_item,
                                               login_as):
    char = _owner_and_char(make_user, make_character, login_as, client, s_char=50, t_char=50)
    daga = make_equipment_item(name='Daga', category='arma', peso=1.0)
    _inv_item(db, char, daga, quantity=3, location='equipamiento')

    resp = client.get(f'/personajes/{char.id}/inventario')
    assert resp.status_code == 200
    assert 'Peso: 3.0 U'.encode() in resp.data


def test_inventario_shows_unit_and_total_weight_per_row(db, client, make_user, make_character,
                                                         make_equipment_item, login_as):
    """The per-row weight must show both the unit peso and the peso*quantity
    total - showing only the unit value (the old behavior) looked like the
    location totals below it didn't add up."""
    char = _owner_and_char(make_user, make_character, login_as, client)
    daga = make_equipment_item(name='Daga', category='arma', peso=2.0)
    _inv_item(db, char, daga, quantity=3, location='equipamiento')

    resp = client.get(f'/personajes/{char.id}/inventario')
    assert resp.status_code == 200
    assert b'2.00 / 6.00' in resp.data


def test_inventario_warns_on_carga_pesada(db, client, make_user, make_character, make_equipment_item, login_as):
    char = _owner_and_char(make_user, make_character, login_as, client, s_char=10, t_char=10)
    pesado = make_equipment_item(name='Yunque portátil', category='otros', peso=100.0)
    _inv_item(db, char, pesado, quantity=1, location='equipamiento')

    resp = client.get(f'/personajes/{char.id}/inventario')
    assert resp.status_code == 200
    assert 'Carga pesada'.encode() in resp.data


def test_inventario_reflects_robusto_talent_on_a_real_character(db, client, make_user, make_character,
                                                                 make_equipment_item, make_talent, login_as):
    """End-to-end: a character with the actual Robusto CharacterTalent row
    (not the fake stand-in used in the unit tests above) gets the +20 shift,
    so a weight that would be carga pesada without it stays under threshold."""
    char = _owner_and_char(make_user, make_character, login_as, client, s_char=10, t_char=10)
    talent = make_talent(name_es='Robusto')
    db.session.add(CharacterTalent(character_id=char.id, talent_id=talent.id))
    db.session.commit()
    # sin_carga threshold(=ligera start) without Robusto would be 10; with it, 30.
    item = make_equipment_item(name='Fardo', category='otros', peso=25.0)
    _inv_item(db, char, item, quantity=1, location='equipamiento')

    resp = client.get(f'/personajes/{char.id}/inventario')
    assert resp.status_code == 200
    assert b'Sin carga' in resp.data


def test_inventario_ignores_stashed_locations_for_carga(db, client, make_user, make_character,
                                                         make_equipment_item, login_as):
    """Weight sitting in Alforjas/Base/Altdorf must not count toward the
    carried-weight total, even if it would trigger carga pesada."""
    char = _owner_and_char(make_user, make_character, login_as, client, s_char=10, t_char=10)
    pesado = make_equipment_item(name='Yunque portátil', category='otros', peso=100.0)
    _inv_item(db, char, pesado, quantity=1, location='base')

    resp = client.get(f'/personajes/{char.id}/inventario')
    assert resp.status_code == 200
    assert 'Carga pesada'.encode() not in resp.data
    assert b'Sin carga' in resp.data


# ── Mochila/Saco container capacity ─────────────────────────────────────────

def test_set_contenedor_inventario_saves_choice(db, client, make_user, make_character, login_as):
    char = _owner_and_char(make_user, make_character, login_as, client)
    resp = client.post(f'/personajes/{char.id}/inventario/contenedor',
                       data={'mochila_o_saco': 'saco'}, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(char)
    assert char.mochila_o_saco == 'saco'


def test_set_contenedor_inventario_rejects_invalid_value(db, client, make_user, make_character, login_as):
    char = _owner_and_char(make_user, make_character, login_as, client, mochila_o_saco='mochila')
    resp = client.post(f'/personajes/{char.id}/inventario/contenedor',
                       data={'mochila_o_saco': 'alforja-magica'}, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(char)
    assert char.mochila_o_saco == 'mochila'


def test_inventario_warns_when_mochila_capacity_exceeded(db, client, make_user, make_character,
                                                          make_equipment_item, login_as):
    char = _owner_and_char(make_user, make_character, login_as, client, mochila_o_saco='mochila')
    pesado = make_equipment_item(name='Yunque portátil', category='otros', peso=60.0)
    _inv_item(db, char, pesado, quantity=1, location='mochila_saco')

    resp = client.get(f'/personajes/{char.id}/inventario')
    assert resp.status_code == 200
    assert 'wh-carga-overflow'.encode() in resp.data
    assert 'superada'.encode() in resp.data


def test_inventario_does_not_warn_under_saco_capacity(db, client, make_user, make_character,
                                                       make_equipment_item, login_as):
    char = _owner_and_char(make_user, make_character, login_as, client, mochila_o_saco='saco')
    ligero = make_equipment_item(name='Cuerda', category='otros', peso=10.0)
    _inv_item(db, char, ligero, quantity=1, location='mochila_saco')

    resp = client.get(f'/personajes/{char.id}/inventario')
    assert resp.status_code == 200
    assert 'wh-carga-overflow'.encode() not in resp.data


def test_inventario_prompts_for_container_choice_when_unset(db, client, make_user, make_character, login_as):
    char = _owner_and_char(make_user, make_character, login_as, client)
    resp = client.get(f'/personajes/{char.id}/inventario')
    assert resp.status_code == 200
    assert 'Elige si llevas mochila o saco'.encode() in resp.data


# ── Carga: color progression is present in the markup ───────────────────────

def test_carga_card_uses_the_right_color_class_per_level(db, client, make_user, make_character,
                                                          make_equipment_item, login_as):
    char = _owner_and_char(make_user, make_character, login_as, client, s_char=10, t_char=10)
    pesado = make_equipment_item(name='Yunque portátil', category='otros', peso=100.0)
    _inv_item(db, char, pesado, quantity=1, location='equipamiento')

    resp = client.get(f'/personajes/{char.id}/inventario')
    assert resp.status_code == 200
    assert 'wh-carga-pesada'.encode() in resp.data


def test_carga_card_shows_turno_and_viaje_penalties_separately(db, client, make_user, make_character,
                                                                make_equipment_item, login_as):
    char = _owner_and_char(make_user, make_character, login_as, client, s_char=10, t_char=10)
    medio = make_equipment_item(name='Fardo', category='otros', peso=15.0)
    _inv_item(db, char, medio, quantity=1, location='equipamiento')

    resp = client.get(f'/personajes/{char.id}/inventario')
    html = resp.data.decode()
    assert resp.status_code == 200
    assert 'Turno:' in html
    assert 'Viaje:' in html


# ── mover_inventario route ───────────────────────────────────────────────────

def test_mover_full_stack_changes_location(db, client, make_user, make_character, make_equipment_item, login_as):
    char = _owner_and_char(make_user, make_character, login_as, client)
    daga = make_equipment_item(name='Daga', category='arma', peso=1.0)
    inv = _inv_item(db, char, daga, quantity=2, location='equipamiento')

    resp = client.post(f'/personajes/{char.id}/inventario/{inv.id}/mover',
                       data={'destino': 'mochila_saco', 'cantidad': '2'}, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(inv)
    assert inv.location == 'mochila_saco'
    assert inv.quantity == 2


def test_mover_partial_quantity_splits_stack(db, client, make_user, make_character, make_equipment_item,
                                              login_as):
    char = _owner_and_char(make_user, make_character, login_as, client)
    daga = make_equipment_item(name='Daga', category='arma', peso=1.0)
    inv = _inv_item(db, char, daga, quantity=5, location='equipamiento')

    resp = client.post(f'/personajes/{char.id}/inventario/{inv.id}/mover',
                       data={'destino': 'mochila_saco', 'cantidad': '2'}, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(inv)
    assert inv.quantity == 3
    assert inv.location == 'equipamiento'

    moved = CharacterInventoryItem.query.filter_by(
        character_id=char.id, location='mochila_saco', equipment_item_id=daga.id,
    ).first()
    assert moved is not None
    assert moved.quantity == 2


def test_mover_merges_into_existing_stack_at_destination(db, client, make_user, make_character,
                                                          make_equipment_item, login_as):
    char = _owner_and_char(make_user, make_character, login_as, client)
    daga = make_equipment_item(name='Daga', category='arma', peso=1.0)
    origin = _inv_item(db, char, daga, quantity=2, location='equipamiento')
    existing_dest = _inv_item(db, char, daga, quantity=1, location='mochila_saco')

    resp = client.post(f'/personajes/{char.id}/inventario/{origin.id}/mover',
                       data={'destino': 'mochila_saco', 'cantidad': '2'}, follow_redirects=True)
    assert resp.status_code == 200

    assert CharacterInventoryItem.query.get(origin.id) is None
    db.session.refresh(existing_dest)
    assert existing_dest.quantity == 3
    assert CharacterInventoryItem.query.filter_by(character_id=char.id, location='mochila_saco').count() == 1


def test_mover_rejects_same_location(db, client, make_user, make_character, make_equipment_item, login_as):
    char = _owner_and_char(make_user, make_character, login_as, client)
    daga = make_equipment_item(name='Daga', category='arma', peso=1.0)
    inv = _inv_item(db, char, daga, quantity=2, location='equipamiento')

    resp = client.post(f'/personajes/{char.id}/inventario/{inv.id}/mover',
                       data={'destino': 'equipamiento', 'cantidad': '1'}, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(inv)
    assert inv.quantity == 2


def test_mover_rejects_quantity_above_stack(db, client, make_user, make_character, make_equipment_item,
                                            login_as):
    char = _owner_and_char(make_user, make_character, login_as, client)
    daga = make_equipment_item(name='Daga', category='arma', peso=1.0)
    inv = _inv_item(db, char, daga, quantity=2, location='equipamiento')

    resp = client.post(f'/personajes/{char.id}/inventario/{inv.id}/mover',
                       data={'destino': 'mochila_saco', 'cantidad': '3'}, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(inv)
    assert inv.quantity == 2
    assert inv.location == 'equipamiento'


def test_mover_multiple_moves_full_stacks_of_each_selected_item(db, client, make_user, make_character,
                                                                 make_equipment_item, login_as):
    char = _owner_and_char(make_user, make_character, login_as, client)
    daga = make_equipment_item(name='Daga', category='arma', peso=1.0)
    espada = make_equipment_item(name='Espada', category='arma', peso=2.0)
    inv1 = _inv_item(db, char, daga, quantity=2, location='equipamiento')
    inv2 = _inv_item(db, char, espada, quantity=1, location='equipamiento')

    resp = client.post(f'/personajes/{char.id}/inventario/mover-multiples',
                       data={'destino': 'mochila_saco', 'inv_item_ids': [str(inv1.id), str(inv2.id)]},
                       follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(inv1)
    db.session.refresh(inv2)
    assert inv1.location == 'mochila_saco'
    assert inv2.location == 'mochila_saco'
    assert inv1.quantity == 2
    assert inv2.quantity == 1


def test_mover_multiple_merges_into_existing_destination_stacks(db, client, make_user, make_character,
                                                                 make_equipment_item, login_as):
    char = _owner_and_char(make_user, make_character, login_as, client)
    daga = make_equipment_item(name='Daga', category='arma', peso=1.0)
    origin = _inv_item(db, char, daga, quantity=2, location='equipamiento')
    existing_dest = _inv_item(db, char, daga, quantity=3, location='mochila_saco')

    resp = client.post(f'/personajes/{char.id}/inventario/mover-multiples',
                       data={'destino': 'mochila_saco', 'inv_item_ids': [str(origin.id)]},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert CharacterInventoryItem.query.get(origin.id) is None
    db.session.refresh(existing_dest)
    assert existing_dest.quantity == 5


def test_mover_multiple_requires_at_least_one_selection(db, client, make_user, make_character, login_as):
    char = _owner_and_char(make_user, make_character, login_as, client)
    resp = client.post(f'/personajes/{char.id}/inventario/mover-multiples',
                       data={'destino': 'mochila_saco'}, follow_redirects=True)
    assert resp.status_code == 200


def test_mover_multiple_rejects_invalid_destino(db, client, make_user, make_character, make_equipment_item,
                                                login_as):
    char = _owner_and_char(make_user, make_character, login_as, client)
    daga = make_equipment_item(name='Daga', category='arma', peso=1.0)
    inv = _inv_item(db, char, daga, quantity=2, location='equipamiento')

    resp = client.post(f'/personajes/{char.id}/inventario/mover-multiples',
                       data={'destino': 'no-existe', 'inv_item_ids': [str(inv.id)]}, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(inv)
    assert inv.location == 'equipamiento'


def test_mover_multiple_ignores_ids_from_another_character(db, client, make_user, make_character,
                                                            make_equipment_item, login_as):
    """A hand-crafted request naming another character's inventory row must
    not move it - only rows that actually belong to this character."""
    owner = make_user(username='owner1', password='ownerpass123')
    other_owner = make_user(username='owner2', password='otherpass123')
    char = make_character(owner, name='Personaje')
    other_char = make_character(other_owner, name='Otro personaje')
    login_as(client, owner, 'ownerpass123')

    daga = make_equipment_item(name='Daga', category='arma', peso=1.0)
    other_inv = _inv_item(db, other_char, daga, quantity=1, location='equipamiento')

    resp = client.post(f'/personajes/{char.id}/inventario/mover-multiples',
                       data={'destino': 'mochila_saco', 'inv_item_ids': [str(other_inv.id)]},
                       follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(other_inv)
    assert other_inv.location == 'equipamiento'


def test_mover_multiple_blocks_other_users(client, make_user, make_character, make_equipment_item, login_as, db):
    owner = make_user(username='owner1', password='ownerpass123')
    other = make_user(username='other1', password='otherpass123')
    char = make_character(owner, name='Personaje')
    daga = make_equipment_item(name='Daga', category='arma', peso=1.0)
    inv = _inv_item(db, char, daga, quantity=2, location='equipamiento')

    login_as(client, other, 'otherpass123')
    resp = client.post(f'/personajes/{char.id}/inventario/mover-multiples',
                       data={'destino': 'mochila_saco', 'inv_item_ids': [str(inv.id)]})
    assert resp.status_code == 403


def test_inventario_page_has_bulk_select_checkboxes_and_zebra_class(db, client, make_user, make_character,
                                                                     make_equipment_item, login_as):
    char = _owner_and_char(make_user, make_character, login_as, client)
    daga = make_equipment_item(name='Daga', category='arma', peso=1.0)
    _inv_item(db, char, daga, quantity=2, location='equipamiento')

    resp = client.get(f'/personajes/{char.id}/inventario')
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'wh-zebra' in html
    assert 'name="inv_item_ids"' in html
    assert 'form="bulk-equipamiento"' in html


def test_single_quantity_move_input_is_readonly_not_disabled(db, client, make_user, make_character,
                                                              make_equipment_item, login_as):
    """A disabled <input> never gets submitted with its form - if the
    quantity=1 case used disabled instead of readonly, moving that item
    would silently send no "cantidad" at all and the move would be rejected
    as an invalid quantity."""
    char = _owner_and_char(make_user, make_character, login_as, client)
    daga = make_equipment_item(name='Daga', category='arma', peso=1.0)
    inv = _inv_item(db, char, daga, quantity=1, location='equipamiento')

    resp = client.get(f'/personajes/{char.id}/inventario')
    html = resp.data.decode()
    assert 'readonly>' in html
    assert 'disabled>' not in html


def test_mover_blocks_other_users(client, make_user, make_character, make_equipment_item, login_as, db):
    owner = make_user(username='owner1', password='ownerpass123')
    other = make_user(username='other1', password='otherpass123')
    char = make_character(owner, name='Personaje')
    daga = make_equipment_item(name='Daga', category='arma', peso=1.0)
    inv = _inv_item(db, char, daga, quantity=2, location='equipamiento')

    login_as(client, other, 'otherpass123')
    resp = client.post(f'/personajes/{char.id}/inventario/{inv.id}/mover',
                       data={'destino': 'mochila_saco', 'cantidad': '1'})
    assert resp.status_code == 403

"""Tests for Untersuchung grados/marcas - since 2026-07-19 exclusive to
Character (player characters who are themselves Untersuchung agents);
Contact/ContactCharacterLink no longer has any grado/marca concept at all
(Untersuchung membership on a contact is now a plain tipo_relacion='Unter'
value on the link - see test_contacts.py):
- app/models/untersuchung.py: clamp_grados enforces two exclusive tiers
  (Agente: up to 3 marks, duplicates allowed = double mark/veterancy;
  Adjunto: exactly 1 mark, never combined with Agente marks), has_marca
  (true whenever any grado is set - the old "sin marca" tier is gone),
  marca_image_path, grados_display.
- Setting any grado auto-flags es_untersuchung=True on Character, even if
  the checkbox wasn't posted.
- The grado picker is 3 independent single-select slots (grado_1/2/3), not
  one multi-select - the same grado can be assigned to two slots at once
  (a "double mark" representing veterancy), which a <select multiple>
  couldn't represent (browsers won't let you pick the same option twice)."""
from app.models.untersuchung import (
    clamp_grados, has_marca, marca_image_path, grados_display,
    UNTERSUCHUNG_GRADOS, UNTERSUCHUNG_GRADOS_AGENTE, UNTERSUCHUNG_GRADOS_ADJUNTO, MAX_GRADOS,
)
from app.models.character import Character


# ── app/models/untersuchung.py unit tests ───────────────────────────────────

def test_clamp_grados_caps_agente_at_max_and_preserves_order():
    result = clamp_grados(['Escudo', 'Gato', 'Brújula', 'Corona'])
    assert result == ['Escudo', 'Gato', 'Brújula']
    assert len(result) == MAX_GRADOS


def test_clamp_grados_keeps_duplicates_within_agente():
    assert clamp_grados(['Gato', 'Gato']) == ['Gato', 'Gato']
    assert clamp_grados(['Gato', '', 'Gato']) == ['Gato', 'Gato']


def test_clamp_grados_filters_unknown_values():
    assert clamp_grados(['Escudo', 'No existe']) == ['Escudo']


def test_clamp_grados_empty_returns_none():
    assert clamp_grados([]) is None
    assert clamp_grados(None) is None
    assert clamp_grados(['No existe']) is None


def test_clamp_grados_rejects_mixed_agente_and_adjunto():
    """The first recognized grado commits the whole selection to its tier;
    values from the other tier are silently dropped, same 'sanitize rather
    than reject' style clamp_grados already used for unknown values."""
    assert clamp_grados(['Escudo', 'Carro']) == ['Escudo']
    assert clamp_grados(['Carro', 'Escudo', 'Gato']) == ['Carro']


def test_clamp_grados_adjunto_capped_at_one():
    assert clamp_grados(['Carro', 'Paloma']) == ['Carro']
    assert clamp_grados(['Carro', 'Carro']) == ['Carro']


def test_has_marca_true_for_any_grado():
    assert has_marca(['Gato'])
    assert has_marca(['Carro'])


def test_has_marca_false_when_empty():
    assert not has_marca([])
    assert not has_marca(None)


def test_marca_image_path_covers_every_grado():
    assert marca_image_path('Escudo') == 'imagenes_untersuchung/escudo.jpg'
    assert marca_image_path('Carro') == 'imagenes_untersuchung/carro.jpg'
    assert marca_image_path('No existe') is None


def test_all_grados_have_an_image():
    for g in UNTERSUCHUNG_GRADOS:
        assert marca_image_path(g) is not None, f'{g} has no marca image mapped'


def test_grados_are_split_into_two_tiers():
    assert set(UNTERSUCHUNG_GRADOS_AGENTE) == {'Escudo', 'Estilete', 'Gato', 'Brújula', 'Pluma', 'Corona'}
    assert set(UNTERSUCHUNG_GRADOS_ADJUNTO) == {'Carro', 'Paloma'}
    assert set(UNTERSUCHUNG_GRADOS) == set(UNTERSUCHUNG_GRADOS_AGENTE) | set(UNTERSUCHUNG_GRADOS_ADJUNTO)


def test_grados_display_collapses_duplicates():
    assert grados_display(['Gato', 'Gato']) == 'Gato x2'
    assert grados_display(['Gato', 'Brújula']) == 'Gato, Brújula'
    assert grados_display(['Gato', 'Gato', 'Brújula']) == 'Gato x2, Brújula'
    assert grados_display(None) == ''
    assert grados_display([]) == ''


# ── Character routes ─────────────────────────────────────────────────────────

def test_create_character_con_marca_grado_auto_sets_es_untersuchung(db, client, make_user, login_as):
    owner = make_user(username='owner2', password='ownerpass123')
    login_as(client, owner, 'ownerpass123')

    client.post('/personajes/nuevo', data={
        'name': 'Personaje Untersuchung', 'grado_1': 'Estilete',
    }, follow_redirects=True)

    char = Character.query.filter_by(name='Personaje Untersuchung').first()
    assert char is not None
    assert char.es_untersuchung is True
    assert char.grados_untersuchung == ['Estilete']


def test_create_character_adjunto_grado_rejects_mixed_tier(db, client, make_user, login_as):
    owner = make_user(username='owner3', password='ownerpass123')
    login_as(client, owner, 'ownerpass123')

    client.post('/personajes/nuevo', data={
        'name': 'Personaje Adjunto', 'grado_1': 'Paloma', 'grado_2': 'Estilete',
    }, follow_redirects=True)

    char = Character.query.filter_by(name='Personaje Adjunto').first()
    assert char is not None
    assert char.es_untersuchung is True
    assert char.grados_untersuchung == ['Paloma']


def test_edit_character_can_hold_the_same_grado_twice(db, client, make_user, make_character, login_as):
    owner = make_user(username='owner4', password='ownerpass123')
    char = make_character(owner, name='Veterano')
    login_as(client, owner, 'ownerpass123')

    client.post(f'/personajes/{char.id}/editar', data={
        'name': 'Veterano', 'grado_1': 'Gato', 'grado_2': 'Gato',
    }, follow_redirects=True)

    db.session.refresh(char)
    assert char.grados_untersuchung == ['Gato', 'Gato']
    assert char.es_untersuchung is True


def test_edit_character_adjunto_capped_at_one(db, client, make_user, make_character, login_as):
    owner = make_user(username='owner4c', password='ownerpass123')
    char = make_character(owner, name='Adjunto')
    login_as(client, owner, 'ownerpass123')

    client.post(f'/personajes/{char.id}/editar', data={
        'name': 'Adjunto', 'grado_1': 'Paloma', 'grado_2': 'Paloma',
    }, follow_redirects=True)

    db.session.refresh(char)
    assert char.grados_untersuchung == ['Paloma']


def test_edit_character_grados_capped_at_three_slots_within_agente(db, client, make_user, make_character, login_as):
    owner = make_user(username='owner4b', password='ownerpass123')
    char = make_character(owner, name='Multimarca')
    login_as(client, owner, 'ownerpass123')

    client.post(f'/personajes/{char.id}/editar', data={
        'name': 'Multimarca', 'grado_1': 'Escudo', 'grado_2': 'Gato', 'grado_3': 'Brújula',
    }, follow_redirects=True)

    db.session.refresh(char)
    assert char.grados_untersuchung == ['Escudo', 'Gato', 'Brújula']


def test_character_detail_shows_marca_image(client, make_user, make_character, login_as):
    owner = make_user(username='owner5', password='ownerpass123')
    char = make_character(owner, name='Con marca', es_untersuchung=True, grados_untersuchung=['Paloma'])
    login_as(client, owner, 'ownerpass123')

    resp = client.get(f'/personajes/{char.id}')
    assert resp.status_code == 200
    assert b'paloma.jpg' in resp.data

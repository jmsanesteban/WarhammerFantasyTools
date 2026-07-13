"""Tests for Untersuchung grados/marcas, shared between Contact (NPCs) and
Character (player characters who are themselves Untersuchung agents):
- app/models/untersuchung.py: clamp_grados (max 3, filters unknown values,
  deliberately keeps duplicates), has_marca (only the 8 "con marca" grados
  count, not Bazas/Contactos), marca_image_path, grados_display.
- Setting any "con marca" grado auto-flags es_untersuchung=True on both
  Contact and Character, even if the checkbox wasn't posted; Bazas/Contactos
  alone never do (they're explicitly not members per the source material).
- The grado picker is 3 independent single-select slots (grado_1/2/3), not
  one multi-select - the same grado can be assigned to two slots at once
  (a "double mark" representing veterancy), which a <select multiple>
  couldn't represent (browsers won't let you pick the same option twice)."""
from app.models.untersuchung import (
    clamp_grados, has_marca, marca_image_path, grados_display, UNTERSUCHUNG_GRADOS, MAX_GRADOS,
)
from app.models.contact import Contact
from app.models.character import Character


# ── app/models/untersuchung.py unit tests ───────────────────────────────────

def test_clamp_grados_caps_at_max_and_preserves_order():
    result = clamp_grados(['Escudo', 'Gato', 'Paloma', 'Corona'])
    assert result == ['Escudo', 'Gato', 'Paloma']
    assert len(result) == MAX_GRADOS


def test_clamp_grados_keeps_duplicates():
    assert clamp_grados(['Gato', 'Gato']) == ['Gato', 'Gato']
    assert clamp_grados(['Gato', '', 'Gato']) == ['Gato', 'Gato']


def test_clamp_grados_filters_unknown_values():
    assert clamp_grados(['Escudo', 'No existe']) == ['Escudo']


def test_clamp_grados_empty_returns_none():
    assert clamp_grados([]) is None
    assert clamp_grados(None) is None
    assert clamp_grados(['No existe']) is None


def test_has_marca_true_for_con_marca_grado():
    assert has_marca(['Gato'])
    assert has_marca(['Bazas', 'Estilete'])


def test_has_marca_false_for_sin_marca_only():
    assert not has_marca(['Bazas', 'Contactos'])
    assert not has_marca([])
    assert not has_marca(None)


def test_marca_image_path_only_for_con_marca_grados():
    assert marca_image_path('Escudo') == 'imagenes_untersuchung/escudo.jpg'
    assert marca_image_path('Bazas') is None
    assert marca_image_path('No existe') is None


def test_all_con_marca_grados_have_an_image():
    from app.models.untersuchung import UNTERSUCHUNG_GRADOS_CON_MARCA
    for g in UNTERSUCHUNG_GRADOS_CON_MARCA:
        assert marca_image_path(g) is not None, f'{g} has no marca image mapped'


def test_grados_display_collapses_duplicates():
    assert grados_display(['Gato', 'Gato']) == 'Gato x2'
    assert grados_display(['Gato', 'Paloma']) == 'Gato, Paloma'
    assert grados_display(['Gato', 'Gato', 'Paloma']) == 'Gato x2, Paloma'
    assert grados_display(None) == ''
    assert grados_display([]) == ''


# ── Contact routes ───────────────────────────────────────────────────────────

def test_new_contact_con_marca_grado_auto_sets_es_untersuchung(db, client, make_user, make_character, login_as):
    owner = make_user(username='owner1', password='ownerpass123')
    char = make_character(owner, name='Personaje')
    login_as(client, owner, 'ownerpass123')

    client.post('/contactos/nuevo', data={
        'nombre': 'Agente Gato', 'personaje_id': str(char.id), 'grado_1': 'Gato',
    }, follow_redirects=True)

    contact = Contact.query.filter_by(nombre='Agente Gato').first()
    assert contact is not None
    assert contact.es_untersuchung is True
    assert contact.grados_untersuchung == ['Gato']


def test_new_contact_sin_marca_grado_does_not_set_es_untersuchung(db, client, make_user, make_character, login_as):
    owner = make_user(username='owner1', password='ownerpass123')
    char = make_character(owner, name='Personaje')
    login_as(client, owner, 'ownerpass123')

    client.post('/contactos/nuevo', data={
        'nombre': 'Baza cualquiera', 'personaje_id': str(char.id), 'grado_1': 'Bazas',
    }, follow_redirects=True)

    contact = Contact.query.filter_by(nombre='Baza cualquiera').first()
    assert contact is not None
    assert contact.es_untersuchung is False
    assert contact.grados_untersuchung == ['Bazas']


def test_edit_contact_can_hold_the_same_grado_twice(db, client, admin_user, make_contact, login_as):
    """The actual feature request: an agent can have a double mark of the
    same grado (represents veterancy) - the 3 independent slots allow this,
    unlike the old single <select multiple>."""
    contact = make_contact(nombre='Veterana')
    login_as(client, admin_user, 'adminpass123')

    client.post(f'/contactos/{contact.id}/editar', data={
        'nombre': 'Veterana', 'grado_1': 'Gato', 'grado_2': 'Gato',
    }, follow_redirects=True)

    db.session.refresh(contact)
    assert contact.grados_untersuchung == ['Gato', 'Gato']
    assert contact.es_untersuchung is True


def test_edit_contact_grados_capped_at_three_slots(db, client, admin_user, make_contact, login_as):
    contact = make_contact(nombre='Multimarca')
    login_as(client, admin_user, 'adminpass123')

    client.post(f'/contactos/{contact.id}/editar', data={
        'nombre': 'Multimarca', 'grado_1': 'Escudo', 'grado_2': 'Gato', 'grado_3': 'Paloma',
    }, follow_redirects=True)

    db.session.refresh(contact)
    assert contact.grados_untersuchung == ['Escudo', 'Gato', 'Paloma']


def test_detail_shows_marca_image_for_con_marca_grado(client, regular_user, login_as, make_character,
                                                       make_contact, make_contact_visibility):
    """Untersuchung facts (including grado/marca) are only shown to admins or
    to a viewing character who is themselves a member - same gate that
    already applies to the plain es_untersuchung boolean."""
    char = make_character(regular_user, es_untersuchung=True)
    contact = make_contact(nombre='Con marca', es_untersuchung=True, grados_untersuchung=['Escudo'])
    make_contact_visibility(char, contact, 'total')
    login_as(client, regular_user, 'userpass123')

    resp = client.get(f'/contactos/{contact.id}')
    assert resp.status_code == 200
    assert b'escudo.jpg' in resp.data


def test_detail_shows_marca_image_twice_for_double_mark(client, regular_user, login_as, make_character,
                                                         make_contact, make_contact_visibility):
    char = make_character(regular_user, es_untersuchung=True)
    contact = make_contact(nombre='Doble marca', es_untersuchung=True, grados_untersuchung=['Gato', 'Gato'])
    make_contact_visibility(char, contact, 'total')
    login_as(client, regular_user, 'userpass123')

    resp = client.get(f'/contactos/{contact.id}')
    assert resp.status_code == 200
    assert resp.data.count(b'gato.jpg') == 2
    assert b'Gato x2' in resp.data


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


def test_create_character_sin_marca_grado_does_not_set_es_untersuchung(db, client, make_user, login_as):
    owner = make_user(username='owner3', password='ownerpass123')
    login_as(client, owner, 'ownerpass123')

    client.post('/personajes/nuevo', data={
        'name': 'Personaje Baza', 'grado_1': 'Contactos',
    }, follow_redirects=True)

    char = Character.query.filter_by(name='Personaje Baza').first()
    assert char is not None
    assert char.es_untersuchung is False
    assert char.grados_untersuchung == ['Contactos']


def test_edit_character_can_hold_the_same_grado_twice(db, client, make_user, make_character, login_as):
    owner = make_user(username='owner4', password='ownerpass123')
    char = make_character(owner, name='Veterano')
    login_as(client, owner, 'ownerpass123')

    client.post(f'/personajes/{char.id}/editar', data={
        'name': 'Veterano', 'grado_1': 'Paloma', 'grado_2': 'Paloma',
    }, follow_redirects=True)

    db.session.refresh(char)
    assert char.grados_untersuchung == ['Paloma', 'Paloma']
    assert char.es_untersuchung is True


def test_edit_character_grados_capped_at_three_slots(db, client, make_user, make_character, login_as):
    owner = make_user(username='owner4b', password='ownerpass123')
    char = make_character(owner, name='Multimarca')
    login_as(client, owner, 'ownerpass123')

    client.post(f'/personajes/{char.id}/editar', data={
        'name': 'Multimarca', 'grado_1': 'Escudo', 'grado_2': 'Gato', 'grado_3': 'Paloma',
    }, follow_redirects=True)

    db.session.refresh(char)
    assert char.grados_untersuchung == ['Escudo', 'Gato', 'Paloma']


def test_character_detail_shows_marca_image(client, make_user, make_character, login_as):
    owner = make_user(username='owner5', password='ownerpass123')
    char = make_character(owner, name='Con marca', es_untersuchung=True, grados_untersuchung=['Paloma'])
    login_as(client, owner, 'ownerpass123')

    resp = client.get(f'/personajes/{char.id}')
    assert resp.status_code == 200
    assert b'paloma.jpg' in resp.data

"""Tests for Untersuchung grados/marcas, shared between Contact (NPCs) and
Character (player characters who are themselves Untersuchung agents):
- app/models/untersuchung.py: clamp_grados (max 3, filters unknown values),
  has_marca (only the 8 "con marca" grados count, not Bazas/Contactos),
  marca_image_path.
- Setting any "con marca" grado auto-flags es_untersuchung=True on both
  Contact and Character, even if the checkbox wasn't posted; Bazas/Contactos
  alone never do (they're explicitly not members per the source material).
- The grado multi-select is no longer gated behind es_untersuchung being
  checked (Bazas/Contactos apply to non-members too)."""
from app.models.untersuchung import (
    clamp_grados, has_marca, marca_image_path, UNTERSUCHUNG_GRADOS, MAX_GRADOS,
)
from app.models.contact import Contact
from app.models.character import Character


# ── app/models/untersuchung.py unit tests ───────────────────────────────────

def test_clamp_grados_caps_at_max_and_preserves_order():
    result = clamp_grados(['Escudo', 'Gato', 'Paloma', 'Corona'])
    assert result == ['Escudo', 'Gato', 'Paloma']
    assert len(result) == MAX_GRADOS


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


# ── Contact routes ───────────────────────────────────────────────────────────

def test_new_contact_con_marca_grado_auto_sets_es_untersuchung(db, client, make_user, make_character, login_as):
    owner = make_user(username='owner1', password='ownerpass123')
    char = make_character(owner, name='Personaje')
    login_as(client, owner, 'ownerpass123')

    client.post('/contactos/nuevo', data={
        'nombre': 'Agente Gato', 'personaje_id': str(char.id), 'grados_untersuchung': ['Gato'],
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
        'nombre': 'Baza cualquiera', 'personaje_id': str(char.id), 'grados_untersuchung': ['Bazas'],
    }, follow_redirects=True)

    contact = Contact.query.filter_by(nombre='Baza cualquiera').first()
    assert contact is not None
    assert contact.es_untersuchung is False
    assert contact.grados_untersuchung == ['Bazas']


def test_edit_contact_grados_capped_at_three(db, client, admin_user, make_contact, login_as):
    contact = make_contact(nombre='Multimarca')
    login_as(client, admin_user, 'adminpass123')

    client.post(f'/contactos/{contact.id}/editar', data={
        'nombre': 'Multimarca',
        'grados_untersuchung': ['Escudo', 'Gato', 'Paloma', 'Corona'],
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


# ── Character routes ─────────────────────────────────────────────────────────

def test_create_character_con_marca_grado_auto_sets_es_untersuchung(db, client, make_user, login_as):
    owner = make_user(username='owner2', password='ownerpass123')
    login_as(client, owner, 'ownerpass123')

    client.post('/personajes/nuevo', data={
        'name': 'Personaje Untersuchung', 'grados_untersuchung': ['Estilete'],
    }, follow_redirects=True)

    char = Character.query.filter_by(name='Personaje Untersuchung').first()
    assert char is not None
    assert char.es_untersuchung is True
    assert char.grados_untersuchung == ['Estilete']


def test_create_character_sin_marca_grado_does_not_set_es_untersuchung(db, client, make_user, login_as):
    owner = make_user(username='owner3', password='ownerpass123')
    login_as(client, owner, 'ownerpass123')

    client.post('/personajes/nuevo', data={
        'name': 'Personaje Baza', 'grados_untersuchung': ['Contactos'],
    }, follow_redirects=True)

    char = Character.query.filter_by(name='Personaje Baza').first()
    assert char is not None
    assert char.es_untersuchung is False
    assert char.grados_untersuchung == ['Contactos']


def test_edit_character_grados_capped_at_three(db, client, make_user, make_character, login_as):
    owner = make_user(username='owner4', password='ownerpass123')
    char = make_character(owner, name='Multimarca')
    login_as(client, owner, 'ownerpass123')

    client.post(f'/personajes/{char.id}/editar', data={
        'name': 'Multimarca',
        'grados_untersuchung': ['Escudo', 'Gato', 'Paloma', 'Corona'],
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

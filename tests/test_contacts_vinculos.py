"""Tests for /contactos/vinculos (2026-07-17 rework - moved out of admin.py,
no longer admin-only). Non-admins default to only their own active
character's links (no Personaje column, no Usuario column at all); ?todos=1
broadens to every link of every character of every user, same view an admin
always gets. Notes only show a count here, never content."""
from app.models.contact_character_link import NIVEL_LABELS


def test_vinculos_requires_login(client):
    resp = client.get('/contactos/vinculos')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_vinculos_no_active_character_shows_prompt(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/contactos/vinculos')
    assert resp.status_code == 200
    assert 'personaje activo'.encode() in resp.data.lower() or b'Elige uno' in resp.data


def test_vinculos_non_admin_defaults_to_own_active_character(
    client, regular_user, make_user, make_character, make_contact, make_contact_link,
    set_active_character, login_as,
):
    other = make_user(username='otro', password='otropass123')
    my_char = make_character(regular_user, name='Mi personaje')
    other_char = make_character(other, name='Personaje ajeno')
    contact = make_contact(nombre='Wilhelm el tabernero')
    make_contact_link(my_char, contact, nivel=3)
    make_contact_link(other_char, contact, nivel=-1)
    set_active_character(regular_user, my_char)
    login_as(client, regular_user, 'userpass123')

    resp = client.get('/contactos/vinculos')
    assert resp.status_code == 200
    assert b'Wilhelm el tabernero' in resp.data
    assert NIVEL_LABELS[3].encode('utf-8') in resp.data
    # No Personaje column in the "solo los míos" view, and no other user's data.
    assert b'Personaje ajeno' not in resp.data


def test_vinculos_todos_broadens_to_every_character_of_every_user(
    client, regular_user, make_user, make_character, make_contact, make_contact_link,
    set_active_character, login_as,
):
    other = make_user(username='otro2', password='otropass123')
    my_char = make_character(regular_user, name='Mi personaje')
    other_char = make_character(other, name='Personaje ajeno')
    contact = make_contact(nombre='Wilhelm el tabernero')
    make_contact_link(my_char, contact, nivel=3)
    make_contact_link(other_char, contact, nivel=-1)
    set_active_character(regular_user, my_char)
    login_as(client, regular_user, 'userpass123')

    resp = client.get('/contactos/vinculos?todos=1')
    assert resp.status_code == 200
    assert b'Mi personaje' in resp.data
    assert b'Personaje ajeno' in resp.data


def test_vinculos_admin_always_sees_everyone_regardless_of_todos(
    client, admin_user, regular_user, make_character, make_contact, make_contact_link, login_as,
):
    char = make_character(regular_user, name='Karl-Heinz')
    contact = make_contact(nombre='Wilhelm el tabernero')
    make_contact_link(char, contact, nivel=3)
    login_as(client, admin_user, 'adminpass123')

    resp = client.get('/contactos/vinculos')
    assert resp.status_code == 200
    assert b'Karl-Heinz' in resp.data
    assert NIVEL_LABELS[3].encode('utf-8') in resp.data


def test_vinculos_no_username_column(client, admin_user, regular_user, make_character,
                                     make_contact, make_contact_link, login_as):
    """The old admin-only version showed the owning user's username - the
    reworked listing drops it entirely, everywhere."""
    char = make_character(regular_user, name='Karl-Heinz')
    contact = make_contact(nombre='Wilhelm el tabernero')
    make_contact_link(char, contact)
    login_as(client, admin_user, 'adminpass123')

    resp = client.get('/contactos/vinculos')
    assert regular_user.username.encode('utf-8') not in resp.data


def test_vinculos_notes_show_count_not_content(client, admin_user, regular_user, make_character,
                                                make_contact, make_contact_link, make_contact_note, login_as):
    char = make_character(regular_user, name='Bardin')
    contact = make_contact(nombre='El posadero')
    make_contact_link(char, contact)
    make_contact_note(contact, char, content='Debe dinero al gremio.')
    login_as(client, admin_user, 'adminpass123')

    resp = client.get('/contactos/vinculos')
    assert resp.status_code == 200
    assert b'Debe dinero al gremio.' not in resp.data
    assert b'1' in resp.data


def test_vinculos_search_filters_by_personaje(client, admin_user, make_user, make_character,
                                              make_contact, make_contact_link, login_as):
    user_a = make_user(username='usera', password='passa12345')
    user_b = make_user(username='userb', password='passb12345')
    char_a = make_character(user_a, name='Personaje A')
    char_b = make_character(user_b, name='Personaje B')
    contact = make_contact()
    make_contact_link(char_a, contact)
    make_contact_link(char_b, contact)
    login_as(client, admin_user, 'adminpass123')

    resp = client.get('/contactos/vinculos?q=Personaje A')
    assert b'Personaje A' in resp.data
    assert b'Personaje B' not in resp.data


def test_vinculos_buscar_contacto_requires_login(client):
    resp = client.get('/contactos/vinculos/buscar')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_vinculos_buscar_contacto_matches_nombre(client, regular_user, make_contact, login_as):
    make_contact(nombre='Wilhelm el tabernero')
    make_contact(nombre='Grombrindal')
    login_as(client, regular_user, 'userpass123')

    resp = client.get('/contactos/vinculos/buscar?q=wilhelm')
    assert resp.status_code == 200
    data = resp.get_json()
    assert [c['nombre'] for c in data['contacts']] == ['Wilhelm el tabernero']


def test_vinculos_buscar_contacto_matches_raza(client, regular_user, make_contact, login_as):
    make_contact(nombre='Grombrindal', raza='Enano')
    make_contact(nombre='Wilhelm el tabernero', raza='Humano')
    login_as(client, regular_user, 'userpass123')

    resp = client.get('/contactos/vinculos/buscar?q=enan')
    data = resp.get_json()
    assert [c['nombre'] for c in data['contacts']] == ['Grombrindal']


def test_vinculos_buscar_contacto_gender_synonym(client, regular_user, make_contact, login_as):
    """Contact.raza solo guarda la forma masculina (RAZA_CHOICES) - buscar
    la palabra completa "enana" debe encontrar igualmente un contacto
    guardado con raza "Enano" (ver _RACE_GENDER_SYNONYMS)."""
    make_contact(nombre='Grombrindal', raza='Enano')
    login_as(client, regular_user, 'userpass123')

    resp = client.get('/contactos/vinculos/buscar?q=enana')
    data = resp.get_json()
    assert [c['nombre'] for c in data['contacts']] == ['Grombrindal']


def test_vinculos_buscar_contacto_hides_invisible_for_non_admin(
    client, regular_user, make_contact, login_as,
):
    make_contact(nombre='Contacto oculto', is_visible=False)
    login_as(client, regular_user, 'userpass123')

    resp = client.get('/contactos/vinculos/buscar?q=oculto')
    data = resp.get_json()
    assert data['contacts'] == []


def test_note_create_redirects_to_vinculos_next_url(
    db, client, admin_user, regular_user, make_character, make_contact, login_as,
):
    char = make_character(regular_user)
    contact = make_contact()
    login_as(client, admin_user, 'adminpass123')

    resp = client.post(f'/contactos/{contact.id}/notas', data={
        'personaje_id': str(char.id), 'content': 'Nota de prueba', 'next_url': '/contactos/vinculos?page=1',
    })
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/contactos/vinculos?page=1'

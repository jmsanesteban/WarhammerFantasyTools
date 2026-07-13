"""Tests for the Contacts feature: visibility rules, per-character notes,
per-character links (nickname/nivel/org/salary), and the Untersuchung
visibility gate — from the regular-user perspective. Admin-only contact
management routes are covered in test_admin_contacts.py."""
from app.models.contact_note import ContactNote
from app.models.contact_character_link import ContactCharacterLink, ContactCharacterSalary


def test_index_requires_login(client):
    resp = client.get('/contactos/')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


# ── Estado / Paradero badges ─────────────────────────────────────────────────

def test_index_shows_muerto_badge(client, regular_user, login_as, make_character, make_contact,
                                  make_contact_visibility):
    char = make_character(regular_user)
    contact = make_contact(nombre='Difunto', estado='muerto')
    make_contact_visibility(char, contact, 'total')
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/contactos/')
    assert b'Muerto' in resp.data


def test_index_shows_corrompido_badge(client, regular_user, login_as, make_character, make_contact,
                                      make_contact_visibility):
    char = make_character(regular_user)
    contact = make_contact(nombre='Mutado', estado='corrompido')
    make_contact_visibility(char, contact, 'total')
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/contactos/')
    assert b'Corrompido' in resp.data


def test_index_shows_paradero_badge_only_when_alive(client, regular_user, login_as, make_character,
                                                     make_contact, make_contact_visibility):
    char = make_character(regular_user)
    contact = make_contact(nombre='Fugitivo', estado='vivo', paradero='exiliado')
    make_contact_visibility(char, contact, 'total')
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/contactos/')
    assert 'Exiliado'.encode() in resp.data


def test_detail_shows_estado_and_paradero(client, regular_user, login_as, make_character, make_contact,
                                          make_contact_visibility):
    char = make_character(regular_user)
    contact = make_contact(nombre='Secuestrada', estado='vivo', paradero='secuestrado')
    make_contact_visibility(char, contact, 'total')
    login_as(client, regular_user, 'userpass123')
    resp = client.get(f'/contactos/{contact.id}')
    assert resp.status_code == 200
    assert 'Secuestrado'.encode() in resp.data


def test_regular_user_only_sees_visible_contacts(client, regular_user, login_as, make_character,
                                                 make_contact, make_contact_visibility):
    char = make_character(regular_user)
    visible = make_contact(nombre='Gotrek Gurnisson', is_visible=True)
    hidden = make_contact(nombre='Espía Oculto', is_visible=False)
    make_contact_visibility(char, visible, 'total')
    make_contact_visibility(char, hidden, 'total')  # grant present, but is_visible=False still hides it

    login_as(client, regular_user, 'userpass123')
    resp = client.get('/contactos/')
    assert f'/contactos/{visible.id}'.encode() in resp.data
    assert f'/contactos/{hidden.id}'.encode() not in resp.data


def test_visible_contact_without_grant_is_not_shown(client, regular_user, login_as, make_character, make_contact):
    """is_visible=True is necessary but not sufficient - a character also
    needs an explicit visibility grant to see the contact at all."""
    char = make_character(regular_user)
    contact = make_contact(nombre='Sin conceder', is_visible=True)

    login_as(client, regular_user, 'userpass123')
    resp = client.get('/contactos/')
    assert f'/contactos/{contact.id}'.encode() not in resp.data

    resp = client.get(f'/contactos/{contact.id}', follow_redirects=True)
    assert resp.request.path == '/contactos/'


def test_admin_sees_hidden_contacts_too(client, admin_user, login_as, make_contact):
    hidden = make_contact(nombre='Espía Oculto', is_visible=False)

    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/contactos/')
    assert f'/contactos/{hidden.id}'.encode() in resp.data


def test_regular_user_cannot_view_hidden_contact_detail(client, regular_user, login_as, make_contact):
    hidden = make_contact(is_visible=False)
    login_as(client, regular_user, 'userpass123')
    resp = client.get(f'/contactos/{hidden.id}', follow_redirects=True)
    assert resp.status_code == 200
    assert resp.request.path == '/contactos/'


def test_regular_user_can_view_visible_contact_detail(client, regular_user, login_as, make_character,
                                                       make_contact, make_contact_visibility):
    char = make_character(regular_user)
    contact = make_contact(is_visible=True)
    make_contact_visibility(char, contact, 'total')
    login_as(client, regular_user, 'userpass123')
    resp = client.get(f'/contactos/{contact.id}')
    assert resp.status_code == 200


def test_search_filters_by_nombre(client, regular_user, login_as, make_character,
                                  make_contact, make_contact_visibility):
    char = make_character(regular_user)
    c1 = make_contact(nombre='Gotrek Gurnisson')
    c2 = make_contact(nombre='Felix Jaeger')
    make_contact_visibility(char, c1, 'total')
    make_contact_visibility(char, c2, 'total')

    login_as(client, regular_user, 'userpass123')
    resp = client.get('/contactos/?q=Gotrek')
    assert f'/contactos/{c1.id}'.encode() in resp.data
    assert f'/contactos/{c2.id}'.encode() not in resp.data


# ── Creating a contact (any character can create one) ───────────────────────

def test_new_contact_creates_contact_and_own_link(db, client, regular_user, make_character, login_as):
    char = make_character(regular_user, name='Karl-Heinz')
    login_as(client, regular_user, 'userpass123')

    resp = client.post('/contactos/nuevo', data={
        'nombre': 'Wilhelm el tabernero', 'personaje_id': str(char.id),
        'nivel': '2', 'apodos': ['Willi'], 'organizacion_secta': '',
    }, follow_redirects=True)
    assert resp.status_code == 200

    from app.models.contact import Contact
    contact = Contact.query.filter_by(nombre='Wilhelm el tabernero').first()
    assert contact is not None
    link = ContactCharacterLink.query.filter_by(character_id=char.id, contact_id=contact.id).first()
    assert link is not None
    assert link.nivel == 2
    assert link.apodos[0].texto == 'Willi'


def test_new_contact_grants_creating_character_total_visibility(db, client, regular_user, make_character, login_as):
    char = make_character(regular_user, name='Karl-Heinz')
    login_as(client, regular_user, 'userpass123')

    client.post('/contactos/nuevo', data={
        'nombre': 'Wilhelm el tabernero', 'personaje_id': str(char.id),
    }, follow_redirects=True)

    from app.models.contact import Contact
    from app.models.contact_character_link import ContactCharacterVisibility
    contact = Contact.query.filter_by(nombre='Wilhelm el tabernero').first()
    grant = ContactCharacterVisibility.query.filter_by(contact_id=contact.id, character_id=char.id).first()
    assert grant is not None
    assert grant.nivel == 'total'


def test_admin_created_contact_without_character_has_no_grant(db, client, admin_user, regular_user,
                                                               make_character, login_as):
    make_character(regular_user)  # any character must exist so admin's "new" form isn't empty
    login_as(client, admin_user, 'adminpass123')

    client.post('/contactos/nuevo', data={'nombre': 'Contacto sin repartir'}, follow_redirects=True)

    from app.models.contact import Contact
    from app.models.contact_character_link import ContactCharacterLink, ContactCharacterVisibility
    contact = Contact.query.filter_by(nombre='Contacto sin repartir').first()
    assert contact is not None
    assert ContactCharacterLink.query.filter_by(contact_id=contact.id).count() == 0
    assert ContactCharacterVisibility.query.filter_by(contact_id=contact.id).count() == 0


def test_new_contact_requires_own_character(client, regular_user, login_as):
    """A user with no characters yet can't register a contact - there's no
    character to attach the per-character link to."""
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/contactos/nuevo', follow_redirects=True)
    assert resp.status_code == 200
    assert resp.request.path == '/personajes/'


# ── Untersuchung visibility gate ─────────────────────────────────────────────

_UNTERSUCHUNG_FACT = b'<dt class="col-sm-4 wh-label">Untersuchung</dt>'


def test_untersuchung_hidden_from_non_member_character(client, regular_user, make_character, make_contact,
                                                       make_contact_visibility, login_as):
    char = make_character(regular_user, name='Civil', es_untersuchung=False)
    contact = make_contact(nombre='Agente secreto', es_untersuchung=True)
    make_contact_visibility(char, contact, 'total')
    login_as(client, regular_user, 'userpass123')

    resp = client.get(f'/contactos/{contact.id}?personaje_id={char.id}')
    assert resp.status_code == 200
    assert _UNTERSUCHUNG_FACT not in resp.data


def test_untersuchung_visible_to_member_character(client, regular_user, make_character, make_contact,
                                                  make_contact_visibility, login_as):
    char = make_character(regular_user, name='Agente', es_untersuchung=True)
    contact = make_contact(nombre='Agente secreto', es_untersuchung=True)
    make_contact_visibility(char, contact, 'total')
    login_as(client, regular_user, 'userpass123')

    resp = client.get(f'/contactos/{contact.id}?personaje_id={char.id}')
    assert _UNTERSUCHUNG_FACT in resp.data


_PROFESIONES_FACT = b'<dt class="col-sm-4 wh-label">Profesiones</dt>'


def test_total_visibility_shows_professions(client, regular_user, make_character, make_contact,
                                            make_contact_visibility, make_profession, login_as):
    char = make_character(regular_user)
    prof = make_profession(name='Herrero')
    contact = make_contact(professions=[prof])
    make_contact_visibility(char, contact, 'total')
    login_as(client, regular_user, 'userpass123')

    resp = client.get(f'/contactos/{contact.id}?personaje_id={char.id}')
    assert _PROFESIONES_FACT in resp.data
    assert b'Herrero' in resp.data


def test_parcial_visibility_hides_professions(client, regular_user, make_character, make_contact,
                                              make_contact_visibility, make_profession, login_as):
    char = make_character(regular_user)
    prof = make_profession(name='Herrero')
    contact = make_contact(professions=[prof])
    make_contact_visibility(char, contact, 'parcial')
    login_as(client, regular_user, 'userpass123')

    resp = client.get(f'/contactos/{contact.id}?personaje_id={char.id}')
    assert resp.status_code == 200
    assert _PROFESIONES_FACT not in resp.data
    assert b'Herrero' not in resp.data


def test_untersuchung_visible_to_admin_regardless(client, admin_user, make_contact, login_as):
    contact = make_contact(nombre='Agente secreto', es_untersuchung=True)
    login_as(client, admin_user, 'adminpass123')

    resp = client.get(f'/contactos/{contact.id}')
    assert _UNTERSUCHUNG_FACT in resp.data


# ── Vínculo personaje-contacto ───────────────────────────────────────────────

def test_link_save_creates_link(db, client, regular_user, make_character, make_contact,
                                make_contact_visibility, login_as):
    char = make_character(regular_user)
    contact = make_contact()
    make_contact_visibility(char, contact, 'total')
    login_as(client, regular_user, 'userpass123')

    client.post(f'/contactos/{contact.id}/vinculo', data={
        'personaje_id': str(char.id), 'nivel': '-3', 'lugar_residencia': 'Desconocido',
    }, follow_redirects=True)

    link = ContactCharacterLink.query.filter_by(character_id=char.id, contact_id=contact.id).first()
    assert link is not None
    assert link.nivel == -3
    assert link.lugar_residencia == 'Desconocido'


def test_link_save_blocks_other_users_character(client, make_user, make_character, make_contact, login_as):
    owner = make_user(username='owner1', password='ownerpass123')
    other = make_user(username='other1', password='otherpass123')
    char = make_character(owner)
    contact = make_contact()

    login_as(client, other, 'otherpass123')
    resp = client.post(f'/contactos/{contact.id}/vinculo', data={'personaje_id': str(char.id), 'nivel': '5'})
    assert resp.status_code == 403


def test_link_delete_removes_link(db, client, regular_user, make_character, make_contact, make_contact_link,
                                  make_contact_visibility, login_as):
    char = make_character(regular_user)
    contact = make_contact()
    make_contact_link(char, contact, nivel=1)
    make_contact_visibility(char, contact, 'total')
    login_as(client, regular_user, 'userpass123')

    client.post(f'/contactos/{contact.id}/vinculo/eliminar', data={'personaje_id': str(char.id)},
               follow_redirects=True)
    assert ContactCharacterLink.query.filter_by(character_id=char.id, contact_id=contact.id).first() is None


def test_two_characters_have_independent_links_to_same_contact(db, client, make_user, make_character,
                                                                 make_contact, make_contact_link):
    user_a = make_user(username='usera', password='passa12345')
    user_b = make_user(username='userb', password='passb12345')
    char_a = make_character(user_a, name='Personaje A')
    char_b = make_character(user_b, name='Personaje B')
    contact = make_contact()
    make_contact_link(char_a, contact, nivel=5, organizacion_secta='Culto de Sigmar')
    make_contact_link(char_b, contact, nivel=-2)

    link_a = ContactCharacterLink.query.filter_by(character_id=char_a.id, contact_id=contact.id).first()
    link_b = ContactCharacterLink.query.filter_by(character_id=char_b.id, contact_id=contact.id).first()
    assert link_a.nivel == 5 and link_a.organizacion_secta == 'Culto de Sigmar'
    assert link_b.nivel == -2 and link_b.organizacion_secta is None


# ── Salario ──────────────────────────────────────────────────────────────────

def test_salary_save_creates_salary_entry(db, client, regular_user, make_character, make_contact,
                                          make_contact_link, make_contact_visibility, make_profession, login_as):
    char = make_character(regular_user)
    prof = make_profession(name='Herrero')
    contact = make_contact(professions=[prof])
    link = make_contact_link(char, contact)
    make_contact_visibility(char, contact, 'total')
    login_as(client, regular_user, 'userpass123')

    client.post(f'/contactos/{contact.id}/salario', data={
        'personaje_id': str(char.id), 'profession_id': str(prof.id),
        'tipo_sueldo': 'Artesanos', 'estado_habilidad': 'Buena',
    }, follow_redirects=True)

    salary = ContactCharacterSalary.query.filter_by(link_id=link.id, profession_id=prof.id).first()
    assert salary is not None
    assert salary.tipo_sueldo == 'Artesanos'
    assert salary.estado_habilidad == 'Buena'


# ── Notas (por personaje) ────────────────────────────────────────────────────

def test_create_note(db, client, regular_user, make_character, make_contact, make_contact_visibility, login_as):
    char = make_character(regular_user)
    contact = make_contact(is_visible=True)
    make_contact_visibility(char, contact, 'total')
    login_as(client, regular_user, 'userpass123')

    resp = client.post(f'/contactos/{contact.id}/notas',
                       data={'content': 'Interesante tipo', 'personaje_id': str(char.id)},
                       follow_redirects=True)
    assert resp.status_code == 200
    note = ContactNote.query.filter_by(contact_id=contact.id).first()
    assert note is not None
    assert note.character_id == char.id


def test_create_note_rejects_empty_content(client, regular_user, make_character, make_contact,
                                           make_contact_visibility, login_as):
    char = make_character(regular_user)
    contact = make_contact(is_visible=True)
    make_contact_visibility(char, contact, 'total')
    login_as(client, regular_user, 'userpass123')
    client.post(f'/contactos/{contact.id}/notas', data={'content': '  ', 'personaje_id': str(char.id)})
    assert ContactNote.query.filter_by(contact_id=contact.id).count() == 0


def test_note_from_one_character_hidden_from_another_characters_view(
    db, client, regular_user, make_character, make_contact, make_contact_note, make_contact_visibility, login_as,
):
    char_a = make_character(regular_user, name='Personaje A')
    char_b = make_character(regular_user, name='Personaje B')
    contact = make_contact(is_visible=True)
    make_contact_visibility(char_a, contact, 'total')
    make_contact_visibility(char_b, contact, 'total')
    make_contact_note(contact, char_a, content='Nota de A')

    login_as(client, regular_user, 'userpass123')
    resp = client.get(f'/contactos/{contact.id}?personaje_id={char_b.id}')
    assert 'Nota de A'.encode('utf-8') not in resp.data

    resp = client.get(f'/contactos/{contact.id}?personaje_id={char_a.id}')
    assert 'Nota de A'.encode('utf-8') in resp.data


def test_edit_note_blocks_non_owner_character(client, make_user, make_character, make_contact,
                                              make_contact_note, login_as):
    owner = make_user(username='owner1', password='ownerpass123')
    other = make_user(username='other1', password='otherpass123')
    owner_char = make_character(owner)
    contact = make_contact(is_visible=True)
    note = make_contact_note(contact, owner_char, content='Original')

    login_as(client, other, 'otherpass123')
    resp = client.post(f'/contactos/{contact.id}/notas/{note.id}/editar', data={'content': 'Hackeado'})
    assert resp.status_code == 403


def test_edit_note_allows_owner(db, client, regular_user, make_character, make_contact, make_contact_note, login_as):
    char = make_character(regular_user)
    contact = make_contact(is_visible=True)
    note = make_contact_note(contact, char, content='Original')
    login_as(client, regular_user, 'userpass123')

    client.post(f'/contactos/{contact.id}/notas/{note.id}/editar', data={'content': 'Actualizada'},
               follow_redirects=True)
    db.session.refresh(note)
    assert note.content == 'Actualizada'


def test_delete_note_blocks_non_owner_character(client, make_user, make_character, make_contact,
                                                make_contact_note, login_as):
    owner = make_user(username='owner1', password='ownerpass123')
    other = make_user(username='other1', password='otherpass123')
    owner_char = make_character(owner)
    contact = make_contact(is_visible=True)
    note = make_contact_note(contact, owner_char)

    login_as(client, other, 'otherpass123')
    resp = client.post(f'/contactos/{contact.id}/notas/{note.id}/eliminar')
    assert resp.status_code == 403


def test_delete_note_allows_admin(db, client, admin_user, regular_user, make_character, make_contact,
                                  make_contact_note, login_as):
    char = make_character(regular_user)
    contact = make_contact(is_visible=True)
    note = make_contact_note(contact, char)
    note_id = note.id
    login_as(client, admin_user, 'adminpass123')

    client.post(f'/contactos/{contact.id}/notas/{note_id}/eliminar', follow_redirects=True)
    assert db.session.get(ContactNote, note_id) is None

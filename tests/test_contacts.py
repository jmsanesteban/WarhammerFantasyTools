"""Tests for the Contacts (EAV) feature: visibility rules, notes,
and persona/contact relationship linking — from the regular-user perspective.
Admin-only contact management routes are covered in test_admin_contacts.py."""
from app.models.contact_note import ContactNote
from app.models.contact_persona import ContactPersonaLink


def test_index_requires_login(client):
    resp = client.get('/contactos/')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_regular_user_only_sees_visible_contacts(client, regular_user, login_as,
                                                 make_contact, make_contact_field):
    make_contact_field(name='nombre', display_name='Nombre')
    visible = make_contact(is_visible=True, values={})
    hidden = make_contact(is_visible=False, values={})

    login_as(client, regular_user, 'userpass123')
    resp = client.get('/contactos/')
    assert f'/contactos/{visible.id}'.encode() in resp.data
    assert f'/contactos/{hidden.id}'.encode() not in resp.data


def test_admin_sees_hidden_contacts_too(client, admin_user, login_as, make_contact, make_contact_field):
    make_contact_field(name='nombre', display_name='Nombre')
    hidden = make_contact(is_visible=False, values={})

    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/contactos/')
    assert f'/contactos/{hidden.id}'.encode() in resp.data


def test_regular_user_cannot_view_hidden_contact_detail(client, regular_user, login_as, make_contact):
    hidden = make_contact(is_visible=False)
    login_as(client, regular_user, 'userpass123')
    resp = client.get(f'/contactos/{hidden.id}', follow_redirects=True)
    assert resp.status_code == 200
    assert resp.request.path == '/contactos/'


def test_regular_user_can_view_visible_contact_detail(client, regular_user, login_as, make_contact):
    contact = make_contact(is_visible=True)
    login_as(client, regular_user, 'userpass123')
    resp = client.get(f'/contactos/{contact.id}')
    assert resp.status_code == 200


def test_search_filters_by_field_value(client, regular_user, login_as,
                                       make_contact_field, make_contact):
    field = make_contact_field(name='nombre', display_name='Nombre')
    c1 = make_contact(values={field.id: 'Gotrek Gurnisson'})
    c2 = make_contact(values={field.id: 'Felix Jaeger'})

    login_as(client, regular_user, 'userpass123')
    resp = client.get('/contactos/?q=Gotrek')
    assert f'/contactos/{c1.id}'.encode() in resp.data
    assert f'/contactos/{c2.id}'.encode() not in resp.data


# ── Notes ────────────────────────────────────────────────────────────────────

def test_create_note(db, client, regular_user, login_as, make_contact):
    contact = make_contact(is_visible=True)
    login_as(client, regular_user, 'userpass123')

    resp = client.post(f'/contactos/{contact.id}/notas', data={'content': 'Interesante tipo'},
                       follow_redirects=True)
    assert resp.status_code == 200
    note = ContactNote.query.filter_by(contact_id=contact.id).first()
    assert note is not None
    assert note.author_id == regular_user.id
    assert note.is_global is False


def test_create_note_rejects_empty_content(client, regular_user, login_as, make_contact):
    contact = make_contact(is_visible=True)
    login_as(client, regular_user, 'userpass123')
    client.post(f'/contactos/{contact.id}/notas', data={'content': '  '})
    assert ContactNote.query.filter_by(contact_id=contact.id).count() == 0


def test_private_note_hidden_from_other_users(client, make_user, make_contact, make_contact_note, login_as):
    author = make_user(username='author1', password='authorpass123')
    other = make_user(username='other1', password='otherpass123')
    contact = make_contact(is_visible=True)
    make_contact_note(contact, author, content='Nota privada', is_global=False)

    login_as(client, other, 'otherpass123')
    resp = client.get(f'/contactos/{contact.id}')
    assert 'Nota privada'.encode('utf-8') not in resp.data


def test_global_note_visible_to_other_users(client, make_user, make_contact, make_contact_note, login_as):
    author = make_user(username='author1', password='authorpass123')
    other = make_user(username='other1', password='otherpass123')
    contact = make_contact(is_visible=True)
    make_contact_note(contact, author, content='Nota global', is_global=True)

    login_as(client, other, 'otherpass123')
    resp = client.get(f'/contactos/{contact.id}')
    assert 'Nota global'.encode('utf-8') in resp.data


def test_edit_note_blocks_non_author(client, make_user, make_contact, make_contact_note, login_as):
    author = make_user(username='author1', password='authorpass123')
    other = make_user(username='other1', password='otherpass123')
    contact = make_contact(is_visible=True)
    note = make_contact_note(contact, author, content='Original')

    login_as(client, other, 'otherpass123')
    resp = client.post(f'/contactos/{contact.id}/notas/{note.id}/editar', data={'content': 'Hackeado'})
    assert resp.status_code == 403


def test_edit_note_allows_author(db, client, regular_user, make_contact, make_contact_note, login_as):
    contact = make_contact(is_visible=True)
    note = make_contact_note(contact, regular_user, content='Original')
    login_as(client, regular_user, 'userpass123')

    client.post(f'/contactos/{contact.id}/notas/{note.id}/editar', data={'content': 'Actualizada'},
               follow_redirects=True)
    db.session.refresh(note)
    assert note.content == 'Actualizada'


def test_delete_note_blocks_non_author(client, make_user, make_contact, make_contact_note, login_as):
    author = make_user(username='author1', password='authorpass123')
    other = make_user(username='other1', password='otherpass123')
    contact = make_contact(is_visible=True)
    note = make_contact_note(contact, author)

    login_as(client, other, 'otherpass123')
    resp = client.post(f'/contactos/{contact.id}/notas/{note.id}/eliminar')
    assert resp.status_code == 403


def test_delete_note_allows_admin(db, client, admin_user, regular_user, make_contact, make_contact_note, login_as):
    contact = make_contact(is_visible=True)
    note = make_contact_note(contact, regular_user)
    note_id = note.id
    login_as(client, admin_user, 'adminpass123')

    client.post(f'/contactos/{contact.id}/notas/{note_id}/eliminar', follow_redirects=True)
    assert db.session.get(ContactNote, note_id) is None


# ── Persona relationships (self-service) ────────────────────────────────────

def test_user_can_link_own_persona_to_contact(db, client, regular_user, login_as,
                                              make_contact, make_contact_persona):
    contact = make_contact(is_visible=True)
    persona = make_contact_persona(user=regular_user, name='Mi Persona')
    login_as(client, regular_user, 'userpass123')

    resp = client.post(f'/contactos/{contact.id}/persona/{persona.id}/relacion',
                       data={'relationship': 'Viejo amigo'}, follow_redirects=True)
    assert resp.status_code == 200

    link = ContactPersonaLink.query.filter_by(persona_id=persona.id, contact_id=contact.id).first()
    assert link is not None
    assert link.relationship_note == 'Viejo amigo'


def test_user_cannot_link_someone_elses_persona(client, make_user, make_contact,
                                                make_contact_persona, login_as):
    owner = make_user(username='owner1', password='ownerpass123')
    other = make_user(username='other1', password='otherpass123')
    contact = make_contact(is_visible=True)
    persona = make_contact_persona(user=owner, name='Persona de Owner')

    login_as(client, other, 'otherpass123')
    resp = client.post(f'/contactos/{contact.id}/persona/{persona.id}/relacion',
                       data={'relationship': 'Intento de hackeo'})
    assert resp.status_code == 403


def test_user_can_unlink_own_persona(db, client, regular_user, login_as,
                                     make_contact, make_contact_persona):
    contact = make_contact(is_visible=True)
    persona = make_contact_persona(user=regular_user, name='Mi Persona')
    db.session.add(ContactPersonaLink(persona_id=persona.id, contact_id=contact.id,
                                       relationship_note='Amigo'))
    db.session.commit()

    login_as(client, regular_user, 'userpass123')
    client.post(f'/contactos/{contact.id}/persona/{persona.id}/desvincular', follow_redirects=True)

    assert ContactPersonaLink.query.filter_by(persona_id=persona.id, contact_id=contact.id).first() is None

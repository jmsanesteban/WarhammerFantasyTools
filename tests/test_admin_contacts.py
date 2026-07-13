"""Tests for admin-only Contacts management: contact CRUD/listing/toggle/
delete, editing global fields, per-character visibility grants, and Excel
import/export against the fixed-column schema (nombre, es_untersuchung,
profesiones)."""
import io
import openpyxl
from app.models.contact import Contact, ContactProfession
from app.models.contact_character_link import ContactCharacterVisibility


# ── Admin contact listing/toggle/delete ─────────────────────────────────────

def test_admin_contacts_listing_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/admin/contactos')
    assert resp.status_code == 403


# ── Editar datos globales ────────────────────────────────────────────────────

def test_edit_contact_requires_admin(client, regular_user, make_contact, login_as):
    contact = make_contact()
    login_as(client, regular_user, 'userpass123')
    resp = client.get(f'/contactos/{contact.id}/editar')
    assert resp.status_code == 403


def test_edit_contact_updates_global_fields(db, client, admin_user, make_contact, make_profession, login_as):
    contact = make_contact(nombre='Nombre original', es_untersuchung=False)
    prof = make_profession(name='Herrero')
    login_as(client, admin_user, 'adminpass123')

    resp = client.post(f'/contactos/{contact.id}/editar', data={
        'nombre': 'Nombre corregido', 'es_untersuchung': 'on', 'estado': 'vivo', 'paradero': 'exiliado',
        'grado_1': 'Paloma', 'grado_2': 'Gato', 'profession_ids': [str(prof.id)],
    }, follow_redirects=True)
    assert resp.status_code == 200

    db.session.refresh(contact)
    assert contact.nombre == 'Nombre corregido'
    assert contact.es_untersuchung is True
    assert contact.estado == 'vivo'
    assert contact.paradero == 'exiliado'
    assert contact.grados_untersuchung == ['Paloma', 'Gato']
    assert ContactProfession.query.filter_by(contact_id=contact.id, profession_id=prof.id).first() is not None


def test_edit_contact_clears_paradero_when_not_alive(db, client, admin_user, make_contact, login_as):
    """Paradero (Encarcelado/Exiliado/...) only makes sense while estado is
    'vivo' - if a hand-crafted request posts one alongside estado='muerto',
    the server must ignore it rather than keep a stale location badge."""
    contact = make_contact(nombre='Contacto')
    login_as(client, admin_user, 'adminpass123')

    resp = client.post(f'/contactos/{contact.id}/editar', data={
        'nombre': 'Contacto', 'estado': 'muerto', 'paradero': 'exiliado',
    }, follow_redirects=True)
    assert resp.status_code == 200

    db.session.refresh(contact)
    assert contact.estado == 'muerto'
    assert contact.paradero is None


def test_edit_contact_allows_creator_to_update_profession(db, client, regular_user, make_contact, make_profession,
                                                            login_as):
    """Non-admins can't edit a contact they didn't register, but the original
    creator can - specifically covers being able to fix a contact's profession
    after the fact, which used to be admin-only."""
    contact = make_contact(nombre='Contacto propio', created_by=regular_user)
    prof = make_profession(name='Cazarrecompensas')
    login_as(client, regular_user, 'userpass123')

    resp = client.post(f'/contactos/{contact.id}/editar', data={
        'nombre': 'Contacto propio', 'profession_ids': [str(prof.id)],
    }, follow_redirects=True)
    assert resp.status_code == 200

    db.session.refresh(contact)
    assert ContactProfession.query.filter_by(contact_id=contact.id, profession_id=prof.id).first() is not None


def test_edit_contact_creator_cannot_toggle_visibility(db, client, regular_user, make_contact, login_as):
    """is_visible is a global admin-moderation flag - a non-admin creator
    editing their own contact must not be able to flip it even if the field
    were posted (e.g. via a hand-crafted request)."""
    contact = make_contact(nombre='Contacto propio', created_by=regular_user, is_visible=True)
    login_as(client, regular_user, 'userpass123')

    resp = client.post(f'/contactos/{contact.id}/editar', data={
        'nombre': 'Contacto propio', 'is_visible': '',
    }, follow_redirects=True)
    assert resp.status_code == 200

    db.session.refresh(contact)
    assert contact.is_visible is True


def test_edit_contact_still_blocks_non_creator_non_admin(client, regular_user, make_user, make_contact, login_as):
    other = make_user('otro_usuario', 'otropass123')
    contact = make_contact(nombre='De otro usuario', created_by=other)
    login_as(client, regular_user, 'userpass123')
    resp = client.get(f'/contactos/{contact.id}/editar')
    assert resp.status_code == 403


# ── Visibilidad por personaje ────────────────────────────────────────────────

def test_visibility_save_requires_admin(client, regular_user, make_character, make_contact, login_as):
    char = make_character(regular_user)
    contact = make_contact()
    login_as(client, regular_user, 'userpass123')
    resp = client.post(f'/contactos/{contact.id}/visibilidad',
                       data={'character_id': str(char.id), 'nivel': 'total'})
    assert resp.status_code == 403


def test_visibility_save_grants_access(db, client, admin_user, regular_user, make_character, make_contact, login_as):
    char = make_character(regular_user)
    contact = make_contact()
    login_as(client, admin_user, 'adminpass123')

    client.post(f'/contactos/{contact.id}/visibilidad',
               data={'character_id': str(char.id), 'nivel': 'parcial'}, follow_redirects=True)

    grant = ContactCharacterVisibility.query.filter_by(contact_id=contact.id, character_id=char.id).first()
    assert grant is not None
    assert grant.nivel == 'parcial'


def test_visibility_save_updates_existing_grant(db, client, admin_user, regular_user, make_character,
                                                make_contact, make_contact_visibility, login_as):
    char = make_character(regular_user)
    contact = make_contact()
    make_contact_visibility(char, contact, 'parcial')
    login_as(client, admin_user, 'adminpass123')

    client.post(f'/contactos/{contact.id}/visibilidad',
               data={'character_id': str(char.id), 'nivel': 'total'}, follow_redirects=True)

    grant = ContactCharacterVisibility.query.filter_by(contact_id=contact.id, character_id=char.id).first()
    assert grant.nivel == 'total'


def test_visibility_save_empty_nivel_revokes_access(db, client, admin_user, regular_user, make_character,
                                                    make_contact, make_contact_visibility, login_as):
    char = make_character(regular_user)
    contact = make_contact()
    make_contact_visibility(char, contact, 'total')
    login_as(client, admin_user, 'adminpass123')

    client.post(f'/contactos/{contact.id}/visibilidad',
               data={'character_id': str(char.id), 'nivel': ''}, follow_redirects=True)

    assert ContactCharacterVisibility.query.filter_by(contact_id=contact.id, character_id=char.id).first() is None


def test_visibility_save_bulk_handles_multiple_characters_in_one_post(
    db, client, admin_user, regular_user, make_character, make_contact, make_contact_visibility, login_as,
):
    """The whole 'Visibilidad por personaje' table now submits as one form -
    grant/update/revoke for several characters must all apply from a single POST."""
    char_grant = make_character(regular_user, name='Nuevo acceso')
    char_update = make_character(regular_user, name='Cambia de nivel')
    char_revoke = make_character(regular_user, name='Pierde acceso')
    contact = make_contact()
    make_contact_visibility(char_update, contact, 'parcial')
    make_contact_visibility(char_revoke, contact, 'total')
    login_as(client, admin_user, 'adminpass123')

    client.post(f'/contactos/{contact.id}/visibilidad', data={
        'character_id': [str(char_grant.id), str(char_update.id), str(char_revoke.id)],
        'nivel': ['total', 'total', ''],
    }, follow_redirects=True)

    grants = {
        g.character_id: g.nivel
        for g in ContactCharacterVisibility.query.filter_by(contact_id=contact.id).all()
    }
    assert grants.get(char_grant.id) == 'total'
    assert grants.get(char_update.id) == 'total'
    assert char_revoke.id not in grants


# ── Vínculos (directorio admin contacto↔personaje) ──────────────────────────

def test_contact_links_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/admin/vinculos')
    assert resp.status_code == 403


def test_contact_links_shows_owner_username_and_level(client, admin_user, regular_user, make_character,
                                                       make_contact, make_contact_link, make_contact_visibility,
                                                       login_as):
    char = make_character(regular_user, name='Karl-Heinz')
    contact = make_contact(nombre='Wilhelm el tabernero')
    make_contact_link(char, contact, nivel=3)
    make_contact_visibility(char, contact, 'parcial')
    login_as(client, admin_user, 'adminpass123')

    resp = client.get('/admin/vinculos')
    assert resp.status_code == 200
    assert b'Wilhelm el tabernero' in resp.data
    assert b'Karl-Heinz' in resp.data
    assert regular_user.username.encode('utf-8') in resp.data
    assert b'Parcial' in resp.data


def test_contact_links_shows_all_characters_with_access_not_just_the_linked_one(
    client, admin_user, regular_user, make_character, make_contact, make_contact_link,
    make_contact_visibility, login_as,
):
    """A character can have visibility into a contact without ever having registered
    it (no ContactCharacterLink) - the 'Personajes con acceso' column must still list them."""
    linked_char = make_character(regular_user, name='Registró el contacto')
    other_char = make_character(regular_user, name='Solo tiene acceso')
    contact = make_contact(nombre='NPC compartido')
    make_contact_link(linked_char, contact, nivel=1)
    make_contact_visibility(linked_char, contact, 'total')
    make_contact_visibility(other_char, contact, 'parcial')
    login_as(client, admin_user, 'adminpass123')

    resp = client.get('/admin/vinculos')
    assert resp.status_code == 200
    assert b'Solo tiene acceso' in resp.data
    assert b'Registr' in resp.data


def test_contact_links_notes_panel_shows_content_not_just_count(
    client, admin_user, regular_user, make_character, make_contact, make_contact_link, login_as,
):
    """The 'Notas' column used to show only a bare count - it must now expose
    the actual note text (and a way to add one) directly from this table."""
    char = make_character(regular_user, name='Bardin')
    contact = make_contact(nombre='El posadero')
    make_contact_link(char, contact)
    from app.models.contact_note import ContactNote
    from app.extensions import db as _db
    _db.session.add(ContactNote(contact_id=contact.id, character_id=char.id, content='Debe dinero al gremio.'))
    _db.session.commit()
    login_as(client, admin_user, 'adminpass123')

    resp = client.get('/admin/vinculos')
    assert resp.status_code == 200
    assert b'Debe dinero al gremio.' in resp.data
    assert f'/contactos/{contact.id}/notas'.encode() in resp.data


def test_note_create_redirects_to_next_url_when_provided(
    db, client, admin_user, regular_user, make_character, make_contact, login_as,
):
    char = make_character(regular_user)
    contact = make_contact()
    login_as(client, admin_user, 'adminpass123')

    resp = client.post(f'/contactos/{contact.id}/notas', data={
        'personaje_id': str(char.id), 'content': 'Nota de prueba', 'next_url': '/admin/vinculos?page=1',
    })
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/admin/vinculos?page=1'


def test_contact_links_search_filters_by_username(client, admin_user, make_user, make_character,
                                                   make_contact, make_contact_link, login_as):
    user_a = make_user(username='searchableuser', password='passa12345')
    user_b = make_user(username='otheruser', password='passb12345')
    char_a = make_character(user_a, name='Personaje A')
    char_b = make_character(user_b, name='Personaje B')
    contact = make_contact()
    make_contact_link(char_a, contact)
    make_contact_link(char_b, contact)
    login_as(client, admin_user, 'adminpass123')

    resp = client.get('/admin/vinculos?q=searchableuser')
    assert b'Personaje A' in resp.data
    assert b'Personaje B' not in resp.data


def test_admin_contacts_listing_shows_nombre(client, admin_user, login_as, make_contact):
    contact = make_contact(nombre='Gotrek Gurnisson')
    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/admin/contactos')
    assert b'Gotrek Gurnisson' in resp.data


def test_admin_contacts_listing_includes_inline_permissions_panel(
    client, admin_user, regular_user, make_character, make_contact, make_contact_visibility, login_as,
):
    """Admin can see and edit per-character visibility directly from the main
    contacts list, without opening each contact's own detail page."""
    char = make_character(regular_user, name='Ulrika')
    contact = make_contact(nombre='Snorri')
    make_contact_visibility(char, contact, 'parcial')
    login_as(client, admin_user, 'adminpass123')

    resp = client.get('/admin/contactos')
    assert resp.status_code == 200
    assert f'perms-{contact.id}'.encode() in resp.data
    assert b'Ulrika' in resp.data
    # The inline form posts to the same visibility_save endpoint used on the contact's own page.
    assert f'/contactos/{contact.id}/visibilidad'.encode() in resp.data


def test_visibility_save_redirects_to_next_url_when_provided(
    db, client, admin_user, regular_user, make_character, make_contact, login_as,
):
    char = make_character(regular_user)
    contact = make_contact()
    login_as(client, admin_user, 'adminpass123')

    resp = client.post(f'/contactos/{contact.id}/visibilidad', data={
        'character_id': str(char.id), 'nivel': 'total', 'next_url': '/admin/contactos?page=2',
    })
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/admin/contactos?page=2'


def test_visibility_save_ignores_unsafe_next_url(
    db, client, admin_user, regular_user, make_character, make_contact, login_as,
):
    """An absolute/external next_url must never be honored (open-redirect guard)."""
    char = make_character(regular_user)
    contact = make_contact()
    login_as(client, admin_user, 'adminpass123')

    resp = client.post(f'/contactos/{contact.id}/visibilidad', data={
        'character_id': str(char.id), 'nivel': 'total', 'next_url': 'https://evil.example.com',
    })
    assert resp.status_code == 302
    assert 'evil.example.com' not in resp.headers['Location']
    assert f'/contactos/{contact.id}' in resp.headers['Location']


def test_admin_contact_toggle(client, admin_user, login_as, make_contact):
    contact = make_contact(is_visible=True)
    login_as(client, admin_user, 'adminpass123')
    resp = client.post(f'/admin/contactos/{contact.id}/toggle')
    assert resp.get_json() == {'visible': False}


def test_admin_contact_delete(db, client, admin_user, login_as, make_contact):
    contact = make_contact()
    contact_id = contact.id
    login_as(client, admin_user, 'adminpass123')
    client.post(f'/admin/contactos/{contact_id}/eliminar', follow_redirects=True)
    assert db.session.get(Contact, contact_id) is None


def test_admin_contacts_delete_selected(db, client, admin_user, login_as, make_contact):
    c1 = make_contact()
    c2 = make_contact()
    c3 = make_contact()
    login_as(client, admin_user, 'adminpass123')

    client.post('/admin/contactos/eliminar-seleccionados',
               data={'contact_ids': [str(c1.id), str(c2.id)]}, follow_redirects=True)

    db.session.expire_all()
    remaining_ids = {c.id for c in Contact.query.all()}
    assert remaining_ids == {c3.id}


# ── Admin can manage any character's link (via contacts.py routes) ─────────

def test_admin_can_save_link_for_any_characters_contact(db, client, admin_user, regular_user,
                                                          make_character, make_contact, login_as):
    char = make_character(regular_user)
    contact = make_contact()
    login_as(client, admin_user, 'adminpass123')

    from app.models.contact_character_link import ContactCharacterLink
    client.post(f'/contactos/{contact.id}/vinculo',
               data={'personaje_id': str(char.id), 'nivel': '4'}, follow_redirects=True)

    link = ContactCharacterLink.query.filter_by(character_id=char.id, contact_id=contact.id).first()
    assert link is not None
    assert link.nivel == 4


# ── Excel import/export ──────────────────────────────────────────────────────

def _build_xlsx(rows, headers=('Nombre', 'Es_Untersuchung', 'Profesiones')):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(list(headers))
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_contacts_import_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/admin/contactos/importar')
    assert resp.status_code == 403


def test_contacts_import_rejects_non_excel(client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    data = {'file': (io.BytesIO(b'not excel'), 'contacts.txt')}
    resp = client.post('/admin/contactos/importar', data=data,
                       content_type='multipart/form-data', follow_redirects=True)
    assert 'solo se permiten'.encode('utf-8') in resp.data.lower()


def test_contacts_import_creates_contacts(db, client, admin_user, login_as, make_profession):
    prof = make_profession(name='Herrero')
    xlsx = _build_xlsx([['Gotrek Gurnisson', 'Si', 'Herrero']])
    login_as(client, admin_user, 'adminpass123')

    resp = client.post('/admin/contactos/importar',
                       data={'file': (xlsx, 'contacts.xlsx')},
                       content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200

    contact = Contact.query.filter_by(nombre='Gotrek Gurnisson').first()
    assert contact is not None
    assert contact.es_untersuchung is True
    assert ContactProfession.query.filter_by(contact_id=contact.id, profession_id=prof.id).first() is not None


def test_contacts_import_ignores_unknown_profession_names(db, client, admin_user, login_as):
    xlsx = _build_xlsx([['Gotrek Gurnisson', 'No', 'Profesión Inventada']])
    login_as(client, admin_user, 'adminpass123')

    client.post('/admin/contactos/importar',
               data={'file': (xlsx, 'contacts.xlsx')},
               content_type='multipart/form-data', follow_redirects=True)

    contact = Contact.query.filter_by(nombre='Gotrek Gurnisson').first()
    assert contact is not None
    assert ContactProfession.query.filter_by(contact_id=contact.id).count() == 0


def test_contacts_import_update_existing_matches_by_nombre(db, client, admin_user, login_as, make_contact):
    make_contact(nombre='Gotrek Gurnisson')

    xlsx = _build_xlsx([['Gotrek Gurnisson', 'Si', '']])
    login_as(client, admin_user, 'adminpass123')

    client.post('/admin/contactos/importar',
               data={'file': (xlsx, 'contacts.xlsx'), 'update_existing': 'on'},
               content_type='multipart/form-data', follow_redirects=True)

    assert Contact.query.count() == 1
    assert Contact.query.first().es_untersuchung is True


def test_contacts_export_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/admin/contactos/exportar')
    assert resp.status_code == 403


def test_contacts_export_returns_xlsx(client, admin_user, login_as, make_contact):
    make_contact(nombre='Gotrek')
    login_as(client, admin_user, 'adminpass123')

    resp = client.post('/admin/contactos/exportar', data={}, follow_redirects=True)
    assert resp.status_code == 200
    assert resp.mimetype == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

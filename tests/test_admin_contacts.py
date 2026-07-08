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
        'nombre': 'Nombre corregido', 'es_untersuchung': 'on', 'profession_ids': [str(prof.id)],
    }, follow_redirects=True)
    assert resp.status_code == 200

    db.session.refresh(contact)
    assert contact.nombre == 'Nombre corregido'
    assert contact.es_untersuchung is True
    assert ContactProfession.query.filter_by(contact_id=contact.id, profession_id=prof.id).first() is not None


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


def test_admin_contacts_listing_shows_nombre(client, admin_user, login_as, make_contact):
    contact = make_contact(nombre='Gotrek Gurnisson')
    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/admin/contactos')
    assert b'Gotrek Gurnisson' in resp.data


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

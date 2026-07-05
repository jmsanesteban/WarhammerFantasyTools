"""Tests for admin-only Contacts management: field definitions (EAV),
personas (vínculos) CRUD, contact admin listing/toggle/delete, persona
linking as admin, and Excel import/export."""
import io
import openpyxl
from app.models.contact import FieldDefinition, Contact, ContactValue
from app.models.contact_persona import ContactPersona, ContactPersonaLink


# ── Field definitions ────────────────────────────────────────────────────────

def test_contact_fields_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/admin/contactos/campos')
    assert resp.status_code == 403


def test_create_field(db, client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    resp = client.post('/admin/contactos/campos/nuevo', data={'display_name': 'Teléfono'},
                       follow_redirects=True)
    assert resp.status_code == 200
    field = FieldDefinition.query.filter_by(name='teléfono').first()
    assert field is not None
    assert field.display_name == 'Teléfono'


def test_create_field_rejects_empty_name(client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    client.post('/admin/contactos/campos/nuevo', data={'display_name': '  '})
    assert FieldDefinition.query.count() == 0


def test_create_field_rejects_duplicate_internal_name(client, admin_user, login_as, make_contact_field):
    make_contact_field(name='teléfono', display_name='Teléfono')
    login_as(client, admin_user, 'adminpass123')
    client.post('/admin/contactos/campos/nuevo', data={'display_name': 'Teléfono'})
    assert FieldDefinition.query.filter_by(name='teléfono').count() == 1


def test_rename_field(db, client, admin_user, login_as, make_contact_field):
    field = make_contact_field(name='nombre', display_name='Nombre')
    login_as(client, admin_user, 'adminpass123')
    client.post(f'/admin/contactos/campos/{field.id}/renombrar', data={'display_name': 'Nombre completo'},
               follow_redirects=True)
    db.session.refresh(field)
    assert field.display_name == 'Nombre completo'


def test_toggle_field_visibility(client, admin_user, login_as, make_contact_field):
    field = make_contact_field(name='nombre', display_name='Nombre', is_visible=True)
    login_as(client, admin_user, 'adminpass123')
    resp = client.post(f'/admin/contactos/campos/{field.id}/toggle')
    assert resp.status_code == 200
    assert resp.get_json() == {'visible': False}


def test_delete_field_cascades_values(db, client, admin_user, login_as, make_contact_field, make_contact):
    field = make_contact_field(name='nombre', display_name='Nombre')
    make_contact(values={field.id: 'Gotrek'})
    field_id = field.id

    login_as(client, admin_user, 'adminpass123')
    client.post(f'/admin/contactos/campos/{field_id}/eliminar', follow_redirects=True)

    assert db.session.get(FieldDefinition, field_id) is None
    assert ContactValue.query.filter_by(field_id=field_id).count() == 0


def test_reorder_fields(db, client, admin_user, login_as, make_contact_field):
    f1 = make_contact_field(name='a', display_name='A', field_order=0)
    f2 = make_contact_field(name='b', display_name='B', field_order=1)
    login_as(client, admin_user, 'adminpass123')

    resp = client.post('/admin/contactos/campos/reordenar', json={'order': [f2.id, f1.id]})
    assert resp.status_code == 200
    db.session.refresh(f1)
    db.session.refresh(f2)
    assert f2.field_order == 0
    assert f1.field_order == 1


# ── Personas (vínculos) CRUD ─────────────────────────────────────────────────

def test_contact_personas_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/admin/personas')
    assert resp.status_code == 403


def test_create_persona(db, client, admin_user, regular_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    resp = client.post('/admin/personas/nueva', data={
        'name': 'Contacto de Juego', 'user_id': str(regular_user.id), 'is_active': 'on',
    }, follow_redirects=True)
    assert resp.status_code == 200

    persona = ContactPersona.query.filter_by(name='Contacto de Juego').first()
    assert persona is not None
    assert persona.user_id == regular_user.id
    assert persona.is_active is True


def test_create_persona_requires_name(client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    client.post('/admin/personas/nueva', data={'name': ''})
    assert ContactPersona.query.count() == 0


def test_edit_persona(db, client, admin_user, login_as, make_contact_persona):
    persona = make_contact_persona(name='Original')
    login_as(client, admin_user, 'adminpass123')
    client.post(f'/admin/personas/{persona.id}/editar', data={
        'name': 'Renombrado', 'user_id': '0',
    }, follow_redirects=True)
    db.session.refresh(persona)
    assert persona.name == 'Renombrado'
    assert persona.user_id is None


def test_delete_persona(db, client, admin_user, login_as, make_contact_persona):
    persona = make_contact_persona(name='Descartable')
    persona_id = persona.id
    login_as(client, admin_user, 'adminpass123')
    client.post(f'/admin/personas/{persona_id}/eliminar', follow_redirects=True)
    assert db.session.get(ContactPersona, persona_id) is None


# ── Admin contact listing/toggle/delete ─────────────────────────────────────

def test_admin_contacts_listing_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/admin/contactos')
    assert resp.status_code == 403


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


# ── Admin persona linking ───────────────────────────────────────────────────

def test_admin_link_persona_to_contact(db, client, admin_user, login_as, make_contact, make_contact_persona):
    contact = make_contact()
    persona = make_contact_persona(name='Vínculo')
    login_as(client, admin_user, 'adminpass123')

    client.post(f'/admin/contactos/{contact.id}/persona/vincular',
               data={'persona_id': str(persona.id), 'relationship': 'Contacto de negocios'},
               follow_redirects=True)

    link = ContactPersonaLink.query.filter_by(persona_id=persona.id, contact_id=contact.id).first()
    assert link is not None
    assert link.relationship_note == 'Contacto de negocios'


def test_admin_update_persona_relationship(db, client, admin_user, login_as, make_contact, make_contact_persona):
    contact = make_contact()
    persona = make_contact_persona(name='Vínculo')
    db.session.add(ContactPersonaLink(persona_id=persona.id, contact_id=contact.id, relationship_note='Antiguo'))
    db.session.commit()

    login_as(client, admin_user, 'adminpass123')
    client.post(f'/admin/contactos/{contact.id}/persona/{persona.id}/relacion',
               data={'relationship': 'Actualizado'}, follow_redirects=True)

    link = ContactPersonaLink.query.filter_by(persona_id=persona.id, contact_id=contact.id).first()
    assert link.relationship_note == 'Actualizado'


def test_admin_unlink_persona(db, client, admin_user, login_as, make_contact, make_contact_persona):
    contact = make_contact()
    persona = make_contact_persona(name='Vínculo')
    db.session.add(ContactPersonaLink(persona_id=persona.id, contact_id=contact.id))
    db.session.commit()

    login_as(client, admin_user, 'adminpass123')
    client.post(f'/admin/contactos/{contact.id}/persona/{persona.id}/desvincular', follow_redirects=True)

    assert ContactPersonaLink.query.filter_by(persona_id=persona.id, contact_id=contact.id).first() is None


# ── Excel import/export ──────────────────────────────────────────────────────

def _build_xlsx(rows, headers=('Nombre', 'Apellidos', 'Email')):
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


def test_contacts_import_creates_fields_and_contacts(db, client, admin_user, login_as):
    xlsx = _build_xlsx([['Gotrek', 'Gurnisson', 'gotrek@example.com']])
    login_as(client, admin_user, 'adminpass123')

    resp = client.post('/admin/contactos/importar',
                       data={'file': (xlsx, 'contacts.xlsx')},
                       content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200

    assert FieldDefinition.query.filter_by(name='nombre').first() is not None
    assert FieldDefinition.query.filter_by(name='email').first() is not None
    assert Contact.query.count() == 1
    field = FieldDefinition.query.filter_by(name='nombre').first()
    value = ContactValue.query.filter_by(field_id=field.id).first()
    assert value.value == 'Gotrek'


def test_contacts_import_update_existing_matches_by_name(db, client, admin_user, login_as, make_contact_field, make_contact):
    nombre = make_contact_field(name='nombre', display_name='Nombre', field_order=0)
    apellidos = make_contact_field(name='apellidos', display_name='Apellidos', field_order=1)
    make_contact(values={nombre.id: 'gotrek', apellidos.id: 'gurnisson'})

    xlsx = _build_xlsx([['Gotrek', 'Gurnisson', 'nuevo@example.com']])
    login_as(client, admin_user, 'adminpass123')

    client.post('/admin/contactos/importar',
               data={'file': (xlsx, 'contacts.xlsx'), 'update_existing': 'on'},
               content_type='multipart/form-data', follow_redirects=True)

    assert Contact.query.count() == 1


def test_contacts_export_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/admin/contactos/exportar')
    assert resp.status_code == 403


def test_contacts_export_returns_xlsx(client, admin_user, login_as, make_contact_field, make_contact):
    field = make_contact_field(name='nombre', display_name='Nombre')
    make_contact(values={field.id: 'Gotrek'})
    login_as(client, admin_user, 'adminpass123')

    resp = client.post('/admin/contactos/exportar', data={}, follow_redirects=True)
    assert resp.status_code == 200
    assert resp.mimetype == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

"""Tests for the admin backup routes (Usuarios, Personajes, Plantillas de
permisos, Sinónimos, Contactos+Vínculos, Backup completo) - all admin-only.
The underlying export/import logic itself is covered exhaustively in
tests/test_backup_service.py; these tests focus on route wiring, permission
gating, and the JSON download/upload plumbing."""
import io
import json

from app.models.user import User
from app.models.character import Character
from app.models.profession import Profession
from app.models.permission import PermissionTemplate
from app.models.synonym import Synonym
from app.models.contact import Contact
from app.models.equipment import EquipmentItem


def _upload(client, url, payload, mode='skip'):
    return client.post(url, data={
        'file': (io.BytesIO(json.dumps(payload).encode('utf-8')), 'data.json'),
        'mode': mode,
    }, content_type='multipart/form-data', follow_redirects=True)


# ── Usuarios ─────────────────────────────────────────────────────────────────

def test_users_export_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/admin/usuarios/exportar')
    assert resp.status_code == 403


def test_users_export_import_round_trip(db, client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/admin/usuarios/exportar')
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert any(u['username'] == 'admin1' for u in data)
    assert not any('password' in u for u in data)

    resp = _upload(client, '/admin/usuarios/importar', [{
        'username': 'zz_new_user', 'email': 'zz_new@example.com', 'role': 'user',
        'active': True, 'must_change_password': False, 'template_name': None,
        'direct_permission_codes': [], 'created_by_username': None,
    }])
    assert resp.status_code == 200
    user = User.query.filter_by(username='zz_new_user').first()
    assert user is not None
    assert user.must_change_password is True


# ── Personajes ───────────────────────────────────────────────────────────────

def test_characters_export_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/admin/personajes/exportar')
    assert resp.status_code == 403


def test_characters_export_import_round_trip(db, client, admin_user, regular_user, make_character, login_as):
    make_character(regular_user, name='Grimm')
    login_as(client, admin_user, 'adminpass123')

    resp = client.get('/admin/personajes/exportar')
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert any(c['name'] == 'Grimm' for c in data)

    Character.query.delete()
    db.session.commit()

    resp = _upload(client, '/admin/personajes/importar', data)
    assert resp.status_code == 200
    assert Character.query.filter_by(name='Grimm').first() is not None


# ── Plantillas de permisos ──────────────────────────────────────────────────

def test_permission_templates_export_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/admin/plantillas/exportar')
    assert resp.status_code == 403


def test_permission_templates_export_import_round_trip(db, client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/admin/plantillas/exportar')
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert any(t['name'] == 'Editor' for t in data)

    for t in PermissionTemplate.query.all():
        db.session.delete(t)
    db.session.commit()

    resp = _upload(client, '/admin/plantillas/importar', data)
    assert resp.status_code == 200
    assert PermissionTemplate.query.filter_by(name='Editor').first() is not None


# ── Sinónimos ────────────────────────────────────────────────────────────────

def test_synonyms_export_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/admin/synonyms/exportar')
    assert resp.status_code == 403


def test_synonyms_export_import_round_trip(db, client, admin_user, login_as):
    with client.application.app_context():
        db.session.add(Synonym(source='ejemplo', target='Ejemplo Correcto', is_prefix=False))
        db.session.commit()

    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/admin/synonyms/exportar')
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert any(s['source'] == 'ejemplo' for s in data)

    Synonym.query.delete()
    db.session.commit()

    resp = _upload(client, '/admin/synonyms/importar', data)
    assert resp.status_code == 200
    assert Synonym.query.filter_by(source='ejemplo').first() is not None


# ── Contactos + Vínculos ─────────────────────────────────────────────────────

def test_contacts_full_export_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/admin/vinculos/exportar')
    assert resp.status_code == 403


def test_contacts_full_export_import_round_trip(db, client, admin_user, regular_user, make_character,
                                                 make_contact, make_contact_link, login_as):
    char = make_character(regular_user, name='Grimm')
    contact = make_contact(nombre='Hans')
    make_contact_link(char, contact, nivel=2)

    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/admin/vinculos/exportar')
    assert resp.status_code == 200
    data = json.loads(resp.data)
    row = next(r for r in data if r['nombre'] == 'Hans')
    assert row['links'][0]['character_name'] == 'Grimm'

    from app.models.contact_character_link import ContactCharacterLink
    for link in ContactCharacterLink.query.all():
        db.session.delete(link)
    for c in Contact.query.all():
        db.session.delete(c)
    db.session.commit()

    resp = _upload(client, '/admin/vinculos/importar', data)
    assert resp.status_code == 200
    restored = Contact.query.filter_by(nombre='Hans').first()
    assert restored is not None
    assert restored.character_links[0].nivel == 2


# ── Backup completo ──────────────────────────────────────────────────────────

def test_backup_home_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/admin/backup')
    assert resp.status_code == 403


def test_backup_export_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.post('/admin/backup/exportar')
    assert resp.status_code == 403


def test_backup_export_returns_all_sections(app, client, admin_user, make_profession, make_equipment_item,
                                             login_as, tmp_path):
    app.config['BACKUP_FOLDER'] = str(tmp_path)
    make_profession(name='Soldado')
    make_equipment_item(name='Daga', category='arma')
    login_as(client, admin_user, 'adminpass123')
    resp = client.post('/admin/backup/exportar')
    assert resp.status_code == 200
    data = json.loads(resp.data)
    for key in ('version', 'exported_at', 'secciones', 'permission_templates', 'synonyms', 'users',
                'professions', 'equipment', 'characters', 'contacts'):
        assert key in data
    assert any(p['name'] == 'Soldado' for p in data['professions'])
    assert any(e['name'] == 'Daga' for e in data['equipment'])


def test_backup_export_selective_sections_only(app, client, admin_user, make_profession, login_as, tmp_path):
    app.config['BACKUP_FOLDER'] = str(tmp_path)
    make_profession(name='Soldado')
    login_as(client, admin_user, 'adminpass123')

    resp = client.post('/admin/backup/exportar', data={'secciones': ['professions']})
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data['secciones'] == ['professions']
    assert 'professions' in data
    assert 'users' not in data
    assert 'characters' not in data


def test_backup_export_saves_a_file_listed_on_the_page(app, client, admin_user, login_as, tmp_path):
    app.config['BACKUP_FOLDER'] = str(tmp_path)
    login_as(client, admin_user, 'adminpass123')

    resp = client.post('/admin/backup/exportar', data={'secciones': ['professions']})
    assert resp.status_code == 200

    import os
    saved = os.listdir(str(tmp_path))
    assert len(saved) == 1
    assert saved[0].startswith('wft_backup_') and saved[0].endswith('.json')

    resp = client.get('/admin/backup')
    assert resp.status_code == 200
    assert saved[0].encode('utf-8') in resp.data


def test_backup_download_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/admin/backup/archivos/anything.json/descargar')
    assert resp.status_code == 403


def test_backup_download_rejects_path_traversal(app, client, admin_user, login_as, tmp_path):
    app.config['BACKUP_FOLDER'] = str(tmp_path)
    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/admin/backup/archivos/..%2F..%2Fapp/descargar')
    assert resp.status_code == 404


def test_backup_download_serves_a_saved_file(app, client, admin_user, login_as, tmp_path):
    app.config['BACKUP_FOLDER'] = str(tmp_path)
    login_as(client, admin_user, 'adminpass123')
    client.post('/admin/backup/exportar', data={'secciones': ['professions']})

    import os
    filename = os.listdir(str(tmp_path))[0]
    resp = client.get(f'/admin/backup/archivos/{filename}/descargar')
    assert resp.status_code == 200
    assert json.loads(resp.data)['secciones'] == ['professions']


def test_backup_view_shows_record_counts_per_section(app, client, admin_user, make_profession, login_as, tmp_path):
    app.config['BACKUP_FOLDER'] = str(tmp_path)
    make_profession(name='Soldado')
    make_profession(name='Mago')
    login_as(client, admin_user, 'adminpass123')
    client.post('/admin/backup/exportar', data={'secciones': ['professions']})

    import os
    filename = os.listdir(str(tmp_path))[0]
    resp = client.get(f'/admin/backup/archivos/{filename}/ver')
    assert resp.status_code == 200
    assert 'Profesiones'.encode('utf-8') in resp.data
    assert b'2' in resp.data  # two professions in this partial backup


def test_backup_compress_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.post('/admin/backup/archivos/anything.json/comprimir')
    assert resp.status_code == 403


def test_backup_compress_shrinks_file_and_stays_readable(app, client, admin_user, make_profession, login_as, tmp_path):
    app.config['BACKUP_FOLDER'] = str(tmp_path)
    make_profession(name='Soldado')
    login_as(client, admin_user, 'adminpass123')
    client.post('/admin/backup/exportar', data={'secciones': ['professions']})

    import os
    original_filename = os.listdir(str(tmp_path))[0]
    resp = client.post(f'/admin/backup/archivos/{original_filename}/comprimir', follow_redirects=True)
    assert resp.status_code == 200

    files = os.listdir(str(tmp_path))
    assert files == [original_filename + '.gz']

    # Still viewable/downloadable/re-importable as plain JSON despite being
    # stored gzipped on disk.
    resp = client.get(f'/admin/backup/archivos/{original_filename}.gz/ver')
    assert resp.status_code == 200
    assert 'Profesiones'.encode('utf-8') in resp.data

    resp = client.get(f'/admin/backup/archivos/{original_filename}.gz/descargar')
    assert resp.status_code == 200
    assert json.loads(resp.data)['secciones'] == ['professions']

    resp = client.get('/admin/backup')
    assert resp.status_code == 200
    assert 'Comprimido'.encode('utf-8') in resp.data


def test_backup_compress_twice_is_a_noop(app, client, admin_user, login_as, tmp_path):
    app.config['BACKUP_FOLDER'] = str(tmp_path)
    login_as(client, admin_user, 'adminpass123')
    client.post('/admin/backup/exportar', data={'secciones': ['professions']})

    import os
    filename = os.listdir(str(tmp_path))[0]
    client.post(f'/admin/backup/archivos/{filename}/comprimir')
    gz_filename = filename + '.gz'

    resp = client.post(f'/admin/backup/archivos/{gz_filename}/comprimir', follow_redirects=True)
    assert resp.status_code == 200
    assert os.listdir(str(tmp_path)) == [gz_filename]  # untouched, not double-compressed


def test_backup_delete_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.post('/admin/backup/archivos/anything.json/eliminar')
    assert resp.status_code == 403


def test_backup_delete_removes_the_file(app, client, admin_user, login_as, tmp_path):
    app.config['BACKUP_FOLDER'] = str(tmp_path)
    login_as(client, admin_user, 'adminpass123')
    client.post('/admin/backup/exportar', data={'secciones': ['professions']})

    import os
    filename = os.listdir(str(tmp_path))[0]
    resp = client.post(f'/admin/backup/archivos/{filename}/eliminar', follow_redirects=True)
    assert resp.status_code == 200
    assert os.listdir(str(tmp_path)) == []


def test_backup_delete_rejects_path_traversal(app, client, admin_user, login_as, tmp_path):
    app.config['BACKUP_FOLDER'] = str(tmp_path)
    login_as(client, admin_user, 'adminpass123')
    resp = client.post('/admin/backup/archivos/..%2F..%2Fapp/eliminar')
    assert resp.status_code == 404


def test_backup_import_restores_everything(db, app, client, admin_user, regular_user, make_character,
                                            make_profession, make_equipment_item, login_as, tmp_path):
    app.config['BACKUP_FOLDER'] = str(tmp_path)
    make_profession(name='Soldado')
    make_equipment_item(name='Daga', category='arma')
    make_character(regular_user, name='Grimm')
    login_as(client, admin_user, 'adminpass123')

    resp = client.post('/admin/backup/exportar')
    data = json.loads(resp.data)

    Character.query.delete()
    Profession.query.delete()
    EquipmentItem.query.delete()
    db.session.commit()

    resp = client.post('/admin/backup/importar', data={
        'file': (io.BytesIO(json.dumps(data).encode('utf-8')), 'backup.json'), 'mode': 'skip',
    }, content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200
    assert Profession.query.filter_by(name='Soldado').first() is not None
    assert EquipmentItem.query.filter_by(name='Daga').first() is not None
    assert Character.query.filter_by(name='Grimm').first() is not None
    body = resp.data.decode('utf-8')
    assert 'Equipamiento' in body


def test_dashboard_food_card_has_direct_import_export_links(client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/admin/')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    assert '/admin/comida/exportar' in body
    assert '/admin/comida/importar' in body

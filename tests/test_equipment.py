"""Tests for the equipment catalog: listing/filters, detail, CRUD, permission
gating, image upload (weapons/armour only), custom fields, and JSON
export/import."""
import io
import json
import os

from app.models.equipment import EquipmentItem
from app.models.permission import Permission


def _grant(db, user, code):
    user.direct_permissions.append(db.session.get(Permission, code))
    db.session.commit()


# ── Listing / filters ────────────────────────────────────────────────────────

def test_list_is_public(client, make_equipment_item):
    make_equipment_item(name='Daga')
    resp = client.get('/equipamiento/')
    assert resp.status_code == 200
    assert b'Daga' in resp.data


def test_list_filters_by_category(client, make_equipment_item):
    make_equipment_item(name='Daga', category='arma')
    make_equipment_item(name='Gorro Acolchado', category='armadura')
    resp = client.get('/equipamiento/?category=armadura')
    assert b'Gorro Acolchado' in resp.data
    assert b'Daga' not in resp.data


def test_list_filters_by_subcategory(client, make_equipment_item):
    make_equipment_item(name='Daga', category='arma', subcategory='cuerpo_a_cuerpo')
    make_equipment_item(name='Arco Corto', category='arma', subcategory='distancia')
    resp = client.get('/equipamiento/?subcategory=distancia')
    assert b'Arco Corto' in resp.data
    assert b'Daga' not in resp.data


def test_list_filters_by_quality(client, make_equipment_item):
    make_equipment_item(name='Ropa Harapienta', category='ropa', quality='mala')
    make_equipment_item(name='Ropa Noble', category='ropa', quality='excelente')
    resp = client.get('/equipamiento/?quality=excelente')
    assert b'Ropa Noble' in resp.data
    assert b'Ropa Harapienta' not in resp.data


def test_list_filters_by_search(client, make_equipment_item):
    make_equipment_item(name='Daga')
    make_equipment_item(name='Espada')
    resp = client.get('/equipamiento/?q=Dag')
    assert b'Daga' in resp.data
    assert b'Espada' not in resp.data


# ── Detail ───────────────────────────────────────────────────────────────────

def test_detail_is_public(client, make_equipment_item):
    item = make_equipment_item(name='Daga', stats={'daño': '1D6+1'}, description='Lanzable.')
    resp = client.get(f'/equipamiento/{item.id}')
    assert resp.status_code == 200
    assert b'Daga' in resp.data
    assert 'Lanzable.'.encode('utf-8') in resp.data


def test_detail_404_for_unknown_item(client):
    resp = client.get('/equipamiento/99999')
    assert resp.status_code == 404


def test_detail_shows_base_item_link_for_special_items(client, make_equipment_item):
    base = make_equipment_item(name='Espada')
    special = make_equipment_item(name='Espada Flamigera', is_special=True, base_item_id=base.id)
    resp = client.get(f'/equipamiento/{special.id}')
    assert resp.status_code == 200
    assert b'Espada' in resp.data


# ── Permission gating ────────────────────────────────────────────────────────

def test_create_requires_login(client):
    resp = client.get('/equipamiento/nuevo')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_create_requires_permission(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/equipamiento/nuevo')
    assert resp.status_code == 403


# ── Create / edit ────────────────────────────────────────────────────────────

def test_create_item_with_permission(db, client, regular_user, login_as):
    _grant(db, regular_user, 'equipment.edit')
    login_as(client, regular_user, 'userpass123')

    resp = client.post('/equipamiento/nuevo', data={
        'name': 'Maza', 'category': 'arma', 'subcategory': 'cuerpo_a_cuerpo',
        'price_text': '10 CO',
        'stat_key': ['daño', 'aguante'], 'stat_value': ['1D8', '50%'],
    }, follow_redirects=True)
    assert resp.status_code == 200

    item = EquipmentItem.query.filter_by(name='Maza').first()
    assert item is not None
    assert item.created_by_id == regular_user.id
    assert item.status == 'admin'
    assert item.stats == {'daño': '1D8', 'aguante': '50%'}


def test_edit_item_updates_custom_fields(db, client, admin_user, login_as, make_equipment_item):
    item = make_equipment_item(name='Daga', category='arma')
    login_as(client, admin_user, 'adminpass123')

    resp = client.post(f'/equipamiento/{item.id}/editar', data={
        'name': 'Daga', 'category': 'arma',
        'custom_key': ['peso'], 'custom_value': ['0.5u'],
    }, follow_redirects=True)
    assert resp.status_code == 200

    db.session.refresh(item)
    assert item.custom_fields == {'peso': '0.5u'}


def test_image_upload_allowed_for_weapon(db, client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    resp = client.post('/equipamiento/nuevo', data={
        'name': 'Espadón', 'category': 'arma',
        'image': (io.BytesIO(b'fake png bytes'), 'espadon.png'),
    }, content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200

    item = EquipmentItem.query.filter_by(name='Espadón').first()
    assert item.image_path == os.path.join('equipamiento', 'espadon.png')


def test_image_ignored_for_clothing(db, client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    resp = client.post('/equipamiento/nuevo', data={
        'name': 'Gorro', 'category': 'ropa',
        'image': (io.BytesIO(b'fake png bytes'), 'gorro.png'),
    }, content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200

    item = EquipmentItem.query.filter_by(name='Gorro').first()
    assert item.image_path is None


def test_delete_requires_permission(client, regular_user, login_as, make_equipment_item):
    item = make_equipment_item(name='Daga')
    login_as(client, regular_user, 'userpass123')
    resp = client.post(f'/equipamiento/{item.id}/eliminar')
    assert resp.status_code == 403


def test_delete_item(db, client, admin_user, login_as, make_equipment_item):
    item = make_equipment_item(name='Daga')
    login_as(client, admin_user, 'adminpass123')
    resp = client.post(f'/equipamiento/{item.id}/eliminar', follow_redirects=True)
    assert resp.status_code == 200
    assert EquipmentItem.query.filter_by(name='Daga').first() is None


# ── Backup: exportar/importar ────────────────────────────────────────────────

def test_export_requires_permission(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/equipamiento/exportar')
    assert resp.status_code == 403


def test_export_returns_json(db, client, admin_user, login_as, make_equipment_item):
    make_equipment_item(name='Daga', stats={'daño': '1D6+1'})
    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/equipamiento/exportar')
    assert resp.status_code == 200
    assert resp.mimetype == 'application/json'

    data = json.loads(resp.data)
    row = next(r for r in data if r['name'] == 'Daga')
    assert row['stats'] == {'daño': '1D6+1'}


def test_import_creates_items_from_json(db, client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    payload = json.dumps([{
        'name': 'Maza Importada', 'category': 'arma', 'subcategory': None,
        'quality': None, 'is_special': False, 'price_text': '10 CO',
        'image_path': None, 'description': None, 'stats': {'daño': '1D8'},
        'custom_fields': None, 'source_book': 'Armas fantastico Revisada', 'status': 'catalogado',
    }]).encode('utf-8')

    resp = client.post('/equipamiento/importar', data={
        'file': (io.BytesIO(payload), 'equipamiento.json'),
        'mode': 'skip',
    }, content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200

    item = EquipmentItem.query.filter_by(name='Maza Importada').first()
    assert item is not None
    assert item.stats == {'daño': '1D8'}


def test_import_wires_base_item_by_name_and_category(db, client, admin_user, login_as, make_equipment_item):
    make_equipment_item(name='Espada', category='arma')
    login_as(client, admin_user, 'adminpass123')

    payload = json.dumps([{
        'name': 'Espada Flamigera', 'category': 'arma', 'subcategory': None,
        'quality': None, 'is_special': True, 'price_text': None,
        'image_path': None, 'description': 'Mágica.', 'stats': None,
        'custom_fields': None, 'source_book': None, 'status': 'catalogado',
        'base_item_name': 'Espada', 'base_item_category': 'arma',
    }]).encode('utf-8')

    resp = client.post('/equipamiento/importar', data={
        'file': (io.BytesIO(payload), 'equipamiento.json'),
        'mode': 'skip',
    }, content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200

    special = EquipmentItem.query.filter_by(name='Espada Flamigera').first()
    assert special is not None
    assert special.base_item is not None
    assert special.base_item.name == 'Espada'

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


# ── Per-category menus ───────────────────────────────────────────────────────

def test_category_route_shows_only_that_category(client, make_equipment_item):
    make_equipment_item(name='Daga', category='arma')
    make_equipment_item(name='Gorro Acolchado', category='armadura')
    resp = client.get('/equipamiento/armaduras')
    assert resp.status_code == 200
    assert b'Gorro Acolchado' in resp.data
    assert b'Daga' not in resp.data


def test_category_route_header_shows_category_context(client):
    resp = client.get('/equipamiento/armas')
    assert 'Equipamiento — Arma'.encode('utf-8') in resp.data


def test_category_route_hides_category_dropdown(client):
    resp = client.get('/equipamiento/armas')
    assert b'name="category"' not in resp.data


def test_full_catalog_keeps_category_dropdown(client):
    resp = client.get('/equipamiento/')
    assert b'name="category"' in resp.data


def test_category_route_still_respects_other_filters(client, make_equipment_item):
    make_equipment_item(name='Daga', category='arma', subcategory='cuerpo_a_cuerpo')
    make_equipment_item(name='Arco Corto', category='arma', subcategory='distancia')
    resp = client.get('/equipamiento/armas?subcategory=distancia')
    assert b'Arco Corto' in resp.data
    assert b'Daga' not in resp.data


# ── Quality-dynamic display (armas/armaduras) ───────────────────────────────

def test_quality_filter_does_not_hide_weapons(client, make_equipment_item):
    """Arma/armadura rows never have `quality` set (it's a purchase-time
    modifier, not a catalog attribute) - filtering by quality used to zero
    out the whole list; now it should keep showing the same rows."""
    make_equipment_item(name='Daga', category='arma')
    resp = client.get('/equipamiento/armas?quality=mala')
    assert resp.status_code == 200
    assert b'Daga' in resp.data


def test_quality_filter_shows_adjusted_stats_and_price(client, make_equipment_item):
    make_equipment_item(name='Daga', category='arma', price_text='4 CO', precio_peniques=960,
                         stats={'daño': '1D6+1', 'aguante': '40%', 'parada': '-10%'})
    resp = client.get('/equipamiento/armas?quality=mala')
    body = resp.data.decode('utf-8')
    assert '1D6' in body and '1D6+1' not in body  # -1 daño: "1D6+1" -> "1D6"
    assert '35%' in body  # -5% aguante: 40% -> 35%
    assert '-15%' in body  # -5% al uso acumulado sobre el -10% propio


def test_quality_filter_leaves_ropa_untouched(client, make_equipment_item):
    """Ropa's quality IS the row - filtering by it should behave exactly as
    before (only rows of that literal quality)."""
    make_equipment_item(name='Ropa Harapienta', category='ropa', quality='mala')
    make_equipment_item(name='Ropa Noble', category='ropa', quality='excelente')
    resp = client.get('/equipamiento/ropa?quality=mala')
    assert b'Ropa Harapienta' in resp.data
    assert b'Ropa Noble' not in resp.data


def test_ammo_stats_never_adjusted_by_quality(client, make_equipment_item):
    make_equipment_item(name='Flecha/virote común', category='arma', subcategory='municion',
                         stats={'uso': '-', 'daño': '-'})
    resp = client.get('/equipamiento/armas?quality=excelente')
    assert resp.status_code == 200  # renders fine, no crash from stats_for_quality on ammo


def test_ammo_card_never_shows_quality_badge(client, make_equipment_item):
    """Ammo is always manufactured "normal" - the quality filter on the
    catalog page shouldn't tag ammo cards with a calidad they don't have."""
    make_equipment_item(name='Flecha/virote común', category='arma', subcategory='municion')
    resp = client.get('/equipamiento/armas?quality=excelente')
    assert 'Calidad: Excelente'.encode('utf-8') not in resp.data


def test_ammo_detail_never_shows_quality_badge(client, make_equipment_item):
    item = make_equipment_item(name='Flecha/virote común', category='arma', subcategory='municion')
    resp = client.get(f'/equipamiento/{item.id}?quality=excelente')
    assert 'Calidad: Excelente'.encode('utf-8') not in resp.data


def test_detail_shows_quality_adjusted_stats(client, make_equipment_item):
    item = make_equipment_item(name='Daga', category='arma', stats={'daño': '1D6+1', 'aguante': '40%'})
    resp = client.get(f'/equipamiento/{item.id}?quality=excelente')
    body = resp.data.decode('utf-8')
    assert '1D6+2' in body  # +1 daño: "1D6+1" -> "1D6+2"
    assert '45%' in body  # +5% aguante: 40% -> 45%


# ── stats_for_quality / adjust_*_stat helpers (model-level) ─────────────────

def test_stats_for_quality_accumulates_on_own_modifier():
    item = EquipmentItem(name='Daga', category='arma',
                          stats={'daño': '1D6+1', 'aguante': '40%', 'parada': '-10%', 'ataque': '-'})
    mala = item.stats_for_quality('mala')
    assert mala['daño'] == '1D6'
    assert mala['aguante'] == '35%'
    assert mala['parada'] == '-15%'
    assert mala['ataque'] == '-5%'  # own modifier was "-" (0), quality fills it in

    excelente = item.stats_for_quality('excelente')
    assert excelente['daño'] == '1D6+2'
    assert excelente['aguante'] == '45%'
    assert excelente['parada'] == '-5%'


def test_stats_for_quality_buena_has_no_stat_change():
    item = EquipmentItem(name='Espada', category='arma', stats={'daño': '1D10', 'aguante': '50%'})
    buena = item.stats_for_quality('buena')
    assert buena == item.stats


def test_stats_for_quality_leaves_unparseable_fields_untouched():
    item = EquipmentItem(name='Maza de guerra', category='arma', stats={'daño': '1D10 + 1D4'})
    mala = item.stats_for_quality('mala')
    assert mala['daño'] == '1D10 + 1D4'  # compound dice, no flat bonus to adjust - left as-is


def test_stats_for_quality_none_returns_full_grouped_view_for_armadura():
    """"Toda calidad" (no quality picked) keeps showing the M/N/B/E summary."""
    item = EquipmentItem(name='Gorro Acolchado', category='armadura',
                          stats={'armadura': 1, 'agilidad_por_calidad': {'mala': '-3', 'normal': '-2',
                                                                          'buena': '-2', 'excelente': '-1'}})
    assert item.stats_for_quality(None) == item.stats


def test_stats_for_quality_collapses_agilidad_por_calidad_for_armadura():
    """Once a specific quality is picked, only that quality's own agilidad
    value is relevant - not the whole M/N/B/E table."""
    item = EquipmentItem(name='Gorro Acolchado', category='armadura',
                          stats={'armadura': 1, 'agilidad_por_calidad': {'mala': '-3', 'normal': '-2',
                                                                          'buena': '-2', 'excelente': '-1'}})
    adjusted = item.stats_for_quality('excelente')
    assert adjusted['agilidad'] == '-1'
    assert 'agilidad_por_calidad' not in adjusted
    assert adjusted['armadura'] == 1
    # original stats untouched
    assert 'agilidad_por_calidad' in item.stats


def test_stats_for_quality_leaves_shields_unchanged():
    """Shields' agilidad is already a single value (not per-quality)."""
    item = EquipmentItem(name='Torre', category='armadura', subcategory='escudos', stats={'agilidad': '-15'})
    assert item.stats_for_quality('mala') == item.stats


# ── peso_for_quality ─────────────────────────────────────────────────────────

def test_peso_for_quality_returns_stored_value_for_non_armadura():
    item = EquipmentItem(name='Daga', category='arma', peso=1.0)
    assert item.peso_for_quality() == 1.0
    assert item.peso_for_quality('excelente') == 1.0  # weapon weight never varies by quality


def test_peso_for_quality_derives_from_agilidad_por_calidad_for_armadura():
    item = EquipmentItem(name='Gorro Acolchado', category='armadura', peso=None,
                          stats={'agilidad_por_calidad': {'mala': '-3', 'normal': '-2',
                                                           'buena': '-2', 'excelente': '-1'}})
    assert item.peso_for_quality('mala') == 3.0
    assert item.peso_for_quality('excelente') == 1.0


def test_peso_for_quality_derives_from_agilidad_for_shields():
    item = EquipmentItem(name='Torre', category='armadura', subcategory='escudos',
                          peso=None, stats={'agilidad': '-15'})
    assert item.peso_for_quality() == 15.0


def test_peso_for_quality_falls_back_to_stored_peso_when_agilidad_is_dash():
    """Rodela has agilidad "-" (genuinely zero in the book) but still has
    real bulk - the book gives it an explicit flat weight instead."""
    item = EquipmentItem(name='Rodela', category='armadura', subcategory='escudos',
                          peso=3.0, stats={'agilidad': '-'})
    assert item.peso_for_quality() == 3.0


def test_peso_for_quality_parses_dual_agilidad_values():
    item = EquipmentItem(name='Perneras', category='armadura', peso=None,
                          stats={'agilidad_por_calidad': {'mala': '-1/-1', 'normal': '-1/-1',
                                                           'buena': '-1/-1', 'excelente': '-1/-1'}})
    assert item.peso_for_quality('normal') == 1.0


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


def test_edit_item_recomputes_batch_pricing_from_price_text(db, client, admin_user, login_as, make_equipment_item):
    item = make_equipment_item(name='Flecha/virote común', category='arma', subcategory='municion')
    login_as(client, admin_user, 'adminpass123')

    resp = client.post(f'/equipamiento/{item.id}/editar', data={
        'name': 'Flecha/virote común', 'category': 'arma', 'subcategory': 'municion',
        'price_text': '1C (5)',
    }, follow_redirects=True)
    assert resp.status_code == 200

    db.session.refresh(item)
    assert item.unidades_por_precio == 5
    assert item.precio_peniques == 12  # 1 chelín in peniques


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


# ── Bulk custom_fields editor ────────────────────────────────────────────────

def test_bulk_fields_requires_permission(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/equipamiento/campos-en-bloque')
    assert resp.status_code == 403


def test_bulk_fields_add_only_touches_items_without_key(db, client, admin_user, login_as, make_equipment_item):
    daga = make_equipment_item(name='Daga', category='arma')
    espada = make_equipment_item(name='Espada', category='arma', custom_fields={'poder_magico': 'ya tenía'})
    login_as(client, admin_user, 'adminpass123')

    resp = client.post('/equipamiento/campos-en-bloque', data={
        'category': 'arma', 'subcategory': '', 'quality': '', 'q': '',
        'mode': 'add', 'add_key': 'poder_magico', 'add_value': 'Nivel 1',
    }, follow_redirects=True)
    assert resp.status_code == 200

    db.session.refresh(daga)
    db.session.refresh(espada)
    assert daga.custom_fields == {'poder_magico': 'Nivel 1'}
    assert espada.custom_fields == {'poder_magico': 'ya tenía'}


def test_bulk_fields_add_with_overwrite_updates_existing(db, client, admin_user, login_as, make_equipment_item):
    espada = make_equipment_item(name='Espada', category='arma', custom_fields={'poder_magico': 'viejo'})
    login_as(client, admin_user, 'adminpass123')

    client.post('/equipamiento/campos-en-bloque', data={
        'category': 'arma', 'subcategory': '', 'quality': '', 'q': '',
        'mode': 'add', 'add_key': 'poder_magico', 'add_value': 'nuevo', 'overwrite': 'on',
    })

    db.session.refresh(espada)
    assert espada.custom_fields == {'poder_magico': 'nuevo'}


def test_bulk_fields_rename_only_affects_items_with_old_key(db, client, admin_user, login_as, make_equipment_item):
    daga = make_equipment_item(name='Daga', category='arma', custom_fields={'poder_magico': 'x'})
    espada = make_equipment_item(name='Espada', category='arma')
    login_as(client, admin_user, 'adminpass123')

    client.post('/equipamiento/campos-en-bloque', data={
        'category': 'arma', 'subcategory': '', 'quality': '', 'q': '',
        'mode': 'rename', 'rename_old_key': 'poder_magico', 'rename_new_key': 'poder_arcano',
    })

    db.session.refresh(daga)
    db.session.refresh(espada)
    assert daga.custom_fields == {'poder_arcano': 'x'}
    assert espada.custom_fields is None


def test_bulk_fields_rename_skips_item_that_already_has_new_key(db, client, admin_user, login_as, make_equipment_item):
    item = make_equipment_item(name='Daga', category='arma',
                                custom_fields={'poder_magico': 'x', 'poder_arcano': 'y'})
    login_as(client, admin_user, 'adminpass123')

    client.post('/equipamiento/campos-en-bloque', data={
        'category': 'arma', 'subcategory': '', 'quality': '', 'q': '',
        'mode': 'rename', 'rename_old_key': 'poder_magico', 'rename_new_key': 'poder_arcano',
    })

    db.session.refresh(item)
    assert item.custom_fields == {'poder_magico': 'x', 'poder_arcano': 'y'}


def test_bulk_fields_delete_only_affects_items_with_key(db, client, admin_user, login_as, make_equipment_item):
    daga = make_equipment_item(name='Daga', category='arma', custom_fields={'peso': '0.5u', 'poder_magico': 'x'})
    espada = make_equipment_item(name='Espada', category='arma')
    login_as(client, admin_user, 'adminpass123')

    client.post('/equipamiento/campos-en-bloque', data={
        'category': 'arma', 'subcategory': '', 'quality': '', 'q': '',
        'mode': 'delete', 'delete_key': 'poder_magico',
    })

    db.session.refresh(daga)
    db.session.refresh(espada)
    assert daga.custom_fields == {'peso': '0.5u'}
    assert espada.custom_fields is None


def test_bulk_fields_respects_filters(db, client, admin_user, login_as, make_equipment_item):
    arma = make_equipment_item(name='Daga', category='arma')
    armadura = make_equipment_item(name='Casco', category='armadura')
    login_as(client, admin_user, 'adminpass123')

    client.post('/equipamiento/campos-en-bloque', data={
        'category': 'arma', 'subcategory': '', 'quality': '', 'q': '',
        'mode': 'add', 'add_key': 'poder_magico', 'add_value': 'x',
    })

    db.session.refresh(arma)
    db.session.refresh(armadura)
    assert arma.custom_fields == {'poder_magico': 'x'}
    assert armadura.custom_fields is None

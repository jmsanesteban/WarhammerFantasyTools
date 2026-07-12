"""Tests for the character equipment shop: quality-based pricing, money
deduction, ropa's per-row pricing, the especial GM-grant-only path, ownership
gating, and purchase-history immutability."""
from app.models.character import Character
from app.models.equipment import EquipmentItem, CharacterInventoryItem, CharacterPurchase


def _login_owner(client, make_user, make_character, login_as, **char_kwargs):
    owner = make_user(username='owner1', password='ownerpass123')
    char = make_character(owner, name='Personaje', **char_kwargs)
    login_as(client, owner, 'ownerpass123')
    return char


# ── Ownership gating ────────────────────────────────────────────────────────

def test_tienda_requires_login(client, make_character, make_user):
    owner = make_user(username='owner1', password='ownerpass123')
    char = make_character(owner, name='Personaje')
    resp = client.get(f'/personajes/{char.id}/tienda')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_tienda_blocks_other_users(client, make_user, make_character, login_as):
    owner = make_user(username='owner1', password='ownerpass123')
    other = make_user(username='other1', password='otherpass123')
    char = make_character(owner, name='Personaje')
    login_as(client, other, 'otherpass123')
    resp = client.get(f'/personajes/{char.id}/tienda')
    assert resp.status_code == 403


def test_inventario_blocks_other_users(client, make_user, make_character, login_as):
    owner = make_user(username='owner1', password='ownerpass123')
    other = make_user(username='other1', password='otherpass123')
    char = make_character(owner, name='Personaje')
    login_as(client, other, 'otherpass123')
    resp = client.get(f'/personajes/{char.id}/inventario')
    assert resp.status_code == 403


def test_historial_blocks_other_users(client, make_user, make_character, login_as):
    owner = make_user(username='owner1', password='ownerpass123')
    other = make_user(username='other1', password='otherpass123')
    char = make_character(owner, name='Personaje')
    login_as(client, other, 'otherpass123')
    resp = client.get(f'/personajes/{char.id}/historial-compras')
    assert resp.status_code == 403


def test_admin_can_buy_for_any_character(client, admin_user, make_user, make_character,
                                          make_equipment_item, login_as):
    player = make_user(username='player1', password='playerpass123')
    char = make_character(player, name='Personaje', dinero_coronas=100)
    item = make_equipment_item(name='Daga', category='arma', quality='normal', precio_peniques=240)

    login_as(client, admin_user, 'adminpass123')
    resp = client.get(f'/personajes/{char.id}/tienda/{item.id}/comprar')
    assert resp.status_code == 200


# ── Tienda listing ───────────────────────────────────────────────────────────

def test_tienda_excludes_especial(client, make_user, make_character, make_equipment_item, login_as):
    char = _login_owner(client, make_user, make_character, login_as)
    make_equipment_item(name='Daga', category='arma')
    make_equipment_item(name='Amuleto raro', category='especial')

    resp = client.get(f'/personajes/{char.id}/tienda')
    assert b'Daga' in resp.data
    assert 'Amuleto raro'.encode('utf-8') not in resp.data


# ── Compra: arma/armadura con multiplicador de calidad ──────────────────────

def test_comprar_arma_normal_quality_deducts_money(db, client, make_user, make_character,
                                                     make_equipment_item, login_as):
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=10)
    item = make_equipment_item(name='Espada', category='arma', precio_peniques=240)  # 1 CO

    resp = client.post(f'/personajes/{char.id}/tienda/{item.id}/comprar', data={
        'quality': 'normal', 'quantity': '1', 'location': 'equipamiento',
    }, follow_redirects=True)
    assert resp.status_code == 200

    db.session.refresh(char)
    assert char.dinero_total_peniques == 9 * 240  # 10 CO - 1 CO

    inv = CharacterInventoryItem.query.filter_by(character_id=char.id).first()
    assert inv is not None
    assert inv.equipment_item_id == item.id
    assert inv.quality == 'normal'
    assert inv.location == 'equipamiento'


def test_comprar_quality_multiplier_buena_and_excelente(db, client, make_user, make_character,
                                                          make_equipment_item, login_as):
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=1000)
    item = make_equipment_item(name='Espadón', category='arma', precio_peniques=240)  # base 1 CO

    client.post(f'/personajes/{char.id}/tienda/{item.id}/comprar', data={
        'quality': 'buena', 'quantity': '1', 'location': 'equipamiento',
    })
    purchase = CharacterPurchase.query.filter_by(character_id=char.id).first()
    assert purchase.precio_peniques_pagado == 240 * 3  # x3

    db.session.refresh(char)
    money_after_buena = char.dinero_total_peniques

    client.post(f'/personajes/{char.id}/tienda/{item.id}/comprar', data={
        'quality': 'excelente', 'quantity': '1', 'location': 'equipamiento',
    })
    second_purchase = (CharacterPurchase.query.filter_by(character_id=char.id)
                        .order_by(CharacterPurchase.id.desc()).first())
    assert second_purchase.precio_peniques_pagado == 240 * 10  # x10

    db.session.refresh(char)
    assert char.dinero_total_peniques == money_after_buena - 240 * 10


def test_comprar_mala_quality_half_price(db, client, make_user, make_character,
                                          make_equipment_item, login_as):
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=10)
    item = make_equipment_item(name='Daga', category='arma', precio_peniques=240)

    client.post(f'/personajes/{char.id}/tienda/{item.id}/comprar', data={
        'quality': 'mala', 'quantity': '1', 'location': 'equipamiento',
    })
    purchase = CharacterPurchase.query.filter_by(character_id=char.id).first()
    assert purchase.precio_peniques_pagado == 120  # 240 * 0.5


def test_comprar_insufficient_funds_rejected(db, client, make_user, make_character,
                                              make_equipment_item, login_as):
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=0)
    item = make_equipment_item(name='Espada', category='arma', precio_peniques=240)

    resp = client.post(f'/personajes/{char.id}/tienda/{item.id}/comprar', data={
        'quality': 'normal', 'quantity': '1', 'location': 'equipamiento',
    }, follow_redirects=True)
    assert resp.status_code == 200

    assert CharacterInventoryItem.query.filter_by(character_id=char.id).count() == 0
    assert CharacterPurchase.query.filter_by(character_id=char.id).count() == 0
    db.session.refresh(char)
    assert char.dinero_total_peniques == 0


def test_comprar_without_precio_peniques_blocked(db, client, make_user, make_character,
                                                  make_equipment_item, login_as):
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=100)
    item = make_equipment_item(name='Yelmo raro', category='armadura', price_text='50/75 CO')  # precio_peniques stays None

    resp = client.post(f'/personajes/{char.id}/tienda/{item.id}/comprar', data={
        'quality': 'normal', 'quantity': '1', 'location': 'equipamiento',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert CharacterInventoryItem.query.filter_by(character_id=char.id).count() == 0


# ── Compra: ropa (cada calidad es su propia fila, sin multiplicador) ───────

def test_comprar_ropa_uses_row_price_without_multiplier(db, client, make_user, make_character,
                                                          make_equipment_item, login_as):
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=20)
    item = make_equipment_item(name='Ropa', category='ropa', quality='excelente', precio_peniques=3000)

    resp = client.post(f'/personajes/{char.id}/tienda/{item.id}/comprar', data={
        'quantity': '1', 'location': 'equipamiento',
    }, follow_redirects=True)
    assert resp.status_code == 200

    purchase = CharacterPurchase.query.filter_by(character_id=char.id).first()
    assert purchase.precio_peniques_pagado == 3000  # not multiplied
    assert purchase.quality_snapshot == 'excelente'


# ── Ropa Noble: precio escala con el nivel social del comprador ─────────────

def test_comprar_ropa_noble_scales_with_nivel_social(db, client, make_user, make_character,
                                                       make_equipment_item, login_as):
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=100, nivel_social=5)
    item = make_equipment_item(name='Ropa', category='ropa', quality='excelente',
                                precio_peniques=36, precio_escala_clase_social=True,
                                price_text='36c (base * (Clase-2))')

    resp = client.post(f'/personajes/{char.id}/tienda/{item.id}/comprar', data={
        'quantity': '1', 'location': 'equipamiento',
    }, follow_redirects=True)
    assert resp.status_code == 200

    purchase = CharacterPurchase.query.filter_by(character_id=char.id).first()
    assert purchase.precio_peniques_pagado == 36 * (5 - 2)  # base * (Clase-2)


def test_comprar_ropa_noble_blocked_below_required_nivel_social(db, client, make_user, make_character,
                                                                  make_equipment_item, login_as):
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=100, nivel_social=2)
    item = make_equipment_item(name='Ropa', category='ropa', quality='excelente',
                                precio_peniques=36, precio_escala_clase_social=True)

    resp = client.post(f'/personajes/{char.id}/tienda/{item.id}/comprar', data={
        'quantity': '1', 'location': 'equipamiento',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert CharacterInventoryItem.query.filter_by(character_id=char.id).count() == 0


def test_parse_price_text_strips_clase_social_formula():
    from app.models.equipment import parse_price_text, is_clase_social_scaled
    assert parse_price_text('36c (base * (Clase-2))') == 36 * 12  # chelines -> peniques
    assert is_clase_social_scaled('36c (base * (Clase-2))') is True
    assert is_clase_social_scaled('20 CO') is False


# ── Objetos especiales "base + modificado": siempre calidad excelente ──────

def test_comprar_special_item_based_on_mundane_ignores_quality_choice(db, client, make_user, make_character,
                                                                        make_equipment_item, login_as):
    """A 'Pincho ocultable' (excellent-quality Daga with a special concealment
    format) is is_special=True but keeps category='arma' - purchasable like
    any weapon, but always at excelente, never a player-chosen quality."""
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=1000)
    base = make_equipment_item(name='Daga', category='arma', precio_peniques=240)
    special = make_equipment_item(name='Pincho ocultable', category='arma', is_special=True,
                                   base_item_id=base.id, quality='excelente', precio_peniques=240)

    confirm = client.get(f'/personajes/{char.id}/tienda/{special.id}/comprar')
    assert b'Excelente' in confirm.data
    assert b'name="quality"' not in confirm.data  # no dropdown - fixed quality

    resp = client.post(f'/personajes/{char.id}/tienda/{special.id}/comprar', data={
        'quality': 'mala', 'quantity': '1', 'location': 'equipamiento',  # attempt to override, should be ignored
    }, follow_redirects=True)
    assert resp.status_code == 200

    purchase = CharacterPurchase.query.filter_by(character_id=char.id).first()
    assert purchase.quality_snapshot == 'excelente'
    assert purchase.precio_peniques_pagado == 240 * 10  # excelente multiplier, not mala


# ── Objetos especiales (únicos/mágicos): solo DJ ────────────────────────────

def test_tienda_comprar_blocks_especial_category(client, make_user, make_character,
                                                  make_equipment_item, login_as):
    char = _login_owner(client, make_user, make_character, login_as)
    item = make_equipment_item(name='Espada Flamigera', category='especial')
    resp = client.get(f'/personajes/{char.id}/tienda/{item.id}/comprar')
    assert resp.status_code == 404


def test_conceder_especial_requires_admin(client, regular_user, make_character, login_as):
    char = make_character(regular_user, name='Personaje')
    login_as(client, regular_user, 'userpass123')
    resp = client.get(f'/personajes/{char.id}/conceder-especial')
    assert resp.status_code == 403


def test_conceder_especial_success_with_manual_price_and_quality(db, client, admin_user, regular_user,
                                                                   make_character, login_as):
    char = make_character(regular_user, name='Personaje')
    login_as(client, admin_user, 'adminpass123')

    resp = client.post(f'/personajes/{char.id}/conceder-especial', data={
        'custom_name': 'Anillo de invisibilidad', 'quality': 'excelente',
        'quantity': '1', 'precio_peniques': '5000', 'location': 'equipamiento',
        'notes': 'Recompensa de misión',
    }, follow_redirects=True)
    assert resp.status_code == 200

    purchase = CharacterPurchase.query.filter_by(character_id=char.id).first()
    assert purchase is not None
    assert purchase.granted_by_gm is True
    assert purchase.precio_peniques_pagado == 5000
    assert purchase.quality_snapshot == 'excelente'
    assert purchase.item_name_snapshot == 'Anillo de invisibilidad'

    inv = CharacterInventoryItem.query.filter_by(character_id=char.id).first()
    assert inv.custom_name == 'Anillo de invisibilidad'


# ── Histórico: inmutable y sobrevive al borrado del catálogo ────────────────

def test_purchase_survives_equipment_item_deletion(db, client, make_user, make_character,
                                                     make_equipment_item, login_as):
    """The FK is ondelete='SET NULL' (enforced by MySQL in prod/prepro; SQLite
    in tests doesn't enforce FKs by default, so the id itself isn't asserted
    here) - what matters is that the snapshot fields survive regardless."""
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=10)
    item = make_equipment_item(name='Espada Vieja', category='arma', precio_peniques=240)

    client.post(f'/personajes/{char.id}/tienda/{item.id}/comprar', data={
        'quality': 'normal', 'quantity': '1', 'location': 'equipamiento',
    })
    purchase = CharacterPurchase.query.filter_by(character_id=char.id).first()
    assert purchase.item_name_snapshot == 'Espada Vieja'
    purchase_id = purchase.id

    # Simulate what MySQL's ON DELETE SET NULL does in prod, since SQLite
    # doesn't enforce FKs without an explicit PRAGMA this test suite doesn't set.
    purchase.equipment_item_id = None
    db.session.delete(item)
    db.session.commit()

    purchase = db.session.get(CharacterPurchase, purchase_id)
    assert purchase is not None
    assert purchase.equipment_item_id is None
    assert purchase.item_name_snapshot == 'Espada Vieja'  # snapshot untouched
    assert purchase.category_snapshot == 'arma'
    assert purchase.quality_snapshot == 'normal'


def test_no_edit_or_delete_route_exists_for_purchase(client):
    """CharacterPurchase is an append-only ledger by convention - assert the
    routes simply don't exist rather than testing a 405/403 on something."""
    endpoints = {rule.endpoint for rule in client.application.url_map.iter_rules()}
    assert not any('purchase' in e and ('edit' in e or 'delete' in e) for e in endpoints)

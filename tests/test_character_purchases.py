"""Tests for the character equipment shop: cart add/remove, checkout (money
deduction, quality multiplier, ropa's per-row pricing, Noble ropa's Clase
social scaling), the especial GM-grant-only path, ownership gating, and
purchase-history immutability."""
from app.models.equipment import EquipmentItem, CharacterInventoryItem, CharacterPurchase, CharacterCartItem


def _login_owner(client, make_user, make_character, login_as, **char_kwargs):
    owner = make_user(username='owner1', password='ownerpass123')
    char = make_character(owner, name='Personaje', **char_kwargs)
    login_as(client, owner, 'ownerpass123')
    return char


def _add_to_cart(client, char, item, quality=None, quantity=1, location='equipamiento'):
    data = {'quantity': str(quantity), 'location': location}
    if quality:
        data['quality'] = quality
    return client.post(f'/personajes/{char.id}/tienda/{item.id}/anadir-carrito', data=data,
                        follow_redirects=True)


def _checkout(client, char):
    return client.post(f'/personajes/{char.id}/carrito/checkout', follow_redirects=True)


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


def test_carrito_blocks_other_users(client, make_user, make_character, login_as):
    owner = make_user(username='owner1', password='ownerpass123')
    other = make_user(username='other1', password='otherpass123')
    char = make_character(owner, name='Personaje')
    login_as(client, other, 'otherpass123')
    resp = client.get(f'/personajes/{char.id}/carrito')
    assert resp.status_code == 403


def test_admin_can_buy_for_any_character(client, admin_user, make_user, make_character,
                                          make_equipment_item, login_as):
    player = make_user(username='player1', password='playerpass123')
    char = make_character(player, name='Personaje', dinero_coronas=100)
    item = make_equipment_item(name='Daga', category='arma', quality='normal', precio_peniques=240)

    login_as(client, admin_user, 'adminpass123')
    resp = client.get(f'/personajes/{char.id}/tienda/{item.id}/anadir-carrito')
    assert resp.status_code == 200


# ── Tienda listing ───────────────────────────────────────────────────────────

def test_tienda_excludes_especial(client, make_user, make_character, make_equipment_item, login_as):
    char = _login_owner(client, make_user, make_character, login_as)
    make_equipment_item(name='Daga', category='arma')
    make_equipment_item(name='Amuleto raro', category='especial')

    resp = client.get(f'/personajes/{char.id}/tienda')
    assert b'Daga' in resp.data
    assert 'Amuleto raro'.encode('utf-8') not in resp.data


# ── Carrito: anadir / quitar ─────────────────────────────────────────────────

def test_anadir_al_carrito(db, client, make_user, make_character, make_equipment_item, login_as):
    char = _login_owner(client, make_user, make_character, login_as)
    item = make_equipment_item(name='Espada', category='arma', precio_peniques=240)

    resp = _add_to_cart(client, char, item, quality='normal')
    assert resp.status_code == 200

    cart_item = CharacterCartItem.query.filter_by(character_id=char.id).first()
    assert cart_item is not None
    assert cart_item.equipment_item_id == item.id
    assert cart_item.quality == 'normal'
    assert cart_item.unit_price == 240
    assert cart_item.subtotal == 240


def test_quitar_linea_del_carrito(db, client, make_user, make_character, make_equipment_item, login_as):
    char = _login_owner(client, make_user, make_character, login_as)
    item = make_equipment_item(name='Espada', category='arma', precio_peniques=240)
    _add_to_cart(client, char, item, quality='normal')
    cart_item = CharacterCartItem.query.filter_by(character_id=char.id).first()

    resp = client.post(f'/personajes/{char.id}/carrito/{cart_item.id}/eliminar', follow_redirects=True)
    assert resp.status_code == 200
    assert CharacterCartItem.query.filter_by(character_id=char.id).count() == 0


def test_carrito_shows_cart_count_on_tienda(client, make_user, make_character, make_equipment_item, login_as):
    char = _login_owner(client, make_user, make_character, login_as)
    item = make_equipment_item(name='Espada', category='arma', precio_peniques=240)
    _add_to_cart(client, char, item, quality='normal')

    resp = client.get(f'/personajes/{char.id}/tienda')
    assert b'1' in resp.data  # cart_count badge


# ── Checkout: arma/armadura con multiplicador de calidad ────────────────────

def test_checkout_arma_normal_quality_deducts_money(db, client, make_user, make_character,
                                                     make_equipment_item, login_as):
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=10)
    item = make_equipment_item(name='Espada', category='arma', precio_peniques=240)  # 1 CO

    _add_to_cart(client, char, item, quality='normal')
    resp = _checkout(client, char)
    assert resp.status_code == 200

    db.session.refresh(char)
    assert char.dinero_total_peniques == 9 * 240  # 10 CO - 1 CO
    assert CharacterCartItem.query.filter_by(character_id=char.id).count() == 0

    inv = CharacterInventoryItem.query.filter_by(character_id=char.id).first()
    assert inv is not None
    assert inv.equipment_item_id == item.id
    assert inv.quality == 'normal'
    assert inv.location == 'equipamiento'


def test_checkout_quality_multiplier_buena_and_excelente(db, client, make_user, make_character,
                                                          make_equipment_item, login_as):
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=1000)
    item = make_equipment_item(name='Espadón', category='arma', precio_peniques=240)  # base 1 CO

    _add_to_cart(client, char, item, quality='buena')
    _checkout(client, char)
    purchase = CharacterPurchase.query.filter_by(character_id=char.id).first()
    assert purchase.precio_peniques_pagado == 240 * 3  # x3

    db.session.refresh(char)
    money_after_buena = char.dinero_total_peniques

    _add_to_cart(client, char, item, quality='excelente')
    _checkout(client, char)
    second_purchase = (CharacterPurchase.query.filter_by(character_id=char.id)
                        .order_by(CharacterPurchase.id.desc()).first())
    assert second_purchase.precio_peniques_pagado == 240 * 10  # x10

    db.session.refresh(char)
    assert char.dinero_total_peniques == money_after_buena - 240 * 10


def test_checkout_mala_quality_half_price(db, client, make_user, make_character,
                                           make_equipment_item, login_as):
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=10)
    item = make_equipment_item(name='Daga', category='arma', precio_peniques=240)

    _add_to_cart(client, char, item, quality='mala')
    _checkout(client, char)
    purchase = CharacterPurchase.query.filter_by(character_id=char.id).first()
    assert purchase.precio_peniques_pagado == 120  # 240 * 0.5


def test_checkout_multiple_lines_different_categories_charges_total_once(db, client, make_user, make_character,
                                                                          make_equipment_item, login_as):
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=100)
    arma = make_equipment_item(name='Espada', category='arma', precio_peniques=240)
    armadura = make_equipment_item(name='Casco', category='armadura', precio_peniques=480)
    ropa = make_equipment_item(name='Ropa', category='ropa', quality='normal', precio_peniques=100)

    _add_to_cart(client, char, arma, quality='normal')
    _add_to_cart(client, char, armadura, quality='normal')
    _add_to_cart(client, char, ropa)

    assert CharacterCartItem.query.filter_by(character_id=char.id).count() == 3

    resp = _checkout(client, char)
    assert resp.status_code == 200

    assert CharacterCartItem.query.filter_by(character_id=char.id).count() == 0
    assert CharacterInventoryItem.query.filter_by(character_id=char.id).count() == 3
    assert CharacterPurchase.query.filter_by(character_id=char.id).count() == 3

    db.session.refresh(char)
    expected_total = 240 + 480 + 100
    assert char.dinero_total_peniques == 24000 - expected_total


def test_checkout_insufficient_funds_leaves_cart_intact(db, client, make_user, make_character,
                                                         make_equipment_item, login_as):
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=0)
    item = make_equipment_item(name='Espada', category='arma', precio_peniques=240)

    _add_to_cart(client, char, item, quality='normal')
    resp = _checkout(client, char)
    assert resp.status_code == 200

    assert CharacterInventoryItem.query.filter_by(character_id=char.id).count() == 0
    assert CharacterPurchase.query.filter_by(character_id=char.id).count() == 0
    assert CharacterCartItem.query.filter_by(character_id=char.id).count() == 1  # still there
    db.session.refresh(char)
    assert char.dinero_total_peniques == 0


def test_checkout_blocked_line_without_price_leaves_cart_intact(db, client, make_user, make_character,
                                                                 make_equipment_item, login_as):
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=100)
    item = make_equipment_item(name='Yelmo raro', category='armadura', price_text='50/75 CO')  # precio_peniques None

    _add_to_cart(client, char, item, quality='normal')
    resp = _checkout(client, char)
    assert resp.status_code == 200

    assert CharacterInventoryItem.query.filter_by(character_id=char.id).count() == 0
    assert CharacterCartItem.query.filter_by(character_id=char.id).count() == 1


def test_checkout_empty_cart_rejected(client, make_user, make_character, login_as):
    char = _login_owner(client, make_user, make_character, login_as)
    resp = _checkout(client, char)
    assert resp.status_code == 200
    assert CharacterPurchase.query.filter_by(character_id=char.id).count() == 0


def test_cart_is_per_character(db, client, make_user, make_character, make_equipment_item, login_as):
    owner = make_user(username='owner1', password='ownerpass123')
    char1 = make_character(owner, name='Personaje 1')
    char2 = make_character(owner, name='Personaje 2')
    login_as(client, owner, 'ownerpass123')
    item = make_equipment_item(name='Espada', category='arma', precio_peniques=240)

    _add_to_cart(client, char1, item, quality='normal')
    assert CharacterCartItem.query.filter_by(character_id=char1.id).count() == 1
    assert CharacterCartItem.query.filter_by(character_id=char2.id).count() == 0


# ── Compra: ropa (cada calidad es su propia fila, sin multiplicador) ───────

def test_checkout_ropa_uses_row_price_without_multiplier(db, client, make_user, make_character,
                                                          make_equipment_item, login_as):
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=20)
    item = make_equipment_item(name='Ropa', category='ropa', quality='excelente', precio_peniques=3000)

    _add_to_cart(client, char, item)
    resp = _checkout(client, char)
    assert resp.status_code == 200

    purchase = CharacterPurchase.query.filter_by(character_id=char.id).first()
    assert purchase.precio_peniques_pagado == 3000  # not multiplied
    assert purchase.quality_snapshot == 'excelente'


# ── Ropa Noble: precio escala con el nivel social del comprador ─────────────

def test_checkout_ropa_noble_scales_with_nivel_social(db, client, make_user, make_character,
                                                       make_equipment_item, login_as):
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=100, nivel_social=5)
    item = make_equipment_item(name='Ropa', category='ropa', quality='excelente',
                                precio_peniques=36, precio_escala_clase_social=True,
                                price_text='36c (base * (Clase-2))')

    _add_to_cart(client, char, item)
    resp = _checkout(client, char)
    assert resp.status_code == 200

    purchase = CharacterPurchase.query.filter_by(character_id=char.id).first()
    assert purchase.precio_peniques_pagado == 36 * (5 - 2)  # base * (Clase-2)


def test_checkout_ropa_noble_blocked_below_required_nivel_social(db, client, make_user, make_character,
                                                                  make_equipment_item, login_as):
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=100, nivel_social=2)
    item = make_equipment_item(name='Ropa', category='ropa', quality='excelente',
                                precio_peniques=36, precio_escala_clase_social=True)

    _add_to_cart(client, char, item)
    resp = _checkout(client, char)
    assert resp.status_code == 200
    assert CharacterInventoryItem.query.filter_by(character_id=char.id).count() == 0
    assert CharacterCartItem.query.filter_by(character_id=char.id).count() == 1


def test_parse_price_text_strips_clase_social_formula():
    from app.models.equipment import parse_price_text, is_clase_social_scaled
    assert parse_price_text('36c (base * (Clase-2))') == 36 * 12  # chelines -> peniques
    assert is_clase_social_scaled('36c (base * (Clase-2))') is True
    assert is_clase_social_scaled('20 CO') is False


# ── Objetos especiales "base + modificado": siempre calidad excelente ──────

def test_special_item_based_on_mundane_ignores_quality_choice(db, client, make_user, make_character,
                                                                make_equipment_item, login_as):
    """A 'Pincho ocultable' (excellent-quality Daga with a special concealment
    format) is is_special=True but keeps category='arma' - purchasable like
    any weapon, but always at excelente, never a player-chosen quality."""
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=1000)
    base = make_equipment_item(name='Daga', category='arma', precio_peniques=240)
    special = make_equipment_item(name='Pincho ocultable', category='arma', is_special=True,
                                   base_item_id=base.id, quality='excelente', precio_peniques=240)

    confirm = client.get(f'/personajes/{char.id}/tienda/{special.id}/anadir-carrito')
    assert b'Excelente' in confirm.data
    assert b'name="quality"' not in confirm.data  # no dropdown - fixed quality

    resp = _add_to_cart(client, char, special, quality='mala')  # attempt to override, should be ignored
    assert resp.status_code == 200
    _checkout(client, char)

    purchase = CharacterPurchase.query.filter_by(character_id=char.id).first()
    assert purchase.quality_snapshot == 'excelente'
    assert purchase.precio_peniques_pagado == 240 * 10  # excelente multiplier, not mala


# ── Objetos especiales (únicos/mágicos): solo DJ ────────────────────────────

def test_tienda_anadir_carrito_blocks_especial_category(client, make_user, make_character,
                                                         make_equipment_item, login_as):
    char = _login_owner(client, make_user, make_character, login_as)
    item = make_equipment_item(name='Espada Flamigera', category='especial')
    resp = client.get(f'/personajes/{char.id}/tienda/{item.id}/anadir-carrito')
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

    _add_to_cart(client, char, item, quality='normal')
    _checkout(client, char)
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

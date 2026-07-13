"""Tests for buying Comida y bebida directly from the catalog: charges the
chosen character's money, creates a CharacterInventoryItem/CharacterPurchase
polymorphic row (drink_id/recipe_id instead of equipment_item_id), respects
ownership (owner or admin only), and applies the global ShopMarkup %."""
from app.models.equipment import CharacterInventoryItem, CharacterPurchase
from app.models.food import Drink, Recipe
from app.models.shop import ShopMarkup


def _make_drink(db, nombre='Cerveza', origen='Imperio', precio_taberna_peniques=12):
    drink = Drink(nombre=nombre, origen=origen, precio_taberna_peniques=precio_taberna_peniques)
    db.session.add(drink)
    db.session.commit()
    return drink


def _make_recipe(db, nombre='Pan', precio_compra_peniques=6, solo_compra=True):
    recipe = Recipe(nombre=nombre, precio_compra_peniques=precio_compra_peniques, solo_compra=solo_compra)
    db.session.add(recipe)
    db.session.commit()
    return recipe


def _login_owner(client, make_user, make_character, login_as, **char_kwargs):
    owner = make_user(username='owner1', password='ownerpass123')
    char = make_character(owner, name='Personaje', **char_kwargs)
    login_as(client, owner, 'ownerpass123')
    return char


def _buy_drink(client, drink, personaje_id, cantidad=1, ubicacion='equipamiento'):
    return client.post(f'/comida/bebidas/{drink.id}/comprar', data={
        'personaje_id': str(personaje_id), 'cantidad': str(cantidad), 'ubicacion': ubicacion,
    }, follow_redirects=True)


def _buy_recipe(client, recipe, personaje_id, cantidad=1, ubicacion='equipamiento'):
    return client.post(f'/comida/recetas/{recipe.id}/comprar', data={
        'personaje_id': str(personaje_id), 'cantidad': str(cantidad), 'ubicacion': ubicacion,
    }, follow_redirects=True)


# ── Comprar bebida ───────────────────────────────────────────────────────────

def test_comprar_bebida_charges_money_and_creates_inventory(db, client, make_user, make_character, login_as):
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=10)
    drink = _make_drink(db, precio_taberna_peniques=12)

    resp = _buy_drink(client, drink, char.id, cantidad=3)
    assert resp.status_code == 200

    db.session.refresh(char)
    assert char.dinero_total_peniques == 10 * 240 - 12 * 3

    inv = CharacterInventoryItem.query.filter_by(character_id=char.id).first()
    assert inv is not None
    assert inv.drink_id == drink.id
    assert inv.equipment_item_id is None
    assert inv.quantity == 3
    assert inv.location == 'equipamiento'

    purchase = CharacterPurchase.query.filter_by(character_id=char.id).first()
    assert purchase.drink_id == drink.id
    assert purchase.category_snapshot == 'bebida'
    assert purchase.precio_peniques_pagado == 12 * 3
    assert purchase.item_name_snapshot == drink.nombre


def test_comprar_bebida_insufficient_funds_charges_nothing(db, client, make_user, make_character, login_as):
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=0)
    drink = _make_drink(db, precio_taberna_peniques=12)

    resp = _buy_drink(client, drink, char.id)
    assert resp.status_code == 200

    assert CharacterInventoryItem.query.filter_by(character_id=char.id).count() == 0
    assert CharacterPurchase.query.filter_by(character_id=char.id).count() == 0
    db.session.refresh(char)
    assert char.dinero_total_peniques == 0


# ── Comprar receta ───────────────────────────────────────────────────────────

def test_comprar_receta_charges_money_and_creates_inventory(db, client, make_user, make_character, login_as):
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=10)
    recipe = _make_recipe(db, precio_compra_peniques=6)

    resp = _buy_recipe(client, recipe, char.id, cantidad=2)
    assert resp.status_code == 200

    db.session.refresh(char)
    assert char.dinero_total_peniques == 10 * 240 - 6 * 2

    inv = CharacterInventoryItem.query.filter_by(character_id=char.id).first()
    assert inv.recipe_id == recipe.id
    assert inv.equipment_item_id is None

    purchase = CharacterPurchase.query.filter_by(character_id=char.id).first()
    assert purchase.recipe_id == recipe.id
    assert purchase.category_snapshot == 'comida'


def test_comprar_receta_sin_precio_de_compra_se_rechaza(db, client, make_user, make_character, login_as):
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=10)
    recipe = _make_recipe(db, precio_compra_peniques=None, solo_compra=False)

    resp = _buy_recipe(client, recipe, char.id)
    assert resp.status_code == 200

    assert CharacterInventoryItem.query.filter_by(character_id=char.id).count() == 0
    assert CharacterPurchase.query.filter_by(character_id=char.id).count() == 0
    db.session.refresh(char)
    assert char.dinero_total_peniques == 10 * 240  # untouched


# ── Ownership gating ─────────────────────────────────────────────────────────

def test_comprar_bebida_blocks_other_users_character(db, client, make_user, make_character, login_as):
    owner = make_user(username='owner1', password='ownerpass123')
    other = make_user(username='other1', password='otherpass123')
    char = make_character(owner, name='Personaje', dinero_coronas=10)
    drink = _make_drink(db)
    login_as(client, other, 'otherpass123')

    resp = client.post(f'/comida/bebidas/{drink.id}/comprar', data={
        'personaje_id': str(char.id), 'cantidad': '1', 'ubicacion': 'equipamiento',
    })
    assert resp.status_code == 403


def test_admin_can_buy_for_any_character(db, client, admin_user, make_user, make_character, login_as):
    player = make_user(username='player1', password='playerpass123')
    char = make_character(player, name='Personaje', dinero_coronas=10)
    drink = _make_drink(db, precio_taberna_peniques=12)
    login_as(client, admin_user, 'adminpass123')

    resp = _buy_drink(client, drink, char.id)
    assert resp.status_code == 200
    assert CharacterInventoryItem.query.filter_by(character_id=char.id).count() == 1


# ── Recargo global (ShopMarkup) ──────────────────────────────────────────────

def test_shop_markup_is_applied_to_purchase_price(db, client, make_user, make_character, login_as):
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=10)
    drink = _make_drink(db, precio_taberna_peniques=100)
    db.session.add(ShopMarkup(pct=20))
    db.session.commit()

    resp = _buy_drink(client, drink, char.id, cantidad=1)
    assert resp.status_code == 200

    purchase = CharacterPurchase.query.filter_by(character_id=char.id).first()
    assert purchase.precio_peniques_pagado == 120  # 100 * 1.20

    db.session.refresh(char)
    assert char.dinero_total_peniques == 10 * 240 - 120


def test_shop_markup_admin_page_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/admin/recargo-precios')
    assert resp.status_code == 403


def test_shop_markup_admin_page_updates_pct(db, client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    resp = client.post('/admin/recargo-precios', data={'pct': '15'}, follow_redirects=True)
    assert resp.status_code == 200

    row = ShopMarkup.query.first()
    assert row is not None
    assert row.pct == 15
    assert row.updated_by_id == admin_user.id


# ── Historial / inventario muestran el enlace correcto ──────────────────────

def test_inventario_links_to_drink_detail(db, client, make_user, make_character, login_as):
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=10)
    drink = _make_drink(db, nombre='Vino especiado', precio_taberna_peniques=12)
    _buy_drink(client, drink, char.id)

    resp = client.get(f'/personajes/{char.id}/inventario')
    assert resp.status_code == 200
    assert f'/comida/bebidas/{drink.id}'.encode('utf-8') in resp.data
    assert 'Vino especiado'.encode('utf-8') in resp.data


def test_historial_links_to_recipe_detail(db, client, make_user, make_character, login_as):
    char = _login_owner(client, make_user, make_character, login_as, dinero_coronas=10)
    recipe = _make_recipe(db, nombre='Guiso especial', precio_compra_peniques=6)
    _buy_recipe(client, recipe, char.id)

    resp = client.get(f'/personajes/{char.id}/historial-compras')
    assert resp.status_code == 200
    assert f'/comida/recetas/{recipe.id}'.encode('utf-8') in resp.data
    assert 'Guiso especial'.encode('utf-8') in resp.data

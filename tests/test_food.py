"""Tests for the Comida y bebida catalog: seed idempotency, currency helper,
and the read-only bebidas/recetas/ingredientes/métodos/normas routes."""
from app.services import currency_service
from app.services.food_seed_service import seed_food_catalog
from app.models.food import CookingMethod, Ingredient, Recipe, Drink


def test_seed_food_catalog_is_idempotent(app, db):
    with app.app_context():
        first = seed_food_catalog()
        assert first > 0
        second = seed_food_catalog()
        assert second == 0
        assert CookingMethod.query.count() == 10
        assert Ingredient.query.count() == 20
        assert Recipe.query.count() == 28
        assert Drink.query.count() == 61


def test_currency_to_peniques():
    assert currency_service.to_peniques(coronas=1) == 240
    assert currency_service.to_peniques(chelines=1) == 12
    assert currency_service.to_peniques(peniques=5) == 5
    assert currency_service.to_peniques(coronas=1, chelines=2, peniques=3) == 240 + 24 + 3


def test_currency_format_peniques():
    assert currency_service.format_peniques(0) == '0 Pe'
    assert currency_service.format_peniques(5) == '5 Pe'
    assert currency_service.format_peniques(12) == '1 C'
    assert currency_service.format_peniques(240) == '1 Co'
    assert currency_service.format_peniques(240 + 24 + 3) == '1 Co 2 C 3 Pe'


def test_drinks_requires_login(client):
    resp = client.get('/comida/bebidas')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_drinks_list_and_filter_by_origen(app, client, regular_user, login_as):
    with app.app_context():
        seed_food_catalog()
    login_as(client, regular_user, 'userpass123')

    resp = client.get('/comida/bebidas')
    assert resp.status_code == 200
    assert 'Cerveza'.encode('utf-8') in resp.data

    resp = client.get('/comida/bebidas?origen=Arabia')
    assert resp.status_code == 200
    assert 'Licor Negro'.encode('utf-8') in resp.data
    assert 'Cerveza negra Bugman 6X'.encode('utf-8') not in resp.data


def test_drinks_filter_by_sabor_calidad_disponibilidad(app, client, regular_user, login_as):
    with app.app_context():
        seed_food_catalog()
    login_as(client, regular_user, 'userpass123')

    # 'Cerveza' (Bretonia) sabor was transcribed as 'Malo (extraño)' - split into
    # base category 'Extraño' + variante 'Malo'.
    resp = client.get('/comida/bebidas?sabor=Extra%C3%B1o')
    assert resp.status_code == 200
    assert 'Cerveza</strong>'.encode('utf-8') in resp.data
    assert 'Malo'.encode('utf-8') in resp.data
    assert 'Kvas'.encode('utf-8') not in resp.data

    resp = client.get('/comida/bebidas?calidad=Excelente')
    assert resp.status_code == 200
    assert 'Cerveza negra Bugman 6X'.encode('utf-8') in resp.data

    resp = client.get('/comida/bebidas?disponibilidad=Muy+rara')
    assert resp.status_code == 200
    assert 'Cerveza negra Bugman 6X'.encode('utf-8') in resp.data
    assert 'Kvas'.encode('utf-8') not in resp.data


def test_drinks_sabor_split_into_categoria_y_variante(app, db):
    with app.app_context():
        seed_food_catalog()
        cerveza = Drink.query.filter_by(nombre='Cerveza', origen='Bretonia').first()
        assert cerveza.sabor == 'Extraño'
        assert cerveza.sabor_variante == 'Malo'
        vino = Drink.query.filter_by(nombre='Vino', origen='Bretonia').first()
        assert vino.sabor == 'Normal'
        assert vino.sabor_variante is None


def test_drinks_sort_by_precio(app, client, regular_user, login_as):
    with app.app_context():
        seed_food_catalog()
    login_as(client, regular_user, 'userpass123')

    resp = client.get('/comida/bebidas?origen=Imperio&sort=precio&dir=asc')
    assert resp.status_code == 200
    text = resp.data.decode('utf-8')
    # Cheapest Imperio drink ('Cerveza rubia', 1p) should appear before the
    # most expensive ones when sorted ascending by price.
    assert text.index('Cerveza rubia') < text.index('Vino</strong>')

    resp = client.get('/comida/bebidas?origen=Imperio&sort=precio&dir=desc')
    text_desc = resp.data.decode('utf-8')
    assert text_desc.index('Vino</strong>') < text_desc.index('Cerveza rubia')


def test_drink_detail_shows_notes(app, client, regular_user, login_as):
    with app.app_context():
        seed_food_catalog()
        drink = Drink.query.filter_by(nombre='Cerveza negra Bugman 6X').first()
    login_as(client, regular_user, 'userpass123')

    resp = client.get(f'/comida/bebidas/{drink.id}')
    assert resp.status_code == 200
    assert 'inmune al miedo'.encode('utf-8') in resp.data


def test_recipes_list_and_filter(app, client, regular_user, login_as):
    with app.app_context():
        seed_food_catalog()
    login_as(client, regular_user, 'userpass123')

    resp = client.get('/comida/recetas')
    assert resp.status_code == 200
    assert 'Olla podrida'.encode('utf-8') in resp.data

    resp = client.get('/comida/recetas?metodo=Hornear')
    assert resp.status_code == 200
    assert 'Tributo de Manann'.encode('utf-8') in resp.data
    assert 'Chuletón a la brasa'.encode('utf-8') not in resp.data


def test_recipes_sort_by_coste_creacion(app, client, regular_user, login_as):
    with app.app_context():
        seed_food_catalog()
    login_as(client, regular_user, 'userpass123')

    resp = client.get('/comida/recetas?sort=coste_creacion&dir=asc')
    assert resp.status_code == 200
    text = resp.data.decode('utf-8')
    # 'Verduras secas' (coste_creacion=3) is the cheapest craftable recipe;
    # 'Venado dulce trufado' (coste_creacion=53) is the most expensive.
    assert text.index('Verduras secas') < text.index('Venado dulce trufado')

    resp = client.get('/comida/recetas?sort=coste_creacion&dir=desc')
    text_desc = resp.data.decode('utf-8')
    assert text_desc.index('Venado dulce trufado') < text_desc.index('Verduras secas')


def test_recipe_detail_shows_ingredients_and_method(app, client, regular_user, login_as):
    with app.app_context():
        seed_food_catalog()
        recipe = Recipe.query.filter_by(nombre='Olla podrida').first()
    login_as(client, regular_user, 'userpass123')

    resp = client.get(f'/comida/recetas/{recipe.id}')
    assert resp.status_code == 200
    assert 'Guisado'.encode('utf-8') in resp.data
    assert 'Carne inferior'.encode('utf-8') in resp.data
    assert 'Especias'.encode('utf-8') in resp.data


def test_recipe_detail_special_recipe_has_no_method(app, client, regular_user, login_as):
    with app.app_context():
        seed_food_catalog()
        recipe = Recipe.query.filter_by(nombre='Lágrimas de Isha').first()
    login_as(client, regular_user, 'userpass123')

    resp = client.get(f'/comida/recetas/{recipe.id}')
    assert resp.status_code == 200
    assert 'Solo se puede comprar'.encode('utf-8') in resp.data


def test_ingredients_reference_page(app, client, regular_user, login_as):
    with app.app_context():
        seed_food_catalog()
    login_as(client, regular_user, 'userpass123')

    resp = client.get('/comida/ingredientes')
    assert resp.status_code == 200
    assert 'Carne superior'.encode('utf-8') in resp.data
    assert 'Especias'.encode('utf-8') in resp.data


def test_cooking_methods_reference_page(app, client, regular_user, login_as):
    with app.app_context():
        seed_food_catalog()
    login_as(client, regular_user, 'userpass123')

    resp = client.get('/comida/metodos')
    assert resp.status_code == 200
    assert 'Guisado'.encode('utf-8') in resp.data
    assert 'Hornear'.encode('utf-8') in resp.data


def test_normas_page_requires_login(client):
    resp = client.get('/comida/normas')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_normas_page_renders(app, client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/comida/normas')
    assert resp.status_code == 200
    assert 'Achispado'.encode('utf-8') in resp.data
    assert 'Borracho'.encode('utf-8') in resp.data

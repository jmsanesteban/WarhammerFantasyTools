"""Tests for the Comida y bebida catalog: seed idempotency, currency helper,
the read-only bebidas/recetas/ingredientes/métodos/normas routes, the
vigor/moral/coste calculation service, and the recipe-proposal workflow
(Fase 2 - queda pendiente hasta que un admin la aprueba)."""
import pytest

from app.services import currency_service
from app.services.food_seed_service import seed_food_catalog
from app.services.recipe_calc_service import validate_and_calculate, RecipeCompositionError
from app.models.food import CookingMethod, Ingredient, Recipe, Drink


def _ingredient(nombre):
    return Ingredient.query.filter_by(nombre=nombre).first()


def _method(nombre):
    return CookingMethod.query.filter_by(nombre=nombre).first()


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


def test_seed_food_catalog_backfills_complejidad_on_preexisting_recipes(app, db):
    """Regression: a recipe already seeded before 'complejidad' existed (Fase 1
    deployments) must get it backfilled on the next seed call, not stay None."""
    with app.app_context():
        seed_food_catalog()
        recipe = Recipe.query.filter_by(nombre='Olla podrida').first()
        recipe.complejidad = None
        db.session.commit()

        added = seed_food_catalog()
        assert added > 0
        db.session.refresh(recipe)
        assert recipe.complejidad == 11


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


# ── Fase 2: cálculo automático + propuesta de recetas nuevas ────────────────

def test_recipe_calc_matches_book_example(app, db):
    """'Olla podrida' (Guisado + Carne inferior/Verduras/Tubérculos/Legumbres +
    Aceites/Especias) is a regression check: the formula must reproduce the
    book's own values exactly."""
    with app.app_context():
        seed_food_catalog()
        result = validate_and_calculate(
            _method('Guisado'),
            [_ingredient('Carne inferior'), _ingredient('Verduras'),
             _ingredient('Tubérculos'), _ingredient('Legumbres')],
            [_ingredient('Aceites'), _ingredient('Especias')],
        )
        assert result == dict(
            vigor=44, moral=30, coste_creacion_peniques=44, precio_compra_peniques=15,
            duracion_dias=8, recalentar=True, complejidad=11, calidad='Buena',
        )


def test_calidad_from_complejidad_thresholds():
    from app.services.recipe_calc_service import calidad_from_complejidad
    assert calidad_from_complejidad(1) == 'Mala'
    assert calidad_from_complejidad(4) == 'Mala'
    assert calidad_from_complejidad(5) == 'Normal'
    assert calidad_from_complejidad(8) == 'Normal'
    assert calidad_from_complejidad(9) == 'Buena'
    assert calidad_from_complejidad(12) == 'Buena'
    assert calidad_from_complejidad(13) == 'Excelente'
    assert calidad_from_complejidad(20) == 'Excelente'


def test_recipe_calc_rejects_too_many_ingredients(app, db):
    with app.app_context():
        seed_food_catalog()
        crudo = _method('Crudo')  # allows only 1 ingredient
        with pytest.raises(RecipeCompositionError):
            validate_and_calculate(crudo, [_ingredient('Verduras'), _ingredient('Frutas')], [])


def test_recipe_calc_rejects_incompatible_ingredient(app, db):
    with app.app_context():
        seed_food_catalog()
        crudo = _method('Crudo')
        # 'Carne inferior' is NO for Crudo per the compatibility matrix
        with pytest.raises(RecipeCompositionError):
            validate_and_calculate(crudo, [_ingredient('Carne inferior')], [])


def test_recipe_calc_rejects_wrong_slot_role(app, db):
    with app.app_context():
        seed_food_catalog()
        guisado = _method('Guisado')
        # 'Sal' is only usable as a condimento for Guisado, not as a regular ingredient
        with pytest.raises(RecipeCompositionError):
            validate_and_calculate(guisado, [_ingredient('Sal')], [])


def test_propose_recipe_requires_login(client):
    resp = client.get('/comida/recetas/nueva')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def _propose_form(nombre, method_id, ing1_id, ing2_id, condi1_id):
    return {
        'nombre': nombre, 'cooking_method_id': method_id,
        'ingrediente_1': ing1_id, 'ingrediente_2': ing2_id, 'ingrediente_3': '', 'ingrediente_4': '',
        'condimento_1': condi1_id, 'condimento_2': '', 'notas': 'Receta de prueba',
    }


def test_propose_recipe_creates_pending_with_computed_stats(app, client, regular_user, login_as):
    with app.app_context():
        seed_food_catalog()
        method_id = _method('Guisado').id
        ing1_id, ing2_id = _ingredient('Carne inferior').id, _ingredient('Verduras').id
        condi1_id = _ingredient('Sal').id

    login_as(client, regular_user, 'userpass123')
    resp = client.post('/comida/recetas/nueva',
                       data=_propose_form('Estofado de prueba', method_id, ing1_id, ing2_id, condi1_id),
                       follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        recipe = Recipe.query.filter_by(nombre='Estofado de prueba').first()
        assert recipe is not None
        assert recipe.status == 'pendiente'
        assert recipe.created_by_id == regular_user.id
        assert recipe.requested_at is not None
        # Guisado(4,10,5) + Carne inferior(10,5,6) + Verduras(5,0,2) + Sal(1,5,4)
        assert recipe.vigor == 4 + 10 + 5 + 1
        assert recipe.moral == 10 + 5 + 0 + 5
        assert recipe.coste_creacion_peniques == 5 + 6 + 2 + 4
        # complejidad = 3 (base Guisado) + 2 ingredientes + 2*1 condimento = 7 -> Normal
        assert recipe.complejidad == 7
        assert recipe.calidad == 'Normal'


def test_propose_recipe_rejects_incompatible_combination(app, client, regular_user, login_as):
    with app.app_context():
        seed_food_catalog()
        crudo_id = _method('Crudo').id
        carne_inferior_id = _ingredient('Carne inferior').id  # NO for Crudo

    login_as(client, regular_user, 'userpass123')
    resp = client.post('/comida/recetas/nueva',
                       data=_propose_form('Receta inválida', crudo_id, carne_inferior_id, '', ''),
                       follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        assert Recipe.query.filter_by(nombre='Receta inválida').first() is None


def test_pending_recipe_hidden_from_public_catalog_and_other_users(app, client, regular_user, make_user, login_as):
    with app.app_context():
        seed_food_catalog()
        method_id = _method('Cocido').id
        ing1_id = _ingredient('Cereales').id
        condi1_id = _ingredient('Sal').id

    login_as(client, regular_user, 'userpass123')
    client.post('/comida/recetas/nueva',
               data=_propose_form('Gachas pendientes', method_id, ing1_id, '', condi1_id),
               follow_redirects=True)
    with app.app_context():
        recipe_id = Recipe.query.filter_by(nombre='Gachas pendientes').first().id

    other = make_user(username='otro_usuario', password='otropass123')
    client.get('/auth/logout')
    login_as(client, other, 'otropass123')

    resp = client.get('/comida/recetas')
    assert 'Gachas pendientes'.encode('utf-8') not in resp.data

    resp = client.get(f'/comida/recetas/{recipe_id}')
    assert resp.status_code == 404


def test_my_recipes_shows_own_pending_proposal(app, client, regular_user, login_as):
    with app.app_context():
        seed_food_catalog()
        method_id = _method('Cocido').id
        ing1_id = _ingredient('Cereales').id

    login_as(client, regular_user, 'userpass123')
    client.post('/comida/recetas/nueva',
               data=_propose_form('Gachas mias', method_id, ing1_id, '', ''),
               follow_redirects=True)

    resp = client.get('/comida/recetas/mias')
    assert resp.status_code == 200
    text = resp.data.decode('utf-8')
    assert 'Gachas mias' in text
    assert 'Pendiente' in text

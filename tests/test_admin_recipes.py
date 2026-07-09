"""Tests for admin review of user-proposed recipes (Comida y bebida, Fase 2)."""
import io

from app.models.food import Recipe, CookingMethod, Ingredient
from app.services.food_seed_service import seed_food_catalog


def _method(nombre):
    return CookingMethod.query.filter_by(nombre=nombre).first()


def _ingredient(nombre):
    return Ingredient.query.filter_by(nombre=nombre).first()


def _propose(client, nombre, method_id, ing1_id, condi1_id=''):
    return client.post('/comida/recetas/nueva', data={
        'nombre': nombre, 'cooking_method_id': method_id,
        'ingrediente_1': ing1_id, 'ingrediente_2': '', 'ingrediente_3': '', 'ingrediente_4': '',
        'condimento_1': condi1_id, 'condimento_2': '', 'notas': '',
    }, follow_redirects=True)


def _seed_and_propose(app, client, regular_user, login_as, nombre='Gachas de prueba admin'):
    with app.app_context():
        seed_food_catalog()
        method_id = _method('Cocido').id
        ing1_id = _ingredient('Cereales').id
        condi1_id = _ingredient('Sal').id
    login_as(client, regular_user, 'userpass123')
    _propose(client, nombre, method_id, ing1_id, condi1_id)
    with app.app_context():
        return Recipe.query.filter_by(nombre=nombre).first().id


def test_recipe_review_shows_per_element_breakdown(app, client, admin_user, regular_user, login_as):
    """Admin shouldn't have to open Métodos/Ingredientes in another tab to see
    where the totals come from - the review page breaks vigor/moral/coste down
    per method/ingredient/condiment, plus a total row matching the recipe."""
    recipe_id = _seed_and_propose(app, client, regular_user, login_as)
    client.get('/auth/logout')
    login_as(client, admin_user, 'adminpass123')

    resp = client.get(f'/admin/recetas/{recipe_id}')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')

    with app.app_context():
        recipe = Recipe.query.get(recipe_id)
        method = recipe.cooking_method
        ingredient = recipe.ingredientes[0]
        condiment = recipe.condimentos[0]

    assert 'Desglose por elemento' in body
    assert method.nombre in body
    assert ingredient.nombre in body
    assert condiment.nombre in body
    assert 'Total (receta, 12 raciones)' in body
    assert f'<td>{recipe.vigor}</td>' in body
    assert f'<td>{recipe.moral}</td>' in body


def test_recipes_pending_requires_login(client):
    resp = client.get('/admin/recetas')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_recipes_pending_requires_admin(app, client, regular_user, login_as):
    with app.app_context():
        seed_food_catalog()
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/admin/recetas')
    assert resp.status_code == 403


def test_recipe_approve_requires_admin(app, client, regular_user, login_as):
    recipe_id = _seed_and_propose(app, client, regular_user, login_as)
    resp = client.post(f'/admin/recetas/{recipe_id}/aprobar', data={}, follow_redirects=True)
    assert resp.status_code == 403


def test_recipes_pending_lists_proposal(app, client, regular_user, admin_user, login_as):
    recipe_id = _seed_and_propose(app, client, regular_user, login_as, nombre='Gachas listado')
    client.get('/auth/logout')
    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/admin/recetas')
    assert resp.status_code == 200
    assert 'Gachas listado'.encode('utf-8') in resp.data
    assert regular_user.username.encode('utf-8') in resp.data


def test_recipe_approve_requires_image(app, client, regular_user, admin_user, login_as, tmp_path):
    app.config['UPLOAD_FOLDER'] = str(tmp_path)
    recipe_id = _seed_and_propose(app, client, regular_user, login_as, nombre='Gachas sin imagen')

    client.get('/auth/logout')
    login_as(client, admin_user, 'adminpass123')
    resp = client.post(f'/admin/recetas/{recipe_id}/aprobar', data={}, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        recipe = Recipe.query.get(recipe_id)
        assert recipe.status == 'pendiente'


def test_recipe_approve_with_image_publishes_to_catalog(app, client, regular_user, admin_user, login_as, tmp_path):
    app.config['UPLOAD_FOLDER'] = str(tmp_path)
    recipe_id = _seed_and_propose(app, client, regular_user, login_as, nombre='Gachas con imagen')

    client.get('/auth/logout')
    login_as(client, admin_user, 'adminpass123')
    data = {'imagen': (io.BytesIO(b'fake-png-bytes'), 'receta.png')}
    resp = client.post(f'/admin/recetas/{recipe_id}/aprobar', data=data,
                       content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        recipe = Recipe.query.get(recipe_id)
        assert recipe.status == 'aprobada'
        assert recipe.image_path is not None
        assert recipe.approved_by_id == admin_user.id
        assert recipe.approved_at is not None

    client.get('/auth/logout')
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/comida/recetas')
    assert 'Gachas con imagen'.encode('utf-8') in resp.data
    assert 'Comunidad'.encode('utf-8') in resp.data


def test_recipe_reject_with_reason(app, client, regular_user, admin_user, login_as):
    recipe_id = _seed_and_propose(app, client, regular_user, login_as, nombre='Gachas rechazadas')

    client.get('/auth/logout')
    login_as(client, admin_user, 'adminpass123')
    resp = client.post(f'/admin/recetas/{recipe_id}/rechazar',
                       data={'motivo': 'Ingrediente incorrecto'}, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        recipe = Recipe.query.get(recipe_id)
        assert recipe.status == 'rechazada'
        assert recipe.rejection_reason == 'Ingrediente incorrecto'

    client.get('/auth/logout')
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/comida/recetas/mias')
    text = resp.data.decode('utf-8')
    assert 'Rechazada' in text
    assert 'Ingrediente incorrecto' in text

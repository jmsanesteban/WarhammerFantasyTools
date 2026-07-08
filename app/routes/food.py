from flask import Blueprint, render_template, request
from flask_login import login_required
from app.models.food import CookingMethod, Ingredient, IngredientCookingMethod, Recipe, Drink

food_bp = Blueprint('food', __name__, template_folder='../templates')

_METHOD_ORDER = ['Crudo', 'Ahumado', 'Secado', 'Salado', 'Almíbar', 'Brasa', 'Cocido', 'Guisado', 'Asar', 'Hornear']


@food_bp.route('/bebidas')
@login_required
def drinks():
    search = request.args.get('q', '').strip()
    origen = request.args.get('origen', '').strip()
    query = Drink.query
    if search:
        query = query.filter(Drink.nombre.ilike(f'%{search}%'))
    if origen:
        query = query.filter_by(origen=origen)
    items = query.order_by(Drink.origen, Drink.nombre).all()
    origenes = [o for (o,) in Drink.query.with_entities(Drink.origen).distinct().order_by(Drink.origen).all()]
    return render_template('food/drinks.html', drinks=items, origenes=origenes, search=search, origen=origen)


@food_bp.route('/bebidas/<int:drink_id>')
@login_required
def drink_detail(drink_id):
    drink = Drink.query.get_or_404(drink_id)
    return render_template('food/drink_detail.html', drink=drink)


@food_bp.route('/recetas')
@login_required
def recipes():
    search = request.args.get('q', '').strip()
    metodo = request.args.get('metodo', '').strip()
    calidad = request.args.get('calidad', '').strip()
    query = Recipe.query
    if search:
        query = query.filter(Recipe.nombre.ilike(f'%{search}%'))
    if metodo:
        query = query.join(CookingMethod).filter(CookingMethod.nombre == metodo)
    if calidad:
        query = query.filter(Recipe.calidad == calidad)
    items = query.order_by(Recipe.nombre).all()
    return render_template('food/recipes.html', recipes=items, metodos=_METHOD_ORDER,
                           search=search, metodo=metodo, calidad=calidad)


@food_bp.route('/recetas/<int:recipe_id>')
@login_required
def recipe_detail(recipe_id):
    recipe = Recipe.query.get_or_404(recipe_id)
    return render_template('food/recipe_detail.html', recipe=recipe)


@food_bp.route('/ingredientes')
@login_required
def ingredients():
    items = Ingredient.query.order_by(Ingredient.nombre).all()
    compat = {}
    for row in IngredientCookingMethod.query.all():
        compat.setdefault(row.ingredient_id, {})[row.cooking_method.nombre] = row.estado
    return render_template('food/ingredients.html', ingredients=items, methods=_METHOD_ORDER, compat=compat)


@food_bp.route('/metodos')
@login_required
def cooking_methods():
    items = CookingMethod.query.order_by(CookingMethod.id).all()
    return render_template('food/cooking_methods.html', methods=items)


@food_bp.route('/normas')
@login_required
def normas():
    return render_template('food/normas.html')

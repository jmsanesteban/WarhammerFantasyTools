from flask import Blueprint, render_template, request
from flask_login import login_required
from app.models.food import CookingMethod, Ingredient, IngredientCookingMethod, Recipe, Drink

food_bp = Blueprint('food', __name__, template_folder='../templates')

_METHOD_ORDER = ['Crudo', 'Ahumado', 'Secado', 'Salado', 'Almíbar', 'Brasa', 'Cocido', 'Guisado', 'Asar', 'Hornear']

_DRINK_SORT_COLUMNS = {
    'nombre': Drink.nombre, 'origen': Drink.origen, 'disponibilidad': Drink.disponibilidad,
    'calidad': Drink.calidad, 'sabor': Drink.sabor, 'precio': Drink.precio_taberna_peniques,
}

_RECIPE_SORT_COLUMNS = {
    'nombre': Recipe.nombre, 'calidad': Recipe.calidad, 'vigor': Recipe.vigor, 'moral': Recipe.moral,
    'duracion': Recipe.duracion_dias, 'coste_creacion': Recipe.coste_creacion_peniques,
    'precio_compra': Recipe.precio_compra_peniques,
}


def _distinct_values(model, column):
    return [v for (v,) in model.query.with_entities(column).filter(column.isnot(None))
            .distinct().order_by(column).all()]


@food_bp.route('/bebidas')
@login_required
def drinks():
    search = request.args.get('q', '').strip()
    origen = request.args.get('origen', '').strip()
    sabor = request.args.get('sabor', '').strip()
    calidad = request.args.get('calidad', '').strip()
    disponibilidad = request.args.get('disponibilidad', '').strip()
    sort = request.args.get('sort', '').strip()
    direction = 'desc' if request.args.get('dir') == 'desc' else 'asc'

    query = Drink.query
    if search:
        query = query.filter(Drink.nombre.ilike(f'%{search}%'))
    if origen:
        query = query.filter_by(origen=origen)
    if sabor:
        query = query.filter_by(sabor=sabor)
    if calidad:
        query = query.filter_by(calidad=calidad)
    if disponibilidad:
        query = query.filter_by(disponibilidad=disponibilidad)

    sort_column = _DRINK_SORT_COLUMNS.get(sort)
    if sort_column is not None:
        query = query.order_by(sort_column.desc() if direction == 'desc' else sort_column.asc())
    else:
        sort = ''
        query = query.order_by(Drink.origen, Drink.nombre)

    items = query.all()
    return render_template(
        'food/drinks.html', drinks=items,
        origenes=_distinct_values(Drink, Drink.origen), sabores=_distinct_values(Drink, Drink.sabor),
        calidades=_distinct_values(Drink, Drink.calidad),
        disponibilidades=_distinct_values(Drink, Drink.disponibilidad),
        search=search, origen=origen, sabor=sabor, calidad=calidad, disponibilidad=disponibilidad,
        sort=sort, direction=direction,
    )


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
    sort = request.args.get('sort', '').strip()
    direction = 'desc' if request.args.get('dir') == 'desc' else 'asc'

    query = Recipe.query.outerjoin(CookingMethod)
    if search:
        query = query.filter(Recipe.nombre.ilike(f'%{search}%'))
    if metodo:
        query = query.filter(CookingMethod.nombre == metodo)
    if calidad:
        query = query.filter(Recipe.calidad == calidad)

    if sort == 'metodo':
        column = CookingMethod.nombre.desc() if direction == 'desc' else CookingMethod.nombre.asc()
        query = query.order_by(column)
    else:
        sort_column = _RECIPE_SORT_COLUMNS.get(sort)
        if sort_column is not None:
            query = query.order_by(sort_column.desc() if direction == 'desc' else sort_column.asc())
        else:
            sort = ''
            query = query.order_by(Recipe.nombre)

    items = query.all()
    return render_template('food/recipes.html', recipes=items, metodos=_METHOD_ORDER,
                           search=search, metodo=metodo, calidad=calidad, sort=sort, direction=direction)


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

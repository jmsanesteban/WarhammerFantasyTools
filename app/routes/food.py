import os
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models.food import CookingMethod, Ingredient, IngredientCookingMethod, Recipe, Drink
from app.services.recipe_calc_service import validate_and_calculate, RecipeCompositionError

food_bp = Blueprint('food', __name__, template_folder='../templates')

_METHOD_ORDER = ['Crudo', 'Ahumado', 'Secado', 'Salado', 'Almíbar', 'Brasa', 'Cocido', 'Guisado', 'Asar', 'Hornear']
_ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}

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


def _save_recipe_image(recipe, file_storage):
    if not file_storage or not file_storage.filename:
        return
    ext = file_storage.filename.rsplit('.', 1)[-1].lower() if '.' in file_storage.filename else ''
    if ext not in _ALLOWED_IMAGE_EXTENSIONS:
        raise RecipeCompositionError('La imagen debe ser PNG, JPG, WEBP o GIF.')
    filename = secure_filename(file_storage.filename)
    save_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'recetas', filename)
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    file_storage.save(save_path)
    recipe.image_path = os.path.join('recetas', filename)


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
    if not current_user.is_admin:
        query = query.filter(Recipe.status == 'aprobada')
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
    if recipe.status != 'aprobada' and not current_user.is_admin and recipe.created_by_id != current_user.id:
        abort(404)
    return render_template('food/recipe_detail.html', recipe=recipe)


@food_bp.route('/recetas/nueva', methods=['GET', 'POST'])
@login_required
def propose_recipe():
    cooking_methods_list = CookingMethod.query.order_by(CookingMethod.id).all()
    ingredients_list = Ingredient.query.filter(Ingredient.nombre != 'Nada').order_by(Ingredient.nombre).all()
    compat = {}
    for row in IngredientCookingMethod.query.all():
        compat.setdefault(row.cooking_method_id, {})[row.ingredient_id] = row.estado

    if request.method == 'POST':
        f = request.form
        nombre = f.get('nombre', '').strip()
        method = CookingMethod.query.get(f.get('cooking_method_id', type=int))

        def _ingredient(field):
            raw = f.get(field, type=int)
            return Ingredient.query.get(raw) if raw else None

        ingredientes = [i for i in (_ingredient('ingrediente_1'), _ingredient('ingrediente_2'),
                                     _ingredient('ingrediente_3'), _ingredient('ingrediente_4')) if i]
        condimentos = [c for c in (_ingredient('condimento_1'), _ingredient('condimento_2')) if c]

        error = None
        if not nombre:
            error = 'El nombre es obligatorio.'
        elif Recipe.query.filter_by(nombre=nombre).first():
            error = f'Ya existe una receta llamada "{nombre}".'
        elif method is None:
            error = 'Elige un método de cocina.'

        if error is None:
            try:
                computed = validate_and_calculate(method, ingredientes, condimentos)
            except RecipeCompositionError as exc:
                error = str(exc)

        if error:
            flash(error, 'danger')
            return render_template('food/recipe_form.html', cooking_methods=cooking_methods_list,
                                   ingredients=ingredients_list, compat=compat, form=f)

        recipe = Recipe(
            nombre=nombre, cooking_method_id=method.id,
            notas=f.get('notas', '').strip() or None, solo_compra=False,
            status='pendiente', created_by_id=current_user.id, requested_at=datetime.utcnow(),
            ingrediente_1_id=ingredientes[0].id if len(ingredientes) > 0 else None,
            ingrediente_2_id=ingredientes[1].id if len(ingredientes) > 1 else None,
            ingrediente_3_id=ingredientes[2].id if len(ingredientes) > 2 else None,
            ingrediente_4_id=ingredientes[3].id if len(ingredientes) > 3 else None,
            condimento_1_id=condimentos[0].id if len(condimentos) > 0 else None,
            condimento_2_id=condimentos[1].id if len(condimentos) > 1 else None,
            **computed,
        )
        try:
            _save_recipe_image(recipe, request.files.get('imagen'))
        except RecipeCompositionError as exc:
            flash(str(exc), 'danger')
            return render_template('food/recipe_form.html', cooking_methods=cooking_methods_list,
                                   ingredients=ingredients_list, compat=compat, form=f)
        db.session.add(recipe)
        db.session.commit()
        flash('Tu receta se ha enviado para revisión. Un administrador la aprobará en cuanto la revise.', 'success')
        return redirect(url_for('food.my_recipes'))

    return render_template('food/recipe_form.html', cooking_methods=cooking_methods_list,
                           ingredients=ingredients_list, compat=compat, form={})


@food_bp.route('/recetas/mias')
@login_required
def my_recipes():
    items = Recipe.query.filter_by(created_by_id=current_user.id).order_by(Recipe.requested_at.desc()).all()
    return render_template('food/my_recipes.html', recipes=items)


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

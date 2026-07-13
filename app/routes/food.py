import os
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models.character import Character
from app.models.equipment import CharacterInventoryItem, CharacterPurchase
from app.models.food import CookingMethod, Ingredient, IngredientCookingMethod, Recipe, Drink
from app.models.shop import apply_markup, current_markup_pct
from app.models.user import User
from app.services.currency_service import format_peniques
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


def _selectable_characters():
    """Personajes que el usuario actual puede elegir para comprar bebida/
    comida: los suyos propios, o todos (con el nombre de su dueño) si es
    admin. Devuelve tuplas (character, owner_username_or_None)."""
    if current_user.is_admin:
        return (Character.query.join(User, Character.user_id == User.id)
                .order_by(User.username, Character.name)
                .with_entities(Character, User.username).all())
    return [(c, None) for c in
            Character.query.filter_by(user_id=current_user.id).order_by(Character.name).all()]


def _process_food_purchase(unit_price_peniques, category_snapshot, item_name, drink_id=None, recipe_id=None):
    """Cobra al personaje elegido en el formulario y crea el inventario +
    ledger de compra. Devuelve (char_or_None, error_message); error_message
    es None cuando la compra se completó. El recargo global se recalcula
    aquí siempre, nunca se confía en un total enviado por el cliente."""
    from app.routes.characters import _get_owned_character

    char_id = request.form.get('personaje_id', type=int)
    if not char_id:
        return None, 'Elige un personaje.'
    char = _get_owned_character(char_id)

    if unit_price_peniques is None:
        return char, f'«{item_name}» no tiene un precio de compra definido.'

    quantity = request.form.get('cantidad', '1').strip()
    quantity = int(quantity) if quantity.isdigit() and int(quantity) > 0 else 1

    location = request.form.get('ubicacion', '').strip()
    if location not in CharacterInventoryItem.LOCATIONS:
        return char, 'Ubicación de almacenamiento no válida.'

    total_price = apply_markup(unit_price_peniques * quantity)
    if total_price > char.dinero_total_peniques:
        return char, (f'{char.name} no tiene suficiente dinero: hacen falta {format_peniques(total_price)}, '
                       f'y tiene {format_peniques(char.dinero_total_peniques)}.')

    char.set_dinero_desde_peniques(char.dinero_total_peniques - total_price)

    inv_item = CharacterInventoryItem(
        character_id=char.id, drink_id=drink_id, recipe_id=recipe_id,
        quantity=quantity, location=location,
    )
    db.session.add(inv_item)
    db.session.flush()

    db.session.add(CharacterPurchase(
        character_id=char.id, drink_id=drink_id, recipe_id=recipe_id,
        item_name_snapshot=item_name, category_snapshot=category_snapshot,
        precio_peniques_pagado=total_price, granted_by_gm=False, granted_by_user_id=current_user.id,
        inventory_item_id=inv_item.id,
    ))
    db.session.commit()
    flash(f'«{item_name}» comprado para {char.name} por {format_peniques(total_price)}.', 'success')
    return char, None


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
        personajes=_selectable_characters(), locations=CharacterInventoryItem.LOCATIONS,
        location_labels=CharacterInventoryItem.LOCATION_LABELS, markup_pct=current_markup_pct(),
    )


@food_bp.route('/bebidas/<int:drink_id>')
@login_required
def drink_detail(drink_id):
    drink = Drink.query.get_or_404(drink_id)
    return render_template('food/drink_detail.html', drink=drink,
                           personajes=_selectable_characters(), locations=CharacterInventoryItem.LOCATIONS,
                           location_labels=CharacterInventoryItem.LOCATION_LABELS, markup_pct=current_markup_pct())


@food_bp.route('/bebidas/<int:drink_id>/comprar', methods=['POST'])
@login_required
def comprar_bebida(drink_id):
    drink = Drink.query.get_or_404(drink_id)
    _, error = _process_food_purchase(
        drink.precio_taberna_peniques, 'bebida', drink.nombre, drink_id=drink.id,
    )
    if error:
        flash(error, 'danger')
    return redirect(url_for('food.drink_detail', drink_id=drink.id))


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
                           search=search, metodo=metodo, calidad=calidad, sort=sort, direction=direction,
                           personajes=_selectable_characters(), locations=CharacterInventoryItem.LOCATIONS,
                           location_labels=CharacterInventoryItem.LOCATION_LABELS, markup_pct=current_markup_pct())


@food_bp.route('/recetas/<int:recipe_id>')
@login_required
def recipe_detail(recipe_id):
    recipe = Recipe.query.get_or_404(recipe_id)
    if recipe.status != 'aprobada' and not current_user.is_admin and recipe.created_by_id != current_user.id:
        abort(404)
    return render_template('food/recipe_detail.html', recipe=recipe,
                           personajes=_selectable_characters(), locations=CharacterInventoryItem.LOCATIONS,
                           location_labels=CharacterInventoryItem.LOCATION_LABELS, markup_pct=current_markup_pct())


@food_bp.route('/recetas/<int:recipe_id>/comprar', methods=['POST'])
@login_required
def comprar_receta(recipe_id):
    recipe = Recipe.query.get_or_404(recipe_id)
    if recipe.status != 'aprobada' and not current_user.is_admin and recipe.created_by_id != current_user.id:
        abort(404)
    _, error = _process_food_purchase(
        recipe.precio_compra_peniques, 'comida', recipe.nombre, recipe_id=recipe.id,
    )
    if error:
        flash(error, 'danger')
    return redirect(url_for('food.recipe_detail', recipe_id=recipe.id))


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

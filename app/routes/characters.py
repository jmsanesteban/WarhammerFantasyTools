import json
import re

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models.character import (
    Character, CharacterProfession, CharacterSkill, CharacterTalent,
    CharacterTrait, CharacterAcquaintance, CharacterPossession, CharacterMagicItem,
    CharacterMoneyGrant,
)
from app.models.profession import Profession
from app.models.skill import Skill
from app.models.talent import Talent
from app.models.user import User
from app.models.equipment import EquipmentItem, CharacterInventoryItem, CharacterPurchase, CharacterCartItem
from app.services import character_creation_service as ccs
from app.services import salary_service
from app.services.currency_service import format_peniques, to_peniques
from app.utils import admin_required

characters_bp = Blueprint('characters', __name__, template_folder='../templates')

_TIENDA_CATEGORIES = ('arma', 'armadura', 'ropa')

_RAZAS = ['Humano', 'Halfling', 'Enano', 'Elfo Silvano', 'Alto Elfo']


def _form_int(field, default=None):
    val = request.form.get(field, '').strip()
    return int(val) if val.lstrip('-').isdigit() else default


def _professions_picker_context(professions):
    """JSON-ready data for the searchable profession picker widget: the
    full catalog (id/name) plus a profession_id -> [exit profession_ids]
    map, built from the career_exits association table in a single query
    to avoid N+1 lazy-loads of Profession.exits per profession."""
    from app.models.profession import career_exits_table
    exits_map = {}
    for source_id, target_id in db.session.query(
        career_exits_table.c.source_id, career_exits_table.c.target_id
    ).all():
        exits_map.setdefault(source_id, []).append(target_id)
    return {
        'professions_picker_list': [{'id': p.id, 'name': p.name} for p in professions],
        'professions_exits_map': exits_map,
    }


@characters_bp.route('/')
@login_required
def list_characters():
    if current_user.is_admin:
        characters = (
            Character.query.join(User, User.id == Character.user_id)
            .order_by(User.username, Character.name)
            .all()
        )
    else:
        characters = Character.query.filter_by(user_id=current_user.id).order_by(Character.name).all()
    return render_template('characters/list.html', characters=characters)


@characters_bp.route('/<int:char_id>')
@login_required
def detail(char_id):
    char = Character.query.get_or_404(char_id)
    if char.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    return render_template('characters/detail.html', char=char)


def _rebuild_professions(char_id):
    """Rebuild a character's ordered profession list (with salary tier) from
    the 3 parallel repeated form fields - profession_ids/tipo_sueldo_list/
    estado_habilidad_list line up by DOM order, same convention already used
    for profession_ids alone."""
    prof_ids = request.form.getlist('profession_ids')
    tipo_list = request.form.getlist('tipo_sueldo_list')
    estado_list = request.form.getlist('estado_habilidad_list')
    for order, prof_id_str in enumerate(prof_ids):
        if prof_id_str:
            db.session.add(CharacterProfession(
                character_id=char_id,
                profession_id=int(prof_id_str),
                order=order,
                is_current=(order == len(prof_ids) - 1),
                tipo_sueldo=(tipo_list[order] if order < len(tipo_list) else '') or None,
                estado_habilidad=(estado_list[order] if order < len(estado_list) else '') or None,
            ))


@characters_bp.route('/nuevo', methods=['GET', 'POST'])
@login_required
def create():
    professions = Profession.query.order_by(Profession.name).all()
    picker_ctx = _professions_picker_context(professions)

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('El personaje necesita un nombre.', 'danger')
            return render_template('characters/form.html', char=None, professions=professions,
                                   salary_table=salary_service.get_salary_table(), **picker_ctx)

        char = Character(
            user_id=current_user.id,
            name=name,
            race=request.form.get('race', '').strip() or None,
            gender=request.form.get('gender', '').strip() or None,
            notes=request.form.get('notes', '').strip() or None,
            es_untersuchung=request.form.get('es_untersuchung') == 'on',
            nivel_social=_form_int('nivel_social', 1),
            dinero_coronas=_form_int('dinero_coronas', 0),
        )
        db.session.add(char)
        db.session.flush()

        _rebuild_professions(char.id)

        db.session.commit()
        flash(f'Personaje "{char.name}" creado.', 'success')
        return redirect(url_for('characters.detail', char_id=char.id))

    return render_template('characters/form.html', char=None, professions=professions,
                           salary_table=salary_service.get_salary_table(), **picker_ctx)


@characters_bp.route('/<int:char_id>/editar', methods=['GET', 'POST'])
@login_required
def edit(char_id):
    char = Character.query.get_or_404(char_id)
    if char.user_id != current_user.id and not current_user.is_admin:
        abort(403)

    professions = Profession.query.order_by(Profession.name).all()
    picker_ctx = _professions_picker_context(professions)

    if request.method == 'POST':
        char.name = request.form.get('name', '').strip()
        char.race = request.form.get('race', '').strip() or None
        char.gender = request.form.get('gender', '').strip() or None
        char.notes = request.form.get('notes', '').strip() or None
        char.es_untersuchung = request.form.get('es_untersuchung') == 'on'
        char.nivel_social = _form_int('nivel_social', char.nivel_social or 1)
        char.dinero_coronas = _form_int('dinero_coronas', char.dinero_coronas or 0)

        # Rebuild profession list
        CharacterProfession.query.filter_by(character_id=char.id).delete()
        _rebuild_professions(char.id)

        db.session.commit()
        flash(f'Personaje "{char.name}" actualizado.', 'success')
        return redirect(url_for('characters.detail', char_id=char.id))

    return render_template('characters/form.html', char=char, professions=professions,
                           salary_table=salary_service.get_salary_table(), **picker_ctx)


@characters_bp.route('/<int:char_id>/eliminar', methods=['POST'])
@login_required
def delete(char_id):
    char = Character.query.get_or_404(char_id)
    if char.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    name = char.name
    db.session.delete(char)
    db.session.commit()
    flash(f'Personaje "{name}" eliminado.', 'warning')
    return redirect(url_for('characters.list_characters'))


# ---------------------------------------------------------------------------
# Tienda / inventario / histórico de compras
# ---------------------------------------------------------------------------

def _get_owned_character(char_id):
    char = Character.query.get_or_404(char_id)
    if char.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    return char


def _cart_count_and_total(char):
    items = char.cart_items
    count = sum(ci.quantity for ci in items)
    subtotals = [ci.subtotal for ci in items]
    total = sum(s for s in subtotals if s is not None) if subtotals else 0
    return count, total


@characters_bp.route('/<int:char_id>/tienda')
@login_required
def tienda(char_id):
    char = _get_owned_character(char_id)

    category = request.args.get('category', '').strip()
    search = request.args.get('q', '').strip()
    query = EquipmentItem.query.filter(EquipmentItem.category.in_(_TIENDA_CATEGORIES))
    if category in _TIENDA_CATEGORIES:
        query = query.filter_by(category=category)
    if search:
        query = query.filter(EquipmentItem.name.ilike(f'%{search}%'))
    items = query.order_by(EquipmentItem.category, EquipmentItem.name).all()

    cart_count, cart_total = _cart_count_and_total(char)
    return render_template('characters/tienda.html', char=char, items=items,
                            category=category, search=search,
                            category_labels=EquipmentItem.CATEGORY_LABELS,
                            tienda_categories=_TIENDA_CATEGORIES,
                            cart_count=cart_count, cart_total=cart_total)


@characters_bp.route('/<int:char_id>/tienda/<int:item_id>/anadir-carrito', methods=['GET'])
@login_required
def anadir_carrito_confirmar(char_id, item_id):
    char = _get_owned_character(char_id)
    item = EquipmentItem.query.get_or_404(item_id)
    if item.category not in _TIENDA_CATEGORIES:
        abort(404)

    # Ropa: quality = the catalog row itself. Special items built on a
    # mundane base (Pincho ocultable = Daga excelente, etc.) are always
    # excelente. Ammo never varies by quality ("No hay modificadores por
    # calidad" - manufacture quality is always treated as normal) - only
    # genuinely-variable-quality arma/armadura show a picker.
    qualities = ([] if (item.category == 'ropa' or item.is_special or item.subcategory == 'municion')
                 else list(EquipmentItem.QUALITIES))
    puede_sin_coste = current_user.is_admin or current_user.puede_anadir_equipo_sin_coste
    return render_template('characters/anadir_carrito_confirmar.html', char=char, item=item,
                            qualities=qualities, locations=CharacterInventoryItem.LOCATIONS,
                            puede_sin_coste=puede_sin_coste)


def _resolve_cart_line(item):
    """Reads quality/quantity/location from the posted form for a purchase
    (or a no-cost inventory add - same picker, same rules). Returns
    (quality, quantity, location, error_message); error_message is None
    when everything is valid."""
    # Ropa's "quality" is really which catalog row was picked (Harapos/Común/
    # Burguesa/Noble are separate rows). Special items built on a mundane base
    # are always excelente. Ammo has no quality concept at all. None of these
    # three is a player choice on this one row.
    if item.category == 'ropa' or item.is_special or item.subcategory == 'municion':
        quality = item.quality
    else:
        quality = request.form.get('quality', '').strip() or None
    quantity = request.form.get('quantity', '1').strip()
    quantity = int(quantity) if quantity.isdigit() and int(quantity) > 0 else 1
    location = request.form.get('location', '').strip()

    if location not in CharacterInventoryItem.LOCATIONS:
        return quality, quantity, location, 'Ubicación de almacenamiento no válida.'

    if quantity % item.unidades_por_precio != 0:
        return quality, quantity, location, (
            f'«{item.name}» se vende en lotes de {item.unidades_por_precio}: '
            f'la cantidad debe ser múltiplo de {item.unidades_por_precio}.'
        )

    return quality, quantity, location, None


@characters_bp.route('/<int:char_id>/tienda/<int:item_id>/anadir-carrito', methods=['POST'])
@login_required
def anadir_carrito(char_id, item_id):
    char = _get_owned_character(char_id)
    item = EquipmentItem.query.get_or_404(item_id)
    if item.category not in _TIENDA_CATEGORIES:
        abort(404)

    quality, quantity, location, error = _resolve_cart_line(item)
    if error:
        flash(error, 'danger')
        return redirect(url_for('characters.anadir_carrito_confirmar', char_id=char.id, item_id=item.id))

    db.session.add(CharacterCartItem(
        character_id=char.id, equipment_item_id=item.id, quality=quality,
        quantity=quantity, location=location,
    ))
    db.session.commit()
    flash(f'«{item.name}» añadido al carrito.', 'success')
    return redirect(url_for('characters.tienda', char_id=char.id))


@characters_bp.route('/<int:char_id>/tienda/<int:item_id>/anadir-sin-coste', methods=['POST'])
@login_required
def anadir_sin_coste(char_id, item_id):
    """Regularizes equipment a character already owned before this shop
    existed: straight to inventory, no cart, no money touched. Gated by the
    same admin-controlled per-user flag as the "Ya lo tenía" checkbox in the
    purchase-confirm screen - not a general free-purchase path."""
    char = _get_owned_character(char_id)
    item = EquipmentItem.query.get_or_404(item_id)
    if item.category not in _TIENDA_CATEGORIES:
        abort(404)
    if not (current_user.is_admin or current_user.puede_anadir_equipo_sin_coste):
        abort(403)

    quality, quantity, location, error = _resolve_cart_line(item)
    if error:
        flash(error, 'danger')
        return redirect(url_for('characters.anadir_carrito_confirmar', char_id=char.id, item_id=item.id))

    inv_item = CharacterInventoryItem(
        character_id=char.id, equipment_item_id=item.id, quality=quality,
        quantity=quantity, location=location,
    )
    db.session.add(inv_item)
    db.session.flush()

    db.session.add(CharacterPurchase(
        character_id=char.id, equipment_item_id=item.id,
        item_name_snapshot=item.name, category_snapshot=item.category, quality_snapshot=quality,
        precio_peniques_pagado=0, granted_by_gm=False, granted_by_user_id=current_user.id,
        inventory_item_id=inv_item.id, notes='Alta sin coste (equipo ya en posesión del personaje).',
    ))
    db.session.commit()
    flash(f'«{item.name}» añadido al inventario de {char.name} sin coste.', 'success')
    return redirect(url_for('characters.inventario', char_id=char.id))


@characters_bp.route('/<int:char_id>/carrito')
@login_required
def carrito(char_id):
    char = _get_owned_character(char_id)
    cart_count, cart_total = _cart_count_and_total(char)
    return render_template('characters/carrito.html', char=char, cart_items=char.cart_items,
                            cart_count=cart_count, cart_total=cart_total)


@characters_bp.route('/<int:char_id>/carrito/<int:cart_item_id>/eliminar', methods=['POST'])
@login_required
def eliminar_del_carrito(char_id, cart_item_id):
    char = _get_owned_character(char_id)
    cart_item = CharacterCartItem.query.filter_by(id=cart_item_id, character_id=char.id).first_or_404()
    db.session.delete(cart_item)
    db.session.commit()
    flash('Objeto quitado del carrito.', 'warning')
    return redirect(url_for('characters.carrito', char_id=char.id))


@characters_bp.route('/<int:char_id>/carrito/checkout', methods=['POST'])
@login_required
def checkout_carrito(char_id):
    char = _get_owned_character(char_id)
    cart_items = char.cart_items
    if not cart_items:
        flash('El carrito está vacío.', 'danger')
        return redirect(url_for('characters.carrito', char_id=char.id))

    # Todo o nada: cualquier línea sin precio calculable aborta el checkout
    # completo sin tocar nada, para que el jugador pueda arreglarla y reintentar.
    total_price = 0
    for cart_item in cart_items:
        line_total = cart_item.subtotal
        if line_total is None:
            flash(f'«{cart_item.equipment_item.name}» no tiene un precio calculable ahora mismo '
                  f'(revisa su precio en el catálogo o el nivel social de {char.name}); '
                  f'quítalo del carrito o corrígelo antes de finalizar la compra.', 'danger')
            return redirect(url_for('characters.carrito', char_id=char.id))
        total_price += line_total

    if total_price > char.dinero_total_peniques:
        flash(f'{char.name} no tiene suficiente dinero: hacen falta {format_peniques(total_price)}, '
              f'y tiene {format_peniques(char.dinero_total_peniques)}.', 'danger')
        return redirect(url_for('characters.carrito', char_id=char.id))

    char.set_dinero_desde_peniques(char.dinero_total_peniques - total_price)

    for cart_item in list(cart_items):
        inv_item = CharacterInventoryItem(
            character_id=char.id, equipment_item_id=cart_item.equipment_item_id,
            quality=cart_item.quality, quantity=cart_item.quantity, location=cart_item.location,
        )
        db.session.add(inv_item)
        db.session.flush()

        db.session.add(CharacterPurchase(
            character_id=char.id, equipment_item_id=cart_item.equipment_item_id,
            item_name_snapshot=cart_item.equipment_item.name, category_snapshot=cart_item.equipment_item.category,
            quality_snapshot=cart_item.quality, precio_peniques_pagado=cart_item.subtotal,
            granted_by_gm=False, granted_by_user_id=current_user.id, inventory_item_id=inv_item.id,
        ))
        db.session.delete(cart_item)

    db.session.commit()
    flash(f'Compra completada por {format_peniques(total_price)}.', 'success')
    return redirect(url_for('characters.inventario', char_id=char.id))


@characters_bp.route('/<int:char_id>/inventario')
@login_required
def inventario(char_id):
    char = _get_owned_character(char_id)
    items_by_location = {loc: [] for loc in CharacterInventoryItem.LOCATIONS}
    for inv_item in char.inventory_items:
        items_by_location.setdefault(inv_item.location, []).append(inv_item)
    return render_template('characters/inventario.html', char=char, items_by_location=items_by_location,
                            locations=CharacterInventoryItem.LOCATIONS)


@characters_bp.route('/<int:char_id>/historial-compras')
@login_required
def historial_compras(char_id):
    char = _get_owned_character(char_id)
    return render_template('characters/historial_compras.html', char=char)


@characters_bp.route('/<int:char_id>/conceder-especial', methods=['GET', 'POST'])
@admin_required
def conceder_especial(char_id):
    char = Character.query.get_or_404(char_id)
    especiales = EquipmentItem.query.filter_by(category='especial').order_by(EquipmentItem.name).all()

    if request.method == 'POST':
        equipment_item_id = request.form.get('equipment_item_id', '').strip()
        item = EquipmentItem.query.get(int(equipment_item_id)) if equipment_item_id else None
        custom_name = request.form.get('custom_name', '').strip() or None
        if not item and not custom_name:
            flash('Elige un objeto especial del catálogo o escribe un nombre.', 'danger')
            return redirect(url_for('characters.conceder_especial', char_id=char.id))

        quality = request.form.get('quality', '').strip() or None
        quantity = request.form.get('quantity', '1').strip()
        quantity = int(quantity) if quantity.isdigit() and int(quantity) > 0 else 1
        location = request.form.get('location', '').strip()
        if location not in CharacterInventoryItem.LOCATIONS:
            flash('Ubicación de almacenamiento no válida.', 'danger')
            return redirect(url_for('characters.conceder_especial', char_id=char.id))
        price_str = request.form.get('precio_peniques', '').strip()
        precio_peniques = int(price_str) if price_str.isdigit() else 0
        notes = request.form.get('notes', '').strip() or None

        inv_item = CharacterInventoryItem(
            character_id=char.id, equipment_item_id=item.id if item else None,
            custom_name=custom_name if not item else None, quality=quality,
            quantity=quantity, location=location, notes=notes,
        )
        db.session.add(inv_item)
        db.session.flush()

        db.session.add(CharacterPurchase(
            character_id=char.id, equipment_item_id=item.id if item else None,
            item_name_snapshot=item.name if item else custom_name,
            category_snapshot='especial', quality_snapshot=quality,
            precio_peniques_pagado=precio_peniques, granted_by_gm=True, granted_by_user_id=current_user.id,
            inventory_item_id=inv_item.id, notes=notes,
        ))
        db.session.commit()
        flash(f'Objeto especial concedido a «{char.name}».', 'success')
        return redirect(url_for('characters.inventario', char_id=char.id))

    return render_template('characters/conceder_especial.html', char=char, especiales=especiales,
                            locations=CharacterInventoryItem.LOCATIONS)


@characters_bp.route('/<int:char_id>/conceder-dinero', methods=['GET', 'POST'])
@admin_required
def conceder_dinero(char_id):
    """Manually credits a character's account - a stand-in for salary/reward
    income the game doesn't automate yet. Kept as a ledger (CharacterMoneyGrant)
    so it stays visible in the money history even though the balance itself
    is just a running total on the character."""
    char = Character.query.get_or_404(char_id)

    if request.method == 'POST':
        coronas = _form_int('coronas', 0)
        chelines = _form_int('chelines', 0)
        peniques = _form_int('peniques', 0)
        total = to_peniques(coronas, chelines, peniques)
        motivo = request.form.get('motivo', '').strip() or None

        if total <= 0:
            flash('Introduce una cantidad mayor que cero.', 'danger')
            return redirect(url_for('characters.conceder_dinero', char_id=char.id))

        char.set_dinero_desde_peniques(char.dinero_total_peniques + total)
        db.session.add(CharacterMoneyGrant(
            character_id=char.id, peniques=total, motivo=motivo, granted_by_user_id=current_user.id,
        ))
        db.session.commit()
        flash(f'Se han añadido {format_peniques(total)} a {char.name}.', 'success')
        return redirect(url_for('characters.detail', char_id=char.id))

    return render_template('characters/conceder_dinero.html', char=char)


# ---------------------------------------------------------------------------
# Generador de personajes (creación guiada por tiradas, WFRP2 casero)
# ---------------------------------------------------------------------------

@characters_bp.route('/generador')
@login_required
def generator():
    professions = Profession.query.order_by(Profession.name).all()
    return render_template(
        'characters/generator.html',
        razas=_RAZAS,
        professions=professions,
        history_point_options=ccs.history_point_options(),
        tables=ccs.get_frontend_tables(),
        salary_table=salary_service.get_salary_table(),
        **_professions_picker_context(professions),
    )


@characters_bp.route('/generador/tirar', methods=['POST'])
@login_required
def generator_roll():
    payload = request.get_json(silent=True) or {}
    step = payload.get('paso')
    ctx = payload.get('contexto') or {}

    handlers = {
        'raza': lambda: ccs.roll_race(),
        'profesion': lambda: _roll_profesion_step(ctx),
        'caracteristicas': lambda: ccs.roll_characteristics(ctx.get('raza', 'Humano')),
        'heridas': lambda: ccs.roll_wounds(ctx.get('raza', 'Humano')),
        'destino': lambda: ccs.roll_fate_points(ctx.get('raza', 'Humano')),
        'historial': lambda: ccs.roll_history_points(ctx.get('raza', 'Humano')),
        'signo_astral': lambda: ccs.roll_signo_astral(),
        'altura': lambda: ccs.roll_altura(ctx.get('raza', 'Humano'), ctx.get('genero', 'Masculino')),
        'peso': lambda: ccs.roll_peso(ctx.get('raza', 'Humano'), int(ctx.get('altura_cm') or 0)),
        'edad': lambda: ccs.roll_edad(ctx.get('raza', 'Humano')),
        'apariencia': lambda: ccs.roll_apariencia(),
        'procedencia': lambda: ccs.roll_procedencia(ctx.get('raza', 'Humano')),
        'situacion_familiar': lambda: ccs.roll_situacion_familiar(ctx.get('raza', 'Humano')),
        'sucesos_juventud': lambda: {'eventos': ccs.roll_sucesos_juventud(int(ctx.get('num_rolls') or 1), ctx.get('excluir'))},
        'talento_aleatorio': lambda: ccs.roll_talento_aleatorio(ctx.get('raza', 'Humano'), ctx.get('excluir')),
        'formula': lambda: {'value': ccs.roll_dice(ctx.get('formula', '0'))},
        'estetica': lambda: ccs.roll_estetica(),
        'personalidad': lambda: ccs.roll_personalidad(),
        'desventaja': lambda: ccs.roll_desventaja(),
        'posesiones': lambda: ccs.roll_posesiones(int(ctx.get('bonus') or 0)),
        'objeto_magico': lambda: ccs.roll_objeto_magico(),
        'horas_sueno': lambda: {'horas': ccs.horas_sueno(ctx.get('raza', 'Humano'), int(ctx.get('resistencia') or 0))},
        'info_racial': lambda: ccs.race_info(ctx.get('raza', 'Humano'), ctx.get('provincia')),
    }

    handler = handlers.get(step)
    if not handler:
        return jsonify({'error': f'Paso desconocido: {step}'}), 400

    try:
        result = handler()
    except Exception as e:
        return jsonify({'error': str(e)}), 400

    return jsonify({'result': result})


def _roll_profesion_step(ctx):
    raza = ctx.get('raza', 'Humano')
    rolled = ccs.roll_profession(raza)
    professions = Profession.query.order_by(Profession.name).all()
    match = ccs.match_profession_to_catalog(rolled.get('profession_name'), professions)
    rolled['matched_profession'] = {'id': match.id, 'name': match.name} if match else None
    return rolled


@characters_bp.route('/generador/guardar', methods=['POST'])
@login_required
def generator_save():
    name = request.form.get('name', '').strip()
    if not name:
        flash('El personaje necesita un nombre.', 'danger')
        return redirect(url_for('characters.generator'))

    raza = request.form.get('race', '').strip() or None
    if raza and raza not in _RAZAS:
        raza = None

    def _int(field):
        val = request.form.get(field, '').strip()
        return int(val) if val.lstrip('-').isdigit() else None

    char = Character(
        user_id=current_user.id,
        name=name,
        race=raza,
        gender=request.form.get('gender', '').strip() or None,
        notes=request.form.get('notes', '').strip() or None,
        signo_astral=request.form.get('signo_astral', '').strip() or None,
        rasgo_personalidad_signo=request.form.get('rasgo_personalidad_signo', '').strip() or None,
        altura_cm=_int('altura_cm'),
        peso_kg=_int('peso_kg'),
        edad=_int('edad'),
        edad_grado=_int('edad_grado'),
        color_pelo=request.form.get('color_pelo', '').strip() or None,
        color_ojos=request.form.get('color_ojos', '').strip() or None,
        mano_dominante=request.form.get('mano_dominante', '').strip() or None,
        procedencia=request.form.get('procedencia', '').strip() or None,
        situacion_familiar=request.form.get('situacion_familiar', '').strip() or None,
        nivel_social=_int('nivel_social') or 1,
        dinero_coronas=_int('dinero_coronas') or 0,
        history_points_total=_int('history_points_total') or 0,
        history_points_spent=_int('history_points_spent') or 0,
        es_untersuchung=request.form.get('es_untersuchung') == 'on',
    )
    for field in Character.PRIMARY_FIELDS + Character.SECONDARY_FIELDS:
        setattr(char, field, _int(field))

    db.session.add(char)
    db.session.flush()

    _rebuild_professions(char.id)

    # Habilidades y talentos raciales/de procedencia (nombres de texto libre -
    # se enlazan al catálogo cuando hay coincidencia exacta con el nombre base;
    # si no, no se crea nada nuevo, igual que en la importación de PDF).
    all_skills = {s.name_es.lower(): s for s in Skill.query.all()}
    all_talents = {t.name_es.lower(): t for t in Talent.query.all()}
    for name_raw in _parse_json_list(request.form.get('racial_skills_json')):
        base, spec = _split_specialization(str(name_raw))
        skill = all_skills.get(base.lower())
        if skill and not any(cs.skill_id == skill.id and cs.specialization == spec for cs in char.skills):
            db.session.add(CharacterSkill(character_id=char.id, skill_id=skill.id, specialization=spec))
    for name_raw in _parse_json_list(request.form.get('racial_talents_json')):
        base, spec = _split_specialization(str(name_raw))
        talent = all_talents.get(base.lower())
        if talent and not any(ct.talent_id == talent.id and ct.specialization == spec for ct in char.talents):
            db.session.add(CharacterTalent(character_id=char.id, talent_id=talent.id, specialization=spec))

    for entry in _parse_json_list(request.form.get('traits_json')):
        if entry.get('description'):
            db.session.add(CharacterTrait(
                character_id=char.id, category=entry.get('category', 'estetica'),
                description=entry['description'],
            ))

    for entry in _parse_json_list(request.form.get('acquaintances_json')):
        if entry.get('description'):
            db.session.add(CharacterAcquaintance(
                character_id=char.id, kind=entry.get('kind', 'contacto'),
                description=entry['description'],
            ))

    for entry in _parse_json_list(request.form.get('possessions_json')):
        text = entry.get('name') if isinstance(entry, dict) else entry
        if text:
            db.session.add(CharacterPossession(character_id=char.id, name=text))

    for entry in _parse_json_list(request.form.get('magic_items_json')):
        if entry.get('description'):
            db.session.add(CharacterMagicItem(
                character_id=char.id, category=entry.get('category', 'amuleto'),
                description=entry['description'],
            ))

    db.session.commit()
    flash(f'Personaje "{char.name}" creado con el generador.', 'success')
    return redirect(url_for('characters.detail', char_id=char.id))


def _parse_json_list(raw):
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return data if isinstance(data, list) else []


_RE_SPEC = re.compile(r'^(.*?)\s*\(([^)]+)\)\s*$')


def _split_specialization(text: str):
    """'Hablar idioma (Reikspiel)' -> ('Hablar idioma', 'Reikspiel')."""
    m = _RE_SPEC.match(text.strip())
    return (m.group(1).strip(), m.group(2).strip()) if m else (text.strip(), None)

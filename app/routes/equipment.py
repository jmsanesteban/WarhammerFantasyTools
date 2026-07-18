import json
import os
from flask import (Blueprint, render_template, redirect, url_for,
                    flash, request, current_app)
from flask_login import current_user
from werkzeug.utils import secure_filename
from app.extensions import db
from app.models.equipment import EquipmentItem, parse_price_text, parse_price_units, is_clase_social_scaled
from app.utils import require_permission, json_download_response, flash_import_summary

equipment_bp = Blueprint('equipment', __name__, template_folder='../templates')

_ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
# Only weapons/armour get a product photo - clothing/special items don't per
# the source books (special items reuse whatever image their mundane base has).
_IMAGE_CATEGORIES = ('arma', 'armadura')


def _distinct_values(model, column, category=None, category_in=None):
    q = model.query
    if category:
        q = q.filter_by(category=category)
    elif category_in:
        q = q.filter(model.category.in_(category_in))
    return [v for (v,) in q.with_entities(column).filter(column.isnot(None))
            .distinct().order_by(column).all()]


def _filtered_query(category, subcategory, quality, search, category_choices=None):
    """Shared scoping logic behind the public catalog list, the character
    shop, and the bulk custom_fields editor - all three define "the matching
    set of objects" the same way, from the same 4 filters. `category_choices`
    restricts which categories are in play at all (the shop only sells
    arma/armadura/ropa); defaults to every catalog category."""
    choices = category_choices or EquipmentItem.CATEGORIES
    query = EquipmentItem.query.filter(EquipmentItem.category.in_(choices))
    if category in choices:
        query = query.filter_by(category=category)
    if subcategory:
        query = query.filter_by(subcategory=subcategory)
    # Quality is a real catalog attribute only for Ropa (each tier is its own
    # row); every other category never has it stored on the row, so
    # filtering by it there would always return zero results - those rows
    # instead show every matching item with its stats/price adjusted to the
    # chosen quality (see list.html/_macros.html). The `or` here matters when
    # category is blank (both Ropa and non-Ropa rows in the same resultset):
    # only the Ropa rows actually get narrowed by quality, everything else
    # passes through untouched.
    if quality in EquipmentItem.QUALITIES:
        query = query.filter(db.or_(EquipmentItem.category != 'ropa', EquipmentItem.quality == quality))
    if search:
        query = query.filter(EquipmentItem.name.ilike(f'%{search}%'))
    # `orden` (book position, see app/data/equipment_orden.py) sorts first
    # when set; anything without one (not yet book-ordered, or a category
    # that never gets one, e.g. municion/libro/otros/especial) falls back to
    # alphabetical, same as before this field existed. MySQL has no NULLS
    # LAST syntax (unlike Postgres), hence the CASE instead of nullslast().
    orden_is_null = db.case((EquipmentItem.orden.is_(None), 1), else_=0)
    return query.order_by(EquipmentItem.category, orden_is_null, EquipmentItem.orden, EquipmentItem.name)


def _render_catalog(category, locked_category):
    subcategory = request.args.get('subcategory', '').strip()
    quality = request.args.get('quality', '').strip()
    search = request.args.get('q', '').strip()

    items = _filtered_query(category, subcategory, quality, search).all()
    # Scope the "tipo" dropdown to whatever subcategories actually exist for
    # the selected category, so picking "Arma" doesn't show armour families.
    scoped_category = category if category in EquipmentItem.CATEGORIES else None
    subcategories = _distinct_values(EquipmentItem, EquipmentItem.subcategory, category=scoped_category)
    # Clothing tiers are the same quality scale, but players call them
    # Harapos/Común/Burguesa/Noble rather than Mala/Normal/Buena/Excelente.
    quality_labels = (EquipmentItem.QUALITY_LABELS_ROPA if category == 'ropa'
                      else EquipmentItem.QUALITY_LABELS)

    return render_template(
        'equipment/list.html',
        items=items, category=category, subcategory=subcategory, quality=quality,
        search=search, subcategories=subcategories, quality_labels=quality_labels,
        category_labels=EquipmentItem.CATEGORY_LABELS,
        category_nav_icons=EquipmentItem.CATEGORY_NAV_ICONS,
        category_nav_labels=EquipmentItem.CATEGORY_NAV_LABELS,
        subcategory_labels=EquipmentItem.SUBCATEGORY_LABELS,
        locked_category=locked_category,
    )


@equipment_bp.route('/')
@require_permission('equipment.view')
def list_items():
    """Full catalog: the category dropdown is free to switch/clear."""
    category = request.args.get('category', '').strip()
    return _render_catalog(category, locked_category=False)


# One dedicated route per category, linked from the nav's "Equipamiento"
# dropdown - unlike list_items(), the category here is fixed by the URL, not
# a switchable filter, so the page can never show an object from another
# catalog and the header can say which one you're in (e.g. "Equipamiento —
# Armas").
@equipment_bp.route('/armas')
@require_permission('equipment.view')
def list_armas():
    return _render_catalog('arma', locked_category=True)


@equipment_bp.route('/armaduras')
@require_permission('equipment.view')
def list_armaduras():
    return _render_catalog('armadura', locked_category=True)


@equipment_bp.route('/municion')
@require_permission('equipment.view')
def list_municion():
    return _render_catalog('municion', locked_category=True)


@equipment_bp.route('/ropa')
@require_permission('equipment.view')
def list_ropa():
    return _render_catalog('ropa', locked_category=True)


@equipment_bp.route('/libros')
@require_permission('equipment.view')
def list_libros():
    return _render_catalog('libro', locked_category=True)


@equipment_bp.route('/otros')
@require_permission('equipment.view')
def list_otros():
    return _render_catalog('otros', locked_category=True)


@equipment_bp.route('/especiales')
@require_permission('equipment.view')
def list_especiales():
    return _render_catalog('especial', locked_category=True)


@equipment_bp.route('/<int:item_id>')
@require_permission('equipment.view')
def detail(item_id):
    item = EquipmentItem.query.get_or_404(item_id)
    quality = request.args.get('quality', '').strip() or None
    if quality not in EquipmentItem.QUALITIES:
        quality = None
    return render_template('equipment/detail.html', item=item, quality=quality)


@equipment_bp.route('/nuevo', methods=['GET', 'POST'])
@require_permission('equipment.edit')
def create():
    if request.method == 'POST':
        item = _item_from_form(None)
        db.session.add(item)
        db.session.commit()
        flash(f'Objeto "{item.name}" creado correctamente.', 'success')
        return redirect(url_for('equipment.detail', item_id=item.id))

    base_items = EquipmentItem.query.order_by(EquipmentItem.name).all()
    return render_template('equipment/form.html', item=None, base_items=base_items)


@equipment_bp.route('/<int:item_id>/editar', methods=['GET', 'POST'])
@require_permission('equipment.edit')
def edit(item_id):
    item = EquipmentItem.query.get_or_404(item_id)

    if request.method == 'POST':
        _item_from_form(item)
        db.session.commit()
        flash(f'Objeto "{item.name}" actualizado.', 'success')
        return redirect(url_for('equipment.detail', item_id=item.id))

    base_items = (EquipmentItem.query
                  .filter(EquipmentItem.id != item.id)
                  .order_by(EquipmentItem.name).all())
    return render_template('equipment/form.html', item=item, base_items=base_items)


@equipment_bp.route('/<int:item_id>/eliminar', methods=['POST'])
@require_permission('equipment.edit')
def delete(item_id):
    item = EquipmentItem.query.get_or_404(item_id)
    name = item.name
    db.session.delete(item)
    db.session.commit()
    flash(f'Objeto "{name}" eliminado.', 'warning')
    return redirect(url_for('equipment.list_items'))


# ---------------------------------------------------------------------------
# Edición en bloque de custom_fields sobre el conjunto filtrado
# ---------------------------------------------------------------------------

def _flash_bulk_summary(summary):
    flash(
        f"Hecho: {summary['updated']} objeto(s) actualizados, {summary['skipped']} omitidos.",
        'success',
    )
    if summary['warnings']:
        shown = summary['warnings'][:20]
        more = '' if len(summary['warnings']) <= 20 else f" (+{len(summary['warnings']) - 20} más)"
        flash('Avisos: ' + '; '.join(shown) + more, 'warning')


@equipment_bp.route('/campos-en-bloque', methods=['GET', 'POST'])
@require_permission('equipment.edit')
def bulk_fields():
    if request.method == 'POST':
        category = request.form.get('category', '').strip()
        subcategory = request.form.get('subcategory', '').strip()
        quality = request.form.get('quality', '').strip()
        search = request.form.get('q', '').strip()
        items = _filtered_query(category, subcategory, quality, search).all()

        mode = request.form.get('mode', '').strip()
        summary = {'updated': 0, 'skipped': 0, 'warnings': []}

        if mode == 'add':
            key = request.form.get('add_key', '').strip()
            value = request.form.get('add_value', '').strip()
            overwrite = request.form.get('overwrite') == 'on'
            if not key:
                flash('Indica el nombre del campo a añadir.', 'danger')
            else:
                for item in items:
                    fields = dict(item.custom_fields or {})
                    if key in fields and not overwrite:
                        summary['skipped'] += 1
                        continue
                    fields[key] = value
                    item.custom_fields = fields
                    summary['updated'] += 1
                db.session.commit()
                _flash_bulk_summary(summary)

        elif mode == 'rename':
            old_key = request.form.get('rename_old_key', '').strip()
            new_key = request.form.get('rename_new_key', '').strip()
            if not old_key or not new_key:
                flash('Indica la clave antigua y la nueva.', 'danger')
            else:
                for item in items:
                    fields = item.custom_fields or {}
                    if old_key not in fields:
                        continue  # fuera de alcance para esta operación
                    if new_key in fields:
                        summary['skipped'] += 1
                        summary['warnings'].append(f'«{item.name}» ya tenía «{new_key}», no se renombró.')
                        continue
                    new_fields = dict(fields)
                    new_fields[new_key] = new_fields.pop(old_key)
                    item.custom_fields = new_fields
                    summary['updated'] += 1
                db.session.commit()
                _flash_bulk_summary(summary)

        elif mode == 'delete':
            key = request.form.get('delete_key', '').strip()
            if not key:
                flash('Indica el nombre del campo a eliminar.', 'danger')
            else:
                for item in items:
                    fields = item.custom_fields or {}
                    if key not in fields:
                        continue  # fuera de alcance para esta operación
                    new_fields = dict(fields)
                    del new_fields[key]
                    item.custom_fields = new_fields or None
                    summary['updated'] += 1
                db.session.commit()
                _flash_bulk_summary(summary)

        else:
            flash('Modo de operación no válido.', 'danger')

        return redirect(url_for('equipment.bulk_fields', category=category, subcategory=subcategory,
                                 quality=quality, q=search))

    category = request.args.get('category', '').strip()
    subcategory = request.args.get('subcategory', '').strip()
    quality = request.args.get('quality', '').strip()
    search = request.args.get('q', '').strip()

    items = _filtered_query(category, subcategory, quality, search).all()
    scoped_category = category if category in EquipmentItem.CATEGORIES else None
    subcategories = _distinct_values(EquipmentItem, EquipmentItem.subcategory, category=scoped_category)
    quality_labels = (EquipmentItem.QUALITY_LABELS_ROPA if category == 'ropa'
                      else EquipmentItem.QUALITY_LABELS)

    return render_template(
        'equipment/bulk_fields.html',
        items=items, category=category, subcategory=subcategory, quality=quality, search=search,
        subcategories=subcategories, quality_labels=quality_labels,
        category_labels=EquipmentItem.CATEGORY_LABELS,
        subcategory_labels=EquipmentItem.SUBCATEGORY_LABELS,
    )


# ---------------------------------------------------------------------------
# Backup: exportar/importar todo el catálogo (JSON completo)
# ---------------------------------------------------------------------------

@equipment_bp.route('/exportar')
@require_permission('equipment.import')
def export():
    from app.services.backup_service import export_equipment
    return json_download_response(export_equipment(), 'equipamiento_backup.json')


@equipment_bp.route('/importar', methods=['GET', 'POST'])
@require_permission('equipment.import')
def import_equipment_route():
    if request.method == 'GET':
        return render_template('equipment/import.html')

    f = request.files.get('file')
    if not f or not f.filename:
        flash('Selecciona un fichero JSON.', 'danger')
        return redirect(request.url)

    try:
        data = json.loads(f.read())
    except Exception as e:
        flash(f'Error al leer el fichero: {e}', 'danger')
        return redirect(request.url)

    from app.services.backup_service import import_equipment
    mode = request.form.get('mode', 'skip')
    summary = import_equipment(data, mode=mode)
    flash_import_summary(summary)
    return redirect(url_for('equipment.list_items'))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _item_from_form(item):
    """Create or update an EquipmentItem from POST form data."""
    f = request.form
    if item is None:
        item = EquipmentItem()
        item.created_by_id = current_user.id
        item.status = 'admin'

    item.name = f.get('name', '').strip()
    item.category = f.get('category', 'arma')
    item.subcategory = f.get('subcategory', '').strip() or None
    item.quality = f.get('quality', '').strip() or None
    orden = f.get('orden', '').strip()
    item.orden = int(orden) if orden else None
    item.is_special = f.get('is_special') == 'on'
    base_item_id = f.get('base_item_id', '').strip()
    item.base_item_id = int(base_item_id) if base_item_id else None
    item.price_text = f.get('price_text', '').strip() or None
    item.description = f.get('description', '').strip() or None

    # Recompute the normalized price fields from price_text on every save,
    # so editing a price later (or fixing an ammo batch price like "1C (5)")
    # doesn't leave precio_peniques stuck at whatever it was when the row
    # was first migrated/imported.
    base_price_text, units = parse_price_units(item.price_text)
    item.unidades_por_precio = units
    item.precio_peniques = parse_price_text(base_price_text)
    item.precio_escala_clase_social = is_clase_social_scaled(base_price_text)

    # Structured stats: posted as parallel stat_key[]/stat_value[] lists so
    # the form can have an arbitrary number of rows without naming each one.
    stats = {}
    for key, value in zip(f.getlist('stat_key'), f.getlist('stat_value')):
        key = key.strip()
        if key:
            stats[key] = value.strip()
    item.stats = stats or None

    # Admin-added ad hoc fields, same shape as stats but kept separate so a
    # future re-import from the source book never clobbers what an admin
    # added by hand.
    custom_fields = {}
    for key, value in zip(f.getlist('custom_key'), f.getlist('custom_value')):
        key = key.strip()
        if key:
            custom_fields[key] = value.strip()
    item.custom_fields = custom_fields or None

    if item.category in _IMAGE_CATEGORIES and 'image' in request.files:
        file = request.files['image']
        if file and file.filename:
            ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
            if ext not in _ALLOWED_IMAGE_EXTENSIONS:
                flash('La imagen debe ser PNG, JPG, WEBP o GIF.', 'danger')
            else:
                filename = secure_filename(file.filename)
                save_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'equipamiento', filename)
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                file.save(save_path)
                item.image_path = os.path.join('equipamiento', filename)

    return item

import json
import os
from flask import (Blueprint, render_template, redirect, url_for,
                    flash, request, current_app)
from flask_login import current_user
from werkzeug.utils import secure_filename
from app.extensions import db
from app.models.equipment import EquipmentItem
from app.utils import require_permission, json_download_response, flash_import_summary

equipment_bp = Blueprint('equipment', __name__, template_folder='../templates')

_ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
# Only weapons/armour get a product photo - clothing/special items don't per
# the source books (special items reuse whatever image their mundane base has).
_IMAGE_CATEGORIES = ('arma', 'armadura')


def _distinct_values(model, column, category=None):
    q = model.query
    if category:
        q = q.filter_by(category=category)
    return [v for (v,) in q.with_entities(column).filter(column.isnot(None))
            .distinct().order_by(column).all()]


@equipment_bp.route('/')
def list_items():
    category = request.args.get('category', '').strip()
    subcategory = request.args.get('subcategory', '').strip()
    quality = request.args.get('quality', '').strip()
    search = request.args.get('q', '').strip()

    query = EquipmentItem.query
    if category in EquipmentItem.CATEGORIES:
        query = query.filter_by(category=category)
    if subcategory:
        query = query.filter_by(subcategory=subcategory)
    if quality in EquipmentItem.QUALITIES:
        query = query.filter_by(quality=quality)
    if search:
        query = query.filter(EquipmentItem.name.ilike(f'%{search}%'))

    items = query.order_by(EquipmentItem.category, EquipmentItem.name).all()
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
        subcategory_labels=EquipmentItem.SUBCATEGORY_LABELS,
    )


@equipment_bp.route('/<int:item_id>')
def detail(item_id):
    item = EquipmentItem.query.get_or_404(item_id)
    return render_template('equipment/detail.html', item=item)


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
    item.is_special = f.get('is_special') == 'on'
    base_item_id = f.get('base_item_id', '').strip()
    item.base_item_id = int(base_item_id) if base_item_id else None
    item.price_text = f.get('price_text', '').strip() or None
    item.description = f.get('description', '').strip() or None

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

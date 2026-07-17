import difflib
import gzip
import io
import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime
from markupsafe import Markup
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, current_app, jsonify, send_file, abort)
from flask_login import login_required, current_user
from app.extensions import db
from app.models.user import User
from app.models.profession import Profession, ProfessionSkill, ProfessionTalent, ProfessionTrapping
from app.models.skill import Skill
from app.models.talent import Talent
from app.models.synonym import Synonym, DEFAULT_SYNONYMS
from app.models.permission import Permission, PermissionTemplate, ALL_PERMISSIONS
from app.models.contact import Contact, ContactProfession
from app.models.character import Character
from app.models.food import CookingMethod, Ingredient, IngredientCookingMethod, Recipe
from app.models.equipment import EquipmentItem
from app.models.shop import current_markup_pct, set_markup_pct
from app.utils import (
    admin_required, allowed_file, generate_secure_password,
    json_download_response, flash_import_summary,
)
from app.services.pdf_processor import process_pdf
from app.services.contact_import_service import import_contacts_from_excel, export_contacts_to_excel

logger = logging.getLogger(__name__)

admin_bp = Blueprint('admin', __name__, template_folder='../templates')

# ---------------------------------------------------------------------------
# Async PDF job management (file-based state, cross-worker safe)
# ---------------------------------------------------------------------------

# Lives on a dedicated volume (not tempfile.gettempdir()/tmp), so a completed
# PDF review session survives a container restart/redeploy - not just a closed
# browser tab. Deliberately NOT under UPLOAD_FOLDER: that folder is served
# publicly (unauthenticated) via main.uploaded_file, and this cache holds
# in-progress admin-only import data.
_PDF_CACHE_ROOT = os.environ.get('PDF_CACHE_DIR', '/app/pdf_cache')
_JOBS_DIR  = os.path.join(_PDF_CACHE_ROOT, 'jobs')
_CACHE_DIR = os.path.join(_PDF_CACHE_ROOT, 'cache')
os.makedirs(_JOBS_DIR,  exist_ok=True)
os.makedirs(_CACHE_DIR, exist_ok=True)

_CACHE_TTL = 48 * 3600   # 48 h


def _job_path(job_id: str) -> str:
    safe = ''.join(c for c in job_id if c.isalnum() or c == '-')
    return os.path.join(_JOBS_DIR, f'{safe}.json')


def _write_job(job_id: str, data: dict) -> None:
    path = _job_path(job_id)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _read_job(job_id: str) -> dict | None:
    path = _job_path(job_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _cache_path(cache_id: str) -> str:
    safe = ''.join(c for c in cache_id if c.isalnum() or c == '-')
    return os.path.join(_CACHE_DIR, f'{safe}.json')


def _write_cache(cache_id: str, data: dict) -> None:
    path = _cache_path(cache_id)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _read_cache(cache_id: str) -> dict | None:
    path = _cache_path(cache_id)
    if not os.path.exists(path):
        return None
    try:
        if time.time() - os.path.getmtime(path) > _CACHE_TTL:
            try:
                os.remove(path)
            except OSError:
                pass
            return None
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _run_pdf_job(job_id: str, file_bytes: bytes, fmt: str = 'auto') -> None:
    def progress_cb(percent: int, stage: str) -> None:
        job = _read_job(job_id) or {}
        job.update(percent=percent, stage=stage)
        _write_job(job_id, job)

    try:
        result = process_pdf(file_bytes, progress_cb=progress_cb, format_hint=fmt)
        job = _read_job(job_id) or {}
        job.update(percent=100, stage='Completado', done=True, result=result)
        _write_job(job_id, job)
    except Exception as e:
        logger.error('PDF job %s failed: %s', job_id, e, exc_info=True)
        job = _read_job(job_id) or {}
        job.update(done=True, error=str(e), stage='Error')
        _write_job(job_id, job)


@admin_bp.route('/')
@login_required
@admin_required
def dashboard():
    stats = {
        'users': User.query.count(),
        'professions': Profession.query.count(),
        'skills': Skill.query.count(),
        'talents': Talent.query.count(),
        'basic': Profession.query.filter_by(type='basic').count(),
        'advanced': Profession.query.filter_by(type='advanced').count(),
        'total_contacts': Contact.query.count(),
        'visible_contacts': Contact.query.filter_by(is_visible=True).count(),
        'characters': Character.query.count(),
        'recipes_pending': Recipe.query.filter_by(status='pendiente').count(),
        'equipment': EquipmentItem.query.count(),
    }
    return render_template('admin/dashboard.html', stats=stats)


# ---- User management ----

@admin_bp.route('/usuarios')
@login_required
@admin_required
def users():
    users_list  = User.query.order_by(User.created_at.desc()).all()
    templates   = PermissionTemplate.query.order_by(PermissionTemplate.name).all()
    return render_template('admin/users.html', users=users_list, templates=templates)


@admin_bp.route('/usuarios/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def user_new():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        role = request.form.get('role', 'user')
        active = request.form.get('active') == 'on'

        if not username or not email:
            flash('Usuario y email son obligatorios.', 'danger')
        elif User.query.filter_by(username=username).first():
            flash('El nombre de usuario ya existe.', 'danger')
        elif User.query.filter_by(email=email).first():
            flash('El email ya está en uso.', 'danger')
        else:
            password = generate_secure_password()
            user = User(
                username=username,
                email=email,
                role=role if role in ('admin', 'user') else 'user',
                active=active,
                must_change_password=True,
                created_by_id=current_user.id,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash(Markup('Usuario creado. Contraseña temporal: <strong>{}</strong>').format(password), 'success')
            return redirect(url_for('admin.users'))

    return render_template('admin/user_new.html')


@admin_bp.route('/usuarios/<int:user_id>/restablecer-clave', methods=['POST'])
@login_required
@admin_required
def user_reset_password(user_id):
    user = User.query.get_or_404(user_id)
    password = generate_secure_password()
    user.set_password(password)
    user.must_change_password = True
    db.session.commit()
    flash(Markup('Contraseña de <strong>{}</strong> restablecida: <strong>{}</strong>')
          .format(user.username, password), 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/usuarios/<int:user_id>/forzar-cambio-clave', methods=['POST'])
@login_required
@admin_required
def user_force_password_change(user_id):
    user = User.query.get_or_404(user_id)
    user.must_change_password = True
    db.session.commit()
    flash(f'«{user.username}» deberá cambiar su contraseña en el próximo inicio de sesión.', 'info')
    return redirect(url_for('admin.users'))


@admin_bp.route('/usuarios/<int:user_id>/establecer-clave', methods=['POST'])
@login_required
@admin_required
def user_set_password(user_id):
    user = User.query.get_or_404(user_id)
    password = request.form.get('password', '')
    confirm = request.form.get('confirm_password', '')

    if len(password) < 8:
        flash('La contraseña debe tener al menos 8 caracteres.', 'danger')
    elif password != confirm:
        flash('Las contraseñas no coinciden.', 'danger')
    else:
        user.set_password(password)
        user.must_change_password = request.form.get('force_change') == 'on'
        db.session.commit()
        flash(f'Contraseña de «{user.username}» actualizada.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/usuarios/<int:user_id>/permisos', methods=['GET', 'POST'])
@login_required
@admin_required
def user_edit(user_id):
    from flask_login import current_user as me
    user      = User.query.get_or_404(user_id)
    templates = PermissionTemplate.query.order_by(PermissionTemplate.name).all()
    # Group permissions by module for display
    perms_by_module = {}
    for code, name, desc, module in ALL_PERMISSIONS:
        perms_by_module.setdefault(module, []).append(
            Permission(code=code, name=name, description=desc, module=module)
        )

    if request.method == 'POST':
        # Template assignment
        tpl_id = request.form.get('template_id', '').strip()
        user.template_id = int(tpl_id) if tpl_id.isdigit() else None

        # Direct permission overrides: rebuild from checkboxes
        selected_codes = set(request.form.getlist('permissions'))
        all_codes      = {code for code, *_ in ALL_PERMISSIONS}
        # Remove permissions no longer checked
        user.direct_permissions = [
            db.session.get(Permission, c)
            for c in selected_codes
            if c in all_codes and db.session.get(Permission, c)
        ]
        db.session.commit()
        flash(f'Permisos de "{user.username}" actualizados.', 'success')
        return redirect(url_for('admin.users'))

    effective = user.effective_perm_codes()
    direct    = {p.code for p in user.direct_permissions}
    return render_template(
        'admin/user_edit.html',
        user=user,
        templates=templates,
        perms_by_module=perms_by_module,
        effective=effective,
        direct=direct,
    )


# ── Permission template management ───────────────────────────────────────────

@admin_bp.route('/plantillas')
@login_required
@admin_required
def permission_templates():
    templates = PermissionTemplate.query.order_by(PermissionTemplate.name).all()
    return render_template('admin/permission_templates.html', templates=templates)


@admin_bp.route('/plantillas/exportar')
@login_required
@admin_required
def permission_templates_export():
    from app.services.backup_service import export_permission_templates
    return json_download_response(export_permission_templates(), 'plantillas_permisos_backup.json')


@admin_bp.route('/plantillas/importar', methods=['GET', 'POST'])
@login_required
@admin_required
def permission_templates_import():
    if request.method == 'GET':
        return render_template('admin/permission_templates_import.html')

    f = request.files.get('file')
    if not f or not f.filename:
        flash('Selecciona un fichero JSON.', 'danger')
        return redirect(request.url)

    try:
        data = json.loads(f.read())
    except Exception as e:
        flash(f'Error al leer el fichero: {e}', 'danger')
        return redirect(request.url)

    from app.services.backup_service import import_permission_templates
    mode = request.form.get('mode', 'skip')
    summary = import_permission_templates(data, mode=mode)
    flash_import_summary(summary)
    return redirect(url_for('admin.permission_templates'))


@admin_bp.route('/plantillas/nueva', methods=['GET', 'POST'])
@login_required
@admin_required
def permission_template_create():
    perms_by_module = {}
    for code, name, desc, module in ALL_PERMISSIONS:
        perms_by_module.setdefault(module, []).append(
            Permission(code=code, name=name, description=desc, module=module)
        )

    if request.method == 'POST':
        name  = request.form.get('name', '').strip()
        desc  = request.form.get('description', '').strip()
        codes = request.form.getlist('permissions')
        if not name:
            flash('El nombre de la plantilla es obligatorio.', 'danger')
        elif PermissionTemplate.query.filter_by(name=name).first():
            flash(f'Ya existe una plantilla llamada "{name}".', 'danger')
        else:
            perms = [db.session.get(Permission, c) for c in codes if db.session.get(Permission, c)]
            db.session.add(PermissionTemplate(name=name, description=desc or None, permissions=perms))
            db.session.commit()
            flash(f'Plantilla "{name}" creada.', 'success')
            return redirect(url_for('admin.permission_templates'))

    return render_template(
        'admin/template_edit.html',
        template=None,
        perms_by_module=perms_by_module,
        checked=set(),
    )


@admin_bp.route('/plantillas/<int:tpl_id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def permission_template_edit(tpl_id):
    tpl  = PermissionTemplate.query.get_or_404(tpl_id)
    perms_by_module = {}
    for code, name, desc, module in ALL_PERMISSIONS:
        perms_by_module.setdefault(module, []).append(
            Permission(code=code, name=name, description=desc, module=module)
        )

    if request.method == 'POST':
        name  = request.form.get('name', '').strip()
        desc  = request.form.get('description', '').strip()
        codes = request.form.getlist('permissions')
        if not name:
            flash('El nombre de la plantilla es obligatorio.', 'danger')
        else:
            existing = PermissionTemplate.query.filter_by(name=name).first()
            if existing and existing.id != tpl_id:
                flash(f'Ya existe otra plantilla llamada "{name}".', 'danger')
            else:
                tpl.name        = name
                tpl.description = desc or None
                tpl.permissions = [
                    db.session.get(Permission, c) for c in codes if db.session.get(Permission, c)
                ]
                db.session.commit()
                flash(f'Plantilla "{name}" guardada.', 'success')
                return redirect(url_for('admin.permission_templates'))

    checked = {p.code for p in tpl.permissions}
    return render_template(
        'admin/template_edit.html',
        template=tpl,
        perms_by_module=perms_by_module,
        checked=checked,
    )


@admin_bp.route('/plantillas/<int:tpl_id>/eliminar', methods=['POST'])
@login_required
@admin_required
def permission_template_delete(tpl_id):
    tpl  = PermissionTemplate.query.get_or_404(tpl_id)
    name = tpl.name
    # Unlink users that had this template
    for u in User.query.filter_by(template_id=tpl_id).all():
        u.template_id = None
    db.session.delete(tpl)
    db.session.commit()
    flash(f'Plantilla "{name}" eliminada.', 'warning')
    return redirect(url_for('admin.permission_templates'))


@admin_bp.route('/usuarios/<int:user_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == request.environ.get('flask_login_user_id'):
        flash('No puedes desactivar tu propia cuenta.', 'danger')
    else:
        user.active = not user.active
        db.session.commit()
        status = 'activado' if user.active else 'desactivado'
        flash(f'Usuario "{user.username}" {status}.', 'info')
    return redirect(url_for('admin.users'))


@admin_bp.route('/usuarios/<int:user_id>/toggle-sin-coste', methods=['POST'])
@login_required
@admin_required
def toggle_no_cost_equipment(user_id):
    user = User.query.get_or_404(user_id)
    user.puede_anadir_equipo_sin_coste = not user.puede_anadir_equipo_sin_coste
    db.session.commit()
    status = 'habilitada' if user.puede_anadir_equipo_sin_coste else 'deshabilitada'
    flash(f'Alta de equipo sin coste {status} para "{user.username}".', 'info')
    return redirect(url_for('admin.users'))


@admin_bp.route('/usuarios/<int:user_id>/rol', methods=['POST'])
@login_required
@admin_required
def change_role(user_id):
    user = User.query.get_or_404(user_id)
    new_role = request.form.get('role', 'user')
    if new_role in ('admin', 'user'):
        user.role = new_role
        db.session.commit()
        flash(f'Rol de "{user.username}" cambiado a {new_role}.', 'info')
    return redirect(url_for('admin.users'))


@admin_bp.route('/usuarios/<int:user_id>/eliminar', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    from flask_login import current_user
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('No puedes eliminar tu propia cuenta.', 'danger')
    else:
        name = user.username
        db.session.delete(user)
        db.session.commit()
        flash(f'Usuario "{name}" eliminado.', 'warning')
    return redirect(url_for('admin.users'))


@admin_bp.route('/usuarios/exportar')
@login_required
@admin_required
def users_export():
    from app.services.backup_service import export_users
    return json_download_response(export_users(), 'usuarios_backup.json')


@admin_bp.route('/usuarios/importar', methods=['GET', 'POST'])
@login_required
@admin_required
def users_import():
    if request.method == 'GET':
        return render_template('admin/users_import.html')

    f = request.files.get('file')
    if not f or not f.filename:
        flash('Selecciona un fichero JSON.', 'danger')
        return redirect(request.url)

    try:
        data = json.loads(f.read())
    except Exception as e:
        flash(f'Error al leer el fichero: {e}', 'danger')
        return redirect(request.url)

    from app.services.backup_service import import_users
    mode = request.form.get('mode', 'skip')
    summary = import_users(data, mode=mode)
    flash_import_summary(summary)
    return redirect(url_for('admin.users'))


# ---- Personajes: backup (todos los personajes del sistema, no solo los
# propios - por eso vive en admin, no en el blueprint de characters) ----

@admin_bp.route('/personajes/exportar')
@login_required
@admin_required
def characters_export():
    from app.services.backup_service import export_characters
    return json_download_response(export_characters(), 'personajes_backup.json')


@admin_bp.route('/personajes/importar', methods=['GET', 'POST'])
@login_required
@admin_required
def characters_import():
    if request.method == 'GET':
        return render_template('admin/characters_import.html')

    f = request.files.get('file')
    if not f or not f.filename:
        flash('Selecciona un fichero JSON.', 'danger')
        return redirect(request.url)

    try:
        data = json.loads(f.read())
    except Exception as e:
        flash(f'Error al leer el fichero: {e}', 'danger')
        return redirect(request.url)

    from app.services.backup_service import import_characters
    mode = request.form.get('mode', 'skip')
    summary = import_characters(data, mode=mode)
    flash_import_summary(summary)
    return redirect(url_for('characters.list_characters'))


# ---- PDF upload & review ----

@admin_bp.route('/pdf', methods=['GET', 'POST'])
@login_required
@admin_required
def pdf_upload():
    if request.method == 'GET':
        return render_template('admin/pdf_upload.html')

    # POST: validate file and start background job; return JSON
    if 'pdf_file' not in request.files:
        return jsonify({'error': 'No se seleccionó ningún archivo.'}), 400

    file = request.files['pdf_file']
    if not file or not file.filename:
        return jsonify({'error': 'Archivo vacío.'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'Solo se aceptan archivos PDF.'}), 400

    file_bytes = file.read()
    pdf_format = request.form.get('pdf_format', 'auto')
    job_id = str(uuid.uuid4())

    _write_job(job_id, {
        'id': job_id,
        'filename': file.filename,
        'percent': 0,
        'stage': 'Iniciando procesamiento…',
        'done': False,
        'error': None,
        'result': None,
        'started_at': time.time(),
        'format': pdf_format,
    })

    thread = threading.Thread(target=_run_pdf_job, args=(job_id, file_bytes, pdf_format), daemon=True)
    thread.start()

    return jsonify({'job_id': job_id})


@admin_bp.route('/pdf/progress/<job_id>')
@login_required
@admin_required
def pdf_progress(job_id):
    job = _read_job(job_id)
    if job is None:
        return jsonify({'error': 'Trabajo no encontrado.'}), 404
    return jsonify({
        'percent': job.get('percent', 0),
        'stage': job.get('stage', ''),
        'done': job.get('done', False),
        'error': job.get('error'),
    })


@admin_bp.route('/pdf/result/<job_id>')
@login_required
@admin_required
def pdf_result(job_id):
    job = _read_job(job_id)
    if job is None or not job.get('done'):
        flash('El procesamiento no ha terminado o el trabajo ha expirado.', 'danger')
        return redirect(url_for('admin.pdf_upload'))

    if job.get('error'):
        flash(f'Error durante el procesamiento: {job["error"]}', 'danger')
        return redirect(url_for('admin.pdf_upload'))

    result   = job.get('result') or {}
    filename = job.get('filename', '')

    # Persist result for resume functionality (survives tab switch / server restart)
    _write_cache(job_id, {'result': result, 'filename': filename, 'saved_at': time.time()})

    try:
        os.remove(_job_path(job_id))
    except OSError:
        pass

    return _render_pdf_review(job_id, result, filename)


def _render_pdf_review(cache_id: str, result: dict, filename: str):
    """Shared rendering logic for pdf_result and pdf_resume."""
    for err in result.get('errors', []):
        flash(err, 'danger')

    all_skills   = Skill.query.order_by(Skill.name_es).all()
    all_talents  = Talent.query.order_by(Talent.name_es).all()
    skills_data  = [{'es': s.name_es, 'en': s.name_en or ''} for s in all_skills]
    talents_data = [{'es': t.name_es, 'en': t.name_en or ''} for t in all_talents]

    professions = _validate_pdf_professions(result.get('professions', []), all_skills, all_talents)
    for idx, prof_data in enumerate(professions, start=1):
        prof_data['idx'] = idx

    synonyms_data = [
        {'source': s.source, 'target': s.target, 'is_prefix': s.is_prefix}
        for s in Synonym.query.order_by(Synonym.source).all()
    ]
    if not synonyms_data:
        synonyms_data = [
            {'source': src, 'target': tgt, 'is_prefix': pfx}
            for src, tgt, pfx, _ in DEFAULT_SYNONYMS
        ]

    return render_template(
        'admin/pdf_review.html',
        pages=result.get('pages', []),
        professions=professions,
        skills_data=skills_data,
        talents_data=talents_data,
        synonyms_data=synonyms_data,
        db_empty=len(all_skills) == 0 and len(all_talents) == 0,
        cache_id=cache_id,
        pdf_filename=filename,
    )


@admin_bp.route('/pdf/resume/<cache_id>')
@login_required
@admin_required
def pdf_resume(cache_id):
    cached = _read_cache(cache_id)
    if not cached:
        flash('La sesión ha expirado o el PDF ya no está disponible. Procesa el PDF de nuevo.', 'warning')
        return redirect(url_for('admin.pdf_upload'))
    return _render_pdf_review(cache_id, cached.get('result') or {}, cached.get('filename', ''))


@admin_bp.route('/pdf/guardar', methods=['POST'])
@login_required
@admin_required
def pdf_save():
    """
    Save one parsed profession from the PDF review form.

    save_mode:
      'create'  — always create a new profession (default)
      'update'  — overwrite the existing profession identified by existing_prof_id
      'skip'    — discard import, go to existing profession
    """
    from flask_login import current_user

    name = request.form.get('name', '').strip()
    if not name:
        flash('La profesión necesita un nombre.', 'danger')
        return redirect(url_for('admin.pdf_upload'))

    save_mode = request.form.get('save_mode', 'create')
    existing_prof_id = request.form.get('existing_prof_id', type=int)

    # ── Skip mode ─────────────────────────────────────────────────────────
    if save_mode == 'skip' and existing_prof_id:
        existing = db.session.get(Profession, existing_prof_id)
        if existing:
            flash(f'Profesión "{existing.name}" omitida — se mantiene la versión existente.', 'info')
            return redirect(url_for('professions.edit', prof_id=existing.id))

    # ── Update mode ────────────────────────────────────────────────────────
    if save_mode == 'update' and existing_prof_id:
        prof = db.session.get(Profession, existing_prof_id)
        if prof:
            prof.name    = name
            prof.name_en = request.form.get('name_en', '').strip() or None
            prof.type    = request.form.get('type', 'basic')
            for field in Profession.PRIMARY_FIELDS + Profession.SECONDARY_FIELDS:
                val = request.form.get(field, '').strip()
                setattr(prof, field, int(val) if val.lstrip('-').isdigit() else None)
            db.session.flush()
            # Clear and re-add relations
            ProfessionSkill.query.filter_by(profession_id=prof.id).delete()
            ProfessionTalent.query.filter_by(profession_id=prof.id).delete()
            ProfessionTrapping.query.filter_by(profession_id=prof.id).delete()
            _apply_prof_relations(prof)
            db.session.commit()
            flash(f'Profesión "{prof.name}" actualizada desde el PDF.', 'success')
            return redirect(url_for('professions.edit', prof_id=prof.id))

    # ── Safety net against silent duplicates ────────────────────────────────
    # The review page's "already exists" banner only reflects DB state at PDF
    # PARSE time. If this form is being submitted without an existing_prof_id
    # (no duplicate was known then), re-check right now before creating - a
    # resumed/cached review session re-submitted after the profession was
    # already saved once is exactly how this created real duplicates before.
    if not existing_prof_id:
        surprise_dup = Profession.query.filter(
            db.func.lower(Profession.name) == name.lower()
        ).first()
        if surprise_dup:
            flash(
                f'Ya existe una profesión llamada "{surprise_dup.name}" — probablemente '
                'guardada después de generarse esta revisión (p.ej. al retomar una sesión '
                'ya guardada antes). No se ha creado un duplicado; revisa la existente.',
                'warning',
            )
            return redirect(url_for('professions.edit', prof_id=surprise_dup.id))

    # ── Create mode (default) ──────────────────────────────────────────────
    prof = Profession(
        name=name,
        name_en=request.form.get('name_en', '').strip() or None,
        type=request.form.get('type', 'basic'),
        description=request.form.get('description', '').strip() or None,
        created_by_id=current_user.id,
    )
    for field in Profession.PRIMARY_FIELDS + Profession.SECONDARY_FIELDS:
        val = request.form.get(field, '').strip()
        setattr(prof, field, int(val) if val.lstrip('-').isdigit() else None)

    db.session.add(prof)
    db.session.flush()
    _apply_prof_relations(prof)
    db.session.commit()
    flash(f'Profesión "{prof.name}" guardada. Recuerda vincular accesos/salidas.', 'success')
    return redirect(url_for('professions.edit', prof_id=prof.id))


def _apply_prof_relations(prof: 'Profession') -> None:
    """Add trappings, skills and talents from the current request form to prof."""
    for item in request.form.get('trappings_raw', '').split(','):
        item = item.strip()
        if item:
            db.session.add(ProfessionTrapping(profession_id=prof.id, name=item))

    _match_and_save_skills(
        prof,
        request.form.get('skills_raw', ''),
        request.form.get('skills_raw_en', ''),
    )
    _match_and_save_talents(
        prof,
        request.form.get('talents_raw', ''),
        request.form.get('talents_raw_en', ''),
    )

    exits_raw   = request.form.get('exits_raw', '').strip()
    entries_raw = request.form.get('entries_raw', '').strip()

    pending_notes = []

    if exits_raw:
        matched, unmatched = _fuzzy_link_professions(exits_raw)
        for target in matched:
            if target.id != prof.id and target not in prof.exits:
                prof.exits.append(target)
        if unmatched:
            pending_notes.append(f'[SALIDAS PENDIENTES DE VINCULAR]: {", ".join(unmatched)}')

    if entries_raw:
        # Entries aren't a stored field (they're derived from other professions'
        # exits) - so an entry name that matches an existing profession gets
        # linked in the OTHER direction: that profession gains this one as an exit.
        matched, unmatched = _fuzzy_link_professions(entries_raw)
        for source in matched:
            if source.id != prof.id and prof not in source.exits:
                source.exits.append(prof)
        if unmatched:
            pending_notes.append(f'[ACCESOS PENDIENTES DE VINCULAR]: {", ".join(unmatched)}')

    if pending_notes:
        prof.description = (prof.description or '') + '\n' + '\n'.join(pending_notes)


def _fuzzy_link_professions(raw_text: str, cutoff: float = 0.8):
    """
    Fuzzy-match each comma-separated profession name in raw_text against
    professions already in the DB.
    Returns (matched_profession_objects, unmatched_name_strings).
    """
    candidates = [c.strip() for c in raw_text.split(',') if c.strip()]
    if not candidates:
        return [], []

    exact_syn, prefix_syn = _get_synonyms_dicts()
    name_map = {p.name.lower(): p for p in Profession.query.all()}

    matched, unmatched = [], []
    for cand in candidates:
        # Correct GTranslate-vs-official-name mismatches before matching
        # (e.g. "Campeón" -> "héroe"), same dictionary used for skill/talent names.
        low = _normalize_item(cand, exact_syn, prefix_syn)
        prof_obj = name_map.get(low)
        if not prof_obj:
            hits = difflib.get_close_matches(low, name_map.keys(), n=1, cutoff=cutoff)
            if hits:
                prof_obj = name_map[hits[0]]
        if prof_obj:
            matched.append(prof_obj)
        else:
            unmatched.append(cand)
    return matched, unmatched


def _capitalize_first(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def _normalize_career_list(raw: str, exact_syns: dict, prefix_syns: dict) -> str:
    """
    Apply the ES synonym dictionary to each comma-separated profession name
    in an exits/entries list, correcting GTranslate-vs-official-name mismatches
    (e.g. 'campeón' -> 'héroe') for display in the PDF review form.
    """
    if not raw:
        return raw
    corrected = []
    for item in raw.split(','):
        item = item.strip()
        if not item:
            continue
        low = item.lower()
        if low in exact_syns:
            corrected.append(_capitalize_first(exact_syns[low]))
            continue
        replaced = False
        for key in sorted(prefix_syns, key=len, reverse=True):
            if low.startswith(key + ' (') or low.startswith(key + '('):
                corrected.append(_capitalize_first(prefix_syns[key] + item[len(key):]))
                replaced = True
                break
        if not replaced:
            corrected.append(item)
    return ', '.join(corrected)


# ---------------------------------------------------------------------------
# Synonym helpers — DB-backed, with hardcoded fallback
# ---------------------------------------------------------------------------

# Stat characteristic abbreviations — used to strip trailing "(Int)", "(Ag)", etc.
_STAT_ABBREVS = frozenset({
    'HA', 'HP', 'F', 'R', 'AG', 'I', 'V', 'EM',
    'A', 'H', 'BF', 'BR', 'M', 'MAG', 'PL', 'PD',
    'WS', 'BS', 'S', 'T', 'INT', 'WP', 'FEL',
    'W', 'SB', 'TB', 'IP', 'FP',
})
_RE_STAT_SUFFIX = re.compile(r'\s*\(([A-Za-z]{1,4})\)\s*$')

# EN synonyms for matching English PDF terms against DB name_en
_EN_SYNONYMS = {
    'academic knowledge': 'academic knowledge',
    'common knowledge':   'common knowledge',
    'read/write':         'read/write',
    'gossip':             'gossip',
    'heal':               'heal',
}


def _strip_stat_suffix(text: str) -> str:
    """Remove trailing '(Xxx)' only when Xxx is a known characteristic abbreviation."""
    m = _RE_STAT_SUFFIX.search(text)
    if m and m.group(1).upper() in _STAT_ABBREVS:
        return text[:m.start()].strip()
    return text.strip()


def _get_synonyms_dicts():
    """
    Load synonym dicts from DB.
    Returns (exact_dict, prefix_dict) where keys are lower-case source terms.
    Falls back to DEFAULT_SYNONYMS if the table is empty or unreachable.
    """
    try:
        rows = Synonym.query.all()
    except Exception:
        rows = []

    exact  = {}
    prefix = {}
    for s in rows:
        key = s.source.lower()
        if s.is_prefix:
            prefix[key] = s.target
        else:
            exact[key] = s.target

    if not exact and not prefix:
        # Seed fallback from defaults (table not yet seeded)
        for source, target, is_prefix, _ in DEFAULT_SYNONYMS:
            if is_prefix:
                prefix[source.lower()] = target
            else:
                exact[source.lower()] = target

    return exact, prefix


def _normalize_item(item: str, exact_syns: dict, prefix_syns: dict = None) -> str:
    """
    Strip stat suffix, apply synonym dicts (exact first, then prefix),
    return lower-cased token.
    """
    stripped = _strip_stat_suffix(item)
    low = stripped.lower().strip()

    if low in exact_syns:
        return exact_syns[low]

    if prefix_syns:
        # Sort by length descending so longer keys win over shorter ones
        for key in sorted(prefix_syns, key=len, reverse=True):
            if low.startswith(key + ' (') or low.startswith(key + '('):
                return prefix_syns[key] + stripped[len(key):]

    return low


def _fuzzy_match(item: str, name_set: set,
                 exact_syns: dict, prefix_syns: dict = None,
                 cutoff: float = 0.65) -> bool:
    """
    Multi-strategy matching.  Returns True on first hit.
      1. Synonym normalization + direct hit
      2. difflib fuzzy on normalised name
      3. Slash-component split
      4. Base-name (strip specialization parens)
    """
    norm = _normalize_item(item, exact_syns, prefix_syns)

    if norm in name_set:
        return True
    if difflib.get_close_matches(norm, name_set, n=1, cutoff=cutoff):
        return True

    parts = [p.strip() for p in re.split(r'[/,]', norm) if p.strip()]
    if len(parts) > 1 and any(
        difflib.get_close_matches(p, name_set, n=1, cutoff=cutoff) for p in parts
    ):
        return True

    base = re.sub(r'\s*\(.*$', '', norm).strip()
    if base and base != norm:
        if base in name_set:
            return True
        if difflib.get_close_matches(base, name_set, n=1, cutoff=cutoff):
            return True

    return False


def _fuzzy_find(item: str, name_map: dict,
                exact_syns: dict, prefix_syns: dict = None,
                cutoff: float = 0.7):
    """
    Like _fuzzy_match but returns the matched DB object (or None).
    name_map: {lower-cased name: db_object}
    """
    norm = _normalize_item(item, exact_syns, prefix_syns)

    if norm in name_map:
        return name_map[norm]

    hits = difflib.get_close_matches(norm, name_map.keys(), n=1, cutoff=cutoff)
    if hits:
        return name_map[hits[0]]

    parts = [p.strip() for p in re.split(r'[/,]', norm) if p.strip()]
    for part in parts:
        hits = difflib.get_close_matches(part, name_map.keys(), n=1, cutoff=cutoff)
        if hits:
            return name_map[hits[0]]

    base = re.sub(r'\s*\(.*$', '', norm).strip()
    if base and base != norm:
        if base in name_map:
            return name_map[base]
        hits = difflib.get_close_matches(base, name_map.keys(), n=1, cutoff=cutoff)
        if hits:
            return name_map[hits[0]]

    return None


_RE_TRAILING_PAREN = re.compile(r'\s*\([^)]*\)\s*$')


def _debase(name: str) -> str:
    """Strip a trailing '(...)' from a catalog name, e.g. 'Actuar (Varios)' ->
    'actuar'. Catalog skills/talents that require a specialization store a
    '(Varios)' marker in name_es/name_en; an item can instead supply its own
    free-form choice-count descriptor (e.g. 'Actuar (dos cualesquiera)') whose
    text has little resemblance to the literal word 'Varios', so a fuzzy-ratio
    comparison against the full catalog name can fall short of the cutoff even
    though the base skill is obviously valid. Adding this bare form alongside
    the full name lets base-name lookups succeed via exact match instead of
    relying on fuzzy similarity to 'Varios'. No-op for names with no
    parenthetical."""
    return _RE_TRAILING_PAREN.sub('', name).strip().lower()


def _validate_pdf_professions(professions: list, all_skills, all_talents) -> list:
    """
    Enrich each profession dict with validation data:
      unmatched_skills  — items that couldn't be matched in DB
      unmatched_talents — same for talents
      is_en_source      — True when English raw is being used for matching
      existing_prof     — dict with DB profession data if a same-name prof already exists
      no_exits / no_entries — structural warnings
    """
    skill_names  = set()
    for s in all_skills:
        skill_names.add(s.name_es.lower())
        skill_names.add(_debase(s.name_es))
        if s.name_en:
            skill_names.add(s.name_en.lower())
            skill_names.add(_debase(s.name_en))

    talent_names = set()
    for t in all_talents:
        talent_names.add(t.name_es.lower())
        talent_names.add(_debase(t.name_es))
        if t.name_en:
            talent_names.add(t.name_en.lower())
            talent_names.add(_debase(t.name_en))

    # Load ES synonyms once — used for both name correction and chip validation
    es_exact, es_prefix = _get_synonyms_dicts()

    # Name → object maps for canonicalizing skills_raw/talents_raw below —
    # same shape _match_and_save_skills/_match_and_save_talents build at save time.
    skill_map  = {s.name_es.lower(): s for s in all_skills}
    skill_map.update({s.name_en.lower(): s for s in all_skills if s.name_en})
    for s in all_skills:
        skill_map.setdefault(_debase(s.name_es), s)
        if s.name_en:
            skill_map.setdefault(_debase(s.name_en), s)
    talent_map = {t.name_es.lower(): t for t in all_talents}
    talent_map.update({t.name_en.lower(): t for t in all_talents if t.name_en})
    for t in all_talents:
        talent_map.setdefault(_debase(t.name_es), t)
        if t.name_en:
            talent_map.setdefault(_debase(t.name_en), t)

    # All existing profession names, loaded once, used for exact + fuzzy duplicate checks below.
    all_prof_rows = Profession.query.with_entities(Profession.id, Profession.name).all()
    prof_name_map = {p.name.lower(): (p.id, p.name) for p in all_prof_rows}

    for prof in professions:
        # ── Apply synonym to profession name ──────────────────────────────
        raw_name = prof.get('name', '')
        if raw_name:
            lower = raw_name.lower()
            if lower in es_exact:
                prof['name'] = es_exact[lower]
            else:
                for key in sorted(es_prefix, key=len, reverse=True):
                    if lower.startswith(key + ' (') or lower.startswith(key + '('):
                        prof['name'] = es_prefix[key] + raw_name[len(key):]
                        break

        # ── Apply synonym to career entries/exits lists ────────────────────
        # Same GTranslate-vs-official-name gap as profession names above
        # (e.g. English "Champion" → official "Héroe", not the literal
        # "Campeón"), but for the OTHER career names listed as accesos/salidas.
        prof['exits_raw']   = _normalize_career_list(prof.get('exits_raw', ''),   es_exact, es_prefix)
        prof['entries_raw'] = _normalize_career_list(prof.get('entries_raw', ''), es_exact, es_prefix)

        # ── Canonicalize skill/talent chips to the exact catalog name ───────
        # A profession may only ever reference skills/talents already in the
        # catalog (an "A o B" choice group is still built from two existing
        # entries, never free text). Using _fuzzy_find here — the exact same
        # matcher _match_and_save_skills/_match_and_save_talents use at save
        # time — means a near-miss like "preparar veneno" is rewritten to the
        # real "Preparar venenos" chip *before* the admin ever sees it, instead
        # of silently linking to the right skill behind a misleading label
        # (or, worse, tempting the admin to create a stray near-duplicate
        # catalog entry via "crea la habilidad/talento primero").
        prof['skills_raw']  = _canonicalize_catalog_list(prof.get('skills_raw', ''),  skill_map,  es_exact, es_prefix)
        prof['talents_raw'] = _canonicalize_catalog_list(prof.get('talents_raw', ''), talent_map, es_exact, es_prefix)

        # ── Duplicate detection ────────────────────────────────────────────
        existing = Profession.query.filter(
            db.func.lower(Profession.name) == prof.get('name', '').lower()
        ).first()
        if existing:
            prof['existing_prof'] = {
                'id':             existing.id,
                'name':           existing.name,
                'type':           existing.type,
                'skill_count':    len(existing.profession_skills),
                'talent_count':   len(existing.profession_talents),
                'trapping_count': len(existing.trappings),
                **{f: getattr(existing, f)
                   for f in (Profession.PRIMARY_FIELDS + Profession.SECONDARY_FIELDS)},
            }
        else:
            prof['existing_prof'] = None

        # ── Near-duplicate detection (fuzzy name match, informational only) ──
        # Exact matches are already handled above via existing_prof; this only
        # flags OTHER professions with a similar-but-not-identical name (e.g.
        # OCR/translation variants), so the admin sees possible collisions
        # before creating what might be an unintentional duplicate.
        possible_duplicates = []
        if not existing and prof.get('name'):
            close = difflib.get_close_matches(
                prof['name'].lower(), prof_name_map.keys(), n=3, cutoff=0.82,
            )
            for key in close:
                pid, pname = prof_name_map[key]
                possible_duplicates.append({'id': pid, 'name': pname})
        prof['possible_duplicates'] = possible_duplicates

        if existing:
            prof['dup_status'] = 'exact'
        elif possible_duplicates:
            prof['dup_status'] = 'possible'
        else:
            prof['dup_status'] = 'new'

        # ── Unmatched validation ───────────────────────────────────────────
        is_en = bool(prof.get('skills_raw_en'))
        skills_to_check  = prof.get('skills_raw_en')  or prof.get('skills_raw', '')
        talents_to_check = prof.get('talents_raw_en') or prof.get('talents_raw', '')

        if is_en:
            exact_syn, prefix_syn = _EN_SYNONYMS, {}
        else:
            exact_syn, prefix_syn = es_exact, es_prefix  # reuse already-loaded dicts

        unmatched_skills = []
        if skill_names:
            for comma_part in _split_items_top_level(_strip_choose_n_connector(skills_to_check)):
                alternatives, _ = _split_top_level(comma_part, _RE_ALT_SPLIT)
                for raw in alternatives:
                    item = raw.strip()
                    if not item or len(item) > 80 or '.' in item:
                        continue
                    if not _fuzzy_match(item, skill_names, exact_syn, prefix_syn, cutoff=0.65):
                        unmatched_skills.append(item)

        unmatched_talents = []
        if talent_names:
            for comma_part in _split_items_top_level(_strip_choose_n_connector(talents_to_check)):
                alternatives, _ = _split_top_level(comma_part, _RE_ALT_SPLIT)
                for raw in alternatives:
                    item = raw.strip()
                    if not item or len(item) > 80 or '.' in item:
                        continue
                    if not _fuzzy_match(item, talent_names, exact_syn, prefix_syn, cutoff=0.65):
                        unmatched_talents.append(item)

        prof['unmatched_skills']  = unmatched_skills
        prof['unmatched_talents'] = unmatched_talents
        prof['is_en_source']      = is_en
        prof['no_exits']    = not prof.get('exits_raw', '').strip()
        # Basic professions are commonly starting careers with no entry
        # requirement - only flag missing entries for advanced professions,
        # where it's much more likely to be a real extraction gap.
        prof['no_entries']  = prof.get('type') != 'basic' and not prof.get('entries_raw', '').strip()

    return professions


_RE_SPECIALIZATION = re.compile(r'\s*\(([^)]+)\)\s*$')


def _extract_specialization(chip_text: str) -> str | None:
    """Return the specialization string from 'Base Name (Specialization)', or None."""
    m = _RE_SPECIALIZATION.search(chip_text.strip())
    if m:
        inner = m.group(1).strip()
        if inner.upper() not in _STAT_ABBREVS:
            return inner
    return None


_RE_ALT_SPLIT = re.compile(r'\s+(?:o|u|or)\s+', re.IGNORECASE)
_RE_COMMA     = re.compile(r',')

# Catalog skills that require a specialization store it literally in name_es,
# e.g. "HABLAR IDIOMA (Varios)" or "ACTUAR (Varios)". "(Varios)" there is just
# a marker meaning "pick one", not an actual specialization value — it must be
# dropped before appending the real one, or chips end up as
# "HABLAR IDIOMA (Varios) (Reikspiel)" instead of "HABLAR IDIOMA (Reikspiel)".
_RE_TRAILING_VARIOS = re.compile(r'\s*\(\s*varios\s*\)\s*$', re.IGNORECASE)


def _split_top_level(text: str, pattern: 're.Pattern') -> tuple:
    """Split text on `pattern`, but only where a match occurs at paren-depth 0.
    Returns (parts, seps). Without this, a specialization's own alternative
    or comma list — e.g. 'Hablar idioma (Bretón, Estaliano o Tileano)' — gets
    mistaken for several different skills/talents instead of one skill with
    a multi-choice specialization."""
    parts, seps = [], []
    pos = 0
    for m in pattern.finditer(text):
        depth = text.count('(', 0, m.start()) - text.count(')', 0, m.start())
        if depth != 0:
            continue
        parts.append(text[pos:m.start()])
        seps.append(m.group(0))
        pos = m.end()
    parts.append(text[pos:])
    return parts, seps


def _split_items_top_level(raw: str) -> list:
    """Top-level comma split: ignores commas that sit inside a specialization's
    own parentheses (see _split_top_level)."""
    parts, _ = _split_top_level(raw, _RE_COMMA)
    return [p.strip() for p in parts if p.strip()]


def _canonicalize_one_item(item: str, name_map: dict, exact_syn: dict, prefix_syn: dict) -> str:
    """Rewrite a single chip's base name to the catalog's exact name_es when
    it fuzzy-matches an existing skill/talent (same matcher/cutoff as
    _match_and_save_skills/_match_and_save_talents), keeping any
    '(specialization)' suffix intact. Leaves genuinely unmatched text as-is."""
    spec = _extract_specialization(item)
    base = item[:item.rfind('(')].strip() if spec else item
    match = _fuzzy_find(base, name_map, exact_syn, prefix_syn, cutoff=0.7)
    if not match:
        return item
    if not spec:
        return match.name_es
    match_base = _RE_TRAILING_VARIOS.sub('', match.name_es).strip()
    return f'{match_base} ({spec})'


def _canonicalize_catalog_list(raw: str, name_map: dict, exact_syn: dict, prefix_syn: dict) -> str:
    """
    Rewrite each comma-separated skill/talent chip to its exact catalog name
    wherever it fuzzy-matches an existing entry, so the PDF review UI always
    shows (and the admin edits) the same name that will actually be linked at
    save time — never a near-miss sitting next to the real catalog entry.
    'A o B' / 'A or B' alternatives are canonicalized on each side; a
    specialization's own internal alternative/comma list is left untouched.
    """
    if not raw:
        return raw
    out = []
    for item in _split_items_top_level(_strip_choose_n_connector(raw)):
        alt_parts, alt_seps = _split_top_level(item, _RE_ALT_SPLIT)
        canon = [_canonicalize_one_item(p.strip(), name_map, exact_syn, prefix_syn) for p in alt_parts]
        rebuilt = canon[0]
        for sep, part in zip(alt_seps, canon[1:]):
            rebuilt += sep + part
        out.append(rebuilt)
    return ', '.join(out)


def _split_choice_groups(raw: str) -> list:
    """Split a comma-separated skills/talents string into groups, where each
    group is the list of one or more alternatives joined by 'o'/'u'/'or'
    (an 'A o B' choice — pick exactly one of the group). A plain comma-separated
    item with no alternatives becomes a single-item group. Commas/alternatives
    inside a specialization's own parentheses are not treated as a new item."""
    groups = []
    for comma_part in _split_items_top_level(raw):
        alternatives, _ = _split_top_level(comma_part, _RE_ALT_SPLIT)
        alternatives = [a.strip() for a in alternatives if a.strip()]
        if alternatives:
            groups.append(alternatives)
    return groups


# WFRP2's "pick N of the following" phrasing, e.g. 'Una cualquiera de las
# siguientes: A, B, C' or 'Dos cualesquiera de los siguientes: A, B, C, D'.
# This clause always appears as the trailing part of a skills_raw/talents_raw
# string in the source book, listing the remaining choices after any earlier
# plain/alternative items.
_CHOOSE_N_WORDS = {
    'una': 1, 'uno': 1, 'dos': 2, 'tres': 3, 'cuatro': 4, 'cinco': 5,
    'seis': 6, 'siete': 7, 'ocho': 8,
}
_RE_CHOOSE_N = re.compile(
    r'\b(?P<num>' + '|'.join(_CHOOSE_N_WORDS) + r')\s+cual(?:quiera|esquiera)\s+de\s+(?:las|los)\s+siguientes\s*:\s*',
    re.IGNORECASE,
)


def _strip_choose_n_connector(raw: str) -> str:
    """Turn 'A, B, Una cualquiera de las siguientes: C, D, E' into the plain
    comma list 'A, B, C, D, E' for display/canonicalization/unmatched-detection
    purposes — every listed item genuinely exists in the catalog, only the
    'pick N of these' semantics are lost here. Those semantics are preserved
    at save time for the pick-exactly-one case by _parse_skill_talent_groups."""
    return _RE_CHOOSE_N.sub('', raw)


def _parse_skill_talent_groups(raw: str) -> list:
    """Like _split_choice_groups, but also recognizes the '<N> cualquiera(s)
    de las/los siguientes: A, B, C' pattern. For N == 1 ('Una'/'Uno
    cualquiera'), every listed item becomes ONE shared choice_group (pick
    exactly one) — the choice_group column already supports groups larger
    than two. For N > 1 ('Dos cualesquiera', etc.) there is no schema support
    for 'pick exactly K of N', so the items are kept ungrouped (individually
    valid/matchable) for an admin to regroup manually when integrating the
    profession."""
    m = _RE_CHOOSE_N.search(raw)
    if not m:
        return _split_choice_groups(raw)

    groups = _split_choice_groups(raw[:m.start()])
    count = _CHOOSE_N_WORDS[m.group('num').lower()]
    tail_items = _split_items_top_level(raw[m.end():])

    if count == 1 and len(tail_items) > 1:
        groups.append(tail_items)
    else:
        groups.extend([item] for item in tail_items)
    return groups


def _split_specialization_values(spec: str) -> list:
    """Split a skill/talent's own specialization text into individual named
    values when it lists several choices via 'o'/'u'/commas (e.g. 'el Imperio
    o las Tierras Desoladas', 'Bretón, Reikspiel o Tileano'). The profession
    edit form models each such choice as its own ProfessionSkill/ProfessionTalent
    row sharing one choice_group ('Mismo Gr. = el jugador elige uno'), not one
    flat string — a single free-form choice-count descriptor with no internal
    alternatives (e.g. 'dos cualesquiera') has nothing to split on and comes
    back as a single-item list unchanged."""
    values = []
    for comma_part in _split_items_top_level(spec):
        alt_parts, _ = _split_top_level(comma_part, _RE_ALT_SPLIT)
        values.extend(p.strip() for p in alt_parts if p.strip())
    return values if values else [spec]


def _match_and_save_skills(prof, skills_raw: str, skills_raw_en: str = ''):
    # skills_raw_en is intentionally unused here: it holds the ORIGINAL PDF-extracted
    # English text and is never updated by the review page's chip editor, which only
    # syncs skills_raw (Spanish). Matching against it instead of the user-confirmed
    # chips silently discarded whatever the admin edited/accepted in the review UI.
    all_skills = Skill.query.all()
    skill_map  = {s.name_es.lower(): s for s in all_skills}
    skill_map.update({s.name_en.lower(): s for s in all_skills if s.name_en})
    for s in all_skills:
        skill_map.setdefault(_debase(s.name_es), s)
        if s.name_en:
            skill_map.setdefault(_debase(s.name_en), s)

    exact_syn, prefix_syn = _get_synonyms_dicts()

    seen: set = set()
    next_group = 1
    for alternatives in _parse_skill_talent_groups(skills_raw):
        group_id = None
        if len(alternatives) > 1:
            group_id = next_group
            next_group += 1
        for raw_part in alternatives:
            if len(raw_part) > 80 or '.' in raw_part:
                continue
            skill = _fuzzy_find(raw_part, skill_map, exact_syn, prefix_syn, cutoff=0.7)
            if not skill:
                continue
            spec = _extract_specialization(raw_part)
            spec_values = _split_specialization_values(spec) if spec else [None]
            row_group_id = group_id
            if len(alternatives) == 1 and spec and len(spec_values) > 1:
                # A single skill's own specialization lists several named choices
                # ('el Imperio o las Tierras Desoladas') - each becomes its own row,
                # sharing a fresh choice_group (pick exactly one), same as an
                # ordinary "A o B" choice between two different skills.
                row_group_id = next_group
                next_group += 1
            for spec_value in spec_values:
                key = (skill.id, spec_value)
                if key not in seen:
                    seen.add(key)
                    db.session.add(ProfessionSkill(
                        profession_id=prof.id, skill_id=skill.id, specialization=spec_value,
                        choice_group=row_group_id,
                    ))


def _match_and_save_talents(prof, talents_raw: str, talents_raw_en: str = ''):
    # talents_raw_en is intentionally unused - see the matching comment in
    # _match_and_save_skills above.
    all_talents = Talent.query.all()
    talent_map  = {t.name_es.lower(): t for t in all_talents}
    talent_map.update({t.name_en.lower(): t for t in all_talents if t.name_en})
    for t in all_talents:
        talent_map.setdefault(_debase(t.name_es), t)
        if t.name_en:
            talent_map.setdefault(_debase(t.name_en), t)

    exact_syn, prefix_syn = _get_synonyms_dicts()

    seen: set = set()
    next_group = 1
    for alternatives in _parse_skill_talent_groups(talents_raw):
        group_id = None
        if len(alternatives) > 1:
            group_id = next_group
            next_group += 1
        for raw_part in alternatives:
            if len(raw_part) > 80 or '.' in raw_part:
                continue
            talent = _fuzzy_find(raw_part, talent_map, exact_syn, prefix_syn, cutoff=0.7)
            if not talent:
                continue
            spec = _extract_specialization(raw_part)
            spec_values = _split_specialization_values(spec) if spec else [None]
            row_group_id = group_id
            if len(alternatives) == 1 and spec and len(spec_values) > 1:
                row_group_id = next_group
                next_group += 1
            for spec_value in spec_values:
                key = (talent.id, spec_value)
                if key not in seen:
                    seen.add(key)
                    db.session.add(ProfessionTalent(
                        profession_id=prof.id, talent_id=talent.id, specialization=spec_value,
                        choice_group=row_group_id,
                    ))


# ---------------------------------------------------------------------------
# Synonym dictionary CRUD
# ---------------------------------------------------------------------------

@admin_bp.route('/synonyms')
@login_required
@admin_required
def synonyms():
    q = request.args.get('q', '').strip()
    query = Synonym.query.order_by(Synonym.source)
    if q:
        like = f'%{q}%'
        query = query.filter(
            db.or_(Synonym.source.ilike(like), Synonym.target.ilike(like),
                   Synonym.notes.ilike(like))
        )
    return render_template('admin/synonyms.html', synonyms=query.all(), search=q)


@admin_bp.route('/synonyms/exportar')
@login_required
@admin_required
def synonyms_export():
    from app.services.backup_service import export_synonyms
    return json_download_response(export_synonyms(), 'sinonimos_backup.json')


@admin_bp.route('/synonyms/importar', methods=['GET', 'POST'])
@login_required
@admin_required
def synonyms_import():
    if request.method == 'GET':
        return render_template('admin/synonyms_import.html')

    f = request.files.get('file')
    if not f or not f.filename:
        flash('Selecciona un fichero JSON.', 'danger')
        return redirect(request.url)

    try:
        data = json.loads(f.read())
    except Exception as e:
        flash(f'Error al leer el fichero: {e}', 'danger')
        return redirect(request.url)

    from app.services.backup_service import import_synonyms
    mode = request.form.get('mode', 'skip')
    summary = import_synonyms(data, mode=mode)
    flash_import_summary(summary)
    return redirect(url_for('admin.synonyms'))


@admin_bp.route('/synonyms/new', methods=['POST'])
@login_required
@admin_required
def synonym_create():
    source = request.form.get('source', '').strip().lower()
    target = request.form.get('target', '').strip()
    is_prefix = bool(request.form.get('is_prefix'))
    notes  = request.form.get('notes', '').strip() or None

    if not source or not target:
        flash('El término original y el correcto son obligatorios.', 'danger')
        return redirect(url_for('admin.synonyms'))

    if Synonym.query.filter_by(source=source).first():
        flash(f'Ya existe un sinónimo para «{source}».', 'warning')
        return redirect(url_for('admin.synonyms'))

    db.session.add(Synonym(source=source, target=target, is_prefix=is_prefix, notes=notes))
    db.session.commit()
    flash(f'Sinónimo «{source}» → «{target}» añadido.', 'success')
    return redirect(url_for('admin.synonyms'))


@admin_bp.route('/synonyms/<int:syn_id>/edit', methods=['POST'])
@login_required
@admin_required
def synonym_edit(syn_id):
    syn = db.get_or_404(Synonym, syn_id)
    syn.source    = request.form.get('source', '').strip().lower()
    syn.target    = request.form.get('target', '').strip()
    syn.is_prefix = bool(request.form.get('is_prefix'))
    syn.notes     = request.form.get('notes', '').strip() or None
    db.session.commit()
    flash('Sinónimo actualizado.', 'success')
    return redirect(url_for('admin.synonyms'))


@admin_bp.route('/synonyms/<int:syn_id>/delete', methods=['POST'])
@login_required
@admin_required
def synonym_delete(syn_id):
    syn = db.get_or_404(Synonym, syn_id)
    source = syn.source
    db.session.delete(syn)
    db.session.commit()
    flash(f'Sinónimo «{source}» eliminado.', 'success')
    return redirect(url_for('admin.synonyms'))


# ---------------------------------------------------------------------------
# Contactos: administración
# ---------------------------------------------------------------------------

@admin_bp.route('/contactos')
@login_required
@admin_required
def contacts():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('q', '').strip()
    per_page = 25

    query = Contact.query.order_by(Contact.nombre)
    if search:
        query = query.filter(Contact.nombre.ilike(f'%{search}%'))

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    contacts_page = pagination.items

    return render_template('admin/contacts.html',
                           contacts=contacts_page,
                           pagination=pagination,
                           search=search)


@admin_bp.route('/contactos/<int:contact_id>/toggle', methods=['POST'])
@login_required
@admin_required
def contact_toggle(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    contact.is_visible = not contact.is_visible
    db.session.commit()
    return jsonify({'visible': contact.is_visible})


@admin_bp.route('/contactos/<int:contact_id>/eliminar', methods=['POST'])
@login_required
@admin_required
def contact_delete(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    db.session.delete(contact)
    db.session.commit()
    flash('Contacto eliminado.', 'success')
    return redirect(url_for('admin.contacts'))


@admin_bp.route('/contactos/eliminar-seleccionados', methods=['POST'])
@login_required
@admin_required
def contacts_delete_selected():
    ids = request.form.getlist('contact_ids')
    if ids:
        Contact.query.filter(Contact.id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()
        flash(f'{len(ids)} contacto(s) eliminado(s).', 'success')
    return redirect(url_for('admin.contacts'))


# ---------------------------------------------------------------------------
# Contactos: importación / exportación Excel (columnas fijas: nombre,
# es_untersuchung, profesiones separadas por coma)
# ---------------------------------------------------------------------------

@admin_bp.route('/contactos/importar', methods=['GET', 'POST'])
@login_required
@admin_required
def contacts_import():
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename:
            flash('Selecciona un archivo Excel.', 'danger')
            return render_template('admin/contacts_import.html')

        ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
        if ext not in ('xlsx', 'xls'):
            flash('Solo se permiten archivos Excel (.xlsx, .xls).', 'danger')
            return render_template('admin/contacts_import.html')

        update_existing = request.form.get('update_existing') == 'on'

        try:
            created, updated = import_contacts_from_excel(
                file.stream, update_existing=update_existing, created_by_id=current_user.id,
            )
        except Exception as e:
            flash(f'Error al leer el archivo: {str(e)}', 'danger')
            return render_template('admin/contacts_import.html')

        db.session.commit()
        flash(f'Importación completada: {created} creados, {updated} actualizados.', 'success')
        return redirect(url_for('admin.contacts'))

    return render_template('admin/contacts_import.html')


@admin_bp.route('/contactos/exportar', methods=['GET', 'POST'])
@login_required
@admin_required
def contacts_export():
    contacts_list = Contact.query.order_by(Contact.nombre).all()

    if request.method == 'POST':
        ids_raw = request.form.get('contact_ids', '').strip()
        if ids_raw:
            ids = [int(x) for x in ids_raw.split(',') if x.strip().isdigit()]
            selected = Contact.query.filter(Contact.id.in_(ids)).all()
        else:
            selected = contacts_list

        buffer = export_contacts_to_excel(selected)
        return send_file(
            buffer,
            as_attachment=True,
            download_name='contactos_export.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )

    return render_template('admin/contacts_export.html', contacts=contacts_list)


@admin_bp.route('/vinculos/exportar')
@login_required
@admin_required
def contacts_full_export():
    from app.services.backup_service import export_contacts_full
    return json_download_response(export_contacts_full(), 'contactos_vinculos_backup.json')


@admin_bp.route('/vinculos/importar', methods=['GET', 'POST'])
@login_required
@admin_required
def contacts_full_import():
    if request.method == 'GET':
        return render_template('admin/contacts_full_import.html')

    f = request.files.get('file')
    if not f or not f.filename:
        flash('Selecciona un fichero JSON.', 'danger')
        return redirect(request.url)

    try:
        data = json.loads(f.read())
    except Exception as e:
        flash(f'Error al leer el fichero: {e}', 'danger')
        return redirect(request.url)

    from app.services.backup_service import import_contacts_full
    mode = request.form.get('mode', 'skip')
    summary = import_contacts_full(data, mode=mode)
    flash_import_summary(summary)
    return redirect(url_for('contacts.vinculos'))


# ---------------------------------------------------------------------------
# Backup completo: exporta/importa todas las secciones anteriores de golpe,
# en el orden correcto de dependencias.
# ---------------------------------------------------------------------------

def _backup_folder():
    folder = current_app.config['BACKUP_FOLDER']
    os.makedirs(folder, exist_ok=True)
    return folder


def _read_backup_json(path):
    """Reads a backup file, transparently gunzipping it first if it was
    compressed via "Comprimir" (filename ending .json.gz)."""
    opener = gzip.open if path.endswith('.gz') else open
    with opener(path, 'rt', encoding='utf-8') as f:
        return json.load(f)


def _write_backup_json(path, data):
    """Writes JSON back to a backup file, preserving gzip compression if it
    was already compressed - used when editing a backup's `notas` in place,
    since that shouldn't force a decompressed/compressed round-trip visible
    to the admin."""
    opener = gzip.open if path.endswith('.gz') else open
    with opener(path, 'wt', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _list_saved_backups():
    """Newest first - reads each file's own `secciones`/`exported_at` rather
    than trusting the filename, so the list stays correct even if a file was
    renamed or dropped in by hand. Includes a per-section record count
    (`rows`) so the admin/backup.html detail panel can render everything
    about a backup without a server round-trip on selection."""
    from app.services.backup_service import _parse_iso, BACKUP_SECTIONS
    labels = {key: label for key, label, _ in BACKUP_SECTIONS}

    folder = _backup_folder()
    items = []
    for filename in sorted(os.listdir(folder), reverse=True):
        if not (filename.endswith('.json') or filename.endswith('.json.gz')):
            continue
        path = os.path.join(folder, filename)
        try:
            data = _read_backup_json(path)
        except Exception:
            data = {}
        exported_at = data.get('exported_at')
        try:
            exported_at = _parse_iso(exported_at).strftime('%Y-%m-%d %H:%M:%S') if exported_at else None
        except ValueError:
            pass  # keep the raw string if it's ever in an unexpected shape

        rows = []
        for key in data.get('secciones', []):
            value = data.get(key)
            count = len(value) if isinstance(value, list) else ('Sí' if value else 'No')
            rows.append({'key': key, 'label': labels.get(key, key), 'count': count})

        items.append({
            'filename': filename,
            'size': os.path.getsize(path),
            'exported_at': exported_at,
            'secciones': data.get('secciones', []),
            'rows': rows,
            'compressed': filename.endswith('.gz'),
            'notas': data.get('notas'),
        })
    return items


def _compress_one(filename):
    """Gzips a single saved backup in place. Returns None on success, or a
    warning string if it was already compressed (never raises for that -
    both the single-file and bulk routes just want to skip and report it)."""
    if filename.endswith('.gz'):
        return f'«{filename}» ya está comprimido.'
    path = _safe_backup_path(filename)
    gz_path = path + '.gz'
    with open(path, 'rb') as src, gzip.open(gz_path, 'wb') as dst:
        dst.write(src.read())
    os.remove(path)
    return None


def _decompress_one(filename):
    """Reverse of _compress_one - same "return a warning instead of raising"
    contract so a bulk pass can skip already-uncompressed files."""
    if not filename.endswith('.gz'):
        return f'«{filename}» no está comprimido.'
    path = _safe_backup_path(filename)
    raw_path = path[:-3]
    with gzip.open(path, 'rb') as src, open(raw_path, 'wb') as dst:
        dst.write(src.read())
    os.remove(path)
    return None


def _safe_backup_path(filename):
    """Resolves filename within BACKUP_FOLDER, 404ing on any path-traversal
    attempt or missing file - same check as main.uploaded_file."""
    folder = _backup_folder()
    path = os.path.join(folder, filename)
    if not os.path.abspath(path).startswith(os.path.abspath(folder)) or not os.path.isfile(path):
        abort(404)
    return path


@admin_bp.route('/backup')
@login_required
@admin_required
def backup_home():
    from app.services.backup_service import BACKUP_SECTIONS
    section_labels = {key: label for key, label, _ in BACKUP_SECTIONS}
    return render_template('admin/backup.html', sections=BACKUP_SECTIONS, section_labels=section_labels,
                            backups=_list_saved_backups())


@admin_bp.route('/backup/exportar', methods=['POST'])
@login_required
@admin_required
def backup_export():
    from app.services.backup_service import export_full_backup, BACKUP_SECTIONS
    all_keys = {key for key, _, _ in BACKUP_SECTIONS}
    selected = set(request.form.getlist('secciones')) & all_keys
    # An empty selection (nothing checked) still means "backup total", not
    # "backup vacío" - a blank submission should never silently create an
    # empty file.
    data = export_full_backup(sections=selected or all_keys)

    folder = _backup_folder()
    base_name = f"wft_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    filename = f'{base_name}.json'
    # Guards against two exports landing in the same second (same base_name)
    # silently overwriting each other - genuinely possible from the bulk
    # "Marcar todas" one-click flow, not just a theoretical race.
    suffix = 2
    while os.path.exists(os.path.join(folder, filename)):
        filename = f'{base_name}_{suffix}.json'
        suffix += 1

    path = os.path.join(folder, filename)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return send_file(path, as_attachment=True, download_name=filename, mimetype='application/json')


@admin_bp.route('/backup/archivos/<path:filename>/descargar')
@login_required
@admin_required
def backup_download(filename):
    """Always serves plain JSON, even if the file is stored gzipped on disk
    - so a downloaded backup can always be fed straight back into Importar,
    regardless of whether "Comprimir" was used on it."""
    path = _safe_backup_path(filename)
    data = _read_backup_json(path)
    download_name = filename[:-3] if filename.endswith('.gz') else filename
    buffer = io.BytesIO(json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'))
    return send_file(buffer, as_attachment=True, download_name=download_name, mimetype='application/json')


@admin_bp.route('/backup/archivos/<path:filename>/comprimir', methods=['POST'])
@login_required
@admin_required
def backup_compress(filename):
    if filename.endswith('.gz'):
        flash(f'«{filename}» ya está comprimido.', 'warning')
        return redirect(url_for('admin.backup_home'))

    path = _safe_backup_path(filename)
    original_size = os.path.getsize(path)
    _compress_one(filename)
    new_size = os.path.getsize(path + '.gz')
    saved_pct = round(100 * (1 - new_size / original_size)) if original_size else 0
    flash(f'«{filename}» comprimido ({saved_pct}% menos de espacio).', 'success')
    return redirect(url_for('admin.backup_home'))


@admin_bp.route('/backup/archivos/comprimir-varios', methods=['POST'])
@login_required
@admin_required
def backup_compress_bulk():
    filenames = request.form.getlist('filenames')
    if not filenames:
        flash('No se seleccionó ningún fichero.', 'warning')
        return redirect(url_for('admin.backup_home'))

    compressed, skipped = [], []
    for filename in filenames:
        warning = _compress_one(filename)
        (skipped if warning else compressed).append(filename)

    if compressed:
        flash(f'{len(compressed)} fichero(s) comprimido(s): {", ".join(compressed)}.', 'success')
    if skipped:
        flash(f'{len(skipped)} ya estaban comprimidos, sin cambios.', 'warning')
    return redirect(url_for('admin.backup_home'))


@admin_bp.route('/backup/archivos/<path:filename>/descomprimir', methods=['POST'])
@login_required
@admin_required
def backup_decompress(filename):
    warning = _decompress_one(filename)
    if warning:
        flash(warning, 'warning')
    else:
        flash(f'«{filename}» descomprimido.', 'success')
    return redirect(url_for('admin.backup_home'))


@admin_bp.route('/backup/archivos/descomprimir-varios', methods=['POST'])
@login_required
@admin_required
def backup_decompress_bulk():
    filenames = request.form.getlist('filenames')
    if not filenames:
        flash('No se seleccionó ningún fichero.', 'warning')
        return redirect(url_for('admin.backup_home'))

    decompressed, skipped = [], []
    for filename in filenames:
        warning = _decompress_one(filename)
        (skipped if warning else decompressed).append(filename)

    if decompressed:
        flash(f'{len(decompressed)} fichero(s) descomprimido(s): {", ".join(decompressed)}.', 'success')
    if skipped:
        flash(f'{len(skipped)} ya estaban sin comprimir, sin cambios.', 'warning')
    return redirect(url_for('admin.backup_home'))


@admin_bp.route('/backup/archivos/<path:filename>/eliminar', methods=['POST'])
@login_required
@admin_required
def backup_delete(filename):
    path = _safe_backup_path(filename)
    os.remove(path)
    flash(f'«{filename}» eliminado.', 'warning')
    return redirect(url_for('admin.backup_home'))


@admin_bp.route('/backup/archivos/<path:filename>/nota', methods=['POST'])
@login_required
@admin_required
def backup_note(filename):
    """Notas are stored inside the backup JSON itself (not a separate
    sidecar index) so they travel with the file wherever it goes - moved,
    downloaded, compressed/decompressed - with no separate index to keep in
    sync. Preserves whatever compression state the file was already in."""
    path = _safe_backup_path(filename)
    data = _read_backup_json(path)
    data['notas'] = request.form.get('nota', '').strip() or None
    _write_backup_json(path, data)
    flash(f'Nota guardada para «{filename}».', 'success')
    return redirect(url_for('admin.backup_home'))


def _flash_backup_import_summaries(summaries):
    from app.services.backup_service import BACKUP_SECTIONS
    for key, label, _ in BACKUP_SECTIONS:
        s = summaries[key]
        flash(f"{label}: {s['created']} creados, {s['updated']} actualizados, {s['skipped']} omitidos.", 'success')
        warnings = s.get('warnings') or []
        if warnings:
            shown = warnings[:10]
            more = '' if len(warnings) <= 10 else f' (+{len(warnings) - 10} más)'
            flash(Markup('<strong>{} — avisos:</strong> {}{}').format(label, '; '.join(shown), more), 'warning')
        passwords = s.get('generated_passwords') or {}
        if passwords:
            detail = '; '.join(f'{u}: {p}' for u, p in passwords.items())
            flash(Markup('<strong>Contraseñas temporales asignadas:</strong> {}').format(detail), 'warning')


@admin_bp.route('/backup/importar', methods=['POST'])
@login_required
@admin_required
def backup_import():
    f = request.files.get('file')
    if not f or not f.filename:
        flash('Selecciona un fichero JSON.', 'danger')
        return redirect(url_for('admin.backup_home'))

    try:
        data = json.loads(f.read())
    except Exception as e:
        flash(f'Error al leer el fichero: {e}', 'danger')
        return redirect(url_for('admin.backup_home'))

    from app.services.backup_service import import_full_backup
    mode = request.form.get('mode', 'skip')
    summaries = import_full_backup(data, mode=mode)
    _flash_backup_import_summaries(summaries)
    return redirect(url_for('admin.backup_home'))


@admin_bp.route('/backup/archivos/<path:filename>/restaurar', methods=['POST'])
@login_required
@admin_required
def backup_restore(filename):
    """Same as backup_import, but reads a backup already saved on the server
    (BACKUP_FOLDER) instead of requiring a re-upload from the admin's device
    - restoring "in place" from the list below, transparently gunzipping if
    the file was compressed."""
    path = _safe_backup_path(filename)
    try:
        data = _read_backup_json(path)
    except Exception as e:
        flash(f'Error al leer «{filename}»: {e}', 'danger')
        return redirect(url_for('admin.backup_home'))

    from app.services.backup_service import import_full_backup
    mode = request.form.get('mode', 'skip')
    summaries = import_full_backup(data, mode=mode)
    _flash_backup_import_summaries(summaries)
    return redirect(url_for('admin.backup_home'))


# ---------------------------------------------------------------------------
# Recargo global de precios (comida/bebida por ahora): un director de juego
# puede subir el precio un % "por disponibilidad u otras razones".
# ---------------------------------------------------------------------------

@admin_bp.route('/recargo-precios', methods=['GET', 'POST'])
@login_required
@admin_required
def shop_markup_edit():
    if request.method == 'POST':
        pct = request.form.get('pct', '0').strip()
        pct = int(pct) if pct.lstrip('-').isdigit() else 0
        set_markup_pct(pct, updated_by_id=current_user.id)
        db.session.commit()
        flash(f'Recargo global actualizado al {pct}%.', 'success')
        return redirect(url_for('admin.shop_markup_edit'))

    return render_template('admin/shop_markup.html', pct=current_markup_pct())


# ---------------------------------------------------------------------------
# Comida y bebida: gestión del catálogo de recetas (export/import, PDF, fotos)
# ---------------------------------------------------------------------------

@admin_bp.route('/comida')
@login_required
@admin_required
def food_home():
    return render_template('admin/comida_home.html')


@admin_bp.route('/comida/exportar')
@login_required
@admin_required
def comida_export():
    from app.services.backup_service import export_recipes
    return json_download_response(export_recipes(), 'recetas_backup.json')


@admin_bp.route('/comida/importar', methods=['GET', 'POST'])
@login_required
@admin_required
def comida_import():
    if request.method == 'GET':
        return render_template('admin/comida_import.html')

    f = request.files.get('file')
    if not f or not f.filename:
        flash('Selecciona un fichero JSON.', 'danger')
        return redirect(request.url)

    try:
        data = json.loads(f.read())
    except Exception as e:
        flash(f'Error al leer el fichero: {e}', 'danger')
        return redirect(request.url)

    from app.services.backup_service import import_recipes
    mode = request.form.get('mode', 'skip')
    summary = import_recipes(data, mode=mode)
    flash_import_summary(summary)
    return redirect(url_for('admin.food_home'))


@admin_bp.route('/comida/importar-pdf', methods=['GET', 'POST'])
@login_required
@admin_required
def comida_import_pdf():
    if request.method == 'GET':
        return render_template('admin/comida_importar_pdf.html', parsed=None)

    f = request.files.get('file')
    if not f or not f.filename or not f.filename.lower().endswith('.pdf'):
        flash('Selecciona un fichero PDF.', 'danger')
        return redirect(request.url)

    import base64
    from app.services.food_pdf_service import parse_recetas_pdf
    try:
        parsed = parse_recetas_pdf(f.read())
    except Exception as e:
        flash(f'No se pudo leer el PDF: {e}', 'danger')
        return redirect(request.url)

    # image_bytes (raw) isn't JSON-serializable for the hidden field on the
    # review form - swap it for a base64 string used both as the thumbnail
    # <img> src and as the payload the confirm step decodes back to bytes.
    for row in parsed:
        image_bytes = row.pop('image_bytes')
        row['image_b64'] = base64.b64encode(image_bytes).decode('ascii') if image_bytes else None

    return render_template('admin/comida_importar_pdf.html', parsed=parsed)


@admin_bp.route('/comida/importar-pdf/confirmar', methods=['POST'])
@login_required
@admin_required
def comida_import_pdf_confirmar():
    import base64
    from app.services.food_pdf_service import save_recipe_image_bytes

    created, skipped = [], []
    for key, raw in request.form.items():
        if not key.startswith('receta_') or not request.form.get(f'importar_{key[7:]}'):
            continue
        row = json.loads(raw)

        # Re-check at commit time - the review screen may be stale (another
        # admin session, or a re-submitted form) - never create a duplicate.
        if Recipe.query.filter_by(nombre=row['nombre']).first():
            skipped.append(row['nombre'])
            continue

        recipe = Recipe(
            nombre=row['nombre'], vigor=row['vigor'], moral=row['moral'],
            cooking_method_id=row.get('cooking_method_id'), calidad=row.get('calidad'),
            complejidad=row.get('complejidad'), duracion_dias=row.get('duracion_dias'),
            recalentar=row.get('recalentar', False),
            precio_compra_peniques=row.get('precio_compra_peniques'),
            coste_creacion_peniques=row.get('coste_creacion_peniques'),
            solo_compra=row.get('solo_compra', False), notas=row.get('notas'),
            status='aprobada',
            ingrediente_1_id=row.get('ingrediente_1_id'), ingrediente_2_id=row.get('ingrediente_2_id'),
            ingrediente_3_id=row.get('ingrediente_3_id'), ingrediente_4_id=row.get('ingrediente_4_id'),
            condimento_1_id=row.get('condimento_1_id'), condimento_2_id=row.get('condimento_2_id'),
        )
        db.session.add(recipe)

        image_b64 = row.get('image_b64')
        if image_b64:
            recipe.image_path = save_recipe_image_bytes(
                row['nombre'], base64.b64decode(image_b64), row.get('image_ext'),
            )
        created.append(row['nombre'])

    db.session.commit()
    if created:
        flash(f"{len(created)} receta(s) importada(s): {', '.join(created)}.", 'success')
    if skipped:
        flash(f"{len(skipped)} ya existían y se omitieron: {', '.join(skipped)}.", 'warning')
    if not created and not skipped:
        flash('No se seleccionó ninguna receta para importar.', 'warning')
    return redirect(url_for('admin.food_home'))


@admin_bp.route('/comida/sincronizar-fotos', methods=['POST'])
@login_required
@admin_required
def comida_sync_fotos():
    from app.services.food_pdf_service import sync_recipe_images_from_folder
    summary = sync_recipe_images_from_folder()
    flash(
        f"{len(summary['linked'])} foto(s) vinculada(s), "
        f"{len(summary['already_had_photo'])} receta(s) ya tenían foto (sin tocar), "
        f"{len(summary['unmatched_files'])} fichero(s) sin receta correspondiente.",
        'success',
    )
    if summary['linked']:
        flash(f"Vinculadas: {', '.join(summary['linked'])}.", 'success')
    if summary['unmatched_files']:
        flash(f"Sin receta correspondiente: {', '.join(summary['unmatched_files'])}.", 'warning')
    return redirect(url_for('admin.food_home'))


# ---------------------------------------------------------------------------
# Comida y bebida: gestión del catálogo de ingredientes
# ---------------------------------------------------------------------------

def _ingredient_from_form(ingredient):
    ingredient.nombre = request.form.get('nombre', '').strip()
    ingredient.vigor = request.form.get('vigor', 0, type=int) or 0
    ingredient.moral = request.form.get('moral', 0, type=int) or 0
    ingredient.coste_docena = request.form.get('coste_docena', 0, type=int) or 0
    ingredient.descripcion = request.form.get('descripcion', '').strip() or None


def _sync_ingredient_compat(ingredient, methods):
    existing = {r.cooking_method_id: r for r in
                IngredientCookingMethod.query.filter_by(ingredient_id=ingredient.id).all()}
    for method in methods:
        estado = request.form.get(f'estado_{method.id}', 'no')
        if estado not in ('si', 'no', 'condimento'):
            estado = 'no'
        row = existing.get(method.id)
        if row:
            row.estado = estado
        else:
            db.session.add(IngredientCookingMethod(
                ingredient_id=ingredient.id, cooking_method_id=method.id, estado=estado,
            ))


@admin_bp.route('/comida/ingredientes')
@login_required
@admin_required
def food_ingredients():
    items = Ingredient.query.order_by(Ingredient.nombre).all()
    methods = CookingMethod.query.order_by(CookingMethod.id).all()
    compat = {}
    for row in IngredientCookingMethod.query.all():
        compat.setdefault(row.ingredient_id, {})[row.cooking_method_id] = row.estado
    return render_template('admin/food_ingredients.html', ingredients=items, methods=methods, compat=compat)


@admin_bp.route('/comida/ingredientes/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def food_ingredient_create():
    methods = CookingMethod.query.order_by(CookingMethod.id).all()
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        if not nombre:
            flash('El nombre es obligatorio.', 'danger')
            return redirect(url_for('admin.food_ingredient_create'))
        if Ingredient.query.filter_by(nombre=nombre).first():
            flash(f'Ya existe un ingrediente llamado «{nombre}».', 'danger')
            return redirect(url_for('admin.food_ingredient_create'))

        ingredient = Ingredient()
        _ingredient_from_form(ingredient)
        db.session.add(ingredient)
        db.session.flush()
        _sync_ingredient_compat(ingredient, methods)
        db.session.commit()
        flash(f'Ingrediente «{ingredient.nombre}» creado.', 'success')
        return redirect(url_for('admin.food_ingredients'))

    return render_template('admin/food_ingredient_form.html', ingredient=None, methods=methods, compat={})


@admin_bp.route('/comida/ingredientes/<int:ingredient_id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def food_ingredient_edit(ingredient_id):
    ingredient = db.get_or_404(Ingredient, ingredient_id)
    methods = CookingMethod.query.order_by(CookingMethod.id).all()

    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        if not nombre:
            flash('El nombre es obligatorio.', 'danger')
            return redirect(url_for('admin.food_ingredient_edit', ingredient_id=ingredient.id))
        duplicate = Ingredient.query.filter(
            Ingredient.nombre == nombre, Ingredient.id != ingredient.id
        ).first()
        if duplicate:
            flash(f'Ya existe un ingrediente llamado «{nombre}».', 'danger')
            return redirect(url_for('admin.food_ingredient_edit', ingredient_id=ingredient.id))

        _ingredient_from_form(ingredient)
        _sync_ingredient_compat(ingredient, methods)
        db.session.commit()
        flash(f'Ingrediente «{ingredient.nombre}» actualizado.', 'success')
        return redirect(url_for('admin.food_ingredients'))

    compat = {r.cooking_method_id: r.estado for r in
              IngredientCookingMethod.query.filter_by(ingredient_id=ingredient.id).all()}
    return render_template('admin/food_ingredient_form.html', ingredient=ingredient, methods=methods, compat=compat)


@admin_bp.route('/comida/ingredientes/<int:ingredient_id>/eliminar', methods=['POST'])
@login_required
@admin_required
def food_ingredient_delete(ingredient_id):
    ingredient = db.get_or_404(Ingredient, ingredient_id)
    en_uso = Recipe.query.filter(db.or_(
        Recipe.ingrediente_1_id == ingredient.id, Recipe.ingrediente_2_id == ingredient.id,
        Recipe.ingrediente_3_id == ingredient.id, Recipe.ingrediente_4_id == ingredient.id,
        Recipe.condimento_1_id == ingredient.id, Recipe.condimento_2_id == ingredient.id,
    )).first()
    if en_uso:
        flash(f'No se puede eliminar «{ingredient.nombre}»: lo usa la receta «{en_uso.nombre}».', 'danger')
        return redirect(url_for('admin.food_ingredients'))

    nombre = ingredient.nombre
    db.session.delete(ingredient)
    db.session.commit()
    flash(f'Ingrediente «{nombre}» eliminado.', 'success')
    return redirect(url_for('admin.food_ingredients'))


# ---------------------------------------------------------------------------
# Comida y bebida: revisión de recetas propuestas por usuarios
# ---------------------------------------------------------------------------

_RECIPE_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}


@admin_bp.route('/recetas')
@login_required
@admin_required
def recipes_pending():
    items = Recipe.query.filter_by(status='pendiente').order_by(Recipe.requested_at).all()
    return render_template('admin/recipes_pending.html', recipes=items)


@admin_bp.route('/recetas/<int:recipe_id>')
@login_required
@admin_required
def recipe_review(recipe_id):
    recipe = Recipe.query.get_or_404(recipe_id)
    return render_template('admin/recipe_review.html', recipe=recipe)


@admin_bp.route('/recetas/<int:recipe_id>/aprobar', methods=['POST'])
@login_required
@admin_required
def recipe_approve(recipe_id):
    recipe = Recipe.query.get_or_404(recipe_id)
    file = request.files.get('imagen')
    if file and file.filename:
        ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
        if ext not in _RECIPE_IMAGE_EXTENSIONS:
            flash('La imagen debe ser PNG, JPG, WEBP o GIF.', 'danger')
            return redirect(url_for('admin.recipe_review', recipe_id=recipe.id))
        filename = f'{recipe.id}_{int(time.time())}.{ext}'
        save_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'recetas', filename)
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        file.save(save_path)
        recipe.image_path = os.path.join('recetas', filename)

    if not recipe.image_path:
        flash('La receta necesita una imagen antes de poder aprobarla.', 'danger')
        return redirect(url_for('admin.recipe_review', recipe_id=recipe.id))

    recipe.status = 'aprobada'
    recipe.approved_by_id = current_user.id
    recipe.approved_at = datetime.utcnow()
    recipe.rejection_reason = None
    db.session.commit()
    flash(f'Receta "{recipe.nombre}" aprobada.', 'success')
    return redirect(url_for('admin.recipes_pending'))


@admin_bp.route('/recetas/<int:recipe_id>/rechazar', methods=['POST'])
@login_required
@admin_required
def recipe_reject(recipe_id):
    recipe = Recipe.query.get_or_404(recipe_id)
    recipe.status = 'rechazada'
    recipe.rejection_reason = request.form.get('motivo', '').strip() or None
    recipe.approved_by_id = current_user.id
    recipe.approved_at = datetime.utcnow()
    db.session.commit()
    flash(f'Receta "{recipe.nombre}" rechazada.', 'warning')
    return redirect(url_for('admin.recipes_pending'))


@admin_bp.route('/recetas/<int:recipe_id>/eliminar', methods=['POST'])
@login_required
@admin_required
def recipe_delete(recipe_id):
    recipe = Recipe.query.get_or_404(recipe_id)
    nombre = recipe.nombre
    if recipe.image_path:
        img_path = os.path.join(current_app.config['UPLOAD_FOLDER'], recipe.image_path)
        if os.path.isfile(img_path):
            os.remove(img_path)
    db.session.delete(recipe)
    db.session.commit()
    flash(f'Receta "{nombre}" eliminada.', 'success')
    return redirect(url_for('food.recipes'))

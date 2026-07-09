import difflib
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
                   flash, request, current_app, jsonify, send_file)
from flask_login import login_required, current_user
from app.extensions import db
from app.models.user import User
from app.models.profession import Profession, ProfessionSkill, ProfessionTalent, ProfessionTrapping
from app.models.skill import Skill
from app.models.talent import Talent
from app.models.synonym import Synonym, DEFAULT_SYNONYMS
from app.models.permission import Permission, PermissionTemplate, ALL_PERMISSIONS
from app.models.contact import Contact, ContactProfession
from app.models.contact_character_link import ContactCharacterLink, ContactCharacterVisibility
from app.models.contact_note import ContactNote
from app.models.character import Character
from app.models.food import Recipe
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
        if s.name_en:
            skill_names.add(s.name_en.lower())

    talent_names = set()
    for t in all_talents:
        talent_names.add(t.name_es.lower())
        if t.name_en:
            talent_names.add(t.name_en.lower())

    # Load ES synonyms once — used for both name correction and chip validation
    es_exact, es_prefix = _get_synonyms_dicts()

    # Name → object maps for canonicalizing skills_raw/talents_raw below —
    # same shape _match_and_save_skills/_match_and_save_talents build at save time.
    skill_map  = {s.name_es.lower(): s for s in all_skills}
    skill_map.update({s.name_en.lower(): s for s in all_skills if s.name_en})
    talent_map = {t.name_es.lower(): t for t in all_talents}
    talent_map.update({t.name_en.lower(): t for t in all_talents if t.name_en})

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
            for raw in skills_to_check.replace(' or ', ',').replace(' o ', ',').split(','):
                item = raw.strip()
                if not item or len(item) > 80 or '.' in item:
                    continue
                if not _fuzzy_match(item, skill_names, exact_syn, prefix_syn, cutoff=0.65):
                    unmatched_skills.append(item)

        unmatched_talents = []
        if talent_names:
            for raw in talents_to_check.replace(' or ', ',').replace(' o ', ',').split(','):
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


_RE_ALTERNATIVE = re.compile(r'(\s+(?:o|or)\s+)', re.IGNORECASE)


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
    return f'{match.name_es} ({spec})' if spec else match.name_es


def _canonicalize_catalog_list(raw: str, name_map: dict, exact_syn: dict, prefix_syn: dict) -> str:
    """
    Rewrite each comma-separated skill/talent chip to its exact catalog name
    wherever it fuzzy-matches an existing entry, so the PDF review UI always
    shows (and the admin edits) the same name that will actually be linked at
    save time — never a near-miss sitting next to the real catalog entry.
    'A o B' / 'A or B' alternatives are canonicalized on each side.
    """
    if not raw:
        return raw
    parts = []
    for item in raw.split(','):
        item = item.strip()
        if not item:
            continue
        alt = _RE_ALTERNATIVE.split(item, maxsplit=1)
        if len(alt) == 3:
            left, sep, right = alt
            parts.append(
                _canonicalize_one_item(left.strip(), name_map, exact_syn, prefix_syn) + sep +
                _canonicalize_one_item(right.strip(), name_map, exact_syn, prefix_syn)
            )
        else:
            parts.append(_canonicalize_one_item(item, name_map, exact_syn, prefix_syn))
    return ', '.join(parts)


def _match_and_save_skills(prof, skills_raw: str, skills_raw_en: str = ''):
    # skills_raw_en is intentionally unused here: it holds the ORIGINAL PDF-extracted
    # English text and is never updated by the review page's chip editor, which only
    # syncs skills_raw (Spanish). Matching against it instead of the user-confirmed
    # chips silently discarded whatever the admin edited/accepted in the review UI.
    all_skills = Skill.query.all()
    skill_map  = {s.name_es.lower(): s for s in all_skills}
    skill_map.update({s.name_en.lower(): s for s in all_skills if s.name_en})

    exact_syn, prefix_syn = _get_synonyms_dicts()

    seen: set = set()
    for raw_part in skills_raw.replace(' or ', ',').replace(' o ', ',').split(','):
        raw_part = raw_part.strip()
        if not raw_part or len(raw_part) > 80 or '.' in raw_part:
            continue
        skill = _fuzzy_find(raw_part, skill_map, exact_syn, prefix_syn, cutoff=0.7)
        if skill:
            spec = _extract_specialization(raw_part)
            key  = (skill.id, spec)
            if key not in seen:
                seen.add(key)
                db.session.add(ProfessionSkill(
                    profession_id=prof.id, skill_id=skill.id, specialization=spec
                ))


def _match_and_save_talents(prof, talents_raw: str, talents_raw_en: str = ''):
    # talents_raw_en is intentionally unused - see the matching comment in
    # _match_and_save_skills above.
    all_talents = Talent.query.all()
    talent_map  = {t.name_es.lower(): t for t in all_talents}
    talent_map.update({t.name_en.lower(): t for t in all_talents if t.name_en})

    exact_syn, prefix_syn = _get_synonyms_dicts()

    seen: set = set()
    for raw_part in talents_raw.replace(' or ', ',').replace(' o ', ',').split(','):
        raw_part = raw_part.strip()
        if not raw_part or len(raw_part) > 80 or '.' in raw_part:
            continue
        talent = _fuzzy_find(raw_part, talent_map, exact_syn, prefix_syn, cutoff=0.7)
        if talent:
            spec = _extract_specialization(raw_part)
            key  = (talent.id, spec)
            if key not in seen:
                seen.add(key)
                db.session.add(ProfessionTalent(
                    profession_id=prof.id, talent_id=talent.id, specialization=spec
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

    all_characters = Character.query.order_by(Character.name).all()
    visibility_map = {}
    contact_ids = [c.id for c in contacts_page]
    if contact_ids:
        grants = ContactCharacterVisibility.query.filter(
            ContactCharacterVisibility.contact_id.in_(contact_ids),
        ).all()
        visibility_map = {(g.contact_id, g.character_id): g.nivel for g in grants}

    return render_template('admin/contacts.html',
                           contacts=contacts_page,
                           pagination=pagination,
                           search=search,
                           all_characters=all_characters,
                           visibility_map=visibility_map)


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


# ---------------------------------------------------------------------------
# Vínculos: directorio de todas las relaciones contacto↔personaje, con el
# usuario propietario de cada personaje - de solo lectura, enlaza a la ficha
# del contacto ya filtrada como ese personaje (donde viven notas/vínculo
# completos) y a la edición del propio personaje.
# ---------------------------------------------------------------------------

@admin_bp.route('/vinculos')
@login_required
@admin_required
def contact_links():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('q', '').strip()
    per_page = 30

    query = (
        ContactCharacterLink.query
        .join(Contact, Contact.id == ContactCharacterLink.contact_id)
        .join(Character, Character.id == ContactCharacterLink.character_id)
        .join(User, User.id == Character.user_id)
        .order_by(Contact.nombre, Character.name)
    )
    if search:
        like = f'%{search}%'
        query = query.filter(db.or_(
            Contact.nombre.ilike(like),
            Character.name.ilike(like),
            User.username.ilike(like),
        ))

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    links = pagination.items

    contact_ids = [l.contact_id for l in links]
    visibility_map = {}
    note_counts = {}
    notes_map = {}
    contact_access_map = {}
    if contact_ids:
        grants = ContactCharacterVisibility.query.filter(
            ContactCharacterVisibility.contact_id.in_(contact_ids),
        ).all()
        visibility_map = {(g.contact_id, g.character_id): g.nivel for g in grants}

        notes = (
            ContactNote.query.filter(ContactNote.contact_id.in_(contact_ids))
            .order_by(ContactNote.created_at.desc())
            .all()
        )
        notes_map = {}
        for n in notes:
            notes_map.setdefault((n.contact_id, n.character_id), []).append(n)
        note_counts = {key: len(rows) for key, rows in notes_map.items()}

        # Every character with visibility into each contact, regardless of whether
        # that character is also the one who registered it (has a ContactCharacterLink) -
        # shown directly in this table so an admin doesn't have to open each contact.
        access_rows = (
            db.session.query(
                ContactCharacterVisibility.contact_id,
                Character.name,
                User.username,
                ContactCharacterVisibility.nivel,
            )
            .join(Character, Character.id == ContactCharacterVisibility.character_id)
            .join(User, User.id == Character.user_id)
            .filter(ContactCharacterVisibility.contact_id.in_(contact_ids))
            .order_by(Character.name)
            .all()
        )
        for cid, char_name, username, nivel in access_rows:
            contact_access_map.setdefault(cid, []).append({
                'character_name': char_name, 'username': username, 'nivel': nivel,
            })

    return render_template(
        'admin/contact_links.html',
        links=links,
        pagination=pagination,
        search=search,
        visibility_map=visibility_map,
        note_counts=note_counts,
        notes_map=notes_map,
        contact_access_map=contact_access_map,
    )


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
    return redirect(url_for('admin.contact_links'))


# ---------------------------------------------------------------------------
# Backup completo: exporta/importa todas las secciones anteriores de golpe,
# en el orden correcto de dependencias.
# ---------------------------------------------------------------------------

@admin_bp.route('/backup')
@login_required
@admin_required
def backup_home():
    return render_template('admin/backup.html')


@admin_bp.route('/backup/exportar')
@login_required
@admin_required
def backup_export():
    from app.services.backup_service import export_full_backup
    return json_download_response(export_full_backup(), 'wft_backup_completo.json')


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

    labels = {
        'permission_templates': 'Plantillas de permisos', 'synonyms': 'Sinónimos', 'users': 'Usuarios',
        'professions': 'Profesiones', 'characters': 'Personajes', 'contacts': 'Contactos y vínculos',
    }
    for key, label in labels.items():
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

    return redirect(url_for('admin.backup_home'))


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

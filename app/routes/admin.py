import os
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, current_app, jsonify)
from flask_login import login_required
from app.extensions import db
from app.models.user import User
from app.models.profession import Profession, ProfessionSkill, ProfessionTalent, ProfessionTrapping
from app.models.skill import Skill
from app.models.talent import Talent
from app.utils import admin_required, allowed_file
from app.services.pdf_processor import process_pdf

admin_bp = Blueprint('admin', __name__, template_folder='../templates')


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
    }
    return render_template('admin/dashboard.html', stats=stats)


# ---- User management ----

@admin_bp.route('/usuarios')
@login_required
@admin_required
def users():
    users_list = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users_list)


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


# ---- PDF upload & review ----

@admin_bp.route('/pdf', methods=['GET', 'POST'])
@login_required
@admin_required
def pdf_upload():
    if request.method == 'POST':
        if 'pdf_file' not in request.files:
            flash('No se seleccionó ningún archivo.', 'danger')
            return redirect(request.url)

        file = request.files['pdf_file']
        if not file or not file.filename:
            flash('Archivo vacío.', 'danger')
            return redirect(request.url)

        if not allowed_file(file.filename):
            flash('Solo se aceptan archivos PDF.', 'danger')
            return redirect(request.url)

        file_bytes = file.read()
        result = process_pdf(file_bytes)

        if result['errors']:
            for err in result['errors']:
                flash(err, 'danger')

        return render_template(
            'admin/pdf_review.html',
            pages=result['pages'],
            professions=result['professions'],
        )

    return render_template('admin/pdf_upload.html')


@admin_bp.route('/pdf/guardar', methods=['POST'])
@login_required
@admin_required
def pdf_save():
    """Save one parsed profession from the PDF review form."""
    from flask_login import current_user

    name = request.form.get('name', '').strip()
    if not name:
        flash('La profesión necesita un nombre.', 'danger')
        return redirect(url_for('admin.pdf_upload'))

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

    # Trappings
    for item in request.form.get('trappings_raw', '').split(','):
        item = item.strip()
        if item:
            db.session.add(ProfessionTrapping(profession_id=prof.id, name=item))

    # Skills: match by name (best-effort fuzzy)
    _match_and_save_skills(prof, request.form.get('skills_raw', ''))
    _match_and_save_talents(prof, request.form.get('talents_raw', ''))

    # Career exits (just store raw names for now; admin can link later)
    # We store them in description as a note if prof doesn't exist yet
    exits_raw = request.form.get('exits_raw', '').strip()
    entries_raw = request.form.get('entries_raw', '').strip()
    if exits_raw or entries_raw:
        note = ''
        if exits_raw:
            note += f'\n[SALIDAS PENDIENTES DE VINCULAR]: {exits_raw}'
        if entries_raw:
            note += f'\n[ACCESOS PENDIENTES DE VINCULAR]: {entries_raw}'
        prof.description = (prof.description or '') + note

    db.session.commit()
    flash(f'Profesión "{prof.name}" guardada. Recuerda vincular accesos/salidas.', 'success')
    return redirect(url_for('professions.edit', prof_id=prof.id))


def _match_and_save_skills(prof, skills_raw: str):
    import difflib
    all_skills = Skill.query.all()
    skill_map = {s.name_es.lower(): s for s in all_skills}
    skill_map.update({s.name_en.lower(): s for s in all_skills if s.name_en})

    # Split on commas and 'o'/'or'
    parts = [p.strip() for p in skills_raw.replace(' o ', ',').replace(' or ', ',').split(',')]
    group = None
    for raw_part in parts:
        if not raw_part:
            continue
        matches = difflib.get_close_matches(raw_part.lower(), skill_map.keys(), n=1, cutoff=0.7)
        if matches:
            skill = skill_map[matches[0]]
            ps = ProfessionSkill(profession_id=prof.id, skill_id=skill.id, choice_group=group)
            db.session.add(ps)


def _match_and_save_talents(prof, talents_raw: str):
    import difflib
    all_talents = Talent.query.all()
    talent_map = {t.name_es.lower(): t for t in all_talents}
    talent_map.update({t.name_en.lower(): t for t in all_talents if t.name_en})

    parts = [p.strip() for p in talents_raw.replace(' o ', ',').replace(' or ', ',').split(',')]
    group = None
    for raw_part in parts:
        if not raw_part:
            continue
        matches = difflib.get_close_matches(raw_part.lower(), talent_map.keys(), n=1, cutoff=0.7)
        if matches:
            talent = talent_map[matches[0]]
            pt = ProfessionTalent(profession_id=prof.id, talent_id=talent.id, choice_group=group)
            db.session.add(pt)

import os
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, current_app, abort)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app.extensions import db
from app.models.profession import Profession, ProfessionSkill, ProfessionTalent, ProfessionTrapping
from app.models.skill import Skill
from app.models.talent import Talent
from app.utils import admin_required

professions_bp = Blueprint('professions', __name__, template_folder='../templates')


@professions_bp.route('/')
def list_professions():
    type_filter = request.args.get('type', '')
    search = request.args.get('q', '').strip()
    query = Profession.query
    if type_filter in ('basic', 'advanced'):
        query = query.filter_by(type=type_filter)
    if search:
        query = query.filter(Profession.name.ilike(f'%{search}%'))
    professions = query.order_by(Profession.name).all()
    return render_template('professions/list.html', professions=professions,
                           type_filter=type_filter, search=search)


@professions_bp.route('/<int:prof_id>')
def detail(prof_id):
    prof = Profession.query.get_or_404(prof_id)
    return render_template('professions/detail.html', prof=prof)


@professions_bp.route('/nueva', methods=['GET', 'POST'])
@login_required
@admin_required
def create():
    skills = Skill.query.order_by(Skill.name_es).all()
    talents = Talent.query.order_by(Talent.name_es).all()

    if request.method == 'POST':
        prof = _profession_from_form(None)
        db.session.add(prof)
        db.session.flush()
        _save_skills_talents(prof)
        _save_trappings(prof)
        db.session.commit()
        flash(f'Profesión "{prof.name}" creada correctamente.', 'success')
        return redirect(url_for('professions.detail', prof_id=prof.id))

    all_profs = Profession.query.order_by(Profession.name).all()
    return render_template('professions/form.html', prof=None, skills=skills, talents=talents, exits_list=all_profs)


@professions_bp.route('/<int:prof_id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def edit(prof_id):
    prof = Profession.query.get_or_404(prof_id)
    skills = Skill.query.order_by(Skill.name_es).all()
    talents = Talent.query.order_by(Talent.name_es).all()

    if request.method == 'POST':
        _profession_from_form(prof)
        # Rebuild relationships
        ProfessionSkill.query.filter_by(profession_id=prof.id).delete()
        ProfessionTalent.query.filter_by(profession_id=prof.id).delete()
        ProfessionTrapping.query.filter_by(profession_id=prof.id).delete()
        db.session.flush()
        _save_skills_talents(prof)
        _save_trappings(prof)
        db.session.commit()
        flash(f'Profesión "{prof.name}" actualizada.', 'success')
        return redirect(url_for('professions.detail', prof_id=prof.id))

    all_profs = Profession.query.order_by(Profession.name).all()
    return render_template('professions/form.html', prof=prof, skills=skills, talents=talents, exits_list=all_profs)


@professions_bp.route('/<int:prof_id>/eliminar', methods=['POST'])
@login_required
@admin_required
def delete(prof_id):
    prof = Profession.query.get_or_404(prof_id)
    name = prof.name
    db.session.delete(prof)
    db.session.commit()
    flash(f'Profesión "{name}" eliminada.', 'warning')
    return redirect(url_for('professions.list_professions'))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _profession_from_form(prof: Profession) -> Profession:
    """Create or update a Profession from POST form data."""
    f = request.form
    if prof is None:
        prof = Profession()
        prof.created_by_id = current_user.id

    prof.name = f.get('name', '').strip()
    prof.name_en = f.get('name_en', '').strip() or None
    prof.type = f.get('type', 'basic')
    prof.description = f.get('description', '').strip() or None

    # Primary characteristics
    for field in Profession.PRIMARY_FIELDS:
        val = f.get(field, '').strip()
        setattr(prof, field, int(val) if val else None)

    # Secondary characteristics
    for field in Profession.SECONDARY_FIELDS:
        val = f.get(field, '').strip()
        setattr(prof, field, int(val) if val else None)

    # Handle image upload
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename:
            filename = secure_filename(file.filename)
            save_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'professions', filename)
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            file.save(save_path)
            prof.image_path = os.path.join('professions', filename)

    return prof


def _save_skills_talents(prof: Profession):
    """Parse skill/talent selections from form and persist association rows."""
    form = request.form

    # Skills: field names like 'skill_<skill_id>' and 'skill_group_<skill_id>'
    skill_ids = [int(k.split('_')[1]) for k in form if k.startswith('skill_') and not k.startswith('skill_group_')]
    for skill_id in skill_ids:
        group_val = form.get(f'skill_group_{skill_id}', '').strip()
        choice_group = int(group_val) if group_val.isdigit() else None
        ps = ProfessionSkill(profession_id=prof.id, skill_id=skill_id, choice_group=choice_group)
        db.session.add(ps)

    # Talents
    talent_ids = [int(k.split('_')[1]) for k in form if k.startswith('talent_') and not k.startswith('talent_group_')]
    for talent_id in talent_ids:
        group_val = form.get(f'talent_group_{talent_id}', '').strip()
        choice_group = int(group_val) if group_val.isdigit() else None
        pt = ProfessionTalent(profession_id=prof.id, talent_id=talent_id, choice_group=choice_group)
        db.session.add(pt)

    # Exits (career exits)
    exit_ids = request.form.getlist('exits')
    all_profs = {p.id: p for p in Profession.query.all()}
    prof.exits = [all_profs[int(eid)] for eid in exit_ids if int(eid) in all_profs and int(eid) != prof.id]


def _save_trappings(prof: Profession):
    trappings_text = request.form.get('trappings', '')
    for line in trappings_text.split(','):
        name = line.strip()
        if name:
            db.session.add(ProfessionTrapping(profession_id=prof.id, name=name))

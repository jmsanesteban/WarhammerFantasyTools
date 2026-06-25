from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from app.extensions import db
from app.models.skill import Skill
from app.models.talent import Talent
from app.models.profession import Profession, ProfessionSkill, ProfessionTalent
from app.utils import admin_required

skills_talents_bp = Blueprint('skills_talents', __name__, template_folder='../templates')


# ---- Skills ----

@skills_talents_bp.route('/habilidades')
def list_skills():
    search = request.args.get('q', '').strip()
    query = Skill.query
    if search:
        query = query.filter(
            Skill.name_es.ilike(f'%{search}%') | Skill.name_en.ilike(f'%{search}%')
        )
    skills = query.order_by(Skill.name_es).all()
    return render_template('skills/list.html', skills=skills, search=search)


@skills_talents_bp.route('/habilidades/<int:skill_id>')
def skill_detail(skill_id):
    skill = Skill.query.get_or_404(skill_id)
    # Professions that grant this skill
    prof_ids = [ps.profession_id for ps in ProfessionSkill.query.filter_by(skill_id=skill_id).all()]
    professions = Profession.query.filter(Profession.id.in_(prof_ids)).order_by(Profession.name).all()
    return render_template('skills/detail.html', skill=skill, professions=professions)


@skills_talents_bp.route('/habilidades/nueva', methods=['GET', 'POST'])
@login_required
@admin_required
def create_skill():
    if request.method == 'POST':
        skill = Skill(
            name_es=request.form.get('name_es', '').strip(),
            name_en=request.form.get('name_en', '').strip() or None,
            description=request.form.get('description', '').strip() or None,
            is_advanced=bool(request.form.get('is_advanced')),
        )
        db.session.add(skill)
        db.session.commit()
        flash(f'Habilidad "{skill.name_es}" creada.', 'success')
        return redirect(url_for('skills_talents.list_skills'))
    return render_template('skills/form.html', skill=None)


@skills_talents_bp.route('/habilidades/<int:skill_id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_skill(skill_id):
    skill = Skill.query.get_or_404(skill_id)
    if request.method == 'POST':
        skill.name_es = request.form.get('name_es', '').strip()
        skill.name_en = request.form.get('name_en', '').strip() or None
        skill.description = request.form.get('description', '').strip() or None
        skill.is_advanced = bool(request.form.get('is_advanced'))
        db.session.commit()
        flash(f'Habilidad "{skill.name_es}" actualizada.', 'success')
        return redirect(url_for('skills_talents.list_skills'))
    return render_template('skills/form.html', skill=skill)


@skills_talents_bp.route('/habilidades/<int:skill_id>/eliminar', methods=['POST'])
@login_required
@admin_required
def delete_skill(skill_id):
    skill = Skill.query.get_or_404(skill_id)
    name = skill.name_es
    db.session.delete(skill)
    db.session.commit()
    flash(f'Habilidad "{name}" eliminada.', 'warning')
    return redirect(url_for('skills_talents.list_skills'))


# ---- Talents ----

@skills_talents_bp.route('/talentos')
def list_talents():
    search = request.args.get('q', '').strip()
    query = Talent.query
    if search:
        query = query.filter(
            Talent.name_es.ilike(f'%{search}%') | Talent.name_en.ilike(f'%{search}%')
        )
    talents = query.order_by(Talent.name_es).all()
    return render_template('talents/list.html', talents=talents, search=search)


@skills_talents_bp.route('/talentos/<int:talent_id>')
def talent_detail(talent_id):
    talent = Talent.query.get_or_404(talent_id)
    prof_ids = [pt.profession_id for pt in ProfessionTalent.query.filter_by(talent_id=talent_id).all()]
    professions = Profession.query.filter(Profession.id.in_(prof_ids)).order_by(Profession.name).all()
    return render_template('talents/detail.html', talent=talent, professions=professions)


@skills_talents_bp.route('/talentos/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def create_talent():
    if request.method == 'POST':
        talent = Talent(
            name_es=request.form.get('name_es', '').strip(),
            name_en=request.form.get('name_en', '').strip() or None,
            description=request.form.get('description', '').strip() or None,
            max_times=int(request.form.get('max_times', 1) or 1),
        )
        db.session.add(talent)
        db.session.commit()
        flash(f'Talento "{talent.name_es}" creado.', 'success')
        return redirect(url_for('skills_talents.list_talents'))
    return render_template('talents/form.html', talent=None)


@skills_talents_bp.route('/talentos/<int:talent_id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_talent(talent_id):
    talent = Talent.query.get_or_404(talent_id)
    if request.method == 'POST':
        talent.name_es = request.form.get('name_es', '').strip()
        talent.name_en = request.form.get('name_en', '').strip() or None
        talent.description = request.form.get('description', '').strip() or None
        talent.max_times = int(request.form.get('max_times', 1) or 1)
        db.session.commit()
        flash(f'Talento "{talent.name_es}" actualizado.', 'success')
        return redirect(url_for('skills_talents.list_talents'))
    return render_template('talents/form.html', talent=talent)


@skills_talents_bp.route('/talentos/<int:talent_id>/eliminar', methods=['POST'])
@login_required
@admin_required
def delete_talent(talent_id):
    talent = Talent.query.get_or_404(talent_id)
    name = talent.name_es
    db.session.delete(talent)
    db.session.commit()
    flash(f'Talento "{name}" eliminado.', 'warning')
    return redirect(url_for('skills_talents.list_talents'))

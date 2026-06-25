from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app.extensions import db
from app.models.character import Character, CharacterProfession, CharacterSkill, CharacterTalent
from app.models.profession import Profession
from app.models.skill import Skill
from app.models.talent import Talent

characters_bp = Blueprint('characters', __name__, template_folder='../templates')


@characters_bp.route('/')
@login_required
def list_characters():
    characters = Character.query.filter_by(user_id=current_user.id).order_by(Character.name).all()
    return render_template('characters/list.html', characters=characters)


@characters_bp.route('/<int:char_id>')
@login_required
def detail(char_id):
    char = Character.query.get_or_404(char_id)
    if char.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    return render_template('characters/detail.html', char=char)


@characters_bp.route('/nuevo', methods=['GET', 'POST'])
@login_required
def create():
    professions = Profession.query.order_by(Profession.name).all()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('El personaje necesita un nombre.', 'danger')
            return render_template('characters/form.html', char=None, professions=professions)

        char = Character(
            user_id=current_user.id,
            name=name,
            race=request.form.get('race', '').strip() or None,
            gender=request.form.get('gender', '').strip() or None,
            notes=request.form.get('notes', '').strip() or None,
        )
        db.session.add(char)
        db.session.flush()

        # Professions ordered list
        prof_ids = request.form.getlist('profession_ids')
        for order, prof_id_str in enumerate(prof_ids):
            if prof_id_str:
                cp = CharacterProfession(
                    character_id=char.id,
                    profession_id=int(prof_id_str),
                    order=order,
                    is_current=(order == len(prof_ids) - 1),
                )
                db.session.add(cp)

        db.session.commit()
        flash(f'Personaje "{char.name}" creado.', 'success')
        return redirect(url_for('characters.detail', char_id=char.id))

    return render_template('characters/form.html', char=None, professions=professions)


@characters_bp.route('/<int:char_id>/editar', methods=['GET', 'POST'])
@login_required
def edit(char_id):
    char = Character.query.get_or_404(char_id)
    if char.user_id != current_user.id and not current_user.is_admin:
        abort(403)

    professions = Profession.query.order_by(Profession.name).all()

    if request.method == 'POST':
        char.name = request.form.get('name', '').strip()
        char.race = request.form.get('race', '').strip() or None
        char.gender = request.form.get('gender', '').strip() or None
        char.notes = request.form.get('notes', '').strip() or None

        # Rebuild profession list
        CharacterProfession.query.filter_by(character_id=char.id).delete()
        prof_ids = request.form.getlist('profession_ids')
        for order, prof_id_str in enumerate(prof_ids):
            if prof_id_str:
                cp = CharacterProfession(
                    character_id=char.id,
                    profession_id=int(prof_id_str),
                    order=order,
                    is_current=(order == len(prof_ids) - 1),
                )
                db.session.add(cp)

        db.session.commit()
        flash(f'Personaje "{char.name}" actualizado.', 'success')
        return redirect(url_for('characters.detail', char_id=char.id))

    return render_template('characters/form.html', char=char, professions=professions)


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

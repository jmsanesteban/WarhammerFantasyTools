import json
import re

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models.character import (
    Character, CharacterProfession, CharacterSkill, CharacterTalent,
    CharacterTrait, CharacterAcquaintance, CharacterPossession, CharacterMagicItem,
)
from app.models.profession import Profession
from app.models.skill import Skill
from app.models.talent import Talent
from app.services import character_creation_service as ccs

characters_bp = Blueprint('characters', __name__, template_folder='../templates')

_RAZAS = ['Humano', 'Halfling', 'Enano', 'Elfo Silvano', 'Alto Elfo']


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
    )
    for field in Character.PRIMARY_FIELDS + Character.SECONDARY_FIELDS:
        setattr(char, field, _int(field))

    db.session.add(char)
    db.session.flush()

    # Professions ordered list (reusa el mismo widget que la creación rápida)
    prof_ids = request.form.getlist('profession_ids')
    for order, prof_id_str in enumerate(prof_ids):
        if prof_id_str:
            db.session.add(CharacterProfession(
                character_id=char.id, profession_id=int(prof_id_str),
                order=order, is_current=(order == len(prof_ids) - 1),
            ))

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

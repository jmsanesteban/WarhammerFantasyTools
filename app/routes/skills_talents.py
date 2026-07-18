import difflib
import os
from collections import Counter
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, Response)
from flask_login import login_required
from markupsafe import Markup
from app.extensions import db
from app.models.skill import Skill
from app.models.talent import Talent
from app.models.profession import Profession, ProfessionSkill, ProfessionTalent
from app.utils import admin_required, require_permission

skills_talents_bp = Blueprint('skills_talents', __name__, template_folder='../templates')


def _check_name_collision(model, name_es: str, exclude_id: int = None):
    """
    Guard against accidentally creating a near-duplicate catalog entry (e.g.
    'Preparar veneno' next to the real 'Preparar venenos') - skills/talents
    used by professions must only ever come from this catalog, so a stray
    almost-duplicate here is exactly how a profession can end up silently
    linked to the wrong one.
    Returns (exact_match_or_None, [near_duplicate_names]).
    """
    query = model.query
    if exclude_id is not None:
        query = query.filter(model.id != exclude_id)
    rows = query.all()
    name_lower = name_es.lower()

    exact = next((r for r in rows if r.name_es.lower() == name_lower), None)
    if exact:
        return exact, []

    name_map = {r.name_es.lower(): r.name_es for r in rows}
    close = difflib.get_close_matches(name_lower, name_map.keys(), n=3, cutoff=0.82)
    return None, [name_map[k] for k in close]


# ─────────────────────────────────────────────────────────────────────────────
# Skills — CRUD
# ─────────────────────────────────────────────────────────────────────────────

@skills_talents_bp.route('/habilidades')
@require_permission('skills.view')
def list_skills():
    search     = request.args.get('q', '').strip()
    search_all = request.args.get('search_all', '0') == '1'
    tipo       = request.args.get('tipo', '')        # 'basic' | 'advanced' | ''
    caract     = request.args.get('caract', '').strip()

    query = Skill.query

    if search:
        if search_all:
            query = query.filter(
                Skill.name_es.ilike(f'%{search}%')
                | Skill.name_en.ilike(f'%{search}%')
                | Skill.description.ilike(f'%{search}%')
                | Skill.caracteristicas.ilike(f'%{search}%')
                | Skill.talentos_asociados.ilike(f'%{search}%')
            )
        else:
            query = query.filter(
                Skill.name_es.ilike(f'%{search}%') | Skill.name_en.ilike(f'%{search}%')
            )

    if tipo == 'basic':
        query = query.filter(Skill.is_advanced == False)
    elif tipo == 'advanced':
        query = query.filter(Skill.is_advanced == True)

    if caract:
        query = query.filter(Skill.caracteristicas.ilike(f'%{caract}%'))

    skills = query.order_by(Skill.name_es).all()

    # Unique characteristic values for the filter dropdown
    rows = db.session.query(Skill.caracteristicas).filter(Skill.caracteristicas.isnot(None)).all()
    all_caracts = sorted({
        c.strip()
        for (raw,) in rows
        for c in raw.split(',')
        if c.strip()
    })

    return render_template(
        'skills/list.html',
        skills=skills, search=search, search_all=search_all,
        tipo=tipo, caract=caract, all_caracts=all_caracts,
    )


def _search_by_specialization(assoc_model, catalog_model, catalog_field_name, q):
    """
    Free-text search across a profession-skill/talent association table,
    matching either the catalog item's name (name_es) or its specialization
    text (e.g. 'Sabiduría académica (Teología)' isn't its own catalog entry -
    'Teología' only exists as the `specialization` value on whichever
    ProfessionSkill rows chose it). Returns a list of
    {'label': 'Sabiduría académica (Teología)', 'professions': [Profession]}
    grouped by (catalog item, specialization) and sorted by label.
    """
    rows = (
        assoc_model.query
        .join(catalog_model)
        .filter(
            catalog_model.name_es.ilike(f'%{q}%')
            | assoc_model.specialization.ilike(f'%{q}%')
        )
        .all()
    )
    if not rows:
        return []

    # Group case-insensitively: free-text specialization values aren't a
    # fixed catalog (unlike Skill/Talent.name_es), so the same specialization
    # entered with different casing on different professions (e.g.
    # "Genealogía/Heráldica" vs "Genealogía/heráldica") must still count as
    # one result rather than silently fragmenting into two - the most common
    # casing across matching rows wins for display.
    groups = {}  # lowercased label -> {'professions': set(), 'label_counts': Counter}
    for row in rows:
        catalog_item = getattr(row, catalog_field_name)
        label = f'{catalog_item.name_es} ({row.specialization})' if row.specialization else catalog_item.name_es
        key = label.lower()
        group = groups.setdefault(key, {'professions': set(), 'label_counts': Counter()})
        group['professions'].add(row.profession_id)
        group['label_counts'][label] += 1

    all_prof_ids = {pid for g in groups.values() for pid in g['professions']}
    prof_map = {p.id: p for p in Profession.query.filter(Profession.id.in_(all_prof_ids)).all()}

    results = []
    for group in groups.values():
        canonical_label = group['label_counts'].most_common(1)[0][0]
        professions = sorted(
            (prof_map[pid] for pid in group['professions'] if pid in prof_map),
            key=lambda p: p.name,
        )
        results.append({'label': canonical_label, 'professions': professions})
    results.sort(key=lambda r: r['label'])
    return results


@skills_talents_bp.route('/habilidades/buscar')
@require_permission('skills.view')
def search_skills():
    skills = Skill.query.order_by(Skill.name_es).all()
    options = [{'id': s.id, 'name': s.name_es} for s in skills]

    q = request.args.get('q', '').strip()
    results = _search_by_specialization(ProfessionSkill, Skill, 'skill', q) if q else None

    return render_template('skills/search.html', options=options, q=q, results=results)


@skills_talents_bp.route('/habilidades/<int:skill_id>')
@require_permission('skills.view')
def skill_detail(skill_id):
    skill    = Skill.query.get_or_404(skill_id)
    prof_ids = [ps.profession_id for ps in ProfessionSkill.query.filter_by(skill_id=skill_id).all()]
    professions = Profession.query.filter(Profession.id.in_(prof_ids)).order_by(Profession.name).all()
    return render_template('skills/detail.html', skill=skill, professions=professions)


@skills_talents_bp.route('/habilidades/nueva', methods=['GET', 'POST'])
@require_permission('skills.edit')
def create_skill():
    if request.method == 'POST':
        name_es = request.form.get('name_es', '').strip()
        exact, near = _check_name_collision(Skill, name_es)
        if exact:
            flash(f'Ya existe la habilidad "{exact.name_es}". No se ha creado un duplicado.', 'danger')
            return render_template('skills/form.html', skill=None)

        skill = Skill(
            name_es=name_es,
            name_en=request.form.get('name_en', '').strip() or None,
            description=request.form.get('description', '').strip() or None,
            is_advanced=bool(request.form.get('is_advanced')),
            caracteristicas=request.form.get('caracteristicas', '').strip() or None,
            talentos_asociados=request.form.get('talentos_asociados', '').strip() or None,
        )
        db.session.add(skill)
        db.session.commit()
        if near:
            flash(Markup('Habilidad "{}" creada. <strong>Aviso:</strong> nombre parecido a: {} — '
                        'comprueba que no sea la misma habilidad con otro nombre.')
                  .format(skill.name_es, ', '.join(near)), 'warning')
        else:
            flash(f'Habilidad "{skill.name_es}" creada.', 'success')
        return redirect(url_for('skills_talents.list_skills'))
    return render_template('skills/form.html', skill=None)


@skills_talents_bp.route('/habilidades/<int:skill_id>/editar', methods=['GET', 'POST'])
@require_permission('skills.edit')
def edit_skill(skill_id):
    skill = Skill.query.get_or_404(skill_id)
    if request.method == 'POST':
        name_es = request.form.get('name_es', '').strip()
        exact, near = _check_name_collision(Skill, name_es, exclude_id=skill.id)
        if exact:
            flash(f'Ya existe otra habilidad "{exact.name_es}". No se ha renombrado para evitar un duplicado.', 'danger')
            return render_template('skills/form.html', skill=skill)

        skill.name_es            = name_es
        skill.name_en            = request.form.get('name_en', '').strip() or None
        skill.description        = request.form.get('description', '').strip() or None
        skill.is_advanced        = bool(request.form.get('is_advanced'))
        skill.caracteristicas    = request.form.get('caracteristicas', '').strip() or None
        skill.talentos_asociados = request.form.get('talentos_asociados', '').strip() or None
        db.session.commit()
        if near:
            flash(Markup('Habilidad "{}" actualizada. <strong>Aviso:</strong> nombre parecido a: {} — '
                        'comprueba que no sea la misma habilidad con otro nombre.')
                  .format(skill.name_es, ', '.join(near)), 'warning')
        else:
            flash(f'Habilidad "{skill.name_es}" actualizada.', 'success')
        return redirect(url_for('skills_talents.list_skills'))
    return render_template('skills/form.html', skill=skill)


@skills_talents_bp.route('/habilidades/<int:skill_id>/eliminar', methods=['POST'])
@require_permission('skills.edit')
def delete_skill(skill_id):
    skill = Skill.query.get_or_404(skill_id)
    name  = skill.name_es
    db.session.delete(skill)
    db.session.commit()
    flash(f'Habilidad "{name}" eliminada.', 'warning')
    return redirect(url_for('skills_talents.list_skills'))


# ─────────────────────────────────────────────────────────────────────────────
# Skills — Import / Export
# ─────────────────────────────────────────────────────────────────────────────

@skills_talents_bp.route('/habilidades/importar', methods=['GET', 'POST'])
@login_required
@admin_required
def import_skills():
    if request.method == 'GET':
        return render_template('skills/import.html')

    f = request.files.get('file')
    if not f or not f.filename:
        flash('Selecciona un fichero.', 'danger')
        return redirect(request.url)

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ('.txt', '.csv', '.xlsx', '.xls'):
        flash('Formato no soportado. Usa .txt, .csv o .xlsx.', 'danger')
        return redirect(request.url)

    from app.services.import_service import parse_skills
    try:
        entries = parse_skills(f.read(), ext)
    except Exception as e:
        flash(f'Error al leer el fichero: {e}', 'danger')
        return redirect(request.url)

    existing = {s.name_es.lower(): s for s in Skill.query.all()}
    created = updated = skipped = 0
    possible_dupes = []
    mode = request.form.get('mode', 'skip')

    for entry in entries:
        name_lower = entry.get('name_es', '').lower()
        if not name_lower:
            continue
        if name_lower in existing:
            if mode == 'update':
                s = existing[name_lower]
                for field in ('description', 'is_advanced', 'caracteristicas', 'talentos_asociados'):
                    if field in entry and entry[field] is not None:
                        setattr(s, field, entry[field])
                updated += 1
            else:
                skipped += 1
        else:
            # Near-duplicate check (e.g. 'preparar veneno' vs the existing
            # 'preparar venenos') — still import it, but flag it prominently
            # so the admin notices and can merge/rename via the catalog UI.
            close = difflib.get_close_matches(name_lower, existing.keys(), n=1, cutoff=0.82)
            if close:
                possible_dupes.append((entry['name_es'], existing[close[0]].name_es))

            s = Skill(
                name_es=entry['name_es'],
                description=entry.get('description'),
                is_advanced=entry.get('is_advanced', False),
                caracteristicas=entry.get('caracteristicas'),
                talentos_asociados=entry.get('talentos_asociados'),
            )
            db.session.add(s)
            existing[name_lower] = s
            created += 1

    db.session.commit()
    flash(f'Importación completada: {created} creadas, {updated} actualizadas, {skipped} omitidas.', 'success')
    if possible_dupes:
        detail = '; '.join(f'"{new}" ≈ "{old}"' for new, old in possible_dupes)
        flash(Markup('<strong>Aviso:</strong> {} habilidad(es) creada(s) con nombre parecido a una ya existente: {}. '
                    'Revisa si son duplicados antes de usarlas en profesiones.')
              .format(len(possible_dupes), detail), 'warning')
    return redirect(url_for('skills_talents.list_skills'))


@skills_talents_bp.route('/habilidades/exportar')
@login_required
@admin_required
def export_skills():
    fmt    = request.args.get('f', 'txt').lower()
    skills = Skill.query.order_by(Skill.name_es).all()
    from app.services.import_service import export_skills_text, export_skills_csv, export_skills_xlsx

    if fmt == 'csv':
        data = export_skills_csv(skills)
        return Response(data, mimetype='text/csv; charset=utf-8-sig',
                        headers={'Content-Disposition': 'attachment; filename=habilidades.csv'})
    if fmt == 'xlsx':
        data = export_skills_xlsx(skills)
        return Response(data,
                        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': 'attachment; filename=habilidades.xlsx'})
    data = export_skills_text(skills).encode('utf-8')
    return Response(data, mimetype='text/plain; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename=habilidades.txt'})


# ─────────────────────────────────────────────────────────────────────────────
# Talents — CRUD
# ─────────────────────────────────────────────────────────────────────────────

@skills_talents_bp.route('/talentos')
@require_permission('skills.view')
def list_talents():
    search     = request.args.get('q', '').strip()
    search_all = request.args.get('search_all', '0') == '1'

    query = Talent.query
    if search:
        if search_all:
            query = query.filter(
                Talent.name_es.ilike(f'%{search}%')
                | Talent.name_en.ilike(f'%{search}%')
                | Talent.description.ilike(f'%{search}%')
            )
        else:
            query = query.filter(
                Talent.name_es.ilike(f'%{search}%') | Talent.name_en.ilike(f'%{search}%')
            )

    talents = query.order_by(Talent.name_es).all()
    return render_template('talents/list.html', talents=talents, search=search, search_all=search_all)


@skills_talents_bp.route('/talentos/buscar')
@require_permission('skills.view')
def search_talents():
    talents = Talent.query.order_by(Talent.name_es).all()
    options = [{'id': t.id, 'name': t.name_es} for t in talents]

    q = request.args.get('q', '').strip()
    results = _search_by_specialization(ProfessionTalent, Talent, 'talent', q) if q else None

    return render_template('talents/search.html', options=options, q=q, results=results)


@skills_talents_bp.route('/talentos/<int:talent_id>')
@require_permission('skills.view')
def talent_detail(talent_id):
    talent   = Talent.query.get_or_404(talent_id)
    prof_ids = [pt.profession_id for pt in ProfessionTalent.query.filter_by(talent_id=talent_id).all()]
    professions = Profession.query.filter(Profession.id.in_(prof_ids)).order_by(Profession.name).all()
    return render_template('talents/detail.html', talent=talent, professions=professions)


@skills_talents_bp.route('/talentos/nuevo', methods=['GET', 'POST'])
@require_permission('skills.edit')
def create_talent():
    if request.method == 'POST':
        name_es = request.form.get('name_es', '').strip()
        exact, near = _check_name_collision(Talent, name_es)
        if exact:
            flash(f'Ya existe el talento "{exact.name_es}". No se ha creado un duplicado.', 'danger')
            return render_template('talents/form.html', talent=None)

        talent = Talent(
            name_es=name_es,
            name_en=request.form.get('name_en', '').strip() or None,
            description=request.form.get('description', '').strip() or None,
            max_times=int(request.form.get('max_times', 1) or 1),
        )
        db.session.add(talent)
        db.session.commit()
        if near:
            flash(Markup('Talento "{}" creado. <strong>Aviso:</strong> nombre parecido a: {} — '
                        'comprueba que no sea el mismo talento con otro nombre.')
                  .format(talent.name_es, ', '.join(near)), 'warning')
        else:
            flash(f'Talento "{talent.name_es}" creado.', 'success')
        return redirect(url_for('skills_talents.list_talents'))
    return render_template('talents/form.html', talent=None)


@skills_talents_bp.route('/talentos/<int:talent_id>/editar', methods=['GET', 'POST'])
@require_permission('skills.edit')
def edit_talent(talent_id):
    talent = Talent.query.get_or_404(talent_id)
    if request.method == 'POST':
        name_es = request.form.get('name_es', '').strip()
        exact, near = _check_name_collision(Talent, name_es, exclude_id=talent.id)
        if exact:
            flash(f'Ya existe otro talento "{exact.name_es}". No se ha renombrado para evitar un duplicado.', 'danger')
            return render_template('talents/form.html', talent=talent)

        talent.name_es    = name_es
        talent.name_en    = request.form.get('name_en', '').strip() or None
        talent.description = request.form.get('description', '').strip() or None
        talent.max_times  = int(request.form.get('max_times', 1) or 1)
        db.session.commit()
        if near:
            flash(Markup('Talento "{}" actualizado. <strong>Aviso:</strong> nombre parecido a: {} — '
                        'comprueba que no sea el mismo talento con otro nombre.')
                  .format(talent.name_es, ', '.join(near)), 'warning')
        else:
            flash(f'Talento "{talent.name_es}" actualizado.', 'success')
        return redirect(url_for('skills_talents.list_talents'))
    return render_template('talents/form.html', talent=talent)


@skills_talents_bp.route('/talentos/<int:talent_id>/eliminar', methods=['POST'])
@require_permission('skills.edit')
def delete_talent(talent_id):
    talent = Talent.query.get_or_404(talent_id)
    name   = talent.name_es
    db.session.delete(talent)
    db.session.commit()
    flash(f'Talento "{name}" eliminado.', 'warning')
    return redirect(url_for('skills_talents.list_talents'))


# ─────────────────────────────────────────────────────────────────────────────
# Talents — Import / Export
# ─────────────────────────────────────────────────────────────────────────────

@skills_talents_bp.route('/talentos/importar', methods=['GET', 'POST'])
@login_required
@admin_required
def import_talents():
    if request.method == 'GET':
        return render_template('talents/import.html')

    f = request.files.get('file')
    if not f or not f.filename:
        flash('Selecciona un fichero.', 'danger')
        return redirect(request.url)

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ('.txt', '.csv', '.xlsx', '.xls'):
        flash('Formato no soportado. Usa .txt, .csv o .xlsx.', 'danger')
        return redirect(request.url)

    from app.services.import_service import parse_talents
    try:
        entries = parse_talents(f.read(), ext)
    except Exception as e:
        flash(f'Error al leer el fichero: {e}', 'danger')
        return redirect(request.url)

    existing = {t.name_es.lower(): t for t in Talent.query.all()}
    created = updated = skipped = 0
    possible_dupes = []
    mode = request.form.get('mode', 'skip')

    for entry in entries:
        name_lower = entry.get('name_es', '').lower()
        if not name_lower:
            continue
        if name_lower in existing:
            if mode == 'update':
                t = existing[name_lower]
                if entry.get('description') is not None:
                    t.description = entry['description']
                updated += 1
            else:
                skipped += 1
        else:
            # Near-duplicate check — still import it, but flag it prominently
            # so the admin notices and can merge/rename via the catalog UI.
            close = difflib.get_close_matches(name_lower, existing.keys(), n=1, cutoff=0.82)
            if close:
                possible_dupes.append((entry['name_es'], existing[close[0]].name_es))

            t = Talent(
                name_es=entry['name_es'],
                description=entry.get('description'),
            )
            db.session.add(t)
            existing[name_lower] = t
            created += 1

    db.session.commit()
    flash(f'Importación completada: {created} creados, {updated} actualizados, {skipped} omitidos.', 'success')
    if possible_dupes:
        detail = '; '.join(f'"{new}" ≈ "{old}"' for new, old in possible_dupes)
        flash(Markup('<strong>Aviso:</strong> {} talento(s) creado(s) con nombre parecido a uno ya existente: {}. '
                    'Revisa si son duplicados antes de usarlos en profesiones.')
              .format(len(possible_dupes), detail), 'warning')
    return redirect(url_for('skills_talents.list_talents'))


@skills_talents_bp.route('/talentos/exportar')
@login_required
@admin_required
def export_talents():
    fmt     = request.args.get('f', 'txt').lower()
    talents = Talent.query.order_by(Talent.name_es).all()
    from app.services.import_service import export_talents_text, export_talents_csv, export_talents_xlsx

    if fmt == 'csv':
        data = export_talents_csv(talents)
        return Response(data, mimetype='text/csv; charset=utf-8-sig',
                        headers={'Content-Disposition': 'attachment; filename=talentos.csv'})
    if fmt == 'xlsx':
        data = export_talents_xlsx(talents)
        return Response(data,
                        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': 'attachment; filename=talentos.xlsx'})
    data = export_talents_text(talents).encode('utf-8')
    return Response(data, mimetype='text/plain; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename=talentos.txt'})

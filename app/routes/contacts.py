import os
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app.extensions import db
from app.models.character import Character
from app.models.profession import Profession
from app.models.contact import Contact, ContactProfession, UNTERSUCHUNG_GRADOS, ESTADO_CHOICES, ESTADO_LABELS, RAZA_CHOICES
from app.models.untersuchung import (
    clamp_grados, has_marca, marca_image_path, grados_display,
    UNTERSUCHUNG_GRADOS_CON_MARCA, UNTERSUCHUNG_GRADOS_AGENTE, UNTERSUCHUNG_GRADOS_ADJUNTO, MAX_GRADOS,
)
from app.models.contact_character_link import (
    ContactCharacterLink, NIVEL_LABELS, TIPO_RELACION_CHOICES, TIPO_RELACION_EXCLUSIVE_PAIRS,
)
from app.models.contact_note import ContactNote
from app.services import salary_service
from app.utils import admin_required

contacts_bp = Blueprint('contacts', __name__, template_folder='../templates')

_ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}


def _grados_from_form():
    """Reads 3 independent single-select slots (grado_1/2/3) rather than one
    multi-select - a <select multiple> can't have the same option chosen
    twice, but an Agente can genuinely hold the same grado twice over (a
    senior/veteran double mark). Tier exclusivity (Agente vs Adjunto) and the
    1-mark cap for Adjunto are enforced server-side by clamp_grados()."""
    values = [request.form.get(f'grado_{i}', '').strip() for i in range(1, MAX_GRADOS + 1)]
    return clamp_grados(values)


def _marca_images():
    """{grado: uploaded-file-url} for every grado - passed to every contact
    form/detail template so it can show the mark image live as grados are
    picked (JS) or read-only (ficha)."""
    images = {}
    for g in UNTERSUCHUNG_GRADOS:
        path = marca_image_path(g)
        if path:
            images[g] = url_for('main.uploaded_file', filename=path)
    return images


def _grado_form_context():
    """Shared template kwargs for every contact form render (new/edit, both
    the happy path and each validation-error re-render)."""
    return dict(
        grados=UNTERSUCHUNG_GRADOS, grados_con_marca=UNTERSUCHUNG_GRADOS_CON_MARCA,
        grados_agente=UNTERSUCHUNG_GRADOS_AGENTE, grados_adjunto=UNTERSUCHUNG_GRADOS_ADJUNTO,
        estado_choices=ESTADO_CHOICES, estado_labels=ESTADO_LABELS, raza_choices=RAZA_CHOICES,
        marca_images=_marca_images(),
    )


def _professions_picker_context(professions):
    """JSON-ready data for the searchable profession picker widget (same
    widget/macro as Character's career - duplicated helper rather than a
    shared import, the two blueprints don't otherwise depend on each other),
    plus the salary reference table and a precomputed tipo x estado -> sueldo
    lookup so the browser can show a live "Sueldo del trabajador" without
    reimplementing the money math in JS."""
    from app.models.profession import career_exits_table
    exits_map = {}
    for source_id, target_id in db.session.query(
        career_exits_table.c.source_id, career_exits_table.c.target_id
    ).all():
        exits_map.setdefault(source_id, []).append(target_id)
    return {
        'professions_picker_list': [{'id': p.id, 'name': p.name} for p in professions],
        'professions_exits_map': exits_map,
        'salary_table': salary_service.get_salary_table(),
        'sueldo_lookup': salary_service.sueldo_lookup(),
    }


def _rebuild_contact_professions(contact_id):
    """Rebuild a contact's profession list (with its objective salary tier -
    2026-07-17, replaces the old bare multi-select) from the 3 parallel
    repeated form fields, same convention as Character._rebuild_professions.
    A profession picked twice in the same submission is silently deduped
    (first occurrence wins) since ContactProfession has a uniqueness
    constraint per contact+profession, unlike a character's career."""
    prof_ids = request.form.getlist('profession_ids')
    tipo_list = request.form.getlist('tipo_sueldo_list')
    estado_list = request.form.getlist('estado_habilidad_list')
    seen = set()
    for i, prof_id_str in enumerate(prof_ids):
        if not prof_id_str or prof_id_str in seen:
            continue
        seen.add(prof_id_str)
        db.session.add(ContactProfession(
            contact_id=contact_id,
            profession_id=int(prof_id_str),
            tipo_sueldo=(tipo_list[i] if i < len(tipo_list) else '') or None,
            estado_habilidad=(estado_list[i] if i < len(estado_list) else '') or None,
        ))


def _estado_from_form():
    estado = request.form.get('estado', '').strip()
    return estado if estado in ESTADO_CHOICES else 'vivo'


def _raza_from_form():
    """raza_choice is the guided <select> (RAZA_CHOICES + the '__nuevo__'
    sentinel); when '__nuevo__' is picked, raza_custom carries the actual
    free-text value the admin typed. Contact.raza stays free text in DB -
    the choices list only guides the form, it isn't a foreign key."""
    choice = request.form.get('raza_choice', '').strip()
    if choice == '__nuevo__':
        return request.form.get('raza_custom', '').strip() or None
    return choice or None


def _save_image_from_form(contact):
    file = request.files.get('image')
    if not file or not file.filename:
        return
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in _ALLOWED_IMAGE_EXTENSIONS:
        flash('La imagen debe ser PNG, JPG, WEBP o GIF.', 'danger')
        return
    filename = secure_filename(file.filename)
    save_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'contactos', filename)
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    file.save(save_path)
    contact.image_path = os.path.join('contactos', filename)


def _global_fields_from_form(contact):
    """Reads every global (non-per-character) Contact field from the POST
    body - shared by new()/edit()."""
    contact.nombre = request.form.get('nombre', '').strip()
    contact.raza = _raza_from_form()
    contact.estado = _estado_from_form()
    grados = _grados_from_form()
    contact.grados_untersuchung = grados
    # es_untersuchung (2026-07-17): hecho del propio contacto, no del vínculo
    # (ver TIPO_RELACION_CHOICES) - se marca a mano con el checkbox, o solo
    # (el checkbox se auto-marca en cliente al asignar una marca - ver
    # initGradoPicker en main.js), pero desmarcar el checkbox sin quitar
    # también las marcas no lo desactiva (has_marca manda).
    contact.es_untersuchung = request.form.get('es_untersuchung') == 'on' or has_marca(grados)
    contact.lugar_descanso = request.form.get('lugar_descanso', '').strip() or None
    contact.lugar_trabajo = request.form.get('lugar_trabajo', '').strip() or None
    contact.lugar_ocio = request.form.get('lugar_ocio', '').strip() or None
    contact.notas_director = request.form.get('notas_director', '').strip() or None


def _safe_redirect(default_endpoint, **default_kwargs):
    """Redirect to request.form['next_url'] if it's a plain same-site relative
    path (avoids open redirect), else fall back to the given endpoint. Lets
    admin-only inline panels (e.g. admin/contactos, admin/vinculos) post back
    to themselves instead of always bouncing to the contact's own detail page."""
    next_url = request.form.get('next_url', '').strip()
    if next_url.startswith('/') and not next_url.startswith('//') and '://' not in next_url:
        return redirect(next_url)
    return redirect(url_for(default_endpoint, **default_kwargs))


def _own_characters():
    return Character.query.filter_by(user_id=current_user.id).order_by(Character.name).all()


def _selectable_characters():
    """Characters the current user is allowed to act as when viewing/editing
    a contact's per-character data: admins can pick anyone, everyone else
    only their own."""
    if current_user.is_admin:
        return Character.query.order_by(Character.name).all()
    return _own_characters()


def _can_view(contact):
    """Whether the current user can see this contact at all. Since 2026-07-16
    the only gate is the admin-controlled Contact.is_visible kill-switch (the
    old per-character ContactCharacterVisibility grant system is gone) - any
    logged-in user can see any visible contact, and can add their own
    per-character link/notes/salary to it."""
    return current_user.is_admin or contact.is_visible


def _active_character():
    """The character whose view of Contacts is currently active. Since
    2026-07-17 this defaults to the user's persisted "personaje activo"
    (current_user.active_character_id) instead of "the first one
    alphabetically" - but an explicit ?personaje_id= still overrides it,
    which is how the admin-only character switcher on the contact ficha
    works (no separate mechanism needed for that)."""
    characters = _selectable_characters()
    if not characters:
        return None
    personaje_id = request.values.get('personaje_id', type=int)
    if personaje_id:
        match = next((c for c in characters if c.id == personaje_id), None)
        if match:
            return match
        if current_user.is_admin:
            return Character.query.get(personaje_id)
    if current_user.active_character_id:
        match = next((c for c in characters if c.id == current_user.active_character_id), None)
        if match:
            return match
    # Falls back to one of the user's OWN characters, never `characters[0]`
    # directly - for admin, `characters` is every character in the system
    # (see _selectable_characters), so that would silently pick some other
    # player's character as "active" (and, since the ficha now marks that
    # row "tú" with inline edit access, actually let an admin with no
    # character of their own edit a stranger's vínculo without realizing it).
    own = _own_characters()
    return own[0] if own else None


@contacts_bp.route('/')
@login_required
def index():
    """Global listing (2026-07-17): no more "view as this character" picker
    here - the active character is a persisted per-user setting now, read
    directly in the template via current_user.active_character. Instead of
    a per-viewer Nivel column, every contact shows how many characters (of
    any user) have a link to it, expandable to nivel+tipo per character."""
    page = request.args.get('page', 1, type=int)
    search = request.args.get('q', '').strip()
    per_page = 25

    query = Contact.query.order_by(Contact.nombre)
    if not current_user.is_admin:
        query = query.filter_by(is_visible=True)
    if search:
        query = query.filter(Contact.nombre.ilike(f'%{search}%'))

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    contact_ids = [c.id for c in pagination.items]
    links_by_contact = {}
    if contact_ids:
        links = (
            ContactCharacterLink.query
            .filter(ContactCharacterLink.contact_id.in_(contact_ids))
            .join(Character, Character.id == ContactCharacterLink.character_id)
            .order_by(Character.name)
            .all()
        )
        for link in links:
            links_by_contact.setdefault(link.contact_id, []).append(link)

    return render_template(
        'contacts/index.html',
        contacts=pagination.items,
        pagination=pagination,
        search=search,
        links_by_contact=links_by_contact,
        nivel_labels=NIVEL_LABELS,
        estado_labels=ESTADO_LABELS,
    )


@contacts_bp.route('/vinculos')
@login_required
def vinculos():
    """All contact<->character links (2026-07-17, moved out of admin.py -
    no longer admin-only). Non-admins default to only their own active
    character's links; ?todos=1 (or being admin) broadens to every link of
    every character, of every user - confirmed scope, not a bug. Notes only
    show a count here, never content (that stays on the contact's own
    ficha, per-character)."""
    page = request.args.get('page', 1, type=int)
    search = request.args.get('q', '').strip()
    per_page = 30
    show_all = current_user.is_admin or request.args.get('todos') == '1'

    if not show_all and not current_user.active_character_id:
        return render_template(
            'contacts/vinculos.html', links=[], pagination=None, search=search,
            show_all=False, no_active_character=True, note_counts={}, nivel_labels=NIVEL_LABELS,
        )

    query = (
        ContactCharacterLink.query
        .join(Contact, Contact.id == ContactCharacterLink.contact_id)
        .join(Character, Character.id == ContactCharacterLink.character_id)
        .order_by(Contact.nombre, Character.name)
    )
    if not show_all:
        query = query.filter(ContactCharacterLink.character_id == current_user.active_character_id)
    if search:
        like = f'%{search}%'
        query = query.filter(db.or_(Contact.nombre.ilike(like), Character.name.ilike(like)))

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    links = pagination.items

    note_counts = {}
    contact_ids = [l.contact_id for l in links]
    if contact_ids:
        rows = (
            db.session.query(ContactNote.contact_id, ContactNote.character_id, db.func.count(ContactNote.id))
            .filter(ContactNote.contact_id.in_(contact_ids))
            .group_by(ContactNote.contact_id, ContactNote.character_id)
            .all()
        )
        note_counts = {(cid, chid): cnt for cid, chid, cnt in rows}

    return render_template(
        'contacts/vinculos.html',
        links=links, pagination=pagination, search=search,
        show_all=show_all, no_active_character=False,
        note_counts=note_counts, nivel_labels=NIVEL_LABELS,
    )


@contacts_bp.route('/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def new():
    """Contact creation is admin-only (2026-07-16 rework) - the admin only
    fills in the contact's global facts here; each character adds their own
    link/notes/salary afterwards from the contact's own ficha (link_save)."""
    professions = Profession.query.order_by(Profession.name).all()
    form_context = {**_grado_form_context(), **_professions_picker_context(professions)}

    if request.method == 'POST':
        contact = Contact(created_by_id=current_user.id)
        _global_fields_from_form(contact)
        if not contact.nombre:
            flash('El contacto necesita un nombre.', 'danger')
            return render_template('contacts/new.html', **form_context)

        _save_image_from_form(contact)
        db.session.add(contact)
        db.session.flush()

        _rebuild_contact_professions(contact.id)

        db.session.commit()
        flash(f'Contacto «{contact.nombre}» creado.', 'success')
        return redirect(url_for('contacts.detail', contact_id=contact.id))

    return render_template('contacts/new.html', **form_context)


def _tipo_relacion_groups():
    """{choice: group_key} for every choice that's part of an exclusive pair
    (see TIPO_RELACION_EXCLUSIVE_PAIRS) - lets the template mark each
    checkbox with a shared data-exclusive-group so main.js can enforce
    "pick at most one per pair" client-side. Choices with no pair (e.g.
    'Otra') are simply absent from the map."""
    groups = {}
    for i, pair in enumerate(TIPO_RELACION_EXCLUSIVE_PAIRS):
        for choice in pair:
            groups[choice] = f'tipo-relacion-pair-{i}'
    return groups


def _dedupe_tipo_relacion(selected):
    """Enforces TIPO_RELACION_EXCLUSIVE_PAIRS server-side (the form's JS
    already keeps both members of a pair from being checked at once, but a
    direct POST could still send both) - if both are present, keeps whichever
    is listed first in the pair, drops the other."""
    result = list(selected)
    for first, second in TIPO_RELACION_EXCLUSIVE_PAIRS:
        if first in result and second in result:
            result.remove(second)
    return result


def _link_fields_from_form():
    nivel = request.form.get('nivel', type=int)
    if nivel is not None:
        nivel = max(-5, min(5, nivel))
    tipo_relacion = _dedupe_tipo_relacion(
        v for v in request.form.getlist('tipo_relacion') if v in TIPO_RELACION_CHOICES
    )
    return {
        'nivel': nivel,
        'tipo_relacion': tipo_relacion or None,
    }


@contacts_bp.route('/<int:contact_id>')
@login_required
def detail(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    characters = _selectable_characters()
    active_character = _active_character()

    if not _can_view(contact):
        return redirect(url_for('contacts.index'))

    my_link = None
    if active_character:
        my_link = ContactCharacterLink.query.filter_by(
            character_id=active_character.id, contact_id=contact_id,
        ).first()

    notes = []
    if active_character:
        notes = (
            ContactNote.query
            .filter_by(contact_id=contact_id, character_id=active_character.id)
            .order_by(ContactNote.created_at.desc())
            .all()
        )

    # "Personajes con relación" (2026-07-17): visible to anyone who can view
    # the contact, not just admin - shows nivel/tipo per character, but only
    # the *count* of notes, never their content (that stays private to each
    # character, same rule as the Vínculos listing).
    links = (
        ContactCharacterLink.query.filter_by(contact_id=contact_id)
        .join(Character, Character.id == ContactCharacterLink.character_id)
        .order_by(Character.name)
        .all()
    )
    note_counts = dict(
        db.session.query(ContactNote.character_id, db.func.count(ContactNote.id))
        .filter(ContactNote.contact_id == contact_id)
        .group_by(ContactNote.character_id)
        .all()
    )

    return render_template(
        'contacts/detail.html',
        contact=contact,
        characters=characters,
        active_character=active_character,
        my_link=my_link,
        notes=notes,
        links=links,
        note_counts=note_counts,
        can_edit=current_user.is_admin,
        estado_labels=ESTADO_LABELS,
        nivel_labels=NIVEL_LABELS,
        tipo_relacion_choices=TIPO_RELACION_CHOICES,
        tipo_relacion_groups=_tipo_relacion_groups(),
        marca_images=_marca_images(),
        grados_display=grados_display,
        compute_sueldo=salary_service.compute_sueldo,
    )


# ── Vínculo personaje-contacto ──────────────────────────────────────────────

@contacts_bp.route('/<int:contact_id>/vinculo', methods=['POST'])
@login_required
def link_save(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    characters = _selectable_characters()
    personaje_id = request.form.get('personaje_id', type=int)
    personaje = next((c for c in characters if c.id == personaje_id), None)
    if not personaje or not _can_view(contact):
        abort(403)

    link = ContactCharacterLink.query.filter_by(character_id=personaje.id, contact_id=contact.id).first()
    fields = _link_fields_from_form()
    if link:
        for key, value in fields.items():
            setattr(link, key, value)
    else:
        link = ContactCharacterLink(character_id=personaje.id, contact_id=contact.id, **fields)
        db.session.add(link)
    db.session.commit()
    flash('Vínculo actualizado.', 'success')
    return redirect(url_for('contacts.detail', contact_id=contact_id, personaje_id=personaje.id))


@contacts_bp.route('/<int:contact_id>/vinculo/eliminar', methods=['POST'])
@login_required
def link_delete(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    characters = _selectable_characters()
    personaje_id = request.form.get('personaje_id', type=int)
    personaje = next((c for c in characters if c.id == personaje_id), None)
    if not personaje or not _can_view(contact):
        abort(403)
    link = ContactCharacterLink.query.filter_by(character_id=personaje.id, contact_id=contact_id).first_or_404()
    db.session.delete(link)
    db.session.commit()
    flash('Vínculo eliminado.', 'success')
    return redirect(url_for('contacts.detail', contact_id=contact_id, personaje_id=personaje.id))


# ── Notas (por personaje) ───────────────────────────────────────────────────

def _note_owner_character(note):
    characters = _selectable_characters()
    return next((c for c in characters if c.id == note.character_id), None)


@contacts_bp.route('/<int:contact_id>/notas', methods=['POST'])
@login_required
def note_create(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    characters = _selectable_characters()
    personaje_id = request.form.get('personaje_id', type=int)
    personaje = next((c for c in characters if c.id == personaje_id), None)
    if not personaje or not _can_view(contact):
        abort(403)
    content = request.form.get('content', '').strip()
    if not content:
        flash('La nota no puede estar vacía.', 'warning')
        return _safe_redirect('contacts.detail', contact_id=contact_id, personaje_id=personaje.id)
    db.session.add(ContactNote(contact_id=contact_id, character_id=personaje.id, content=content))
    db.session.commit()
    flash('Nota añadida.', 'success')
    return _safe_redirect('contacts.detail', contact_id=contact_id, personaje_id=personaje.id)


@contacts_bp.route('/<int:contact_id>/notas/<int:note_id>/editar', methods=['POST'])
@login_required
def note_edit(contact_id, note_id):
    note = ContactNote.query.get_or_404(note_id)
    if note.contact_id != contact_id:
        abort(404)
    if not current_user.is_admin and not _note_owner_character(note):
        abort(403)
    content = request.form.get('content', '').strip()
    if not content:
        flash('La nota no puede estar vacía.', 'warning')
        return redirect(url_for('contacts.detail', contact_id=contact_id, personaje_id=note.character_id))
    note.content = content
    db.session.commit()
    flash('Nota actualizada.', 'success')
    return redirect(url_for('contacts.detail', contact_id=contact_id, personaje_id=note.character_id))


@contacts_bp.route('/<int:contact_id>/notas/<int:note_id>/eliminar', methods=['POST'])
@login_required
def note_delete(contact_id, note_id):
    note = ContactNote.query.get_or_404(note_id)
    if note.contact_id != contact_id:
        abort(404)
    if not current_user.is_admin and not _note_owner_character(note):
        abort(403)
    personaje_id = note.character_id
    db.session.delete(note)
    db.session.commit()
    flash('Nota eliminada.', 'success')
    return redirect(url_for('contacts.detail', contact_id=contact_id, personaje_id=personaje_id))


# ── Edición de datos globales (admin) ───────────────────────────────────────

@contacts_bp.route('/<int:contact_id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def edit(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    professions = Profession.query.order_by(Profession.name).all()
    form_context = {**_grado_form_context(), **_professions_picker_context(professions)}

    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        if not nombre:
            flash('El contacto necesita un nombre.', 'danger')
            return render_template('contacts/edit.html', contact=contact, **form_context)

        _global_fields_from_form(contact)
        _save_image_from_form(contact)
        contact.is_visible = request.form.get('is_visible') == 'on'

        ContactProfession.query.filter_by(contact_id=contact.id).delete()
        db.session.flush()
        _rebuild_contact_professions(contact.id)

        db.session.commit()
        flash(f'Contacto «{contact.nombre}» actualizado.', 'success')
        return redirect(url_for('contacts.detail', contact_id=contact.id))

    return render_template('contacts/edit.html', contact=contact, **form_context)

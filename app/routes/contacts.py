from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from flask_login import login_required, current_user
from app.extensions import db
from app.models.character import Character
from app.models.profession import Profession
from app.models.contact import Contact, ContactProfession
from app.models.contact_character_link import ContactCharacterLink, ContactApodo, ContactCharacterSalary
from app.models.contact_note import ContactNote
from app.services import salary_service

contacts_bp = Blueprint('contacts', __name__, template_folder='../templates')


def _own_characters():
    return Character.query.filter_by(user_id=current_user.id).order_by(Character.name).all()


def _selectable_characters():
    """Characters the current user is allowed to act as when viewing/editing
    a contact's per-character data: admins can pick anyone, everyone else
    only their own."""
    if current_user.is_admin:
        return Character.query.order_by(Character.name).all()
    return _own_characters()


def _active_character():
    """The character whose view of Contacts is currently active - explicit
    ?personaje_id=, defaulting to the user's first character."""
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
    return characters[0]


@contacts_bp.route('/')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('q', '').strip()
    per_page = 25

    query = Contact.query.order_by(Contact.nombre)
    if not current_user.is_admin:
        query = query.filter_by(is_visible=True)
    if search:
        query = query.filter(Contact.nombre.ilike(f'%{search}%'))

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    active_character = _active_character()
    link_by_contact = {}
    if active_character:
        contact_ids = [c.id for c in pagination.items]
        if contact_ids:
            links = ContactCharacterLink.query.filter(
                ContactCharacterLink.character_id == active_character.id,
                ContactCharacterLink.contact_id.in_(contact_ids),
            ).all()
            link_by_contact = {l.contact_id: l for l in links}

    return render_template(
        'contacts/index.html',
        contacts=pagination.items,
        pagination=pagination,
        search=search,
        my_characters=_selectable_characters(),
        active_character=active_character,
        link_by_contact=link_by_contact,
    )


@contacts_bp.route('/nuevo', methods=['GET', 'POST'])
@login_required
def new():
    characters = _selectable_characters()
    professions = Profession.query.order_by(Profession.name).all()
    if not characters:
        flash('Necesitas al menos un personaje antes de poder registrar contactos.', 'warning')
        return redirect(url_for('characters.list_characters'))

    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        personaje_id = request.form.get('personaje_id', type=int)
        personaje = next((c for c in characters if c.id == personaje_id), None)
        if not nombre:
            flash('El contacto necesita un nombre.', 'danger')
            return render_template('contacts/new.html', characters=characters, professions=professions)
        if not personaje:
            flash('Selecciona el personaje que registra este contacto.', 'danger')
            return render_template('contacts/new.html', characters=characters, professions=professions)

        contact = Contact(
            nombre=nombre,
            es_untersuchung=request.form.get('es_untersuchung') == 'on',
            created_by_id=current_user.id,
        )
        db.session.add(contact)
        db.session.flush()

        for prof_id in request.form.getlist('profession_ids'):
            if prof_id:
                db.session.add(ContactProfession(contact_id=contact.id, profession_id=int(prof_id)))

        link = ContactCharacterLink(
            character_id=personaje.id,
            contact_id=contact.id,
            **_link_fields_from_form(),
        )
        db.session.add(link)
        db.session.flush()
        _save_apodos_from_form(link)

        db.session.commit()
        flash(f'Contacto «{contact.nombre}» creado.', 'success')
        return redirect(url_for('contacts.detail', contact_id=contact.id))

    return render_template('contacts/new.html', characters=characters, professions=professions)


def _link_fields_from_form():
    nivel = request.form.get('nivel', type=int)
    if nivel is not None:
        nivel = max(-5, min(5, nivel))
    return {
        'nivel': nivel,
        'organizacion_secta': request.form.get('organizacion_secta', '').strip() or None,
        'lugar_residencia': request.form.get('lugar_residencia', '').strip() or None,
        'lugar_contacto': request.form.get('lugar_contacto', '').strip() or None,
        'creacion': request.form.get('creacion') == 'on',
        'gm': request.form.get('gm', '').strip() or None,
        'mision': request.form.get('mision', '').strip() or None,
    }


def _save_apodos_from_form(link):
    ContactApodo.query.filter_by(link_id=link.id).delete()
    for texto in request.form.getlist('apodos'):
        texto = texto.strip()
        if texto:
            db.session.add(ContactApodo(link_id=link.id, texto=texto))


@contacts_bp.route('/<int:contact_id>')
@login_required
def detail(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    if not current_user.is_admin and not contact.is_visible:
        return redirect(url_for('contacts.index'))

    characters = _selectable_characters()
    active_character = _active_character()
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

    return render_template(
        'contacts/detail.html',
        contact=contact,
        characters=characters,
        active_character=active_character,
        my_link=my_link,
        notes=notes,
        salary_table=salary_service.get_salary_table(),
    )


# ── Vínculo personaje-contacto ──────────────────────────────────────────────

@contacts_bp.route('/<int:contact_id>/vinculo', methods=['POST'])
@login_required
def link_save(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    characters = _selectable_characters()
    personaje_id = request.form.get('personaje_id', type=int)
    personaje = next((c for c in characters if c.id == personaje_id), None)
    if not personaje:
        abort(403)

    link = ContactCharacterLink.query.filter_by(character_id=personaje.id, contact_id=contact.id).first()
    fields = _link_fields_from_form()
    if link:
        for key, value in fields.items():
            setattr(link, key, value)
    else:
        link = ContactCharacterLink(character_id=personaje.id, contact_id=contact.id, **fields)
        db.session.add(link)
    db.session.flush()
    _save_apodos_from_form(link)
    db.session.commit()
    flash('Vínculo actualizado.', 'success')
    return redirect(url_for('contacts.detail', contact_id=contact_id, personaje_id=personaje.id))


@contacts_bp.route('/<int:contact_id>/vinculo/eliminar', methods=['POST'])
@login_required
def link_delete(contact_id):
    characters = _selectable_characters()
    personaje_id = request.form.get('personaje_id', type=int)
    personaje = next((c for c in characters if c.id == personaje_id), None)
    if not personaje:
        abort(403)
    link = ContactCharacterLink.query.filter_by(character_id=personaje.id, contact_id=contact_id).first_or_404()
    db.session.delete(link)
    db.session.commit()
    flash('Vínculo eliminado.', 'success')
    return redirect(url_for('contacts.detail', contact_id=contact_id, personaje_id=personaje.id))


@contacts_bp.route('/<int:contact_id>/salario', methods=['POST'])
@login_required
def salary_save(contact_id):
    characters = _selectable_characters()
    personaje_id = request.form.get('personaje_id', type=int)
    personaje = next((c for c in characters if c.id == personaje_id), None)
    if not personaje:
        abort(403)
    link = ContactCharacterLink.query.filter_by(character_id=personaje.id, contact_id=contact_id).first_or_404()
    profession_id = request.form.get('profession_id', type=int)
    if not profession_id:
        abort(400)

    salary = ContactCharacterSalary.query.filter_by(link_id=link.id, profession_id=profession_id).first()
    tipo_sueldo = request.form.get('tipo_sueldo', '').strip() or None
    estado_habilidad = request.form.get('estado_habilidad', '').strip() or None
    if salary:
        salary.tipo_sueldo = tipo_sueldo
        salary.estado_habilidad = estado_habilidad
    else:
        salary = ContactCharacterSalary(
            link_id=link.id, profession_id=profession_id,
            tipo_sueldo=tipo_sueldo, estado_habilidad=estado_habilidad,
        )
        db.session.add(salary)
    db.session.commit()
    flash('Salario actualizado.', 'success')
    return redirect(url_for('contacts.detail', contact_id=contact_id, personaje_id=personaje.id))


# ── Notas (por personaje) ───────────────────────────────────────────────────

def _note_owner_character(note):
    characters = _selectable_characters()
    return next((c for c in characters if c.id == note.character_id), None)


@contacts_bp.route('/<int:contact_id>/notas', methods=['POST'])
@login_required
def note_create(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    if not current_user.is_admin and not contact.is_visible:
        abort(403)
    characters = _selectable_characters()
    personaje_id = request.form.get('personaje_id', type=int)
    personaje = next((c for c in characters if c.id == personaje_id), None)
    if not personaje:
        abort(403)
    content = request.form.get('content', '').strip()
    if not content:
        flash('La nota no puede estar vacía.', 'warning')
        return redirect(url_for('contacts.detail', contact_id=contact_id, personaje_id=personaje.id))
    db.session.add(ContactNote(contact_id=contact_id, character_id=personaje.id, content=content))
    db.session.commit()
    flash('Nota añadida.', 'success')
    return redirect(url_for('contacts.detail', contact_id=contact_id, personaje_id=personaje.id))


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

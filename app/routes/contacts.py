from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from flask_login import login_required, current_user
from app.extensions import db
from app.models.contact import Contact, ContactValue, FieldDefinition
from app.models.contact_persona import ContactPersona, ContactPersonaLink
from app.models.contact_note import ContactNote

contacts_bp = Blueprint('contacts', __name__, template_folder='../templates')


@contacts_bp.route('/')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('q', '').strip()
    per_page = 25

    if current_user.is_admin:
        fields = FieldDefinition.query.order_by(FieldDefinition.field_order).all()
        query = Contact.query.order_by(Contact.id.desc())
    else:
        fields = FieldDefinition.query.filter_by(is_visible=True).order_by(FieldDefinition.field_order).all()
        query = Contact.query.filter_by(is_visible=True).order_by(Contact.id.desc())

    if search and fields:
        matching_ids = (
            ContactValue.query
            .filter(ContactValue.value.ilike(f'%{search}%'))
            .with_entities(ContactValue.contact_id)
            .distinct()
        )
        query = query.filter(Contact.id.in_(matching_ids))

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return render_template('contacts/index.html',
                           contacts=pagination.items,
                           fields=fields,
                           pagination=pagination,
                           search=search)


@contacts_bp.route('/<int:contact_id>')
@login_required
def detail(contact_id):
    contact = Contact.query.get_or_404(contact_id)

    if not current_user.is_admin and not contact.is_visible:
        return redirect(url_for('contacts.index'))

    if current_user.is_admin:
        fields = FieldDefinition.query.order_by(FieldDefinition.field_order).all()
        persona_links = (
            ContactPersonaLink.query
            .filter_by(contact_id=contact_id)
            .join(ContactPersona)
            .order_by(ContactPersona.name)
            .all()
        )
        linked_ids = {pl.persona_id for pl in persona_links}
        available_personas = (
            ContactPersona.query
            .filter(ContactPersona.id.notin_(linked_ids))
            .order_by(ContactPersona.name)
            .all()
        )
        notes = (
            ContactNote.query
            .filter_by(contact_id=contact_id)
            .order_by(ContactNote.created_at.desc())
            .all()
        )
        my_personas = None
        my_persona_links = None
    else:
        fields = FieldDefinition.query.filter_by(is_visible=True).order_by(FieldDefinition.field_order).all()
        persona_links = None
        available_personas = None
        my_personas = (
            ContactPersona.query
            .filter_by(user_id=current_user.id, is_active=True)
            .order_by(ContactPersona.name)
            .all()
        )
        persona_ids = [p.id for p in my_personas]
        my_persona_links = {}
        if persona_ids:
            for pl in ContactPersonaLink.query.filter(
                ContactPersonaLink.persona_id.in_(persona_ids),
                ContactPersonaLink.contact_id == contact_id
            ).all():
                my_persona_links[pl.persona_id] = pl
        notes = (
            ContactNote.query
            .filter(
                ContactNote.contact_id == contact_id,
                db.or_(
                    ContactNote.is_global == True,
                    ContactNote.author_id == current_user.id
                )
            )
            .order_by(ContactNote.created_at.desc())
            .all()
        )

    return render_template('contacts/detail.html',
                           contact=contact,
                           fields=fields,
                           persona_links=persona_links,
                           available_personas=available_personas,
                           my_personas=my_personas,
                           my_persona_links=my_persona_links,
                           notes=notes)


# ── Persona-Contact (self-service) ─────────────────────────────────────────

@contacts_bp.route('/<int:contact_id>/persona/<int:persona_id>/relacion', methods=['POST'])
@login_required
def persona_relationship_save(contact_id, persona_id):
    contact = Contact.query.get_or_404(contact_id)
    if not current_user.is_admin and not contact.is_visible:
        abort(403)
    persona = ContactPersona.query.get_or_404(persona_id)
    if not current_user.is_admin and persona.user_id != current_user.id:
        abort(403)
    relationship_note = request.form.get('relationship', '').strip()
    link = ContactPersonaLink.query.filter_by(persona_id=persona_id, contact_id=contact_id).first()
    if link:
        link.relationship_note = relationship_note
    else:
        link = ContactPersonaLink(persona_id=persona_id, contact_id=contact_id,
                                   relationship_note=relationship_note)
        db.session.add(link)
    db.session.commit()
    flash('Relación actualizada.', 'success')
    return redirect(url_for('contacts.detail', contact_id=contact_id))


@contacts_bp.route('/<int:contact_id>/persona/<int:persona_id>/desvincular', methods=['POST'])
@login_required
def persona_unlink(contact_id, persona_id):
    persona = ContactPersona.query.get_or_404(persona_id)
    if not current_user.is_admin and persona.user_id != current_user.id:
        abort(403)
    link = ContactPersonaLink.query.filter_by(persona_id=persona_id, contact_id=contact_id).first_or_404()
    db.session.delete(link)
    db.session.commit()
    flash('Vínculo eliminado del contacto.', 'success')
    return redirect(url_for('contacts.detail', contact_id=contact_id))


# ── Notes ────────────────────────────────────────────────────────────────────

@contacts_bp.route('/<int:contact_id>/notas', methods=['POST'])
@login_required
def note_create(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    if not current_user.is_admin and not contact.is_visible:
        abort(403)
    content = request.form.get('content', '').strip()
    if not content:
        flash('La nota no puede estar vacía.', 'warning')
        return redirect(url_for('contacts.detail', contact_id=contact_id))
    note = ContactNote(
        contact_id=contact_id,
        author_id=current_user.id,
        content=content,
        is_global=request.form.get('is_global') == 'on'
    )
    db.session.add(note)
    db.session.commit()
    flash('Nota añadida.', 'success')
    return redirect(url_for('contacts.detail', contact_id=contact_id))


@contacts_bp.route('/<int:contact_id>/notas/<int:note_id>/editar', methods=['POST'])
@login_required
def note_edit(contact_id, note_id):
    note = ContactNote.query.get_or_404(note_id)
    if note.contact_id != contact_id:
        abort(404)
    if not current_user.is_admin and note.author_id != current_user.id:
        abort(403)
    content = request.form.get('content', '').strip()
    if not content:
        flash('La nota no puede estar vacía.', 'warning')
        return redirect(url_for('contacts.detail', contact_id=contact_id))
    note.content = content
    note.is_global = request.form.get('is_global') == 'on'
    db.session.commit()
    flash('Nota actualizada.', 'success')
    return redirect(url_for('contacts.detail', contact_id=contact_id))


@contacts_bp.route('/<int:contact_id>/notas/<int:note_id>/eliminar', methods=['POST'])
@login_required
def note_delete(contact_id, note_id):
    note = ContactNote.query.get_or_404(note_id)
    if note.contact_id != contact_id:
        abort(404)
    if not current_user.is_admin and note.author_id != current_user.id:
        abort(403)
    db.session.delete(note)
    db.session.commit()
    flash('Nota eliminada.', 'success')
    return redirect(url_for('contacts.detail', contact_id=contact_id))

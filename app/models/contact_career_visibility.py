from app.extensions import db


class ContactCareerVisibility(db.Model):
    """Admin-granted exception: lets a specific Character see a specific
    Contact's "Carrera Profesional" (Profesiones) even though that section
    is admin-only by default - see Contact detail view and
    Character.puede_ver_carreras_contactos for the global version of this
    same grant. Managed from the Character's own edit form, admin-only
    (app/routes/characters.py).

    This narrowly revives the shape of the old ContactCharacterVisibility
    grant (a per-character/per-contact table, removed 2026-07-16 in favor of
    a single admin-controlled Contact.is_visible kill-switch, deemed too
    complex for whole-contact visibility) but scoped to just the career
    section, not the contact as a whole - the director asked for this
    exact kind of granularity again on 2026-07-19, deliberately narrower
    than what was removed before.
    """
    __tablename__ = 'contact_career_visibilities'

    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey('characters.id', ondelete='CASCADE'), nullable=False)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id', ondelete='CASCADE'), nullable=False)

    character = db.relationship('Character', backref=db.backref('career_visibility_grants', passive_deletes=True))
    contact = db.relationship('Contact')

    __table_args__ = (
        db.UniqueConstraint('character_id', 'contact_id', name='uq_character_contact_career_visibility'),
    )

    def __repr__(self):
        return f'<ContactCareerVisibility character={self.character_id} contact={self.contact_id}>'

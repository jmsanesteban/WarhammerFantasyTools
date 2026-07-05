from datetime import datetime
from app.extensions import db


class ContactPersona(db.Model):
    """A user-owned persona/actor used to track relationships with contacts.

    Unrelated to app.models.character.Character (a WFRP tabletop player
    character) — kept as a separate model/table to avoid name collision.
    """
    __tablename__ = 'contact_personas'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship('User', backref=db.backref('contact_personas', lazy='dynamic'))
    persona_links = db.relationship('ContactPersonaLink', backref='persona',
                                     cascade='all, delete-orphan', lazy='dynamic')

    def __repr__(self):
        return f'<ContactPersona {self.name}>'


class ContactPersonaLink(db.Model):
    __tablename__ = 'contact_persona_links'

    id = db.Column(db.Integer, primary_key=True)
    persona_id = db.Column(db.Integer, db.ForeignKey('contact_personas.id', ondelete='CASCADE'), nullable=False)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id', ondelete='CASCADE'), nullable=False)
    relationship_note = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('persona_id', 'contact_id', name='uq_persona_contact'),
    )

    contact = db.relationship('Contact', backref=db.backref('persona_links', passive_deletes=True))

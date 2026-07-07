from datetime import datetime
from app.extensions import db


class ContactNote(db.Model):
    """A note about a contact, private to the character that wrote it - a
    note from character A never shows up for character B, even if both
    belong to the same user. Admins see all notes regardless."""
    __tablename__ = 'contact_notes'

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id', ondelete='CASCADE'), nullable=False)
    character_id = db.Column(db.Integer, db.ForeignKey('characters.id', ondelete='CASCADE'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    character = db.relationship('Character', backref=db.backref('contact_notes', passive_deletes=True))
    contact = db.relationship('Contact', backref=db.backref('notes', passive_deletes=True))

from datetime import datetime
from app.extensions import db


class FieldDefinition(db.Model):
    __tablename__ = 'field_definitions'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), unique=True, nullable=False)
    display_name = db.Column(db.String(128), nullable=False)
    is_visible = db.Column(db.Boolean, default=True, nullable=False)
    field_order = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    values = db.relationship('ContactValue', backref='field', lazy='dynamic',
                              cascade='all, delete-orphan')

    def __repr__(self):
        return f'<FieldDefinition {self.name}>'


class Contact(db.Model):
    __tablename__ = 'contacts'

    id = db.Column(db.Integer, primary_key=True)
    is_visible = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    created_by = db.relationship('User', backref='imported_contacts')
    values = db.relationship('ContactValue', backref='contact', lazy='joined',
                              cascade='all, delete-orphan')

    def get_value(self, field_id):
        for v in self.values:
            if v.field_id == field_id:
                return v.value
        return ''

    def get_display_name(self, fields):
        """Returns a short display label for the contact using the first two visible fields."""
        parts = []
        for f in fields[:2]:
            val = self.get_value(f.id)
            if val:
                parts.append(val)
        return ' '.join(parts) if parts else f'Contacto #{self.id}'

    def __repr__(self):
        return f'<Contact {self.id}>'


class ContactValue(db.Model):
    __tablename__ = 'contact_values'

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id'), nullable=False, index=True)
    field_id = db.Column(db.Integer, db.ForeignKey('field_definitions.id'), nullable=False, index=True)
    value = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('contact_id', 'field_id', name='uq_contact_field'),
    )

    def __repr__(self):
        return f'<ContactValue contact={self.contact_id} field={self.field_id}>'

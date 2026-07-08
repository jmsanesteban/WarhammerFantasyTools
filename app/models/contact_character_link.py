from datetime import datetime
from app.extensions import db


class ContactCharacterLink(db.Model):
    """A character's own view of a contact - nickname(s), relationship level,
    org/sect (unless Untersuchung, which is a global Contact fact), where they
    live/can be found, whether the link came from character creation, which
    GM/mission it was met through. Never visible to another character."""
    __tablename__ = 'contact_character_links'

    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey('characters.id', ondelete='CASCADE'), nullable=False)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id', ondelete='CASCADE'), nullable=False)
    nivel = db.Column(db.Integer, nullable=True)  # -5..5
    organizacion_secta = db.Column(db.String(150), nullable=True)
    lugar_residencia = db.Column(db.Text, nullable=True)
    lugar_contacto = db.Column(db.Text, nullable=True)
    creacion = db.Column(db.Boolean, default=False, nullable=False)
    gm = db.Column(db.String(100), nullable=True)
    mision = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    character = db.relationship('Character', backref=db.backref('contact_links', passive_deletes=True))
    contact = db.relationship('Contact', backref=db.backref('character_links', passive_deletes=True))
    apodos = db.relationship('ContactApodo', backref='link', lazy='joined', cascade='all, delete-orphan')
    salarios = db.relationship('ContactCharacterSalary', backref='link', lazy='joined', cascade='all, delete-orphan')

    __table_args__ = (
        db.UniqueConstraint('character_id', 'contact_id', name='uq_character_contact'),
    )

    def __repr__(self):
        return f'<ContactCharacterLink character={self.character_id} contact={self.contact_id}>'


class ContactApodo(db.Model):
    """A nickname this character knows the contact by. Multiple allowed;
    visibility to other characters simply doesn't exist since it's owned by
    the link, not the contact."""
    __tablename__ = 'contact_apodos'

    id = db.Column(db.Integer, primary_key=True)
    link_id = db.Column(db.Integer, db.ForeignKey('contact_character_links.id', ondelete='CASCADE'), nullable=False)
    texto = db.Column(db.String(100), nullable=False)


class ContactCharacterVisibility(db.Model):
    """Grants a character permission to see a contact at all. Absence of a
    row means the character can't see the contact, regardless of
    Contact.is_visible (which is a separate, coarser admin kill-switch that
    hides a contact from every non-admin regardless of grants).

    'total' shows every global field on the contact; 'parcial' hides some
    (currently: profesiones) - see contacts.py's _visibility_level()."""
    __tablename__ = 'contact_character_visibilities'

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id', ondelete='CASCADE'), nullable=False)
    character_id = db.Column(db.Integer, db.ForeignKey('characters.id', ondelete='CASCADE'), nullable=False)
    nivel = db.Column(db.String(10), nullable=False, default='total')  # 'total' | 'parcial'

    character = db.relationship('Character', backref=db.backref('contact_visibilities', passive_deletes=True))
    contact = db.relationship('Contact', backref=db.backref('character_visibilities', passive_deletes=True))

    __table_args__ = (
        db.UniqueConstraint('contact_id', 'character_id', name='uq_contact_character_visibility'),
    )


class ContactCharacterSalary(db.Model):
    """This character's recorded salary tier for one of the contact's
    professions (picked manually from the reference salary table, not
    computed from any actual skill percentage)."""
    __tablename__ = 'contact_character_salaries'

    id = db.Column(db.Integer, primary_key=True)
    link_id = db.Column(db.Integer, db.ForeignKey('contact_character_links.id', ondelete='CASCADE'), nullable=False)
    profession_id = db.Column(db.Integer, db.ForeignKey('professions.id', ondelete='CASCADE'), nullable=False)
    tipo_sueldo = db.Column(db.String(30), nullable=True)
    estado_habilidad = db.Column(db.String(20), nullable=True)

    profession = db.relationship('Profession', lazy='joined')

    __table_args__ = (
        db.UniqueConstraint('link_id', 'profession_id', name='uq_link_profession_salary'),
    )

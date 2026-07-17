from datetime import datetime
from app.extensions import db

# Nivel de relación (-5..5), con nombres descriptivos (2026-07-16 rework).
NIVEL_LABELS = {
    -5: 'Enemigo mortal', -4: 'Enemigo hostil', -3: 'Rival profesional', -2: 'Antipatía',
    -1: 'Desconfianza', 0: 'Conocido', 1: 'Cercano', 2: 'Amigo', 3: 'Amigo profesional',
    4: 'Amigo hermanado', 5: 'Amigo incondicional',
}
# Cómo se relaciona ESTE personaje con el contacto - independiente del grado
# global de la Untersuchung del contacto (eso es un hecho objetivo sobre el
# NPC; esto es la relación concreta de un personaje con él). Sustituye a los
# antiguos grados "sin marca" (Bazas/Contactos) para ese caso concreto.
TIPO_RELACION_CHOICES = ['Baza', 'Unter/Untersuchung', 'Súbdito', 'Señor', 'Otra']


class ContactCharacterLink(db.Model):
    """A character's own view of a contact - nickname(s), relationship level
    and type, org/sect (unless Untersuchung, which is a global Contact fact),
    whether the link came from character creation, which GM/mission it was
    met through. Never visible to another character."""
    __tablename__ = 'contact_character_links'

    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey('characters.id', ondelete='CASCADE'), nullable=False)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id', ondelete='CASCADE'), nullable=False)
    nivel = db.Column(db.Integer, nullable=True)  # -5..5, ver NIVEL_LABELS
    tipo_relacion = db.Column(db.JSON, nullable=True)  # lista de TIPO_RELACION_CHOICES
    organizacion_secta = db.Column(db.String(150), nullable=True)
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

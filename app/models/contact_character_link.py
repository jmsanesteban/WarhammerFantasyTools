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
    """A character's own view of a contact - relationship level and type.
    Never visible to another character."""
    __tablename__ = 'contact_character_links'

    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey('characters.id', ondelete='CASCADE'), nullable=False)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id', ondelete='CASCADE'), nullable=False)
    nivel = db.Column(db.Integer, nullable=True)  # -5..5, ver NIVEL_LABELS
    tipo_relacion = db.Column(db.JSON, nullable=True)  # lista de TIPO_RELACION_CHOICES
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    character = db.relationship('Character', backref=db.backref('contact_links', passive_deletes=True))
    contact = db.relationship('Contact', backref=db.backref('character_links', passive_deletes=True))

    __table_args__ = (
        db.UniqueConstraint('character_id', 'contact_id', name='uq_character_contact'),
    )

    def __repr__(self):
        return f'<ContactCharacterLink character={self.character_id} contact={self.contact_id}>'

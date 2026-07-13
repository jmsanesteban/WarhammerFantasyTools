from datetime import datetime
from app.extensions import db

# Grados fijos de la Untersuchung (documento "untersuchung.pdf"): los primeros
# 8 son agentes "con marca" (miembros reales de la organización); Bazas y
# Contactos son "sin marca" - no pertenecen a la Untersuchung pero trabajan
# para ella. Un contacto puede tener varios grados a la vez ("grados mixtos",
# p.ej. Paloma/Gato), de ahí que se guarde como lista, no como valor único.
UNTERSUCHUNG_GRADOS = [
    'Escudo', 'Estilete', 'Gato', 'Brújula', 'Pluma', 'Corona', 'Carro', 'Paloma',
    'Bazas', 'Contactos',
]

# Dos preguntas distintas sobre la situación de un contacto (2026-07-14, tras
# discutirlo con el usuario): "estado" es si sigue con vida o no; "paradero"
# es dónde está, que solo tiene sentido preguntarlo si sigue vivo (un
# personaje puede estar Vivo pero Desaparecido - no son lo mismo que "muerto"
# ni que "paradero desconocido" sin más). "Asesinado" quedó fuera a propósito:
# es la causa de "Muerto", no un estado distinto - se anota en las notas del
# contacto si importa para una trama de venganza.
ESTADO_CHOICES = ['vivo', 'muerto', 'corrompido']
ESTADO_LABELS = {'vivo': 'Vivo', 'muerto': 'Muerto', 'corrompido': 'Corrompido'}
PARADERO_CHOICES = ['encarcelado', 'exiliado', 'secuestrado', 'desaparecido', 'paradero_desconocido']
PARADERO_LABELS = {
    'encarcelado': 'Encarcelado', 'exiliado': 'Exiliado', 'secuestrado': 'Secuestrado',
    'desaparecido': 'Desaparecido', 'paradero_desconocido': 'Paradero desconocido',
}


class Contact(db.Model):
    """An NPC/contact — global facts shared by every character who knows them.
    Per-character facts (nickname, relationship level, notes...) live on
    ContactCharacterLink instead, so one character's view never leaks to another's.
    """
    __tablename__ = 'contacts'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    es_untersuchung = db.Column(db.Boolean, default=False, nullable=False)
    estado = db.Column(db.String(20), nullable=False, default='vivo')
    paradero = db.Column(db.String(30), nullable=True)  # solo relevante si estado == 'vivo'
    grados_untersuchung = db.Column(db.JSON, nullable=True)  # lista de UNTERSUCHUNG_GRADOS; solo aplica si es_untersuchung
    image_path = db.Column(db.String(300), nullable=True)
    is_visible = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    created_by = db.relationship('User', backref='imported_contacts')
    professions = db.relationship('ContactProfession', backref='contact', lazy='joined',
                                   cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Contact {self.nombre}>'


class ContactProfession(db.Model):
    """Which of the existing Profession catalog entries this contact has."""
    __tablename__ = 'contact_professions'

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id', ondelete='CASCADE'), nullable=False)
    profession_id = db.Column(db.Integer, db.ForeignKey('professions.id', ondelete='CASCADE'), nullable=False)

    profession = db.relationship('Profession', lazy='joined')

    __table_args__ = (
        db.UniqueConstraint('contact_id', 'profession_id', name='uq_contact_profession'),
    )

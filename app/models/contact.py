from datetime import datetime
from app.extensions import db
from app.models.untersuchung import UNTERSUCHUNG_GRADOS  # noqa: F401 (re-exported for existing importers)

# Simplificado a un único campo de 3 valores (2026-07-16 rework, sustituye al
# antiguo par estado+paradero) - "corrompido" y los distintos paraderos
# (encarcelado/exiliado/secuestrado/desaparecido/paradero_desconocido) se
# consideraron demasiado granulares para el uso real; cualquier matiz que se
# pierda se anota como texto libre en las notas del contacto si hace falta.
ESTADO_CHOICES = ['vivo', 'muerto', 'desconocido']
ESTADO_LABELS = {'vivo': 'Vivo', 'muerto': 'Muerto', 'desconocido': 'Desconocido'}

# Lista guiada para el desplegable de Raza (2026-07-17) - raza sigue siendo
# texto libre en BD; esta lista solo orienta el formulario. "Nuevo" no es un
# valor real, es un centinela de UI que revela un campo de texto libre.
RAZA_CHOICES = [
    'Humano', 'Enano', 'Alto elfo', 'Elfo Silvano', 'Halfling', 'Ogro', 'Hombre bestia',
    'Piel verde', 'No muerto', 'Slam', 'Criatura', 'Monstruo', 'Demonio',
]


class Contact(db.Model):
    """An NPC/contact — global facts shared by every character who knows them.
    Per-character facts (nickname, relationship level, notes...) live on
    ContactCharacterLink instead, so one character's view never leaks to another's.
    """
    __tablename__ = 'contacts'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    raza = db.Column(db.String(100), nullable=True)
    es_untersuchung = db.Column(db.Boolean, default=False, nullable=False)
    estado = db.Column(db.String(20), nullable=False, default='vivo')
    grados_untersuchung = db.Column(db.JSON, nullable=True)  # lista de UNTERSUCHUNG_GRADOS (ver app/models/untersuchung.py)
    # Hechos globales del contacto (2026-07-16 rework) - antes vivían por
    # personaje en ContactCharacterLink (lugar_residencia/lugar_contacto);
    # dónde vive/trabaja/se relaja un NPC no depende de quién pregunta.
    lugar_descanso = db.Column(db.Text, nullable=True)
    lugar_trabajo = db.Column(db.Text, nullable=True)
    lugar_ocio = db.Column(db.Text, nullable=True)
    # Solo visible/editable por el director de juego (admin) - distinta de
    # ContactNote, que es privada POR PERSONAJE; esto es una única nota
    # global del director sobre el contacto.
    notas_director = db.Column(db.Text, nullable=True)
    # Notas visibles para cualquiera que pueda ver el contacto (a diferencia de
    # notas_director, que es solo para admin, y ContactNote, que es privada
    # por personaje).
    notas_generales = db.Column(db.Text, nullable=True)
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
    """Which of the existing Profession catalog entries this contact has, with
    its objective salary tier (tipo_sueldo/estado_habilidad, same reference
    table as Personajes - see salary_service - but set directly by the
    director as a fact about the NPC, not a per-character guess)."""
    __tablename__ = 'contact_professions'

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id', ondelete='CASCADE'), nullable=False)
    profession_id = db.Column(db.Integer, db.ForeignKey('professions.id', ondelete='CASCADE'), nullable=False)
    tipo_sueldo = db.Column(db.String(30), nullable=True)
    estado_habilidad = db.Column(db.String(20), nullable=True)

    profession = db.relationship('Profession', lazy='joined')

    __table_args__ = (
        db.UniqueConstraint('contact_id', 'profession_id', name='uq_contact_profession'),
    )

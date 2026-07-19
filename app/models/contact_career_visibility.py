from datetime import datetime
from app.extensions import db

# Dos niveles: 'ver' (solo lectura de la sección Profesiones en la ficha del
# contacto) y 'editar' (además puede añadir/quitar profesiones de ese
# contacto, la misma acción que ya podía hacer un admin - ver
# contacts.career_save). 'editar' implica 'ver'. Compartido por
# Character.carreras_contactos_nivel (concesión global) y
# ContactCareerVisibility.nivel (concesión por contacto concreto).
CARRERA_NIVELES = ['ver', 'editar']
CARRERA_NIVEL_LABELS = {'ver': 'Ver', 'editar': 'Ver y editar'}
_CARRERA_NIVEL_RANK = {None: 0, 'ver': 1, 'editar': 2}


def nivel_permite(nivel, minimo):
    """True si `nivel` (None/'ver'/'editar') alcanza al menos `minimo`
    ('ver' o 'editar') en el orden ninguno < ver < editar."""
    return _CARRERA_NIVEL_RANK.get(nivel, 0) >= _CARRERA_NIVEL_RANK[minimo]


def nivel_mas_alto(*niveles):
    """El más permisivo de varios niveles (None/'ver'/'editar')."""
    return max(niveles, key=lambda n: _CARRERA_NIVEL_RANK.get(n, 0))


class ContactCareerVisibility(db.Model):
    """Admin-granted exception: lets a specific Character see (and,
    depending on `nivel`, edit) a specific Contact's "Carrera Profesional"
    (Profesiones) even though that section is admin-only by default - see
    Contact detail view and Character.carreras_contactos_nivel for the
    global version of this same grant. Managed from the Character's own
    edit form, admin-only (app/routes/characters.py).

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
    nivel = db.Column(db.String(10), nullable=False, default='ver')  # 'ver' | 'editar', ver CARRERA_NIVELES

    character = db.relationship('Character', backref=db.backref('career_visibility_grants', passive_deletes=True))
    contact = db.relationship('Contact')

    __table_args__ = (
        db.UniqueConstraint('character_id', 'contact_id', name='uq_character_contact_career_visibility'),
    )

    def __repr__(self):
        return f'<ContactCareerVisibility character={self.character_id} contact={self.contact_id} nivel={self.nivel}>'


class CareerVisibilityDefault(db.Model):
    """Un único nivel por defecto (2026-07-19, "de forma global" a nivel de
    aplicación, no solo por personaje) - mismo patrón de fila única que
    ShopMarkup (app/models/shop.py): se espera una sola fila (o ninguna, lo
    que equivale a "ninguno"). Se aplica automáticamente a todo personaje
    NUEVO en el momento de crearse (ver characters.create) - los ya
    existentes no cambian solos; para eso está el botón "Aplicar a todos los
    personajes existentes ahora" en Admin, que hace un UPDATE puntual, no
    una vinculación permanente a este valor."""
    __tablename__ = 'career_visibility_default'

    id = db.Column(db.Integer, primary_key=True)
    nivel = db.Column(db.String(10), nullable=True)  # None | 'ver' | 'editar', ver CARRERA_NIVELES
    updated_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    updated_by = db.relationship('User')


def current_career_default():
    row = CareerVisibilityDefault.query.first()
    return row.nivel if row else None


def set_career_default(nivel, updated_by_id=None):
    row = CareerVisibilityDefault.query.first()
    if row is None:
        row = CareerVisibilityDefault()
        db.session.add(row)
    row.nivel = nivel
    row.updated_by_id = updated_by_id
    return row

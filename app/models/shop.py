from datetime import datetime
from app.extensions import db


class ShopMarkup(db.Model):
    """Un único recargo global (%) que un admin puede activar/desactivar -
    "por disponibilidad u otras razones". Se espera una sola fila (o
    ninguna, lo que equivale a 0%); current_markup_pct()/set_markup_pct()
    son el único punto de acceso, nunca se consulta la tabla directamente."""
    __tablename__ = 'shop_markup'

    id = db.Column(db.Integer, primary_key=True)
    pct = db.Column(db.Integer, nullable=False, default=0)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    updated_by = db.relationship('User')


def current_markup_pct():
    row = ShopMarkup.query.first()
    return row.pct if row else 0


def set_markup_pct(pct, updated_by_id=None):
    row = ShopMarkup.query.first()
    if row is None:
        row = ShopMarkup()
        db.session.add(row)
    row.pct = pct
    row.updated_by_id = updated_by_id
    return row


def apply_markup(peniques):
    """Aplica el recargo global al precio base en peniques, redondeando al
    entero más cercano. Nunca confía en un total calculado en el cliente -
    se recalcula aquí siempre en el momento de cobrar."""
    pct = current_markup_pct()
    if not pct:
        return peniques
    return round(peniques * (100 + pct) / 100)

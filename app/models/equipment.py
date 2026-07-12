import re
from datetime import datetime
from app.extensions import db
from app.services.currency_service import PENIQUES_POR_CORONA, PENIQUES_POR_CHELIN

# Reuses the same peniques-as-smallest-unit convention as currency_service
# (already used for Comida y bebida prices) instead of a second money scheme.
_PENIQUES_POR_UNIDAD = {'CO': PENIQUES_POR_CORONA, 'C': PENIQUES_POR_CHELIN, 'P': 1}
_PRICE_RE = re.compile(r'^(\d+(?:[.,]\d+)?)\s*(CO|C|P)$', re.IGNORECASE)
# Noble-tier ropa prices are printed as e.g. "36c (base * (Clase-2))": the
# leading amount is a per-unit base, and the real price scales with the
# BUYING character's nivel_social (Clase social), not a fixed catalog number.
_CLASE_SOCIAL_RE = re.compile(r'^(.*?)\s*\(\s*base\s*\*\s*\(\s*clase\s*-\s*2\s*\)\s*\)$', re.IGNORECASE)


def parse_price_text(text):
    """Best-effort parse of a book price string ("20 CO", "8c", "6p") into
    peniques. Returns None for anything that isn't a single clean amount+unit
    - dual prices ("50/75 CO"), unrecognized formulas, missing text, etc.
    Those need a manually-entered precio_peniques from an admin; "Gratis" is
    the one unambiguous non-numeric case, parsed as 0. The "(base *
    (Clase-2))" suffix is stripped before parsing (see is_clase_social_scaled)
    since the leading amount alone is still a clean numeric base price."""
    if not text:
        return None
    text = text.strip()
    if text.lower() in ('gratis', 'gratuito'):
        return 0
    clase_match = _CLASE_SOCIAL_RE.match(text)
    if clase_match:
        text = clase_match.group(1).strip()
    match = _PRICE_RE.match(text)
    if not match:
        return None
    amount = float(match.group(1).replace(',', '.'))
    peniques_por_unidad = _PENIQUES_POR_UNIDAD[match.group(2).upper()]
    return round(amount * peniques_por_unidad)


def is_clase_social_scaled(text):
    """True for prices like '36c (base * (Clase-2))' - the base amount is
    per unit of (Clase social - 2), not a fixed price by itself."""
    return bool(text) and bool(_CLASE_SOCIAL_RE.match(text.strip()))


class EquipmentItem(db.Model):
    """A catalog item: weapon, armour, clothing, or a special (magic) item
    built on top of one of those. Category-specific stats (damage, armour
    value, range, protection...) live in `stats` since the shape varies too
    much between categories for fixed columns; `custom_fields` is reserved
    for whatever an admin bolts on by hand, so new attributes never need a
    migration (e.g. weapon weight, still unreleased while the carry-weight
    rules are being balanced)."""
    __tablename__ = 'equipment_items'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, index=True)
    category = db.Column(db.String(20), nullable=False, index=True)  # arma | armadura | ropa | especial
    subcategory = db.Column(db.String(50), nullable=True, index=True)
    quality = db.Column(db.String(20), nullable=True, index=True)  # mala | normal | buena | excelente
    is_special = db.Column(db.Boolean, nullable=False, default=False)
    base_item_id = db.Column(db.Integer, db.ForeignKey('equipment_items.id', ondelete='SET NULL'), nullable=True)

    price_text = db.Column(db.String(100), nullable=True)
    precio_peniques = db.Column(db.Integer, nullable=True)  # normalized base price; None if price_text was irregular
    # True for Noble-tier ropa rows ("36c (base * (Clase-2))"): precio_peniques
    # is a per-unit base that must be multiplied by (buyer.nivel_social - 2)
    # at purchase time, not a fixed price on its own.
    precio_escala_clase_social = db.Column(db.Boolean, nullable=False, default=False)
    image_path = db.Column(db.String(300), nullable=True)
    description = db.Column(db.Text, nullable=True)
    stats = db.Column(db.JSON, nullable=True)
    custom_fields = db.Column(db.JSON, nullable=True)

    source_book = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='catalogado')  # catalogado | admin
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    base_item = db.relationship('EquipmentItem', remote_side=[id], backref='special_variants')
    created_by = db.relationship('User')

    CATEGORIES = ('arma', 'armadura', 'ropa', 'especial', 'libro', 'otros')
    QUALITIES = ('mala', 'normal', 'buena', 'excelente')
    # Book rule (Armaduras "Datos adicionales"): quality only scales price for
    # arma/armadura. Ropa's tiers are already separate catalog rows with their
    # own literal price; especial items are priced by the GM, not computed.
    QUALITY_PRICE_MULTIPLIER = {'mala': 0.5, 'normal': 1, 'buena': 3, 'excelente': 10}

    CATEGORY_LABELS = {
        'arma': 'Arma', 'armadura': 'Armadura', 'ropa': 'Ropa', 'especial': 'Especial',
        'libro': 'Libro', 'otros': 'Otros objetos',
    }
    QUALITY_LABELS = {'mala': 'Mala', 'normal': 'Normal', 'buena': 'Buena', 'excelente': 'Excelente'}
    # Clothing tiers are the same quality scale under the hood, but players
    # refer to them by their book names, not by "mala/buena/...".
    QUALITY_LABELS_ROPA = {'mala': 'Harapos', 'normal': 'Común', 'buena': 'Burguesa', 'excelente': 'Noble'}
    SUBCATEGORY_LABELS = {
        'cuerpo_a_cuerpo': 'Cuerpo a cuerpo',
        'distancia': 'A distancia',
        'municion': 'Munición',
        'acolchada': 'Acolchada / Gambesón',
        'cuero': 'Cuero',
        'pieles': 'Pieles gruesas',
        'cuero_endurecido': 'Cuero endurecido',
        'malla': 'Cota de malla',
        'escamas': 'Escamas / Lamelar',
        'placas': 'Placas',
        'escudos': 'Escudos',
        'ropa': 'Ropa',
        'ropa_ligera': 'Ropa ligera',
        'ropa_invernal': 'Ropa invernal',
        'ropa_veraniega': 'Ropa veraniega',
        'gorro': 'Gorro',
        'sombrero': 'Sombrero',
        'zapatos_botines': 'Zapatos/botines',
        'botas': 'Botas',
        'abrigo': 'Abrigo',
        'manto_capa': 'Manto/capa',
        'sobretodo': 'Sobretodo',
        'guantes': 'Guantes',
        'tahali': 'Tahalí',
        'adorno': 'Adorno',
        'sobrevesta': 'Sobrevesta',
    }

    @property
    def category_label(self):
        return self.CATEGORY_LABELS.get(self.category, self.category)

    @property
    def subcategory_label(self):
        if not self.subcategory:
            return None
        return self.SUBCATEGORY_LABELS.get(self.subcategory, self.subcategory.replace('_', ' ').capitalize())

    @property
    def quality_label(self):
        if not self.quality:
            return None
        labels = self.QUALITY_LABELS_ROPA if self.category == 'ropa' else self.QUALITY_LABELS
        return labels.get(self.quality, self.quality)

    def price_for_quality(self, quality=None, nivel_social=None):
        """Purchase price in peniques for a given quality, or None if it
        can't be computed: precio_peniques unset (irregular price_text needs
        a manual admin entry), category is 'especial' (the GM always sets
        that price by hand), or - for Noble ropa - nivel_social wasn't given
        or isn't high enough to afford a Noble tier at all (Clase-2 <= 0)."""
        if self.precio_peniques is None or self.category == 'especial':
            return None
        if self.precio_escala_clase_social:
            if nivel_social is None or nivel_social - 2 <= 0:
                return None
            return self.precio_peniques * (nivel_social - 2)
        if self.category == 'ropa':
            return self.precio_peniques  # each quality tier is already its own row
        multiplier = self.QUALITY_PRICE_MULTIPLIER.get(quality or self.quality, 1)
        return round(self.precio_peniques * multiplier)

    def __repr__(self):
        return f'<EquipmentItem {self.name} ({self.category})>'


class CharacterInventoryItem(db.Model):
    """One entry in a character's inventory, placed in one of the 5 storage
    locations. Created via the purchase/grant flow in app/routes/characters.py."""
    __tablename__ = 'character_inventory_items'

    LOCATIONS = ('equipamiento', 'mochila_saco', 'alforjas', 'base', 'altdorf')

    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey('characters.id', ondelete='CASCADE'), nullable=False)
    equipment_item_id = db.Column(db.Integer, db.ForeignKey('equipment_items.id', ondelete='SET NULL'), nullable=True)
    custom_name = db.Column(db.String(150), nullable=True)  # used when equipment_item_id is null
    quality = db.Column(db.String(20), nullable=True)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    location = db.Column(db.String(20), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    # Placeholder for the future wear/damage/repair phase (durability points,
    # quality degradation, per-location damage for multi-location armour) -
    # unused, always NULL for now. Reserved so that phase needs no migration.
    condition = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    character = db.relationship('Character', backref=db.backref('inventory_items', cascade='all, delete-orphan'))
    equipment_item = db.relationship('EquipmentItem')

    @property
    def quality_label(self):
        """Label for THIS instance's quality - not the same as
        equipment_item.quality_label, which reflects the catalog row's own
        (often unset) quality, not what was actually bought."""
        if not self.quality:
            return None
        is_ropa = self.equipment_item and self.equipment_item.category == 'ropa'
        labels = EquipmentItem.QUALITY_LABELS_ROPA if is_ropa else EquipmentItem.QUALITY_LABELS
        return labels.get(self.quality, self.quality)


class CharacterCartItem(db.Model):
    """A pending, not-yet-paid-for line in a character's shopping cart.
    Kept in its own table (not CharacterInventoryItem with a status flag) so
    abandoned carts never pollute real-inventory queries. Price is never
    stored here - always recomputed from EquipmentItem.price_for_quality at
    display and checkout time, since nivel_social (Clase social) can change
    between adding an item and checking out."""
    __tablename__ = 'character_cart_items'

    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey('characters.id', ondelete='CASCADE'), nullable=False)
    equipment_item_id = db.Column(db.Integer, db.ForeignKey('equipment_items.id', ondelete='CASCADE'), nullable=False)
    quality = db.Column(db.String(20), nullable=True)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    location = db.Column(db.String(20), nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    character = db.relationship('Character', backref=db.backref('cart_items', cascade='all, delete-orphan'))
    equipment_item = db.relationship('EquipmentItem')

    @property
    def unit_price(self):
        return self.equipment_item.price_for_quality(self.quality, nivel_social=self.character.nivel_social)

    @property
    def subtotal(self):
        price = self.unit_price
        return None if price is None else price * self.quantity


class CharacterPurchase(db.Model):
    """Immutable purchase-history ledger entry: created once when a character
    buys (or a GM grants) an equipment item, never edited or deleted
    afterwards - no edit/delete route exists for this model, by convention,
    same as every other historical record in this codebase. Snapshot fields
    freeze what was actually bought so the record stays meaningful even if
    the catalog row is later renamed, re-priced, or deleted."""
    __tablename__ = 'character_purchases'

    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey('characters.id', ondelete='CASCADE'), nullable=False)
    equipment_item_id = db.Column(db.Integer, db.ForeignKey('equipment_items.id', ondelete='SET NULL'), nullable=True)
    item_name_snapshot = db.Column(db.String(150), nullable=False)
    category_snapshot = db.Column(db.String(20), nullable=True)
    quality_snapshot = db.Column(db.String(20), nullable=True)
    precio_peniques_pagado = db.Column(db.Integer, nullable=False)
    granted_by_gm = db.Column(db.Boolean, nullable=False, default=False)
    granted_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    inventory_item_id = db.Column(db.Integer, db.ForeignKey('character_inventory_items.id', ondelete='SET NULL'), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    character = db.relationship('Character', backref=db.backref(
        'purchases', cascade='all, delete-orphan', order_by='CharacterPurchase.created_at.desc()'))
    equipment_item = db.relationship('EquipmentItem')
    granted_by = db.relationship('User')
    inventory_item = db.relationship('CharacterInventoryItem', backref='purchase_records')

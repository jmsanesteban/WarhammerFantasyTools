from datetime import datetime
from app.extensions import db


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

    CATEGORIES = ('arma', 'armadura', 'ropa', 'especial')
    QUALITIES = ('mala', 'normal', 'buena', 'excelente')

    CATEGORY_LABELS = {'arma': 'Arma', 'armadura': 'Armadura', 'ropa': 'Ropa', 'especial': 'Especial'}
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

    def __repr__(self):
        return f'<EquipmentItem {self.name} ({self.category})>'


class CharacterInventoryItem(db.Model):
    """One entry in a character's inventory, placed in one of the 5 storage
    locations. Not wired into any route/template yet - modeled now so the
    upcoming character-inventory UI doesn't need its own migration."""
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    character = db.relationship('Character', backref=db.backref('inventory_items', cascade='all, delete-orphan'))
    equipment_item = db.relationship('EquipmentItem')

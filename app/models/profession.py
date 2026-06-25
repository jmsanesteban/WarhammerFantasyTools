from datetime import datetime
from app.extensions import db

# Self-referential many-to-many: career exits (salidas)
# From profession A, you can exit to profession B
career_exits_table = db.Table(
    'career_exits',
    db.Column('source_id', db.Integer, db.ForeignKey('professions.id', ondelete='CASCADE'), primary_key=True),
    db.Column('target_id', db.Integer, db.ForeignKey('professions.id', ondelete='CASCADE'), primary_key=True),
)


class ProfessionSkill(db.Model):
    """Association between a profession and a skill, with optional OR-group."""
    __tablename__ = 'profession_skills'

    profession_id = db.Column(db.Integer, db.ForeignKey('professions.id', ondelete='CASCADE'), primary_key=True)
    skill_id = db.Column(db.Integer, db.ForeignKey('skills.id', ondelete='CASCADE'), primary_key=True)
    # Null = mandatory skill. Same integer = player picks one from the group.
    choice_group = db.Column(db.Integer, nullable=True)

    skill = db.relationship('Skill', lazy='joined')


class ProfessionTalent(db.Model):
    """Association between a profession and a talent, with optional OR-group."""
    __tablename__ = 'profession_talents'

    profession_id = db.Column(db.Integer, db.ForeignKey('professions.id', ondelete='CASCADE'), primary_key=True)
    talent_id = db.Column(db.Integer, db.ForeignKey('talents.id', ondelete='CASCADE'), primary_key=True)
    choice_group = db.Column(db.Integer, nullable=True)

    talent = db.relationship('Talent', lazy='joined')


class ProfessionTrapping(db.Model):
    """An item/trapping required to enter or practice a profession."""
    __tablename__ = 'profession_trappings'

    id = db.Column(db.Integer, primary_key=True)
    profession_id = db.Column(db.Integer, db.ForeignKey('professions.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(200), nullable=False)


class Profession(db.Model):
    __tablename__ = 'professions'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, index=True)
    name_en = db.Column(db.String(150), nullable=True)
    type = db.Column(db.String(20), nullable=False, default='basic')  # 'basic' or 'advanced'
    description = db.Column(db.Text, nullable=True)
    image_path = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    # --- Características Primarias (% improvements, multiples of 5) ---
    # HA  - Habilidad de Armas   (WS - Weapon Skill)
    ws = db.Column(db.Integer, nullable=True)
    # HP  - Habilidad de Proyectiles  (BS - Ballistic Skill)
    bs = db.Column(db.Integer, nullable=True)
    # F   - Fuerza                    (S  - Strength)
    s_char = db.Column(db.Integer, nullable=True)
    # R   - Resistencia               (T  - Toughness)
    t_char = db.Column(db.Integer, nullable=True)
    # Ag  - Agilidad                  (Ag - Agility)
    ag = db.Column(db.Integer, nullable=True)
    # I   - Inteligencia              (Int - Intelligence)
    int_char = db.Column(db.Integer, nullable=True)
    # V   - Voluntad                  (WP - Willpower)
    wp = db.Column(db.Integer, nullable=True)
    # Em  - Empatía                   (Fel - Fellowship)
    fel = db.Column(db.Integer, nullable=True)

    # --- Características Secundarias (unit improvements) ---
    # A   - Ataques                   (A  - Attacks)
    attacks = db.Column(db.Integer, nullable=True)
    # H   - Heridas                   (W  - Wounds)
    wounds = db.Column(db.Integer, nullable=True)
    # BF  - Bonus de Fuerza           (SB - Strength Bonus)
    strength_bonus = db.Column(db.Integer, nullable=True)
    # BR  - Bonus de Resistencia      (TB - Toughness Bonus)
    toughness_bonus = db.Column(db.Integer, nullable=True)
    # M   - Movimiento                (M  - Movement)
    movement = db.Column(db.Integer, nullable=True)
    # Mag - Magia                     (Mag - Magic)
    magic = db.Column(db.Integer, nullable=True)
    # PL  - Puntos de Locura          (IP - Insanity Points)
    insanity_points = db.Column(db.Integer, nullable=True)
    # PD  - Puntos de Destino         (FP - Fate Points)
    fate_points = db.Column(db.Integer, nullable=True)

    # --- Relationships ---
    profession_skills = db.relationship(
        'ProfessionSkill',
        backref='profession',
        lazy='subquery',
        cascade='all, delete-orphan',
    )
    profession_talents = db.relationship(
        'ProfessionTalent',
        backref='profession',
        lazy='subquery',
        cascade='all, delete-orphan',
    )
    trappings = db.relationship(
        'ProfessionTrapping',
        backref='profession',
        lazy='subquery',
        cascade='all, delete-orphan',
    )

    # Career exits (salidas): professions accessible after completing this one
    exits = db.relationship(
        'Profession',
        secondary=career_exits_table,
        primaryjoin=lambda: Profession.id == career_exits_table.c.source_id,
        secondaryjoin=lambda: Profession.id == career_exits_table.c.target_id,
        lazy='subquery',
    )
    # Career entries (accesos): professions from which you can enter this one
    entries = db.relationship(
        'Profession',
        secondary=career_exits_table,
        primaryjoin=lambda: Profession.id == career_exits_table.c.target_id,
        secondaryjoin=lambda: Profession.id == career_exits_table.c.source_id,
        lazy='subquery',
    )

    # --- Helpers ---
    PRIMARY_FIELDS = ('ws', 'bs', 's_char', 't_char', 'ag', 'int_char', 'wp', 'fel')
    PRIMARY_LABELS = {
        'ws': ('HA', 'WS', 'Habilidad de Armas'),
        'bs': ('HP', 'BS', 'Habilidad de Proyectiles'),
        's_char': ('F', 'S', 'Fuerza'),
        't_char': ('R', 'T', 'Resistencia'),
        'ag': ('Ag', 'Ag', 'Agilidad'),
        'int_char': ('I', 'Int', 'Inteligencia'),
        'wp': ('V', 'WP', 'Voluntad'),
        'fel': ('Em', 'Fel', 'Empatía'),
    }
    SECONDARY_FIELDS = (
        'attacks', 'wounds', 'strength_bonus', 'toughness_bonus',
        'movement', 'magic', 'insanity_points', 'fate_points',
    )
    SECONDARY_LABELS = {
        'attacks': ('A', 'A', 'Ataques'),
        'wounds': ('H', 'W', 'Heridas'),
        'strength_bonus': ('BF', 'SB', 'Bonus de Fuerza'),
        'toughness_bonus': ('BR', 'TB', 'Bonus de Resistencia'),
        'movement': ('M', 'M', 'Movimiento'),
        'magic': ('Mag', 'Mag', 'Magia'),
        'insanity_points': ('PL', 'IP', 'Puntos de Locura'),
        'fate_points': ('PD', 'FP', 'Puntos de Destino'),
    }

    def get_skills_by_group(self):
        """Return skills grouped: {None: [mandatory], 1: [opt_a, opt_b], ...}"""
        groups = {}
        for ps in self.profession_skills:
            key = ps.choice_group
            groups.setdefault(key, []).append(ps.skill)
        return groups

    def get_talents_by_group(self):
        """Return talents grouped: {None: [mandatory], 1: [opt_a, opt_b], ...}"""
        groups = {}
        for pt in self.profession_talents:
            key = pt.choice_group
            groups.setdefault(key, []).append(pt.talent)
        return groups

    def __repr__(self):
        return f'<Profession {self.name}>'

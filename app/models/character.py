from datetime import datetime
from app.extensions import db


class CharacterProfession(db.Model):
    """Ordered list of professions a character has taken."""
    __tablename__ = 'character_professions'

    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey('characters.id', ondelete='CASCADE'), nullable=False)
    profession_id = db.Column(db.Integer, db.ForeignKey('professions.id', ondelete='SET NULL'), nullable=True)
    order = db.Column(db.Integer, nullable=False, default=0)
    is_current = db.Column(db.Boolean, default=False)

    profession = db.relationship('Profession', lazy='joined')


class CharacterSkill(db.Model):
    __tablename__ = 'character_skills'

    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey('characters.id', ondelete='CASCADE'), nullable=False)
    skill_id = db.Column(db.Integer, db.ForeignKey('skills.id', ondelete='CASCADE'), nullable=False)
    specialization = db.Column(db.String(150), nullable=True)

    skill = db.relationship('Skill', lazy='joined')


class CharacterTalent(db.Model):
    __tablename__ = 'character_talents'

    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey('characters.id', ondelete='CASCADE'), nullable=False)
    talent_id = db.Column(db.Integer, db.ForeignKey('talents.id', ondelete='CASCADE'), nullable=False)
    times_taken = db.Column(db.Integer, default=1, nullable=False)
    specialization = db.Column(db.String(150), nullable=True)

    talent = db.relationship('Talent', lazy='joined')


class CharacterTrait(db.Model):
    """An aesthetic/personality/disadvantage entry rolled during creation
    (see the Puntos de Historial table - some options require also rolling
    here as a 'peaje')."""
    __tablename__ = 'character_traits'

    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey('characters.id', ondelete='CASCADE'), nullable=False)
    category = db.Column(db.String(20), nullable=False)  # 'estetica' | 'personalidad' | 'desventaja'
    description = db.Column(db.Text, nullable=False)


class CharacterAcquaintance(db.Model):
    """A contact/friend/enemy/mortal enemy gained from a youth event roll,
    or a sibling from the initial family-situation roll."""
    __tablename__ = 'character_acquaintances'

    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey('characters.id', ondelete='CASCADE'), nullable=False)
    kind = db.Column(db.String(20), nullable=False)  # 'contacto' | 'amigo' | 'enemigo' | 'enemigo_mortal' | 'hermano'
    description = db.Column(db.Text, nullable=False)


class CharacterPossession(db.Model):
    """A starting inventory item (weapon, armour, mount, gear, property...)."""
    __tablename__ = 'character_possessions'

    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey('characters.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(255), nullable=False)


class CharacterMagicItem(db.Model):
    """A magic item rolled while spending Puntos de Historial."""
    __tablename__ = 'character_magic_items'

    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey('characters.id', ondelete='CASCADE'), nullable=False)
    category = db.Column(db.String(30), nullable=False)  # amuleto | bolsa | cuerda | ropa | varita | arma | armadura
    description = db.Column(db.Text, nullable=False)


class Character(db.Model):
    __tablename__ = 'characters'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    race = db.Column(db.String(50), nullable=True)
    gender = db.Column(db.String(20), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # --- Características (mismos nombres/convención que Profession) ---
    ws = db.Column(db.Integer, nullable=True)
    bs = db.Column(db.Integer, nullable=True)
    s_char = db.Column(db.Integer, nullable=True)
    t_char = db.Column(db.Integer, nullable=True)
    ag = db.Column(db.Integer, nullable=True)
    int_char = db.Column(db.Integer, nullable=True)
    wp = db.Column(db.Integer, nullable=True)
    fel = db.Column(db.Integer, nullable=True)
    attacks = db.Column(db.Integer, nullable=True)
    wounds = db.Column(db.Integer, nullable=True)
    strength_bonus = db.Column(db.Integer, nullable=True)
    toughness_bonus = db.Column(db.Integer, nullable=True)
    movement = db.Column(db.Integer, nullable=True)
    magic = db.Column(db.Integer, nullable=True)
    insanity_points = db.Column(db.Integer, nullable=True)
    fate_points = db.Column(db.Integer, nullable=True)

    # --- Trasfondo (generador de personajes) ---
    signo_astral = db.Column(db.String(100), nullable=True)
    rasgo_personalidad_signo = db.Column(db.String(150), nullable=True)
    altura_cm = db.Column(db.Integer, nullable=True)
    peso_kg = db.Column(db.Integer, nullable=True)
    edad = db.Column(db.Integer, nullable=True)
    edad_grado = db.Column(db.Integer, nullable=True)
    color_pelo = db.Column(db.String(50), nullable=True)
    color_ojos = db.Column(db.String(50), nullable=True)
    mano_dominante = db.Column(db.String(20), nullable=True)
    procedencia = db.Column(db.String(150), nullable=True)
    situacion_familiar = db.Column(db.String(255), nullable=True)
    nivel_social = db.Column(db.Integer, nullable=True, default=1)
    dinero_coronas = db.Column(db.Integer, nullable=True, default=0)
    history_points_total = db.Column(db.Integer, nullable=False, default=0)
    history_points_spent = db.Column(db.Integer, nullable=False, default=0)

    professions = db.relationship(
        'CharacterProfession',
        backref='character',
        lazy='subquery',
        cascade='all, delete-orphan',
        order_by='CharacterProfession.order',
    )
    skills = db.relationship(
        'CharacterSkill',
        backref='character',
        lazy='subquery',
        cascade='all, delete-orphan',
    )
    talents = db.relationship(
        'CharacterTalent',
        backref='character',
        lazy='subquery',
        cascade='all, delete-orphan',
    )
    traits = db.relationship(
        'CharacterTrait',
        backref='character',
        lazy='subquery',
        cascade='all, delete-orphan',
    )
    acquaintances = db.relationship(
        'CharacterAcquaintance',
        backref='character',
        lazy='subquery',
        cascade='all, delete-orphan',
    )
    possessions = db.relationship(
        'CharacterPossession',
        backref='character',
        lazy='subquery',
        cascade='all, delete-orphan',
    )
    magic_items = db.relationship(
        'CharacterMagicItem',
        backref='character',
        lazy='subquery',
        cascade='all, delete-orphan',
    )

    PRIMARY_FIELDS = ('ws', 'bs', 's_char', 't_char', 'ag', 'int_char', 'wp', 'fel')
    SECONDARY_FIELDS = (
        'attacks', 'wounds', 'strength_bonus', 'toughness_bonus',
        'movement', 'magic', 'insanity_points', 'fate_points',
    )

    @property
    def history_points_available(self):
        return self.history_points_total - self.history_points_spent

    def __repr__(self):
        return f'<Character {self.name}>'

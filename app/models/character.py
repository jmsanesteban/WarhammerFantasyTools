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

    skill = db.relationship('Skill', lazy='joined')


class CharacterTalent(db.Model):
    __tablename__ = 'character_talents'

    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey('characters.id', ondelete='CASCADE'), nullable=False)
    talent_id = db.Column(db.Integer, db.ForeignKey('talents.id', ondelete='CASCADE'), nullable=False)
    times_taken = db.Column(db.Integer, default=1, nullable=False)

    talent = db.relationship('Talent', lazy='joined')


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

    def __repr__(self):
        return f'<Character {self.name}>'

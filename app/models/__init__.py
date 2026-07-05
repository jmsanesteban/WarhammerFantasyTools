# Models package - imported in app factory to register with Flask-Migrate
from app.models.permission import Permission, PermissionTemplate, user_permissions, template_permissions
from app.models.user import User
from app.models.profession import (
    Profession, ProfessionSkill, ProfessionTalent, ProfessionTrapping,
    career_exits_table
)
from app.models.skill import Skill
from app.models.talent import Talent
from app.models.character import Character, CharacterProfession, CharacterSkill, CharacterTalent
from app.models.synonym import Synonym
from app.models.contact import FieldDefinition, Contact, ContactValue
from app.models.contact_persona import ContactPersona, ContactPersonaLink
from app.models.contact_note import ContactNote

__all__ = [
    'Permission', 'PermissionTemplate', 'user_permissions', 'template_permissions',
    'User',
    'Profession', 'ProfessionSkill', 'ProfessionTalent', 'ProfessionTrapping',
    'career_exits_table',
    'Skill', 'Talent',
    'Character', 'CharacterProfession', 'CharacterSkill', 'CharacterTalent',
    'Synonym',
    'FieldDefinition', 'Contact', 'ContactValue',
    'ContactPersona', 'ContactPersonaLink',
    'ContactNote',
]

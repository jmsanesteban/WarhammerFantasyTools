# Models package - imported in app factory to register with Flask-Migrate
from app.models.permission import Permission, PermissionTemplate, user_permissions, template_permissions
from app.models.user import User
from app.models.profession import (
    Profession, ProfessionSkill, ProfessionTalent, ProfessionTrapping,
    career_exits_table
)
from app.models.skill import Skill
from app.models.talent import Talent
from app.models.character import (
    Character, CharacterProfession, CharacterSkill, CharacterTalent,
    CharacterTrait, CharacterAcquaintance, CharacterPossession, CharacterMagicItem,
    CharacterMoneyGrant,
)
from app.models.synonym import Synonym
from app.models.contact import Contact, ContactProfession
from app.models.contact_character_link import (
    ContactCharacterLink, ContactApodo, ContactCharacterSalary, ContactCharacterVisibility,
)
from app.models.contact_note import ContactNote
from app.models.equipment import EquipmentItem, CharacterInventoryItem, CharacterPurchase, CharacterCartItem

__all__ = [
    'Permission', 'PermissionTemplate', 'user_permissions', 'template_permissions',
    'User',
    'Profession', 'ProfessionSkill', 'ProfessionTalent', 'ProfessionTrapping',
    'career_exits_table',
    'Skill', 'Talent',
    'Character', 'CharacterProfession', 'CharacterSkill', 'CharacterTalent',
    'CharacterTrait', 'CharacterAcquaintance', 'CharacterPossession', 'CharacterMagicItem',
    'CharacterMoneyGrant',
    'Synonym',
    'Contact', 'ContactProfession',
    'ContactCharacterLink', 'ContactApodo', 'ContactCharacterSalary', 'ContactCharacterVisibility',
    'ContactNote',
    'EquipmentItem', 'CharacterInventoryItem', 'CharacterPurchase', 'CharacterCartItem',
]

"""Faithful JSON export/import for disaster recovery: Profesiones, Usuarios,
Personajes (incluido su inventario, historial de compras y dinero concedido),
Contactos+Vínculos (incluidas sus notas privadas por personaje), Recetas
propuestas, Equipamiento, Plantillas de permisos y Sinónimos.

Las cinco secciones con foto propia (Profesiones, Equipamiento, Recetas,
Contactos, Personajes) incrustan también los bytes de la imagen en base64
(`image_data_b64`, ver `_encode_image_b64`/`_write_image_b64`) junto a
`image_path` - sin esto, el JSON solo llevaba la ruta y una instancia nueva
se quedaba sin las fotos porque `uploads/` no viaja con el backup ni con
`git pull`. Un backup sin `image_data_b64` (fichero viejo, o fila sin foto)
simplemente no reescribe nada al importar.

The stated goal (2026-07-14) is that this "Backup completo" is the single
source of truth for standing up a brand new instance from scratch (e.g. a
fresh container on a NAS after a disk failure) with zero data loss other than
passwords, which get regenerated and force-reset - so every table with real
user-entered data must be represented here, not just the catalog-shaped ones.
Ephemeral state (an in-progress shopping cart, `CharacterCartItem`) is the
one deliberate exception - it has no recovery value.

Every `import_*` function is idempotent-by-natural-key (never by id, so a
JSON export is portable across databases) and returns a summary dict
`{created, updated, skipped, warnings}` - same shape/spirit as the existing
Skills/Talents import (`app/services/import_service.py`) and the PDF import
review flow. `mode='skip'` (default) never touches an existing row;
`mode='update'` overwrites it (and its nested children) with the imported
data.

Cross-references are resolved by natural key (username, profession/skill/
talent/equipment-item name...) rather than database id, exactly so the JSON
stays portable between databases. A missing reference never aborts the
import - the row is still created/updated and a human-readable warning is
appended instead, mirroring how the PDF import tolerates unrecognized
talents/trappings. One exception: `CharacterPurchase`/`CharacterInventoryItem`
don't try to re-link `CharacterPurchase.inventory_item_id` back to its
originating inventory row on import (both get fresh ids and the relationship
is purely informational) - the financial/ownership facts themselves are
preserved regardless.

Dependency order for a full restore: permission_templates -> users ->
professions -> equipment -> recipes -> characters -> contacts. Habilidades/
Talentos are NOT part of this module (they already have their own import at
app/services/import_service.py) and must be restored first if starting from
an empty database, since professions/characters reference them by name.
Comida y bebida's catalog (métodos de cocina, ingredientes, bebidas) is
seeded idempotently at container startup (`food_seed_service`), not part of
this module - only user-facing Recetas are backed up here.
"""
import base64
import os
from datetime import datetime

from flask import current_app

from app.extensions import db
from app.utils import generate_secure_password
from app.models.user import User
from app.models.permission import Permission, PermissionTemplate
from app.models.synonym import Synonym
from app.models.skill import Skill
from app.models.talent import Talent
from app.models.profession import Profession, ProfessionSkill, ProfessionTalent, ProfessionTrapping
from app.models.character import (
    Character, CharacterProfession, CharacterSkill, CharacterTalent,
    CharacterTrait, CharacterAcquaintance, CharacterPossession, CharacterMagicItem, CharacterMoneyGrant,
)
from app.models.equipment import EquipmentItem, CharacterInventoryItem, CharacterPurchase
from app.models.contact import Contact, ContactProfession
from app.models.contact_character_link import ContactCharacterLink
from app.models.contact_note import ContactNote
from app.models.food import Recipe, CookingMethod, Ingredient, Drink

BACKUP_VERSION = 1


def _new_summary():
    return {'created': 0, 'updated': 0, 'skipped': 0, 'warnings': []}


def _find_character(username, name):
    return (
        Character.query.join(User, User.id == Character.user_id)
        .filter(User.username == username, Character.name == name)
        .first()
    )


def _find_equipment_item(name, category, subcategory, quality):
    """Same natural key as import_equipment: (name, category, subcategory,
    quality) - `quality` here is the CATALOG row's own quality attribute
    (only ever set for Ropa, where each tier is its own row), not the
    quality a character actually bought/carries, which is a separate field
    on CharacterInventoryItem/CharacterPurchase."""
    if not name:
        return None
    return EquipmentItem.query.filter_by(
        name=name, category=category, subcategory=subcategory, quality=quality,
    ).first()


def _parse_iso(value):
    return datetime.fromisoformat(value) if value else None


# ---------------------------------------------------------------------------
# Imágenes: cada `image_path` guardado en BD es relativo a UPLOAD_FOLDER
# (uploads/), que no viaja con `git pull` ni con el JSON de por sí - solo la
# ruta quedaba respaldada, no el fichero. Las cuatro secciones con fotos
# (Profesiones, Equipamiento, Recetas, Contactos) incrustan también los bytes
# en base64 junto a la ruta, así el JSON es autocontenido de principio a fin:
# reconstruir una instancia nueva desde cero recupera las imágenes sin
# depender de que uploads/ del origen siga existiendo o se copie a mano.
# ---------------------------------------------------------------------------

def _encode_image_b64(image_path):
    if not image_path:
        return None
    full_path = os.path.join(current_app.config['UPLOAD_FOLDER'], image_path)
    if not os.path.isfile(full_path):
        return None
    with open(full_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('ascii')


def _write_image_b64(image_path, b64_data):
    """No-op if there's no path or no image data - covers rows without a
    photo, and old backups taken before this field existed."""
    if not image_path or not b64_data:
        return
    full_path = os.path.join(current_app.config['UPLOAD_FOLDER'], image_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, 'wb') as f:
        f.write(base64.b64decode(b64_data))


# ---------------------------------------------------------------------------
# Plantillas de permisos
# ---------------------------------------------------------------------------

def export_permission_templates():
    return [
        {
            'name': t.name, 'description': t.description,
            'permission_codes': [p.code for p in t.permissions],
        }
        for t in PermissionTemplate.query.order_by(PermissionTemplate.name).all()
    ]


def import_permission_templates(data, mode='skip'):
    summary = _new_summary()
    for row in data:
        existing = PermissionTemplate.query.filter_by(name=row['name']).first()
        if existing and mode != 'update':
            summary['skipped'] += 1
            continue

        perms = []
        for code in row.get('permission_codes', []):
            perm = db.session.get(Permission, code)
            if perm is None:
                summary['warnings'].append(f"Plantilla '{row['name']}': permiso '{code}' no existe, omitido.")
                continue
            perms.append(perm)

        if existing:
            existing.description = row.get('description')
            existing.permissions = perms
            summary['updated'] += 1
        else:
            db.session.add(PermissionTemplate(name=row['name'], description=row.get('description'), permissions=perms))
            summary['created'] += 1

    db.session.commit()
    return summary


# ---------------------------------------------------------------------------
# Diccionario de sinónimos
# ---------------------------------------------------------------------------

def export_synonyms():
    return [
        {'source': s.source, 'target': s.target, 'is_prefix': s.is_prefix, 'notes': s.notes}
        for s in Synonym.query.order_by(Synonym.source).all()
    ]


def import_synonyms(data, mode='skip'):
    summary = _new_summary()
    for row in data:
        existing = Synonym.query.filter_by(source=row['source']).first()
        if existing and mode != 'update':
            summary['skipped'] += 1
            continue
        if existing:
            existing.target = row['target']
            existing.is_prefix = row.get('is_prefix', False)
            existing.notes = row.get('notes')
            summary['updated'] += 1
        else:
            db.session.add(Synonym(
                source=row['source'], target=row['target'],
                is_prefix=row.get('is_prefix', False), notes=row.get('notes'),
            ))
            summary['created'] += 1

    db.session.commit()
    return summary


# ---------------------------------------------------------------------------
# Usuarios (nunca exporta/toca la contraseña de un usuario ya existente)
# ---------------------------------------------------------------------------

def export_users():
    return [
        {
            'username': u.username, 'email': u.email, 'role': u.role, 'active': u.active,
            'must_change_password': u.must_change_password,
            'template_name': u.template.name if u.template else None,
            'direct_permission_codes': [p.code for p in u.direct_permissions],
            'created_by_username': u.created_by.username if u.created_by else None,
        }
        for u in User.query.order_by(User.username).all()
    ]


def import_users(data, mode='skip'):
    summary = _new_summary()
    summary['generated_passwords'] = {}

    for row in data:
        existing = User.query.filter_by(username=row['username']).first()
        if existing and mode != 'update':
            summary['skipped'] += 1
            continue

        template = None
        if row.get('template_name'):
            template = PermissionTemplate.query.filter_by(name=row['template_name']).first()
            if template is None:
                summary['warnings'].append(
                    f"Usuario '{row['username']}': plantilla '{row['template_name']}' no existe, se deja sin plantilla."
                )

        perms = []
        for code in row.get('direct_permission_codes', []):
            perm = db.session.get(Permission, code)
            if perm is None:
                summary['warnings'].append(f"Usuario '{row['username']}': permiso '{code}' no existe, omitido.")
                continue
            perms.append(perm)

        if existing:
            existing.email = row['email']
            existing.role = row.get('role', 'user')
            existing.active = row.get('active', True)
            existing.template_id = template.id if template else None
            existing.direct_permissions = perms
            summary['updated'] += 1
        else:
            new_password = generate_secure_password()
            user = User(
                username=row['username'], email=row['email'], role=row.get('role', 'user'),
                active=row.get('active', True), must_change_password=True,
                template_id=template.id if template else None,
            )
            user.set_password(new_password)
            user.direct_permissions = perms
            db.session.add(user)
            summary['created'] += 1
            summary['generated_passwords'][row['username']] = new_password

    db.session.flush()

    # Best-effort second pass: wire up created_by (informational lineage only).
    for row in data:
        if not row.get('created_by_username'):
            continue
        user = User.query.filter_by(username=row['username']).first()
        creator = User.query.filter_by(username=row['created_by_username']).first()
        if user and creator:
            user.created_by_id = creator.id

    db.session.commit()
    return summary


# ---------------------------------------------------------------------------
# Profesiones
# ---------------------------------------------------------------------------

_PROFESSION_SCALAR_FIELDS = (
    'name_en', 'type', 'description', 'image_path',
    'ws', 'bs', 's_char', 't_char', 'ag', 'int_char', 'wp', 'fel',
    'attacks', 'wounds', 'strength_bonus', 'toughness_bonus', 'movement', 'magic',
    'insanity_points', 'fate_points',
)


def export_professions():
    result = []
    for p in Profession.query.order_by(Profession.name).all():
        row = {field: getattr(p, field) for field in _PROFESSION_SCALAR_FIELDS}
        row['name'] = p.name
        row['image_data_b64'] = _encode_image_b64(p.image_path)
        row['skills'] = [
            {'skill_name': ps.skill.name_es, 'specialization': ps.specialization, 'choice_group': ps.choice_group}
            for ps in p.profession_skills
        ]
        row['talents'] = [
            {'talent_name': pt.talent.name_es, 'specialization': pt.specialization, 'choice_group': pt.choice_group}
            for pt in p.profession_talents
        ]
        row['trappings'] = [t.name for t in p.trappings]
        row['exits'] = [e.name for e in p.exits]
        result.append(row)
    return result


def import_professions(data, mode='skip'):
    summary = _new_summary()
    by_name = {}
    to_wire_exits = {}

    for row in data:
        existing = Profession.query.filter_by(name=row['name']).first()
        if existing and mode != 'update':
            summary['skipped'] += 1
            by_name[row['name']] = existing
            continue

        if existing:
            prof = existing
            prof.profession_skills = []
            prof.profession_talents = []
            prof.trappings = []
            summary['updated'] += 1
        else:
            prof = Profession(name=row['name'])
            db.session.add(prof)
            summary['created'] += 1

        for field in _PROFESSION_SCALAR_FIELDS:
            if field in row:
                setattr(prof, field, row[field])
        _write_image_b64(prof.image_path, row.get('image_data_b64'))

        for s in row.get('skills', []):
            skill = Skill.query.filter_by(name_es=s['skill_name']).first()
            if skill is None:
                summary['warnings'].append(f"Profesión '{row['name']}': habilidad '{s['skill_name']}' no existe, omitida.")
                continue
            prof.profession_skills.append(ProfessionSkill(
                skill_id=skill.id, specialization=s.get('specialization'), choice_group=s.get('choice_group'),
            ))
        for t in row.get('talents', []):
            talent = Talent.query.filter_by(name_es=t['talent_name']).first()
            if talent is None:
                summary['warnings'].append(f"Profesión '{row['name']}': talento '{t['talent_name']}' no existe, omitido.")
                continue
            prof.profession_talents.append(ProfessionTalent(
                talent_id=talent.id, specialization=t.get('specialization'), choice_group=t.get('choice_group'),
            ))
        for name in row.get('trappings', []):
            prof.trappings.append(ProfessionTrapping(name=name))

        by_name[row['name']] = prof
        to_wire_exits[row['name']] = row.get('exits', [])

    db.session.flush()

    for name, exit_names in to_wire_exits.items():
        prof = by_name[name]
        exits = []
        for exit_name in exit_names:
            target = by_name.get(exit_name) or Profession.query.filter_by(name=exit_name).first()
            if target is None:
                summary['warnings'].append(f"Profesión '{name}': salida a '{exit_name}' no existe, omitida.")
                continue
            exits.append(target)
        prof.exits = exits

    db.session.commit()
    return summary


# ---------------------------------------------------------------------------
# Equipamiento
# ---------------------------------------------------------------------------

_EQUIPMENT_SCALAR_FIELDS = (
    'category', 'subcategory', 'quality', 'is_special', 'price_text',
    'image_path', 'description', 'stats', 'custom_fields', 'source_book', 'status',
)


def export_equipment():
    result = []
    for item in EquipmentItem.query.order_by(EquipmentItem.category, EquipmentItem.name).all():
        row = {field: getattr(item, field) for field in _EQUIPMENT_SCALAR_FIELDS}
        row['name'] = item.name
        row['image_data_b64'] = _encode_image_b64(item.image_path)
        if item.base_item_id and item.base_item:
            row['base_item_name'] = item.base_item.name
            row['base_item_category'] = item.base_item.category
        result.append(row)
    return result


def import_equipment(data, mode='skip'):
    """Matched by (name, category, subcategory, quality) - not id - so the
    JSON stays portable across databases, same convention as
    import_professions. subcategory/quality are part of the key because the
    catalog legitimately has multiple items sharing a name within a category
    (e.g. "Abrigo" once per quality tier) - matching on (name, category)
    alone collapsed those into a single row and silently dropped the rest."""
    summary = _new_summary()
    by_key = {}
    by_name_category = {}  # base-item lookup only cares about (name, category)
    to_wire_base = {}

    for row in data:
        key = (row['name'], row['category'], row.get('subcategory'), row.get('quality'))
        existing = EquipmentItem.query.filter_by(
            name=row['name'], category=row['category'],
            subcategory=row.get('subcategory'), quality=row.get('quality'),
        ).first()
        if existing and mode != 'update':
            summary['skipped'] += 1
            by_key[key] = existing
            by_name_category[(row['name'], row['category'])] = existing
            continue

        if existing:
            item = existing
            summary['updated'] += 1
        else:
            item = EquipmentItem(name=row['name'], category=row['category'])
            db.session.add(item)
            summary['created'] += 1

        for field in _EQUIPMENT_SCALAR_FIELDS:
            if field in row:
                setattr(item, field, row[field])
        _write_image_b64(item.image_path, row.get('image_data_b64'))

        by_key[key] = item
        by_name_category[(row['name'], row['category'])] = item
        base_name = row.get('base_item_name')
        if base_name:
            to_wire_base[key] = (base_name, row.get('base_item_category'))

    db.session.flush()

    for key, (base_name, base_category) in to_wire_base.items():
        item = by_key[key]
        base = by_name_category.get((base_name, base_category)) or EquipmentItem.query.filter_by(
            name=base_name, category=base_category).first()
        if base is None:
            summary['warnings'].append(
                f"Objeto '{item.name}': objeto base '{base_name}' no existe, omitido.")
            continue
        item.base_item_id = base.id

    db.session.commit()
    return summary


# ---------------------------------------------------------------------------
# Personajes
# ---------------------------------------------------------------------------

_CHARACTER_SCALAR_FIELDS = (
    'race', 'gender', 'image_path', 'notes',
    'ws', 'bs', 's_char', 't_char', 'ag', 'int_char', 'wp', 'fel',
    'attacks', 'wounds', 'strength_bonus', 'toughness_bonus', 'movement', 'magic',
    'insanity_points', 'fate_points',
    'signo_astral', 'rasgo_personalidad_signo', 'altura_cm', 'peso_kg', 'edad', 'edad_grado',
    'color_pelo', 'color_ojos', 'mano_dominante', 'procedencia', 'situacion_familiar',
    'nivel_social', 'dinero_coronas', 'dinero_peniques_extra', 'history_points_total', 'history_points_spent',
    'es_untersuchung', 'grados_untersuchung', 'mochila_o_saco',
)


def export_characters():
    result = []
    for c in Character.query.order_by(Character.name).all():
        row = {field: getattr(c, field) for field in _CHARACTER_SCALAR_FIELDS}
        row['owner_username'] = c.owner.username
        row['name'] = c.name
        row['image_data_b64'] = _encode_image_b64(c.image_path)
        row['professions'] = [
            {
                'profession_name': cp.profession.name if cp.profession else None,
                'order': cp.order, 'is_current': cp.is_current,
                'tipo_sueldo': cp.tipo_sueldo, 'estado_habilidad': cp.estado_habilidad,
            }
            for cp in c.professions
        ]
        row['skills'] = [{'skill_name': cs.skill.name_es, 'specialization': cs.specialization} for cs in c.skills]
        row['talents'] = [
            {'talent_name': ct.talent.name_es, 'specialization': ct.specialization, 'times_taken': ct.times_taken}
            for ct in c.talents
        ]
        row['traits'] = [{'category': t.category, 'description': t.description} for t in c.traits]
        row['acquaintances'] = [{'kind': a.kind, 'description': a.description} for a in c.acquaintances]
        row['possessions'] = [p.name for p in c.possessions]
        row['magic_items'] = [{'category': m.category, 'description': m.description} for m in c.magic_items]
        row['inventory_items'] = [
            {
                'equipment_item_name': ii.equipment_item.name if ii.equipment_item else None,
                'equipment_item_category': ii.equipment_item.category if ii.equipment_item else None,
                'equipment_item_subcategory': ii.equipment_item.subcategory if ii.equipment_item else None,
                'equipment_item_catalog_quality': ii.equipment_item.quality if ii.equipment_item else None,
                'drink_name': ii.drink.nombre if ii.drink else None,
                'drink_origen': ii.drink.origen if ii.drink else None,
                'recipe_name': ii.recipe.nombre if ii.recipe else None,
                'custom_name': ii.custom_name, 'quality': ii.quality, 'quantity': ii.quantity,
                'location': ii.location, 'notes': ii.notes, 'condition': ii.condition,
            }
            for ii in c.inventory_items
        ]
        row['purchases'] = [
            {
                'equipment_item_name': p.equipment_item.name if p.equipment_item else None,
                'equipment_item_category': p.equipment_item.category if p.equipment_item else None,
                'equipment_item_subcategory': p.equipment_item.subcategory if p.equipment_item else None,
                'equipment_item_catalog_quality': p.equipment_item.quality if p.equipment_item else None,
                'drink_name': p.drink.nombre if p.drink else None,
                'drink_origen': p.drink.origen if p.drink else None,
                'recipe_name': p.recipe.nombre if p.recipe else None,
                'item_name_snapshot': p.item_name_snapshot, 'category_snapshot': p.category_snapshot,
                'quality_snapshot': p.quality_snapshot, 'precio_peniques_pagado': p.precio_peniques_pagado,
                'granted_by_gm': p.granted_by_gm,
                'granted_by_username': p.granted_by.username if p.granted_by else None,
                'notes': p.notes, 'created_at': p.created_at.isoformat() if p.created_at else None,
            }
            for p in c.purchases
        ]
        row['money_grants'] = [
            {
                'peniques': mg.peniques, 'motivo': mg.motivo,
                'granted_by_username': mg.granted_by.username if mg.granted_by else None,
                'created_at': mg.created_at.isoformat() if mg.created_at else None,
            }
            for mg in c.money_grants
        ]
        result.append(row)
    return result


def import_characters(data, mode='skip'):
    summary = _new_summary()
    for row in data:
        owner = User.query.filter_by(username=row['owner_username']).first()
        if owner is None:
            summary['warnings'].append(
                f"Personaje '{row['name']}': usuario '{row['owner_username']}' no existe, omitido."
            )
            summary['skipped'] += 1
            continue

        existing = Character.query.filter_by(user_id=owner.id, name=row['name']).first()
        if existing and mode != 'update':
            summary['skipped'] += 1
            continue

        if existing:
            char = existing
            char.professions = []
            char.skills = []
            char.talents = []
            char.traits = []
            char.acquaintances = []
            char.possessions = []
            char.magic_items = []
            char.inventory_items = []
            char.purchases = []
            char.money_grants = []
            summary['updated'] += 1
        else:
            char = Character(user_id=owner.id, name=row['name'])
            db.session.add(char)
            summary['created'] += 1

        for field in _CHARACTER_SCALAR_FIELDS:
            if field in row:
                setattr(char, field, row[field])
        _write_image_b64(char.image_path, row.get('image_data_b64'))

        for cp in row.get('professions', []):
            profession = None
            if cp.get('profession_name'):
                profession = Profession.query.filter_by(name=cp['profession_name']).first()
                if profession is None:
                    summary['warnings'].append(
                        f"Personaje '{row['name']}': profesión '{cp['profession_name']}' no existe, se deja sin vincular."
                    )
            char.professions.append(CharacterProfession(
                profession_id=profession.id if profession else None,
                order=cp.get('order', 0), is_current=cp.get('is_current', False),
                tipo_sueldo=cp.get('tipo_sueldo'), estado_habilidad=cp.get('estado_habilidad'),
            ))
        for cs in row.get('skills', []):
            skill = Skill.query.filter_by(name_es=cs['skill_name']).first()
            if skill is None:
                summary['warnings'].append(f"Personaje '{row['name']}': habilidad '{cs['skill_name']}' no existe, omitida.")
                continue
            char.skills.append(CharacterSkill(skill_id=skill.id, specialization=cs.get('specialization')))
        for ct in row.get('talents', []):
            talent = Talent.query.filter_by(name_es=ct['talent_name']).first()
            if talent is None:
                summary['warnings'].append(f"Personaje '{row['name']}': talento '{ct['talent_name']}' no existe, omitido.")
                continue
            char.talents.append(CharacterTalent(
                talent_id=talent.id, specialization=ct.get('specialization'), times_taken=ct.get('times_taken', 1),
            ))
        for tr in row.get('traits', []):
            char.traits.append(CharacterTrait(category=tr['category'], description=tr['description']))
        for a in row.get('acquaintances', []):
            char.acquaintances.append(CharacterAcquaintance(kind=a['kind'], description=a['description']))
        for name in row.get('possessions', []):
            char.possessions.append(CharacterPossession(name=name))
        for m in row.get('magic_items', []):
            char.magic_items.append(CharacterMagicItem(category=m['category'], description=m['description']))

        for ii in row.get('inventory_items', []):
            equipment_item = _find_equipment_item(
                ii.get('equipment_item_name'), ii.get('equipment_item_category'),
                ii.get('equipment_item_subcategory'), ii.get('equipment_item_catalog_quality'),
            )
            if ii.get('equipment_item_name') and equipment_item is None:
                summary['warnings'].append(
                    f"Personaje '{row['name']}': objeto de inventario '{ii['equipment_item_name']}' "
                    "no existe en el catálogo, se deja como objeto personalizado."
                )
            drink = Drink.query.filter_by(nombre=ii['drink_name'], origen=ii.get('drink_origen')).first() \
                if ii.get('drink_name') else None
            if ii.get('drink_name') and drink is None:
                summary['warnings'].append(
                    f"Personaje '{row['name']}': bebida de inventario '{ii['drink_name']}' no existe en el catálogo."
                )
            recipe = Recipe.query.filter_by(nombre=ii['recipe_name']).first() if ii.get('recipe_name') else None
            if ii.get('recipe_name') and recipe is None:
                summary['warnings'].append(
                    f"Personaje '{row['name']}': receta de inventario '{ii['recipe_name']}' no existe en el catálogo."
                )
            char.inventory_items.append(CharacterInventoryItem(
                equipment_item_id=equipment_item.id if equipment_item else None,
                drink_id=drink.id if drink else None, recipe_id=recipe.id if recipe else None,
                custom_name=ii.get('custom_name') or (ii.get('equipment_item_name') if not equipment_item else None),
                quality=ii.get('quality'), quantity=ii.get('quantity', 1),
                location=ii.get('location', 'equipamiento'), notes=ii.get('notes'), condition=ii.get('condition'),
            ))
        for p in row.get('purchases', []):
            equipment_item = _find_equipment_item(
                p.get('equipment_item_name'), p.get('equipment_item_category'),
                p.get('equipment_item_subcategory'), p.get('equipment_item_catalog_quality'),
            )
            drink = Drink.query.filter_by(nombre=p['drink_name'], origen=p.get('drink_origen')).first() \
                if p.get('drink_name') else None
            recipe = Recipe.query.filter_by(nombre=p['recipe_name']).first() if p.get('recipe_name') else None
            granted_by = User.query.filter_by(username=p.get('granted_by_username')).first() \
                if p.get('granted_by_username') else None
            char.purchases.append(CharacterPurchase(
                equipment_item_id=equipment_item.id if equipment_item else None,
                drink_id=drink.id if drink else None, recipe_id=recipe.id if recipe else None,
                item_name_snapshot=p.get('item_name_snapshot', p.get('equipment_item_name', '?')),
                category_snapshot=p.get('category_snapshot'), quality_snapshot=p.get('quality_snapshot'),
                precio_peniques_pagado=p.get('precio_peniques_pagado', 0),
                granted_by_gm=p.get('granted_by_gm', False),
                granted_by_user_id=granted_by.id if granted_by else None,
                notes=p.get('notes'), created_at=_parse_iso(p.get('created_at')),
            ))
        for mg in row.get('money_grants', []):
            granted_by = User.query.filter_by(username=mg.get('granted_by_username')).first() \
                if mg.get('granted_by_username') else None
            char.money_grants.append(CharacterMoneyGrant(
                peniques=mg.get('peniques', 0), motivo=mg.get('motivo'),
                granted_by_user_id=granted_by.id if granted_by else None,
                created_at=_parse_iso(mg.get('created_at')),
            ))

    db.session.commit()
    return summary


# ---------------------------------------------------------------------------
# Contactos + Vínculos (la exportación Excel existente de Contactos, limitada
# a nombre/Untersuchung/profesiones, se deja intacta - esto es un backup
# nuevo y más completo que además incluye los vínculos por personaje)
# ---------------------------------------------------------------------------

def export_contacts_full():
    result = []
    for contact in Contact.query.order_by(Contact.nombre).all():
        result.append({
            'nombre': contact.nombre, 'raza': contact.raza, 'es_untersuchung': contact.es_untersuchung,
            'estado': contact.estado,
            'grados_untersuchung': contact.grados_untersuchung,
            'lugar_descanso': contact.lugar_descanso, 'lugar_trabajo': contact.lugar_trabajo,
            'lugar_ocio': contact.lugar_ocio, 'notas_director': contact.notas_director,
            'image_path': contact.image_path,
            'image_data_b64': _encode_image_b64(contact.image_path),
            'is_visible': contact.is_visible,
            'created_by_username': contact.created_by.username if contact.created_by else None,
            'profesiones': [
                {
                    'profession_name': cp.profession.name,
                    'tipo_sueldo': cp.tipo_sueldo, 'estado_habilidad': cp.estado_habilidad,
                }
                for cp in contact.professions if cp.profession
            ],
            'notes': [
                {
                    'character_username': n.character.owner.username, 'character_name': n.character.name,
                    'content': n.content,
                    'created_at': n.created_at.isoformat() if n.created_at else None,
                    'updated_at': n.updated_at.isoformat() if n.updated_at else None,
                }
                for n in contact.notes
            ],
            'links': [
                {
                    'character_username': link.character.owner.username,
                    'character_name': link.character.name,
                    'nivel': link.nivel, 'tipo_relacion': link.tipo_relacion,
                }
                for link in contact.character_links
            ],
        })
    return result


def import_contacts_full(data, mode='skip'):
    summary = _new_summary()
    for row in data:
        existing = Contact.query.filter_by(nombre=row['nombre']).first()
        if existing and mode != 'update':
            summary['skipped'] += 1
            continue

        if existing:
            contact = existing
            contact.professions = []
            for link in list(contact.character_links):
                db.session.delete(link)
            for note in list(contact.notes):
                db.session.delete(note)
            summary['updated'] += 1
        else:
            contact = Contact(nombre=row['nombre'])
            db.session.add(contact)
            summary['created'] += 1

        contact.raza = row.get('raza')
        contact.es_untersuchung = row.get('es_untersuchung', False)
        contact.estado = row.get('estado') or ('vivo' if row.get('vivo', True) else 'muerto')
        contact.grados_untersuchung = row.get('grados_untersuchung')
        contact.lugar_descanso = row.get('lugar_descanso')
        contact.lugar_trabajo = row.get('lugar_trabajo')
        contact.lugar_ocio = row.get('lugar_ocio')
        contact.notas_director = row.get('notas_director')
        contact.image_path = row.get('image_path')
        _write_image_b64(contact.image_path, row.get('image_data_b64'))
        contact.is_visible = row.get('is_visible', True)
        if row.get('created_by_username'):
            creator = User.query.filter_by(username=row['created_by_username']).first()
            if creator is None:
                summary['warnings'].append(
                    f"Contacto '{row['nombre']}': usuario creador '{row['created_by_username']}' no existe, se deja sin creador."
                )
            contact.created_by_id = creator.id if creator else None

        for prof_data in row.get('profesiones', []):
            prof_name = prof_data['profession_name']
            profession = Profession.query.filter_by(name=prof_name).first()
            if profession is None:
                summary['warnings'].append(f"Contacto '{row['nombre']}': profesión '{prof_name}' no existe, omitida.")
                continue
            contact.professions.append(ContactProfession(
                profession_id=profession.id,
                tipo_sueldo=prof_data.get('tipo_sueldo'), estado_habilidad=prof_data.get('estado_habilidad'),
            ))

        db.session.flush()

        for link_data in row.get('links', []):
            character = _find_character(link_data['character_username'], link_data['character_name'])
            if character is None:
                summary['warnings'].append(
                    f"Contacto '{row['nombre']}': personaje "
                    f"'{link_data['character_username']}/{link_data['character_name']}' no existe, vínculo omitido."
                )
                continue
            link = ContactCharacterLink(
                contact_id=contact.id, character_id=character.id,
                nivel=link_data.get('nivel'), tipo_relacion=link_data.get('tipo_relacion'),
            )
            db.session.add(link)

        for note_data in row.get('notes', []):
            character = _find_character(note_data['character_username'], note_data['character_name'])
            if character is None:
                summary['warnings'].append(
                    f"Contacto '{row['nombre']}': personaje de la nota "
                    f"'{note_data['character_username']}/{note_data['character_name']}' no existe, nota omitida."
                )
                continue
            db.session.add(ContactNote(
                contact_id=contact.id, character_id=character.id, content=note_data['content'],
                created_at=_parse_iso(note_data.get('created_at')) or datetime.utcnow(),
                updated_at=_parse_iso(note_data.get('updated_at')),
            ))

    db.session.commit()
    return summary


# ---------------------------------------------------------------------------
# Comida y bebida: solo Recetas (Fase 2, propuestas de usuarios). El resto
# del catálogo (métodos de cocina, ingredientes, bebidas) se siembra solo,
# de forma idempotente, en el arranque de la app (food_seed_service) - no
# hace falta respaldarlo. Las recetas del libro también se resiembran, pero
# se incluyen aquí de todos modos para no perder ediciones manuales sobre
# ellas ni depender implícitamente de que la siembra ya haya corrido.
# ---------------------------------------------------------------------------

_RECIPE_SCALAR_FIELDS = (
    'vigor', 'moral', 'calidad', 'duracion_dias', 'recalentar',
    'coste_creacion_peniques', 'precio_compra_peniques', 'complejidad', 'solo_compra',
    'notas', 'status', 'image_path', 'requested_at', 'approved_at', 'rejection_reason',
)


def export_recipes():
    result = []
    for r in Recipe.query.order_by(Recipe.nombre).all():
        row = {field: getattr(r, field) for field in _RECIPE_SCALAR_FIELDS}
        row['nombre'] = r.nombre
        row['image_data_b64'] = _encode_image_b64(r.image_path)
        row['cooking_method_name'] = r.cooking_method.nombre if r.cooking_method else None
        row['ingredientes'] = [i.nombre for i in r.ingredientes]
        row['condimentos'] = [i.nombre for i in r.condimentos]
        row['created_by_username'] = r.created_by.username if r.created_by else None
        row['approved_by_username'] = r.approved_by.username if r.approved_by else None
        for key in ('requested_at', 'approved_at'):
            if row.get(key):
                row[key] = row[key].isoformat()
        result.append(row)
    return result


def import_recipes(data, mode='skip'):
    summary = _new_summary()
    for row in data:
        existing = Recipe.query.filter_by(nombre=row['nombre']).first()
        if existing and mode != 'update':
            summary['skipped'] += 1
            continue

        if existing:
            recipe = existing
            summary['updated'] += 1
        else:
            recipe = Recipe(nombre=row['nombre'])
            db.session.add(recipe)
            summary['created'] += 1

        for field in _RECIPE_SCALAR_FIELDS:
            if field in row:
                value = row[field]
                if field in ('requested_at', 'approved_at'):
                    value = _parse_iso(value)
                setattr(recipe, field, value)
        _write_image_b64(recipe.image_path, row.get('image_data_b64'))

        if row.get('cooking_method_name'):
            method = CookingMethod.query.filter_by(nombre=row['cooking_method_name']).first()
            if method is None:
                summary['warnings'].append(
                    f"Receta '{row['nombre']}': método de cocina '{row['cooking_method_name']}' no existe, omitido."
                )
            recipe.cooking_method_id = method.id if method else None

        ingredientes = row.get('ingredientes', [])
        for i in range(4):
            field = f'ingrediente_{i + 1}_id'
            if i < len(ingredientes):
                ing = Ingredient.query.filter_by(nombre=ingredientes[i]).first()
                if ing is None:
                    summary['warnings'].append(
                        f"Receta '{row['nombre']}': ingrediente '{ingredientes[i]}' no existe, omitido."
                    )
                setattr(recipe, field, ing.id if ing else None)
            else:
                setattr(recipe, field, None)

        condimentos = row.get('condimentos', [])
        for i in range(2):
            field = f'condimento_{i + 1}_id'
            if i < len(condimentos):
                cond = Ingredient.query.filter_by(nombre=condimentos[i]).first()
                if cond is None:
                    summary['warnings'].append(
                        f"Receta '{row['nombre']}': condimento '{condimentos[i]}' no existe, omitido."
                    )
                setattr(recipe, field, cond.id if cond else None)
            else:
                setattr(recipe, field, None)

        if row.get('created_by_username'):
            creator = User.query.filter_by(username=row['created_by_username']).first()
            recipe.created_by_id = creator.id if creator else None
        if row.get('approved_by_username'):
            approver = User.query.filter_by(username=row['approved_by_username']).first()
            recipe.approved_by_id = approver.id if approver else None

    db.session.commit()
    return summary


# ---------------------------------------------------------------------------
# Recargo global de precios: fila única (o ninguna), no un catálogo - se
# exporta como un dict, no una lista, para que quede claro que es un ajuste
# singleton en lugar de una colección de registros.
# ---------------------------------------------------------------------------

def export_shop_markup():
    from app.models.shop import ShopMarkup
    row = ShopMarkup.query.first()
    if row is None:
        return None
    return {
        'pct': row.pct,
        'updated_by_username': row.updated_by.username if row.updated_by else None,
        'updated_at': row.updated_at.isoformat() if row.updated_at else None,
    }


def import_shop_markup(data, mode='skip'):
    from app.models.shop import ShopMarkup
    summary = _new_summary()
    if not data:
        return summary

    existing = ShopMarkup.query.first()
    if existing and mode != 'update':
        summary['skipped'] += 1
        return summary

    updated_by = User.query.filter_by(username=data['updated_by_username']).first() \
        if data.get('updated_by_username') else None
    if existing:
        row = existing
        summary['updated'] += 1
    else:
        row = ShopMarkup()
        db.session.add(row)
        summary['created'] += 1
    row.pct = data.get('pct', 0)
    row.updated_by_id = updated_by.id if updated_by else None
    row.updated_at = _parse_iso(data.get('updated_at'))

    db.session.commit()
    return summary


# ---------------------------------------------------------------------------
# Backup completo: orquesta todas las secciones en el orden de dependencias
# ---------------------------------------------------------------------------

# Única fuente de verdad para el orden/etiquetas/función de cada sección -
# usada tanto por export_full_backup() como por la UI de selección y el
# resumen de import (app/routes/admin.py).
BACKUP_SECTIONS = [
    ('permission_templates', 'Plantillas de permisos', export_permission_templates),
    ('synonyms', 'Sinónimos', export_synonyms),
    ('users', 'Usuarios', export_users),
    ('professions', 'Profesiones', export_professions),
    ('equipment', 'Equipamiento', export_equipment),
    ('recipes', 'Recetas', export_recipes),
    ('shop_markup', 'Recargo de precios', export_shop_markup),
    ('characters', 'Personajes', export_characters),
    ('contacts', 'Contactos y vínculos', export_contacts_full),
]


def export_full_backup(sections=None):
    """`sections=None` (o todas) exporta las nueve secciones - el "backup
    total" de siempre. Si se pide un subconjunto, las claves no incluidas
    no aparecen en absoluto en el resultado (no listas vacías) - el nuevo
    campo `secciones` deja sin ambigüedad qué trae el fichero, tanto para un
    humano como para el visor de backups guardados."""
    include = set(sections) if sections is not None else {key for key, _, _ in BACKUP_SECTIONS}
    data = {
        'version': BACKUP_VERSION,
        'exported_at': datetime.utcnow().isoformat() + 'Z',
        'secciones': [key for key, _, _ in BACKUP_SECTIONS if key in include],
    }
    for key, _, export_fn in BACKUP_SECTIONS:
        if key in include:
            data[key] = export_fn()
    return data


def import_full_backup(data, mode='skip'):
    return {
        'permission_templates': import_permission_templates(data.get('permission_templates', []), mode),
        'synonyms': import_synonyms(data.get('synonyms', []), mode),
        'users': import_users(data.get('users', []), mode),
        'professions': import_professions(data.get('professions', []), mode),
        'equipment': import_equipment(data.get('equipment', []), mode),
        'recipes': import_recipes(data.get('recipes', []), mode),
        'shop_markup': import_shop_markup(data.get('shop_markup'), mode),
        'characters': import_characters(data.get('characters', []), mode),
        'contacts': import_contacts_full(data.get('contacts', []), mode),
    }

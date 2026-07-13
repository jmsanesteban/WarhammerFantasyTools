"""Faithful JSON export/import for disaster recovery: Profesiones, Usuarios,
Personajes, Contactos+Vínculos, Plantillas de permisos y Sinónimos.

Every `import_*` function is idempotent-by-natural-key (never by id, so a
JSON export is portable across databases) and returns a summary dict
`{created, updated, skipped, warnings}` - same shape/spirit as the existing
Skills/Talents import (`app/services/import_service.py`) and the PDF import
review flow. `mode='skip'` (default) never touches an existing row;
`mode='update'` overwrites it (and its nested children) with the imported
data.

Cross-references are resolved by natural key (username, profession/skill/
talent name...) rather than database id, exactly so the JSON stays portable
between databases. A missing reference never aborts the import - the row is
still created/updated and a human-readable warning is appended instead,
mirroring how the PDF import tolerates unrecognized talents/trappings.

Dependency order for a full restore: permission_templates -> users ->
professions -> characters -> contacts. Habilidades/Talentos are NOT part of
this module (they already have their own import at app/services/
import_service.py) and must be restored first if starting from an empty
database, since professions/characters reference them by name.
"""
from datetime import datetime

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
    CharacterTrait, CharacterAcquaintance, CharacterPossession, CharacterMagicItem,
)
from app.models.equipment import EquipmentItem
from app.models.contact import Contact, ContactProfession
from app.models.contact_character_link import (
    ContactCharacterLink, ContactApodo, ContactCharacterSalary, ContactCharacterVisibility,
)

BACKUP_VERSION = 1


def _new_summary():
    return {'created': 0, 'updated': 0, 'skipped': 0, 'warnings': []}


def _find_character(username, name):
    return (
        Character.query.join(User, User.id == Character.user_id)
        .filter(User.username == username, Character.name == name)
        .first()
    )


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
    'race', 'gender', 'notes',
    'ws', 'bs', 's_char', 't_char', 'ag', 'int_char', 'wp', 'fel',
    'attacks', 'wounds', 'strength_bonus', 'toughness_bonus', 'movement', 'magic',
    'insanity_points', 'fate_points',
    'signo_astral', 'rasgo_personalidad_signo', 'altura_cm', 'peso_kg', 'edad', 'edad_grado',
    'color_pelo', 'color_ojos', 'mano_dominante', 'procedencia', 'situacion_familiar',
    'nivel_social', 'dinero_coronas', 'history_points_total', 'history_points_spent',
    'es_untersuchung',
)


def export_characters():
    result = []
    for c in Character.query.order_by(Character.name).all():
        row = {field: getattr(c, field) for field in _CHARACTER_SCALAR_FIELDS}
        row['owner_username'] = c.owner.username
        row['name'] = c.name
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
            summary['updated'] += 1
        else:
            char = Character(user_id=owner.id, name=row['name'])
            db.session.add(char)
            summary['created'] += 1

        for field in _CHARACTER_SCALAR_FIELDS:
            if field in row:
                setattr(char, field, row[field])

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
            'nombre': contact.nombre, 'es_untersuchung': contact.es_untersuchung,
            'estado': contact.estado, 'paradero': contact.paradero,
            'grados_untersuchung': contact.grados_untersuchung,
            'image_path': contact.image_path,
            'is_visible': contact.is_visible,
            'profesiones': [cp.profession.name for cp in contact.professions if cp.profession],
            'links': [
                {
                    'character_username': link.character.owner.username,
                    'character_name': link.character.name,
                    'nivel': link.nivel, 'organizacion_secta': link.organizacion_secta,
                    'lugar_residencia': link.lugar_residencia, 'lugar_contacto': link.lugar_contacto,
                    'creacion': link.creacion, 'gm': link.gm, 'mision': link.mision,
                    'apodos': [a.texto for a in link.apodos],
                    'salarios': [
                        {
                            'profession_name': s.profession.name,
                            'tipo_sueldo': s.tipo_sueldo, 'estado_habilidad': s.estado_habilidad,
                        }
                        for s in link.salarios
                    ],
                }
                for link in contact.character_links
            ],
            'visibilidades': [
                {
                    'character_username': v.character.owner.username,
                    'character_name': v.character.name, 'nivel': v.nivel,
                }
                for v in contact.character_visibilities
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
            for vis in list(contact.character_visibilities):
                db.session.delete(vis)
            summary['updated'] += 1
        else:
            contact = Contact(nombre=row['nombre'])
            db.session.add(contact)
            summary['created'] += 1

        contact.es_untersuchung = row.get('es_untersuchung', False)
        contact.estado = row.get('estado') or ('vivo' if row.get('vivo', True) else 'muerto')
        contact.paradero = row.get('paradero')
        contact.grados_untersuchung = row.get('grados_untersuchung')
        contact.image_path = row.get('image_path')
        contact.is_visible = row.get('is_visible', True)

        for prof_name in row.get('profesiones', []):
            profession = Profession.query.filter_by(name=prof_name).first()
            if profession is None:
                summary['warnings'].append(f"Contacto '{row['nombre']}': profesión '{prof_name}' no existe, omitida.")
                continue
            contact.professions.append(ContactProfession(profession_id=profession.id))

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
                nivel=link_data.get('nivel'), organizacion_secta=link_data.get('organizacion_secta'),
                lugar_residencia=link_data.get('lugar_residencia'), lugar_contacto=link_data.get('lugar_contacto'),
                creacion=link_data.get('creacion', False), gm=link_data.get('gm'), mision=link_data.get('mision'),
            )
            db.session.add(link)
            db.session.flush()
            for texto in link_data.get('apodos', []):
                db.session.add(ContactApodo(link_id=link.id, texto=texto))
            for sal in link_data.get('salarios', []):
                profession = Profession.query.filter_by(name=sal['profession_name']).first()
                if profession is None:
                    summary['warnings'].append(
                        f"Contacto '{row['nombre']}': profesión de salario '{sal['profession_name']}' no existe, omitida."
                    )
                    continue
                db.session.add(ContactCharacterSalary(
                    link_id=link.id, profession_id=profession.id,
                    tipo_sueldo=sal.get('tipo_sueldo'), estado_habilidad=sal.get('estado_habilidad'),
                ))

        for vis_data in row.get('visibilidades', []):
            character = _find_character(vis_data['character_username'], vis_data['character_name'])
            if character is None:
                summary['warnings'].append(f"Contacto '{row['nombre']}': personaje de visibilidad no existe, omitida.")
                continue
            db.session.add(ContactCharacterVisibility(
                contact_id=contact.id, character_id=character.id, nivel=vis_data.get('nivel', 'total'),
            ))

    db.session.commit()
    return summary


# ---------------------------------------------------------------------------
# Backup completo: orquesta todas las secciones en el orden de dependencias
# ---------------------------------------------------------------------------

def export_full_backup():
    return {
        'version': BACKUP_VERSION,
        'exported_at': datetime.utcnow().isoformat() + 'Z',
        'permission_templates': export_permission_templates(),
        'synonyms': export_synonyms(),
        'users': export_users(),
        'professions': export_professions(),
        'equipment': export_equipment(),
        'characters': export_characters(),
        'contacts': export_contacts_full(),
    }


def import_full_backup(data, mode='skip'):
    return {
        'permission_templates': import_permission_templates(data.get('permission_templates', []), mode),
        'synonyms': import_synonyms(data.get('synonyms', []), mode),
        'users': import_users(data.get('users', []), mode),
        'professions': import_professions(data.get('professions', []), mode),
        'equipment': import_equipment(data.get('equipment', []), mode),
        'characters': import_characters(data.get('characters', []), mode),
        'contacts': import_contacts_full(data.get('contacts', []), mode),
    }

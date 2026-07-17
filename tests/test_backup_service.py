"""Round-trip tests for app/services/backup_service.py: every export_*/import_*
pair must reproduce the original data when re-imported into an empty table,
'update' mode must overwrite in place without duplicating, and a dangling
cross-reference (unknown username/profession/skill/talent) must be skipped
with a warning rather than raising."""
import base64
import os

from app.services import backup_service as bkp


# ── Plantillas de permisos ──────────────────────────────────────────────────

def test_permission_templates_round_trip(app, db):
    with app.app_context():
        from app.models.permission import seed_permissions_and_templates, PermissionTemplate
        seed_permissions_and_templates()
        data = bkp.export_permission_templates()
        assert any(t['name'] == 'Editor' for t in data)

        for t in PermissionTemplate.query.all():
            db.session.delete(t)
        db.session.commit()

        summary = bkp.import_permission_templates(data)
        assert summary['created'] == len(data)
        assert summary['skipped'] == 0

        second = bkp.import_permission_templates(data)
        assert second['created'] == 0
        assert second['skipped'] == len(data)

        editor = PermissionTemplate.query.filter_by(name='Editor').first()
        assert editor is not None
        assert 'professions.edit' in [p.code for p in editor.permissions]


def test_permission_templates_update_mode_overwrites(app, db):
    with app.app_context():
        from app.models.permission import seed_permissions_and_templates, PermissionTemplate
        seed_permissions_and_templates()
        editor = PermissionTemplate.query.filter_by(name='Editor').first()
        editor.description = 'changed'
        db.session.commit()

        data = [{'name': 'Editor', 'description': 'restored', 'permission_codes': ['professions.view']}]
        summary = bkp.import_permission_templates(data, mode='update')
        assert summary['updated'] == 1
        db.session.refresh(editor)
        assert editor.description == 'restored'
        assert [p.code for p in editor.permissions] == ['professions.view']


def test_permission_templates_warns_on_missing_permission(app, db):
    with app.app_context():
        from app.models.permission import seed_permissions_and_templates
        seed_permissions_and_templates()
        data = [{'name': 'Nueva', 'description': 'x', 'permission_codes': ['no.existe']}]
        summary = bkp.import_permission_templates(data)
        assert summary['created'] == 1
        assert any('no.existe' in w for w in summary['warnings'])


# ── Sinónimos ────────────────────────────────────────────────────────────────

def test_synonyms_round_trip(app, db):
    with app.app_context():
        from app.models.synonym import Synonym, DEFAULT_SYNONYMS
        for source, target, is_prefix, notes in DEFAULT_SYNONYMS[:3]:
            db.session.add(Synonym(source=source, target=target, is_prefix=is_prefix, notes=notes))
        db.session.commit()

        data = bkp.export_synonyms()
        assert len(data) == 3

        Synonym.query.delete()
        db.session.commit()

        summary = bkp.import_synonyms(data)
        assert summary['created'] == 3
        assert Synonym.query.count() == 3

        second = bkp.import_synonyms(data)
        assert second['skipped'] == 3
        assert Synonym.query.count() == 3


# ── Usuarios ─────────────────────────────────────────────────────────────────

def test_users_export_excludes_password(app, db, make_user):
    with app.app_context():
        make_user(username='zz_export_user', password='whatever123')
        data = bkp.export_users()
        row = next(r for r in data if r['username'] == 'zz_export_user')
        assert 'password' not in row
        assert 'password_hash' not in row


def test_users_import_creates_with_random_password_and_forces_change(app, db):
    with app.app_context():
        from app.models.user import User
        data = [{
            'username': 'zz_restored_user', 'email': 'zz_restored@example.com', 'role': 'user',
            'active': True, 'must_change_password': False, 'template_name': None,
            'direct_permission_codes': [], 'created_by_username': None,
        }]
        summary = bkp.import_users(data)
        assert summary['created'] == 1
        user = User.query.filter_by(username='zz_restored_user').first()
        assert user is not None
        assert user.must_change_password is True
        assert 'zz_restored_user' in summary['generated_passwords']
        generated = summary['generated_passwords']['zz_restored_user']
        assert user.check_password(generated)


def test_users_update_mode_never_touches_password(app, db, make_user):
    with app.app_context():
        user = make_user(username='zz_update_user', password='originalpass123')
        original_hash = user.password_hash

        data = [{
            'username': 'zz_update_user', 'email': 'changed@example.com', 'role': 'user',
            'active': True, 'must_change_password': False, 'template_name': None,
            'direct_permission_codes': [], 'created_by_username': None,
        }]
        summary = bkp.import_users(data, mode='update')
        assert summary['updated'] == 1
        db.session.refresh(user)
        assert user.email == 'changed@example.com'
        assert user.password_hash == original_hash


def test_users_import_resolves_template_by_name(app, db):
    with app.app_context():
        from app.models.permission import seed_permissions_and_templates
        from app.models.user import User
        seed_permissions_and_templates()
        data = [{
            'username': 'zz_templated_user', 'email': 'zz_t@example.com', 'role': 'user', 'active': True,
            'must_change_password': False, 'template_name': 'Editor',
            'direct_permission_codes': ['professions.view'], 'created_by_username': None,
        }]
        summary = bkp.import_users(data)
        assert summary['created'] == 1
        user = User.query.filter_by(username='zz_templated_user').first()
        assert user.template.name == 'Editor'
        assert 'professions.view' in [p.code for p in user.direct_permissions]


# ── Profesiones ──────────────────────────────────────────────────────────────

def test_professions_round_trip_with_skills_talents_trappings_exits(app, db, make_profession, make_skill, make_talent):
    with app.app_context():
        from app.models.profession import Profession, ProfessionSkill, ProfessionTalent, ProfessionTrapping
        skill = make_skill(name_es='Percepción')
        talent = make_talent(name_es='Ambidiestro')
        soldado = make_profession(name='Soldado', ws=20, attacks=1)
        veterano = make_profession(name='Veterano')
        db.session.add(ProfessionSkill(profession_id=soldado.id, skill_id=skill.id, specialization='algo', choice_group=None))
        db.session.add(ProfessionTalent(profession_id=soldado.id, talent_id=talent.id))
        db.session.add(ProfessionTrapping(profession_id=soldado.id, name='Espada'))
        db.session.commit()
        soldado.exits = [veterano]
        db.session.commit()

        data = bkp.export_professions()
        soldado_row = next(r for r in data if r['name'] == 'Soldado')
        assert soldado_row['ws'] == 20
        assert soldado_row['skills'] == [{'skill_name': 'Percepción', 'specialization': 'algo', 'choice_group': None}]
        assert soldado_row['talents'] == [{'talent_name': 'Ambidiestro', 'specialization': None, 'choice_group': None}]
        assert soldado_row['trappings'] == ['Espada']
        assert soldado_row['exits'] == ['Veterano']

        soldado.exits = []
        db.session.commit()
        for p in Profession.query.all():
            db.session.delete(p)
        db.session.commit()

        summary = bkp.import_professions(data)
        assert summary['created'] == 2
        restored = Profession.query.filter_by(name='Soldado').first()
        assert restored.ws == 20
        assert [ps.skill.name_es for ps in restored.profession_skills] == ['Percepción']
        assert [pt.talent.name_es for pt in restored.profession_talents] == ['Ambidiestro']
        assert [t.name for t in restored.trappings] == ['Espada']
        assert [e.name for e in restored.exits] == ['Veterano']


def test_professions_import_skip_mode_does_not_duplicate(app, db, make_profession):
    with app.app_context():
        from app.models.profession import Profession
        make_profession(name='Alborotador')
        data = bkp.export_professions()
        summary = bkp.import_professions(data)
        assert summary['skipped'] == 1
        assert summary['created'] == 0
        assert Profession.query.count() == 1


def test_professions_import_warns_on_missing_skill(app, db):
    with app.app_context():
        from app.models.profession import Profession
        data = [{'name': 'Nueva', 'skills': [{'skill_name': 'No existe', 'specialization': None, 'choice_group': None}],
                 'talents': [], 'trappings': [], 'exits': []}]
        summary = bkp.import_professions(data)
        assert summary['created'] == 1
        assert any('No existe' in w for w in summary['warnings'])
        prof = Profession.query.filter_by(name='Nueva').first()
        assert prof.profession_skills == []


# ── Equipamiento ─────────────────────────────────────────────────────────────

def test_equipment_round_trip_with_base_item(app, db, make_equipment_item):
    with app.app_context():
        from app.models.equipment import EquipmentItem
        espada = make_equipment_item(name='Espada', category='arma')
        make_equipment_item(name='Espada Flamigera', category='arma', is_special=True,
                             base_item_id=espada.id, stats={'daño': '1D8+2'})

        data = bkp.export_equipment()
        flamigera_row = next(r for r in data if r['name'] == 'Espada Flamigera')
        assert flamigera_row['base_item_name'] == 'Espada'
        assert flamigera_row['base_item_category'] == 'arma'
        assert flamigera_row['stats'] == {'daño': '1D8+2'}

        EquipmentItem.query.delete()
        db.session.commit()

        summary = bkp.import_equipment(data)
        assert summary['created'] == 2
        restored = EquipmentItem.query.filter_by(name='Espada Flamigera').first()
        assert restored.base_item is not None
        assert restored.base_item.name == 'Espada'


def test_equipment_import_skip_mode_does_not_duplicate(app, db, make_equipment_item):
    with app.app_context():
        from app.models.equipment import EquipmentItem
        make_equipment_item(name='Daga', category='arma')
        data = bkp.export_equipment()
        summary = bkp.import_equipment(data)
        assert summary['skipped'] == 1
        assert summary['created'] == 0
        assert EquipmentItem.query.count() == 1


def test_equipment_import_disambiguates_same_name_by_subcategory_and_quality(app, db, make_equipment_item):
    """The catalog legitimately has several items sharing a name within a
    category (e.g. clothing quality tiers) - matching only on (name,
    category) used to collapse them into a single row and silently drop
    the rest on import."""
    with app.app_context():
        from app.models.equipment import EquipmentItem
        make_equipment_item(name='Abrigo', category='ropa', quality='mala')
        make_equipment_item(name='Abrigo', category='ropa', quality='normal')
        make_equipment_item(name='Abrigo', category='ropa', quality='buena')
        make_equipment_item(name='Abrigo', category='ropa', quality='excelente')

        data = bkp.export_equipment()
        EquipmentItem.query.delete()
        db.session.commit()

        summary = bkp.import_equipment(data)
        assert summary['created'] == 4
        assert summary['skipped'] == 0
        assert EquipmentItem.query.filter_by(name='Abrigo', category='ropa').count() == 4


def test_equipment_update_mode_overwrites(app, db, make_equipment_item):
    with app.app_context():
        from app.models.equipment import EquipmentItem
        item = make_equipment_item(name='Daga', category='arma', price_text='5 CO')
        data = bkp.export_equipment()
        data[0]['price_text'] = '8 CO'

        summary = bkp.import_equipment(data, mode='update')
        assert summary['updated'] == 1
        db.session.refresh(item)
        assert item.price_text == '8 CO'


def test_equipment_import_warns_on_missing_base_item(app, db):
    with app.app_context():
        from app.models.equipment import EquipmentItem
        data = [{'name': 'Espada Flamigera', 'category': 'arma', 'is_special': True,
                 'base_item_name': 'No existe', 'base_item_category': 'arma'}]
        summary = bkp.import_equipment(data)
        assert summary['created'] == 1
        assert any('No existe' in w for w in summary['warnings'])
        item = EquipmentItem.query.filter_by(name='Espada Flamigera').first()
        assert item.base_item_id is None


# ── Personajes ───────────────────────────────────────────────────────────────

def test_characters_round_trip_with_children(app, db, make_user, make_character, make_profession, make_skill, make_talent):
    with app.app_context():
        from app.models.character import (
            Character, CharacterProfession, CharacterSkill, CharacterTalent,
            CharacterTrait, CharacterAcquaintance, CharacterPossession, CharacterMagicItem,
        )
        user = make_user(username='zz_char_owner')
        prof = make_profession(name='Soldado')
        skill = make_skill(name_es='Percepción')
        talent = make_talent(name_es='Ambidiestro')
        char = make_character(user, name='Grimm', race='Enano', s_char=45)
        db.session.add(CharacterProfession(character_id=char.id, profession_id=prof.id, order=0, is_current=True))
        db.session.add(CharacterSkill(character_id=char.id, skill_id=skill.id, specialization='algo'))
        db.session.add(CharacterTalent(character_id=char.id, talent_id=talent.id, times_taken=2))
        db.session.add(CharacterTrait(character_id=char.id, category='personalidad', description='Terco'))
        db.session.add(CharacterAcquaintance(character_id=char.id, kind='amigo', description='Un tabernero'))
        db.session.add(CharacterPossession(character_id=char.id, name='Hacha'))
        db.session.add(CharacterMagicItem(character_id=char.id, category='amuleto', description='Brilla en la oscuridad'))
        db.session.commit()

        data = bkp.export_characters()
        row = next(r for r in data if r['name'] == 'Grimm')
        assert row['owner_username'] == 'zz_char_owner'
        assert row['race'] == 'Enano'
        assert row['s_char'] == 45
        assert row['professions'][0]['profession_name'] == 'Soldado'
        assert row['skills'][0]['skill_name'] == 'Percepción'
        assert row['talents'][0]['talent_name'] == 'Ambidiestro'
        assert row['traits'][0]['description'] == 'Terco'
        assert row['acquaintances'][0]['description'] == 'Un tabernero'
        assert row['possessions'] == ['Hacha']
        assert row['magic_items'][0]['description'] == 'Brilla en la oscuridad'

        Character.query.delete()
        db.session.commit()

        summary = bkp.import_characters(data)
        assert summary['created'] == 1
        restored = Character.query.filter_by(name='Grimm').first()
        assert restored.owner.username == 'zz_char_owner'
        assert restored.race == 'Enano'
        assert restored.professions[0].profession.name == 'Soldado'
        assert restored.skills[0].skill.name_es == 'Percepción'
        assert restored.talents[0].times_taken == 2
        assert restored.possessions[0].name == 'Hacha'


def test_characters_round_trip_includes_untersuchung_and_mochila_fields(app, db, make_user, make_character):
    with app.app_context():
        from app.models.character import Character
        user = make_user(username='zz_char_owner2')
        char = make_character(
            user, name='Marcada', es_untersuchung=True, grados_untersuchung=['Gato', 'Gato'],
            mochila_o_saco='saco', dinero_peniques_extra=57,
        )
        db.session.commit()

        data = bkp.export_characters()
        row = next(r for r in data if r['name'] == 'Marcada')
        assert row['grados_untersuchung'] == ['Gato', 'Gato']
        assert row['mochila_o_saco'] == 'saco'
        assert row['dinero_peniques_extra'] == 57

        Character.query.delete()
        db.session.commit()

        bkp.import_characters(data)
        restored = Character.query.filter_by(name='Marcada').first()
        assert restored.grados_untersuchung == ['Gato', 'Gato']
        assert restored.mochila_o_saco == 'saco'
        assert restored.dinero_peniques_extra == 57


def test_characters_round_trip_includes_inventory_purchases_and_money_grants(
    app, db, make_user, make_character, make_equipment_item,
):
    with app.app_context():
        from app.models.character import Character, CharacterMoneyGrant
        from app.models.equipment import CharacterInventoryItem, CharacterPurchase

        owner = make_user(username='zz_char_owner3')
        admin = make_user(username='zz_admin_granter', role='admin')
        char = make_character(owner, name='Rica', dinero_coronas=100)
        item = make_equipment_item(name='Daga backup', category='arma', subcategory='cuerpo_a_cuerpo',
                                   precio_peniques=240)

        db.session.add(CharacterInventoryItem(
            character_id=char.id, equipment_item_id=item.id, quality='buena',
            quantity=2, location='mochila_saco', notes='de repuesto',
        ))
        db.session.add(CharacterPurchase(
            character_id=char.id, equipment_item_id=item.id, item_name_snapshot='Daga backup',
            category_snapshot='arma', quality_snapshot='buena', precio_peniques_pagado=720,
            granted_by_gm=False, notes='comprada en la tienda',
        ))
        db.session.add(CharacterMoneyGrant(
            character_id=char.id, peniques=500, motivo='Recompensa de misión', granted_by_user_id=admin.id,
        ))
        db.session.commit()

        data = bkp.export_characters()
        row = next(r for r in data if r['name'] == 'Rica')
        assert row['inventory_items'][0]['equipment_item_name'] == 'Daga backup'
        assert row['inventory_items'][0]['quality'] == 'buena'
        assert row['inventory_items'][0]['quantity'] == 2
        assert row['inventory_items'][0]['location'] == 'mochila_saco'
        assert row['purchases'][0]['precio_peniques_pagado'] == 720
        assert row['money_grants'][0]['peniques'] == 500
        assert row['money_grants'][0]['granted_by_username'] == 'zz_admin_granter'

        for ii in CharacterInventoryItem.query.all():
            db.session.delete(ii)
        for p in CharacterPurchase.query.all():
            db.session.delete(p)
        for mg in CharacterMoneyGrant.query.all():
            db.session.delete(mg)
        Character.query.delete()
        db.session.commit()

        bkp.import_characters(data)
        restored = Character.query.filter_by(name='Rica').first()
        assert len(restored.inventory_items) == 1
        assert restored.inventory_items[0].equipment_item.name == 'Daga backup'
        assert restored.inventory_items[0].quantity == 2
        assert len(restored.purchases) == 1
        assert restored.purchases[0].precio_peniques_pagado == 720
        assert len(restored.money_grants) == 1
        assert restored.money_grants[0].peniques == 500
        assert restored.money_grants[0].granted_by.username == 'zz_admin_granter'


def test_characters_import_handles_missing_equipment_item_in_inventory(app, db, make_user):
    """An inventory/purchase row whose catalog item no longer exists must
    still import (as a custom/unlinked entry with a warning), not abort."""
    with app.app_context():
        from app.models.character import Character
        make_user(username='zz_char_owner4')
        db.session.commit()

        data = [{
            'owner_username': 'zz_char_owner4', 'name': 'Con objeto perdido',
            'inventory_items': [{
                'equipment_item_name': 'Objeto que ya no existe', 'equipment_item_category': 'arma',
                'equipment_item_subcategory': None, 'equipment_item_catalog_quality': None,
                'custom_name': None, 'quality': 'normal', 'quantity': 1, 'location': 'equipamiento',
                'notes': None, 'condition': None,
            }],
        }]
        summary = bkp.import_characters(data)
        assert summary['warnings']
        restored = Character.query.filter_by(name='Con objeto perdido').first()
        assert len(restored.inventory_items) == 1
        assert restored.inventory_items[0].equipment_item_id is None
        assert restored.inventory_items[0].custom_name == 'Objeto que ya no existe'


def test_characters_import_skips_and_warns_when_owner_missing(app, db):
    with app.app_context():
        data = [{'owner_username': 'no_existe', 'name': 'Fantasma'}]
        summary = bkp.import_characters(data)
        assert summary['skipped'] == 1
        assert any('no_existe' in w for w in summary['warnings'])


# ── Contactos + Vínculos ─────────────────────────────────────────────────────

def test_contacts_full_round_trip(app, db, make_user, make_character, make_profession, make_contact):
    with app.app_context():
        from app.models.contact import Contact
        user = make_user(username='zz_contact_owner')
        char = make_character(user, name='Grimm')
        prof = make_profession(name='Mercader')
        contact = make_contact(
            nombre='Hans', es_untersuchung=True, professions=[prof], created_by=user,
            raza='Humano', lugar_descanso='Un carromato', notas_director='Doble agente',
        )
        contact.estado = 'desconocido'
        db.session.commit()

        from app.models.contact_character_link import ContactCharacterLink, ContactApodo, ContactCharacterSalary
        from app.models.contact_note import ContactNote
        link = ContactCharacterLink(
            character_id=char.id, contact_id=contact.id, nivel=3, tipo_relacion=['Baza', 'Otra'],
            gm='GM1', mision='Rescate',
        )
        db.session.add(link)
        db.session.flush()
        db.session.add(ContactApodo(link_id=link.id, texto='El Gordo'))
        db.session.add(ContactCharacterSalary(link_id=link.id, profession_id=prof.id, tipo_sueldo='Artesanos', estado_habilidad='Buena'))
        db.session.add(ContactNote(contact_id=contact.id, character_id=char.id, content='Le debe un favor a Grimm'))
        db.session.commit()

        data = bkp.export_contacts_full()
        row = next(r for r in data if r['nombre'] == 'Hans')
        assert row['es_untersuchung'] is True
        assert row['estado'] == 'desconocido'
        assert row['raza'] == 'Humano'
        assert row['lugar_descanso'] == 'Un carromato'
        assert row['notas_director'] == 'Doble agente'
        assert row['created_by_username'] == 'zz_contact_owner'
        assert row['profesiones'] == ['Mercader']
        assert row['links'][0]['character_username'] == 'zz_contact_owner'
        assert row['links'][0]['character_name'] == 'Grimm'
        assert row['links'][0]['nivel'] == 3
        assert set(row['links'][0]['tipo_relacion']) == {'Baza', 'Otra'}
        assert row['links'][0]['apodos'] == ['El Gordo']
        assert row['links'][0]['salarios'][0]['profession_name'] == 'Mercader'
        assert row['notes'][0]['content'] == 'Le debe un favor a Grimm'
        assert row['notes'][0]['character_username'] == 'zz_contact_owner'

        for n in ContactNote.query.all():
            db.session.delete(n)
        for l in link.__class__.query.all():
            db.session.delete(l)
        for c in Contact.query.all():
            db.session.delete(c)
        db.session.commit()

        summary = bkp.import_contacts_full(data)
        assert summary['created'] == 1
        restored = Contact.query.filter_by(nombre='Hans').first()
        assert restored.es_untersuchung is True
        assert restored.estado == 'desconocido'
        assert restored.raza == 'Humano'
        assert restored.lugar_descanso == 'Un carromato'
        assert restored.notas_director == 'Doble agente'
        assert restored.created_by.username == 'zz_contact_owner'
        assert [cp.profession.name for cp in restored.professions] == ['Mercader']
        assert len(restored.character_links) == 1
        restored_link = restored.character_links[0]
        assert restored_link.nivel == 3
        assert set(restored_link.tipo_relacion) == {'Baza', 'Otra'}
        assert restored_link.apodos[0].texto == 'El Gordo'
        assert restored_link.salarios[0].tipo_sueldo == 'Artesanos'
        assert len(restored.notes) == 1
        assert restored.notes[0].content == 'Le debe un favor a Grimm'


def test_contacts_full_import_backfills_estado_from_legacy_vivo_flag(app, db):
    """Old backups made before "vivo" (bool) was replaced by "estado" must
    still import sensibly instead of erroring or silently dropping the fact."""
    with app.app_context():
        from app.models.contact import Contact
        data = [
            {'nombre': 'Legacy vivo', 'es_untersuchung': False, 'is_visible': True, 'profesiones': [],
             'vivo': True, 'links': []},
            {'nombre': 'Legacy muerto', 'es_untersuchung': False, 'is_visible': True, 'profesiones': [],
             'vivo': False, 'links': []},
        ]
        bkp.import_contacts_full(data)
        assert Contact.query.filter_by(nombre='Legacy vivo').first().estado == 'vivo'
        assert Contact.query.filter_by(nombre='Legacy muerto').first().estado == 'muerto'


def test_contacts_full_import_warns_on_missing_character(app, db):
    with app.app_context():
        from app.models.contact import Contact
        data = [{
            'nombre': 'Sin vinculo', 'es_untersuchung': False, 'is_visible': True, 'profesiones': [],
            'links': [{'character_username': 'no_existe', 'character_name': 'Nadie', 'nivel': 1,
                       'tipo_relacion': None, 'organizacion_secta': None,
                       'creacion': False, 'gm': None, 'mision': None, 'apodos': [], 'salarios': []}],
        }]
        summary = bkp.import_contacts_full(data)
        assert summary['created'] == 1
        assert any('no_existe' in w for w in summary['warnings'])
        contact = Contact.query.filter_by(nombre='Sin vinculo').first()
        assert contact.character_links == []


# ── Backup completo ──────────────────────────────────────────────────────────

# ── Recetas ──────────────────────────────────────────────────────────────────

def test_recipes_round_trip(app, db, make_user):
    with app.app_context():
        from app.models.food import CookingMethod, Ingredient, Recipe

        author = make_user(username='zz_recipe_author')
        approver = make_user(username='zz_recipe_approver', role='admin')
        method = CookingMethod(nombre='Guisado zz', duracion_dias=1, complejidad_base=1,
                               ingredientes_permitidos=2, condimentos_permitidos=1)
        ing1 = Ingredient(nombre='Zanahoria zz')
        ing2 = Ingredient(nombre='Sal zz')
        db.session.add_all([method, ing1, ing2])
        db.session.commit()

        recipe = Recipe(
            nombre='Guiso de la abuela zz', vigor=5, moral=2, cooking_method_id=method.id,
            calidad='Buena', complejidad=4, status='pendiente', notas='receta de prueba',
            created_by_id=author.id, ingrediente_1_id=ing1.id, condimento_1_id=ing2.id,
        )
        db.session.add(recipe)
        db.session.commit()

        data = bkp.export_recipes()
        row = next(r for r in data if r['nombre'] == 'Guiso de la abuela zz')
        assert row['cooking_method_name'] == 'Guisado zz'
        assert row['ingredientes'] == ['Zanahoria zz']
        assert row['condimentos'] == ['Sal zz']
        assert row['created_by_username'] == 'zz_recipe_author'
        assert row['status'] == 'pendiente'

        Recipe.query.delete()
        db.session.commit()

        summary = bkp.import_recipes(data)
        assert summary['created'] >= 1
        restored = Recipe.query.filter_by(nombre='Guiso de la abuela zz').first()
        assert restored.cooking_method.nombre == 'Guisado zz'
        assert restored.ingrediente_1.nombre == 'Zanahoria zz'
        assert restored.condimento_1.nombre == 'Sal zz'
        assert restored.created_by.username == 'zz_recipe_author'
        assert restored.status == 'pendiente'


def test_recipes_import_warns_on_missing_ingredient(app, db):
    with app.app_context():
        from app.models.food import Recipe
        data = [{'nombre': 'Receta huerfana', 'ingredientes': ['No existe'], 'condimentos': []}]
        summary = bkp.import_recipes(data)
        assert summary['created'] == 1
        assert summary['warnings']
        restored = Recipe.query.filter_by(nombre='Receta huerfana').first()
        assert restored.ingrediente_1_id is None


# ── Imágenes (Profesiones/Equipamiento/Recetas/Contactos/Personajes) ───────────
# El JSON de backup solo llevaba `image_path`; sin los bytes en base64, una
# instancia nueva (o cualquiera sin acceso al `uploads/` original) se quedaba
# sin fotos aunque el JSON se reimportase perfectamente. Cada test escribe un
# fichero real bajo UPLOAD_FOLDER, lo borra tras exportar, y comprueba que
# importar lo reconstruye con el mismo contenido.

def _write_fake_image(app, relative_path, content=b'fake-image-bytes'):
    full_path = os.path.join(app.config['UPLOAD_FOLDER'], relative_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, 'wb') as f:
        f.write(content)
    return full_path


def test_profession_image_round_trips_through_backup(app, db, make_profession, tmp_path):
    app.config['UPLOAD_FOLDER'] = str(tmp_path)
    with app.app_context():
        from app.models.profession import Profession
        make_profession(name='Zz Con Foto', image_path='professions/zz.jpg')
        _write_fake_image(app, 'professions/zz.jpg', b'profession-bytes')

        data = bkp.export_professions()
        row = next(r for r in data if r['name'] == 'Zz Con Foto')
        assert base64.b64decode(row['image_data_b64']) == b'profession-bytes'

        Profession.query.filter_by(name='Zz Con Foto').delete()
        db.session.commit()
        (tmp_path / 'professions' / 'zz.jpg').unlink()

        bkp.import_professions(data)
        restored_path = tmp_path / 'professions' / 'zz.jpg'
        assert restored_path.read_bytes() == b'profession-bytes'


def test_equipment_image_round_trips_through_backup(app, db, make_equipment_item, tmp_path):
    app.config['UPLOAD_FOLDER'] = str(tmp_path)
    with app.app_context():
        from app.models.equipment import EquipmentItem
        make_equipment_item(name='Zz Espada Foto', category='arma', image_path='equipamiento/zz.jpg')
        _write_fake_image(app, 'equipamiento/zz.jpg', b'equipment-bytes')

        data = bkp.export_equipment()
        row = next(r for r in data if r['name'] == 'Zz Espada Foto')
        assert base64.b64decode(row['image_data_b64']) == b'equipment-bytes'

        EquipmentItem.query.filter_by(name='Zz Espada Foto').delete()
        db.session.commit()
        (tmp_path / 'equipamiento' / 'zz.jpg').unlink()

        bkp.import_equipment(data)
        restored_path = tmp_path / 'equipamiento' / 'zz.jpg'
        assert restored_path.read_bytes() == b'equipment-bytes'


def test_recipe_image_round_trips_through_backup(app, db, tmp_path):
    app.config['UPLOAD_FOLDER'] = str(tmp_path)
    with app.app_context():
        from app.models.food import Recipe
        recipe = Recipe(nombre='Zz Receta Foto', status='aprobada', image_path='recetas/zz.jpg')
        db.session.add(recipe)
        db.session.commit()
        _write_fake_image(app, 'recetas/zz.jpg', b'recipe-bytes')

        data = bkp.export_recipes()
        row = next(r for r in data if r['nombre'] == 'Zz Receta Foto')
        assert base64.b64decode(row['image_data_b64']) == b'recipe-bytes'

        Recipe.query.filter_by(nombre='Zz Receta Foto').delete()
        db.session.commit()
        (tmp_path / 'recetas' / 'zz.jpg').unlink()

        bkp.import_recipes(data)
        restored_path = tmp_path / 'recetas' / 'zz.jpg'
        assert restored_path.read_bytes() == b'recipe-bytes'


def test_contact_image_round_trips_through_backup(app, db, make_contact, tmp_path):
    app.config['UPLOAD_FOLDER'] = str(tmp_path)
    with app.app_context():
        from app.models.contact import Contact
        make_contact(nombre='Zz Contacto Foto', image_path='contactos/zz.jpg')
        _write_fake_image(app, 'contactos/zz.jpg', b'contact-bytes')

        data = bkp.export_contacts_full()
        row = next(r for r in data if r['nombre'] == 'Zz Contacto Foto')
        assert base64.b64decode(row['image_data_b64']) == b'contact-bytes'

        Contact.query.filter_by(nombre='Zz Contacto Foto').delete()
        db.session.commit()
        (tmp_path / 'contactos' / 'zz.jpg').unlink()

        bkp.import_contacts_full(data)
        restored_path = tmp_path / 'contactos' / 'zz.jpg'
        assert restored_path.read_bytes() == b'contact-bytes'


def test_character_image_round_trips_through_backup(app, db, make_user, make_character, tmp_path):
    app.config['UPLOAD_FOLDER'] = str(tmp_path)
    with app.app_context():
        from app.models.character import Character
        user = make_user(username='zz_char_photo_owner')
        make_character(user, name='Zz Personaje Foto', image_path='personajes/zz.jpg')
        _write_fake_image(app, 'personajes/zz.jpg', b'character-bytes')

        data = bkp.export_characters()
        row = next(r for r in data if r['name'] == 'Zz Personaje Foto')
        assert base64.b64decode(row['image_data_b64']) == b'character-bytes'

        Character.query.filter_by(name='Zz Personaje Foto').delete()
        db.session.commit()
        (tmp_path / 'personajes' / 'zz.jpg').unlink()

        bkp.import_characters(data)
        restored_path = tmp_path / 'personajes' / 'zz.jpg'
        assert restored_path.read_bytes() == b'character-bytes'


def test_image_backup_is_noop_without_b64_data(app, db, make_profession, tmp_path):
    """Old backups (taken before this field existed) or rows without a photo
    must import cleanly without trying to write anything."""
    app.config['UPLOAD_FOLDER'] = str(tmp_path)
    with app.app_context():
        data = [{'name': 'Zz Sin Foto', 'image_path': None, 'skills': [], 'talents': [], 'trappings': [], 'exits': []}]
        summary = bkp.import_professions(data)
        assert summary['created'] == 1
        assert list(tmp_path.iterdir()) == []


# ── Backup completo ──────────────────────────────────────────────────────────

def test_full_backup_round_trip(app, db, make_user, make_character, make_profession):
    with app.app_context():
        from app.models.permission import seed_permissions_and_templates
        from app.models.user import User
        from app.models.profession import Profession
        from app.models.character import Character
        seed_permissions_and_templates()
        user = make_user(username='zz_full_backup_user')
        make_profession(name='Soldado')
        make_character(user, name='Grimm')

        data = bkp.export_full_backup()
        assert data['version'] == bkp.BACKUP_VERSION
        assert 'exported_at' in data
        assert 'recipes' in data
        assert any(u['username'] == 'zz_full_backup_user' for u in data['users'])
        assert any(p['name'] == 'Soldado' for p in data['professions'])
        assert any(c['name'] == 'Grimm' for c in data['characters'])

        Character.query.delete()
        Profession.query.delete()
        User.query.filter_by(username='zz_full_backup_user').delete()
        db.session.commit()

        summary = bkp.import_full_backup(data)
        assert 'recipes' in summary
        assert summary['users']['created'] >= 1
        assert summary['professions']['created'] >= 1
        assert summary['characters']['created'] >= 1
        assert Character.query.filter_by(name='Grimm').first() is not None

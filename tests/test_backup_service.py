"""Round-trip tests for app/services/backup_service.py: every export_*/import_*
pair must reproduce the original data when re-imported into an empty table,
'update' mode must overwrite in place without duplicating, and a dangling
cross-reference (unknown username/profession/skill/talent) must be skipped
with a warning rather than raising."""
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
        contact = make_contact(nombre='Hans', es_untersuchung=True, professions=[prof])

        from app.models.contact_character_link import ContactCharacterLink, ContactApodo, ContactCharacterSalary, ContactCharacterVisibility
        link = ContactCharacterLink(character_id=char.id, contact_id=contact.id, nivel=3, gm='GM1', mision='Rescate')
        db.session.add(link)
        db.session.flush()
        db.session.add(ContactApodo(link_id=link.id, texto='El Gordo'))
        db.session.add(ContactCharacterSalary(link_id=link.id, profession_id=prof.id, tipo_sueldo='Artesanos', estado_habilidad='Buena'))
        db.session.add(ContactCharacterVisibility(contact_id=contact.id, character_id=char.id, nivel='total'))
        db.session.commit()

        data = bkp.export_contacts_full()
        row = next(r for r in data if r['nombre'] == 'Hans')
        assert row['es_untersuchung'] is True
        assert row['profesiones'] == ['Mercader']
        assert row['links'][0]['character_username'] == 'zz_contact_owner'
        assert row['links'][0]['character_name'] == 'Grimm'
        assert row['links'][0]['nivel'] == 3
        assert row['links'][0]['apodos'] == ['El Gordo']
        assert row['links'][0]['salarios'][0]['profession_name'] == 'Mercader'
        assert row['visibilidades'][0]['nivel'] == 'total'

        for l in link.__class__.query.all():
            db.session.delete(l)
        for v in ContactCharacterVisibility.query.all():
            db.session.delete(v)
        for c in Contact.query.all():
            db.session.delete(c)
        db.session.commit()

        summary = bkp.import_contacts_full(data)
        assert summary['created'] == 1
        restored = Contact.query.filter_by(nombre='Hans').first()
        assert restored.es_untersuchung is True
        assert [cp.profession.name for cp in restored.professions] == ['Mercader']
        assert len(restored.character_links) == 1
        restored_link = restored.character_links[0]
        assert restored_link.nivel == 3
        assert restored_link.apodos[0].texto == 'El Gordo'
        assert restored_link.salarios[0].tipo_sueldo == 'Artesanos'
        assert len(restored.character_visibilities) == 1


def test_contacts_full_import_warns_on_missing_character(app, db):
    with app.app_context():
        from app.models.contact import Contact
        data = [{
            'nombre': 'Sin vinculo', 'es_untersuchung': False, 'is_visible': True, 'profesiones': [],
            'links': [{'character_username': 'no_existe', 'character_name': 'Nadie', 'nivel': 1,
                       'organizacion_secta': None, 'lugar_residencia': None, 'lugar_contacto': None,
                       'creacion': False, 'gm': None, 'mision': None, 'apodos': [], 'salarios': []}],
            'visibilidades': [],
        }]
        summary = bkp.import_contacts_full(data)
        assert summary['created'] == 1
        assert any('no_existe' in w for w in summary['warnings'])
        contact = Contact.query.filter_by(nombre='Sin vinculo').first()
        assert contact.character_links == []


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
        assert any(u['username'] == 'zz_full_backup_user' for u in data['users'])
        assert any(p['name'] == 'Soldado' for p in data['professions'])
        assert any(c['name'] == 'Grimm' for c in data['characters'])

        Character.query.delete()
        Profession.query.delete()
        User.query.filter_by(username='zz_full_backup_user').delete()
        db.session.commit()

        summary = bkp.import_full_backup(data)
        assert summary['users']['created'] >= 1
        assert summary['professions']['created'] >= 1
        assert summary['characters']['created'] >= 1
        assert Character.query.filter_by(name='Grimm').first() is not None

"""Tests for professions: listing, detail, CRUD, permission gating,
and exits/entries (career links)."""
from app.models.profession import Profession
from app.models.permission import Permission


def _grant(db, user, code):
    user.direct_permissions.append(db.session.get(Permission, code))
    db.session.commit()


def test_list_professions_is_public(client, make_profession):
    make_profession(name='Alborotador')
    resp = client.get('/profesiones/')
    assert resp.status_code == 200
    assert 'Alborotador'.encode('utf-8') in resp.data


def test_list_professions_filters_by_type(client, make_profession):
    make_profession(name='Alborotador', type='basic')
    make_profession(name='Caballero', type='advanced')
    resp = client.get('/profesiones/?type=advanced')
    assert b'Caballero' in resp.data
    assert b'Alborotador' not in resp.data


def test_list_professions_filters_by_search(client, make_profession):
    make_profession(name='Alborotador')
    make_profession(name='Caballero')
    resp = client.get('/profesiones/?q=Alboro')
    assert b'Alborotador' in resp.data
    assert b'Caballero' not in resp.data


def test_detail_is_public(client, make_profession):
    prof = make_profession(name='Alborotador')
    resp = client.get(f'/profesiones/{prof.id}')
    assert resp.status_code == 200
    assert 'Alborotador'.encode('utf-8') in resp.data


def test_detail_404_for_unknown_profession(client):
    resp = client.get('/profesiones/99999')
    assert resp.status_code == 404


def test_create_requires_login(client):
    resp = client.get('/profesiones/nueva')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_create_requires_permission(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/profesiones/nueva')
    assert resp.status_code == 403


def test_create_profession_with_permission(db, client, regular_user, login_as):
    _grant(db, regular_user, 'professions.edit')
    login_as(client, regular_user, 'userpass123')

    resp = client.post('/profesiones/nueva', data={
        'name': 'Bufón', 'type': 'basic',
    }, follow_redirects=True)
    assert resp.status_code == 200

    prof = Profession.query.filter_by(name='Bufón').first()
    assert prof is not None
    assert prof.created_by_id == regular_user.id
    assert prof.type == 'basic'


def test_create_profession_persists_primary_and_secondary_characteristics(db, client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    resp = client.post('/profesiones/nueva', data={
        'name': 'Soldado', 'type': 'basic',
        'ws': '5', 'bs': '5', 'movement': '1', 'fate_points': '2',
    }, follow_redirects=True)
    assert resp.status_code == 200

    prof = Profession.query.filter_by(name='Soldado').first()
    assert prof.ws == 5
    assert prof.bs == 5
    assert prof.movement == 1
    assert prof.fate_points == 2


def test_create_profession_with_skills_and_talents(db, client, admin_user, login_as, make_skill, make_talent):
    skill = make_skill(name_es='Percepción')
    talent = make_talent(name_es='Ambidiestro')
    login_as(client, admin_user, 'adminpass123')

    resp = client.post('/profesiones/nueva', data={
        'name': 'Explorador', 'type': 'basic',
        f'skill_{skill.id}': 'on',
        f'talent_{talent.id}': 'on',
    }, follow_redirects=True)
    assert resp.status_code == 200

    prof = Profession.query.filter_by(name='Explorador').first()
    assert len(prof.profession_skills) == 1
    assert prof.profession_skills[0].skill_id == skill.id
    assert len(prof.profession_talents) == 1
    assert prof.profession_talents[0].talent_id == talent.id


def test_create_profession_with_trappings(db, client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    resp = client.post('/profesiones/nueva', data={
        'name': 'Mercader', 'type': 'basic',
        'trappings': 'Vara de medir, Ábaco, Ropa buena',
    }, follow_redirects=True)
    assert resp.status_code == 200

    prof = Profession.query.filter_by(name='Mercader').first()
    names = {t.name for t in prof.trappings}
    assert names == {'Vara de medir', 'Ábaco', 'Ropa buena'}


def test_create_profession_with_exits(db, client, admin_user, login_as, make_profession):
    target = make_profession(name='Veterano', type='advanced')
    login_as(client, admin_user, 'adminpass123')

    resp = client.post('/profesiones/nueva', data={
        'name': 'Soldado', 'type': 'basic',
        'exits': [str(target.id)],
    }, follow_redirects=True)
    assert resp.status_code == 200

    prof = Profession.query.filter_by(name='Soldado').first()
    assert target in prof.exits
    assert prof in target.entries


def test_edit_requires_permission(client, regular_user, login_as, make_profession):
    prof = make_profession(name='Alborotador')
    login_as(client, regular_user, 'userpass123')
    resp = client.get(f'/profesiones/{prof.id}/editar')
    assert resp.status_code == 403


def test_edit_updates_fields(db, client, admin_user, login_as, make_profession):
    prof = make_profession(name='Alborotador', type='basic')
    login_as(client, admin_user, 'adminpass123')

    resp = client.post(f'/profesiones/{prof.id}/editar', data={
        'name': 'Alborotador Reformado', 'type': 'advanced',
    }, follow_redirects=True)
    assert resp.status_code == 200

    db.session.refresh(prof)
    assert prof.name == 'Alborotador Reformado'
    assert prof.type == 'advanced'


def test_edit_replaces_skills_and_talents(db, client, admin_user, login_as, make_profession, make_skill):
    prof = make_profession(name='Alborotador')
    skill1 = make_skill(name_es='Percepción')
    skill2 = make_skill(name_es='Callejeo')

    from app.models.profession import ProfessionSkill
    db.session.add(ProfessionSkill(profession_id=prof.id, skill_id=skill1.id))
    db.session.commit()

    login_as(client, admin_user, 'adminpass123')
    resp = client.post(f'/profesiones/{prof.id}/editar', data={
        'name': 'Alborotador', 'type': 'basic',
        f'skill_{skill2.id}': 'on',
    }, follow_redirects=True)
    assert resp.status_code == 200

    db.session.refresh(prof)
    skill_ids = {ps.skill_id for ps in prof.profession_skills}
    assert skill_ids == {skill2.id}


def test_delete_requires_permission(db, client, regular_user, login_as, make_profession):
    prof = make_profession(name='Alborotador')
    login_as(client, regular_user, 'userpass123')
    resp = client.post(f'/profesiones/{prof.id}/eliminar')
    assert resp.status_code == 403
    assert db.session.get(Profession, prof.id) is not None


def test_delete_profession(db, client, admin_user, login_as, make_profession):
    prof = make_profession(name='Alborotador')
    prof_id = prof.id
    login_as(client, admin_user, 'adminpass123')

    resp = client.post(f'/profesiones/{prof_id}/eliminar', follow_redirects=True)
    assert resp.status_code == 200
    assert db.session.get(Profession, prof_id) is None


def test_delete_profession_cascades_relations(db, client, admin_user, login_as, make_profession, make_skill):
    prof = make_profession(name='Alborotador')
    skill = make_skill(name_es='Percepción')
    from app.models.profession import ProfessionSkill
    db.session.add(ProfessionSkill(profession_id=prof.id, skill_id=skill.id))
    db.session.commit()
    prof_id = prof.id

    login_as(client, admin_user, 'adminpass123')
    client.post(f'/profesiones/{prof_id}/eliminar', follow_redirects=True)

    assert ProfessionSkill.query.filter_by(profession_id=prof_id).count() == 0


# ── Backup: exportar/importar ───────────────────────────────────────────────

def test_export_requires_permission(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/profesiones/exportar')
    assert resp.status_code == 403


def test_export_returns_json_with_nested_data(db, client, regular_user, login_as, make_profession, make_skill):
    _grant(db, regular_user, 'professions.edit')
    prof = make_profession(name='Alborotador')
    skill = make_skill(name_es='Percepción')
    from app.models.profession import ProfessionSkill
    db.session.add(ProfessionSkill(profession_id=prof.id, skill_id=skill.id, specialization=None, choice_group=None))
    db.session.commit()

    login_as(client, regular_user, 'userpass123')
    resp = client.get('/profesiones/exportar')
    assert resp.status_code == 200
    assert resp.mimetype == 'application/json'

    import json
    data = json.loads(resp.data)
    row = next(r for r in data if r['name'] == 'Alborotador')
    assert row['skills'] == [{'skill_name': 'Percepción', 'specialization': None, 'choice_group': None}]


def test_import_requires_permission(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/profesiones/importar')
    assert resp.status_code == 403


def test_import_creates_professions_from_json(db, client, regular_user, login_as):
    _grant(db, regular_user, 'professions.edit')
    login_as(client, regular_user, 'userpass123')

    import io
    import json
    payload = json.dumps([{
        'name': 'Bufón Importado', 'type': 'basic', 'ws': 10,
        'skills': [], 'talents': [], 'trappings': [], 'exits': [],
    }]).encode('utf-8')

    resp = client.post('/profesiones/importar', data={
        'file': (io.BytesIO(payload), 'profesiones.json'),
        'mode': 'skip',
    }, content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200

    prof = Profession.query.filter_by(name='Bufón Importado').first()
    assert prof is not None
    assert prof.ws == 10

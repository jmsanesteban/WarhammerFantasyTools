"""Tests for talent specializations (e.g. 'Especialista en armas (Parada)'),
which now use the same entry-list model as specialization skills like
'Sabiduría académica' instead of a free-text field."""
import json

from app.routes.professions import _load_talent_specs, _load_specializations
from app.models.profession import ProfessionTalent


def test_load_talent_specs_matches_by_normalized_name(make_talent):
    talent = make_talent(name_es='Especialista en armas')
    specs = _load_talent_specs([talent])
    assert talent.id in specs
    names = {entry['nombre'] for entry in specs[talent.id]}
    assert 'Parada' in names
    assert 'Arrojadiza' in names


def test_load_talent_specs_ignores_talents_without_predefined_specs(make_talent):
    talent = make_talent(name_es='Ambidiestro')
    specs = _load_talent_specs([talent])
    assert talent.id not in specs


def test_load_specializations_is_shared_by_skills_and_talents(make_skill, make_talent):
    skill = make_skill(name_es='Sabiduría académica')
    talent = make_talent(name_es='Especialista en armas')
    skill_specs  = _load_specializations([skill],  'skill_specializations.json')
    talent_specs = _load_specializations([talent], 'talent_specializations.json')
    assert skill.id in skill_specs
    assert talent.id in talent_specs


def test_create_profession_with_talent_spec_entries(db, client, admin_user, login_as, make_talent):
    talent = make_talent(name_es='Especialista en armas')
    login_as(client, admin_user, 'adminpass123')

    entries = json.dumps([{'spec': 'Parada', 'group': None}, {'spec': 'Arrojadiza', 'group': None}])
    resp = client.post('/profesiones/nueva', data={
        'name': 'Asesino', 'type': 'advanced',
        f'talent_{talent.id}': '1',
        f'talent_spec_{talent.id}': entries,
    }, follow_redirects=True)
    assert resp.status_code == 200

    rows = ProfessionTalent.query.filter_by(talent_id=talent.id).all()
    specs = {r.specialization for r in rows}
    assert specs == {'Parada', 'Arrojadiza'}


def test_edit_profession_replaces_talent_spec_entries(db, client, admin_user, login_as, make_profession, make_talent):
    talent = make_talent(name_es='Especialista en armas')
    prof = make_profession(name='Asesino', type='advanced')
    db.session.add(ProfessionTalent(profession_id=prof.id, talent_id=talent.id, specialization='Parada'))
    db.session.commit()

    login_as(client, admin_user, 'adminpass123')
    entries = json.dumps([{'spec': 'Presa', 'group': None}])
    resp = client.post(f'/profesiones/{prof.id}/editar', data={
        'name': 'Asesino', 'type': 'advanced',
        f'talent_{talent.id}': '1',
        f'talent_spec_{talent.id}': entries,
    }, follow_redirects=True)
    assert resp.status_code == 200

    rows = ProfessionTalent.query.filter_by(profession_id=prof.id, talent_id=talent.id).all()
    assert {r.specialization for r in rows} == {'Presa'}


def test_talent_spec_entries_support_choice_groups(db, client, admin_user, login_as, make_talent):
    talent = make_talent(name_es='Especialista en armas')
    login_as(client, admin_user, 'adminpass123')

    entries = json.dumps([
        {'spec': 'Parada', 'group': 1},
        {'spec': 'Arrojadiza', 'group': 1},
    ])
    client.post('/profesiones/nueva', data={
        'name': 'Asesino', 'type': 'advanced',
        f'talent_{talent.id}': '1',
        f'talent_spec_{talent.id}': entries,
    }, follow_redirects=True)

    rows = ProfessionTalent.query.filter_by(talent_id=talent.id).all()
    assert all(r.choice_group == 1 for r in rows)


def test_plain_talent_still_uses_comma_separated_free_text(db, client, admin_user, login_as, make_talent):
    """Talents without predefined specs must keep working exactly as before."""
    talent = make_talent(name_es='Oficio')
    login_as(client, admin_user, 'adminpass123')

    client.post('/profesiones/nueva', data={
        'name': 'Artesano', 'type': 'basic',
        f'talent_{talent.id}': '1',
        f'talent_spec_{talent.id}': 'Herrero, Carpintero',
    }, follow_redirects=True)

    rows = ProfessionTalent.query.filter_by(talent_id=talent.id).all()
    assert {r.specialization for r in rows} == {'Herrero', 'Carpintero'}

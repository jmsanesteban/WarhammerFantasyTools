"""Tests for skills and talents: listing/search, CRUD, permission gating,
and plain-text import/export."""
import io
from app.models.skill import Skill
from app.models.talent import Talent
from app.models.permission import Permission


def _grant(db, user, code):
    user.direct_permissions.append(db.session.get(Permission, code))
    db.session.commit()


# ── Skills ───────────────────────────────────────────────────────────────────

def test_list_skills_is_public(client, make_skill):
    make_skill(name_es='Percepción')
    resp = client.get('/habilidades')
    assert resp.status_code == 200
    assert 'Percepción'.encode('utf-8') in resp.data


def test_list_skills_search_by_name(client, make_skill):
    make_skill(name_es='Percepción')
    make_skill(name_es='Callejeo')
    resp = client.get('/habilidades?q=Percep')
    assert 'Percepción'.encode('utf-8') in resp.data
    assert b'Callejeo' not in resp.data


def test_list_skills_filter_by_tipo(client, make_skill):
    make_skill(name_es='Percepción', is_advanced=False)
    make_skill(name_es='Actuar', is_advanced=True)
    resp = client.get('/habilidades?tipo=advanced')
    assert b'Actuar' in resp.data
    assert 'Percepción'.encode('utf-8') not in resp.data


def test_skill_detail_shows_professions_using_it(client, make_skill, make_profession, db):
    skill = make_skill(name_es='Percepción')
    prof = make_profession(name='Alborotador')
    from app.models.profession import ProfessionSkill
    db.session.add(ProfessionSkill(profession_id=prof.id, skill_id=skill.id))
    db.session.commit()

    resp = client.get(f'/habilidades/{skill.id}')
    assert resp.status_code == 200
    assert b'Alborotador' in resp.data


def test_search_skills_page_embeds_all_skill_names(client, make_skill):
    # Names picked without accents: they're embedded via Jinja's |tojson
    # filter (ensure_ascii), so an accented name would show up as a \uXXXX
    # escape rather than the literal character in the raw response bytes.
    make_skill(name_es='Regatear')
    make_skill(name_es='Callejeo')
    resp = client.get('/habilidades/buscar')
    assert resp.status_code == 200
    assert b'Regatear' in resp.data
    assert b'Callejeo' in resp.data


def test_create_skill_requires_permission(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/habilidades/nueva')
    assert resp.status_code == 403


def test_create_skill_with_permission(db, client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    resp = client.post('/habilidades/nueva', data={
        'name_es': 'Percepción', 'is_advanced': '',
        'caracteristicas': 'Intelig.',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert Skill.query.filter_by(name_es='Percepción').first() is not None


def test_edit_skill(db, client, admin_user, login_as, make_skill):
    skill = make_skill(name_es='Percepción')
    login_as(client, admin_user, 'adminpass123')
    resp = client.post(f'/habilidades/{skill.id}/editar', data={
        'name_es': 'Percepción Mejorada', 'is_advanced': 'on',
    }, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(skill)
    assert skill.name_es == 'Percepción Mejorada'
    assert skill.is_advanced is True


# ── Skill/talent name-collision guard (a profession may only ever reference
# catalog entries - a stray near-duplicate like 'Preparar veneno' next to
# the real 'Preparar venenos' is exactly how that invariant breaks) ────────

def test_create_skill_blocks_exact_duplicate(db, client, admin_user, login_as, make_skill):
    make_skill(name_es='Percepción')
    login_as(client, admin_user, 'adminpass123')
    resp = client.post('/habilidades/nueva', data={'name_es': 'Percepción'}, follow_redirects=True)
    assert resp.status_code == 200
    assert Skill.query.filter_by(name_es='Percepción').count() == 1
    assert 'ya existe'.encode('utf-8') in resp.data.lower()


def test_create_skill_warns_on_near_duplicate_but_still_creates(db, client, admin_user, login_as, make_skill):
    make_skill(name_es='Preparar venenos')
    login_as(client, admin_user, 'adminpass123')
    resp = client.post('/habilidades/nueva', data={'name_es': 'Preparar veneno'}, follow_redirects=True)
    assert resp.status_code == 200
    assert Skill.query.filter_by(name_es='Preparar veneno').first() is not None
    assert 'aviso'.encode('utf-8') in resp.data.lower()


def test_edit_skill_blocks_rename_into_existing_duplicate(db, client, admin_user, login_as, make_skill):
    make_skill(name_es='Percepción')
    other = make_skill(name_es='Callejeo')
    login_as(client, admin_user, 'adminpass123')
    resp = client.post(f'/habilidades/{other.id}/editar', data={'name_es': 'Percepción'}, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(other)
    assert other.name_es == 'Callejeo'


def test_delete_skill_requires_permission(client, regular_user, login_as, make_skill):
    skill = make_skill(name_es='Percepción')
    login_as(client, regular_user, 'userpass123')
    resp = client.post(f'/habilidades/{skill.id}/eliminar')
    assert resp.status_code == 403


def test_delete_skill(db, client, admin_user, login_as, make_skill):
    skill = make_skill(name_es='Percepción')
    skill_id = skill.id
    login_as(client, admin_user, 'adminpass123')
    resp = client.post(f'/habilidades/{skill_id}/eliminar', follow_redirects=True)
    assert resp.status_code == 200
    assert db.session.get(Skill, skill_id) is None


def test_import_skills_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/habilidades/importar')
    assert resp.status_code == 403


def test_import_skills_from_text_creates_new(db, client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    text = (
        'Nombre: Percepción\n'
        'Tipo: Básica.\n'
        'Características: Intelig.\n'
        'Descripción: Detectar cosas.\n'
    )
    data = {'file': (io.BytesIO(text.encode('utf-8')), 'skills.txt'), 'mode': 'skip'}
    resp = client.post('/habilidades/importar', data=data,
                       content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200
    skill = Skill.query.filter_by(name_es='Percepción').first()
    assert skill is not None
    assert skill.is_advanced is False
    assert skill.caracteristicas == 'Intelig'


def test_import_skills_skip_mode_does_not_overwrite_existing(db, client, admin_user, login_as, make_skill):
    make_skill(name_es='Percepción', description='original')
    login_as(client, admin_user, 'adminpass123')
    text = 'Nombre: Percepción\nDescripción: nueva descripción.\n'
    data = {'file': (io.BytesIO(text.encode('utf-8')), 'skills.txt'), 'mode': 'skip'}
    client.post('/habilidades/importar', data=data, content_type='multipart/form-data')

    skill = Skill.query.filter_by(name_es='Percepción').first()
    assert skill.description == 'original'


def test_import_skills_update_mode_overwrites_existing(db, client, admin_user, login_as, make_skill):
    make_skill(name_es='Percepción', description='original')
    login_as(client, admin_user, 'adminpass123')
    text = 'Nombre: Percepción\nDescripción: nueva descripción.\n'
    data = {'file': (io.BytesIO(text.encode('utf-8')), 'skills.txt'), 'mode': 'update'}
    client.post('/habilidades/importar', data=data, content_type='multipart/form-data')

    skill = Skill.query.filter_by(name_es='Percepción').first()
    assert 'nueva descripción' in skill.description


def test_import_skills_rejects_unsupported_extension(client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    data = {'file': (io.BytesIO(b'whatever'), 'skills.pdf')}
    resp = client.post('/habilidades/importar', data=data,
                       content_type='multipart/form-data', follow_redirects=True)
    assert 'no soportado'.encode('utf-8') in resp.data.lower() or b'Formato no soportado' in resp.data


def test_import_skills_flags_near_duplicate_but_still_creates(db, client, admin_user, login_as, make_skill):
    make_skill(name_es='Preparar venenos')
    login_as(client, admin_user, 'adminpass123')
    text = 'Nombre: Preparar veneno\n'
    data = {'file': (io.BytesIO(text.encode('utf-8')), 'skills.txt'), 'mode': 'skip'}
    resp = client.post('/habilidades/importar', data=data,
                       content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200
    assert Skill.query.filter_by(name_es='Preparar veneno').first() is not None
    assert 'aviso'.encode('utf-8') in resp.data.lower()


def test_export_skills_text(client, admin_user, login_as, make_skill):
    make_skill(name_es='Percepción')
    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/habilidades/exportar?f=txt')
    assert resp.status_code == 200
    assert 'Percepción'.encode('utf-8') in resp.data


def test_export_skills_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/habilidades/exportar')
    assert resp.status_code == 403


# ── Talents ──────────────────────────────────────────────────────────────────

def test_list_talents_is_public(client, make_talent):
    make_talent(name_es='Ambidiestro')
    resp = client.get('/talentos')
    assert resp.status_code == 200
    assert b'Ambidiestro' in resp.data


def test_talent_detail_shows_professions_using_it(client, make_talent, make_profession, db):
    talent = make_talent(name_es='Ambidiestro')
    prof = make_profession(name='Alborotador')
    from app.models.profession import ProfessionTalent
    db.session.add(ProfessionTalent(profession_id=prof.id, talent_id=talent.id))
    db.session.commit()

    resp = client.get(f'/talentos/{talent.id}')
    assert resp.status_code == 200
    assert b'Alborotador' in resp.data


def test_search_talents_page_embeds_all_talent_names(client, make_talent):
    make_talent(name_es='Ambidiestro')
    make_talent(name_es='Suerte')
    resp = client.get('/talentos/buscar')
    assert resp.status_code == 200
    assert b'Ambidiestro' in resp.data
    assert b'Suerte' in resp.data


def test_create_talent_requires_permission(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/talentos/nuevo')
    assert resp.status_code == 403


def test_create_talent_with_permission(db, client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    resp = client.post('/talentos/nuevo', data={
        'name_es': 'Ambidiestro', 'max_times': '1',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert Talent.query.filter_by(name_es='Ambidiestro').first() is not None


def test_create_talent_blocks_exact_duplicate(db, client, admin_user, login_as, make_talent):
    make_talent(name_es='Ambidiestro')
    login_as(client, admin_user, 'adminpass123')
    resp = client.post('/talentos/nuevo', data={'name_es': 'Ambidiestro'}, follow_redirects=True)
    assert resp.status_code == 200
    assert Talent.query.filter_by(name_es='Ambidiestro').count() == 1
    assert 'ya existe'.encode('utf-8') in resp.data.lower()


def test_create_talent_warns_on_near_duplicate_but_still_creates(db, client, admin_user, login_as, make_talent):
    make_talent(name_es='Especialista en armas')
    login_as(client, admin_user, 'adminpass123')
    resp = client.post('/talentos/nuevo', data={'name_es': 'Especialistas en armas'}, follow_redirects=True)
    assert resp.status_code == 200
    assert Talent.query.filter_by(name_es='Especialistas en armas').first() is not None
    assert 'aviso'.encode('utf-8') in resp.data.lower()


def test_edit_talent_blocks_rename_into_existing_duplicate(db, client, admin_user, login_as, make_talent):
    make_talent(name_es='Ambidiestro')
    other = make_talent(name_es='Certero')
    login_as(client, admin_user, 'adminpass123')
    resp = client.post(f'/talentos/{other.id}/editar', data={'name_es': 'Ambidiestro'}, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(other)
    assert other.name_es == 'Certero'


def test_delete_talent(db, client, admin_user, login_as, make_talent):
    talent = make_talent(name_es='Ambidiestro')
    talent_id = talent.id
    login_as(client, admin_user, 'adminpass123')
    resp = client.post(f'/talentos/{talent_id}/eliminar', follow_redirects=True)
    assert resp.status_code == 200
    assert db.session.get(Talent, talent_id) is None


def test_import_talents_from_text_creates_new(db, client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    text = 'Nombre: Ambidiestro\nDescripción: Usa ambas manos igual de bien.\n'
    data = {'file': (io.BytesIO(text.encode('utf-8')), 'talents.txt'), 'mode': 'skip'}
    resp = client.post('/talentos/importar', data=data,
                       content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200
    assert Talent.query.filter_by(name_es='Ambidiestro').first() is not None


def test_import_talents_flags_near_duplicate_but_still_creates(db, client, admin_user, login_as, make_talent):
    make_talent(name_es='Especialista en armas')
    login_as(client, admin_user, 'adminpass123')
    text = 'Nombre: Especialistas en armas\n'
    data = {'file': (io.BytesIO(text.encode('utf-8')), 'talents.txt'), 'mode': 'skip'}
    resp = client.post('/talentos/importar', data=data,
                       content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200
    assert Talent.query.filter_by(name_es='Especialistas en armas').first() is not None
    assert 'aviso'.encode('utf-8') in resp.data.lower()


def test_export_talents_text(client, admin_user, login_as, make_talent):
    make_talent(name_es='Ambidiestro')
    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/talentos/exportar?f=txt')
    assert resp.status_code == 200
    assert b'Ambidiestro' in resp.data

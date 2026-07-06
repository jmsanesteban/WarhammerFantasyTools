"""Integration tests for the character generator wizard routes:
/personajes/generador (page), /personajes/generador/tirar (AJAX roll
dispatch) and /personajes/generador/guardar (final save)."""
import json
import re

from app.models.character import (
    Character, CharacterSkill, CharacterTalent, CharacterTrait,
    CharacterAcquaintance, CharacterPossession, CharacterMagicItem,
)


def test_generator_page_requires_login(client):
    resp = client.get('/personajes/generador')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_generator_page_renders(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/personajes/generador')
    assert resp.status_code == 200
    assert 'Generador de Personaje'.encode('utf-8') in resp.data


# ── CSRF (real regression: the roll endpoint's fetch() call must send the
# token, and a CSRF failure there must come back as JSON - not an HTML
# redirect that `await resp.json()` can't parse, which is what silently hung
# the "Tirando…" UI forever before this was caught) ─────────────────────────

def test_roll_without_csrf_token_returns_json_error_not_redirect(app, client, regular_user, login_as):
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        login_as(client, regular_user, 'userpass123')
        resp = client.post('/personajes/generador/tirar', json={'paso': 'raza'})
        assert resp.status_code == 400
        assert resp.is_json
        assert 'error' in resp.get_json()
    finally:
        app.config['WTF_CSRF_ENABLED'] = False


def _extract_csrf_token(html_bytes):
    match = re.search(rb'name="csrf_token" value="([^"]+)"', html_bytes)
    assert match, 'Could not find a csrf_token in the rendered page'
    return match.group(1).decode()


def test_roll_with_csrf_header_succeeds(app, client, regular_user):
    """The real fix: generator.html's fetch() call must send the same
    csrf_token the page rendered, via the X-CSRFToken header."""
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        login_page = client.get('/auth/login')
        login_token = _extract_csrf_token(login_page.data)
        client.post('/auth/login', data={
            'username': regular_user.username, 'password': 'userpass123',
            'csrf_token': login_token,
        })

        page = client.get('/personajes/generador')
        token = _extract_csrf_token(page.data)

        resp = client.post(
            '/personajes/generador/tirar',
            json={'paso': 'raza'},
            headers={'X-CSRFToken': token},
        )
        assert resp.status_code == 200
        assert 'race' in resp.get_json()['result']
    finally:
        app.config['WTF_CSRF_ENABLED'] = False


# ── Roll dispatch endpoint ───────────────────────────────────────────────────

def test_roll_requires_login(client):
    resp = client.post('/personajes/generador/tirar', json={'paso': 'raza'})
    assert resp.status_code == 302


def test_roll_unknown_step_returns_400(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.post('/personajes/generador/tirar', json={'paso': 'no_existe'})
    assert resp.status_code == 400
    assert 'error' in resp.get_json()


def test_roll_raza(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.post('/personajes/generador/tirar', json={'paso': 'raza'})
    assert resp.status_code == 200
    body = resp.get_json()['result']
    assert body['race'] in ('Humano', 'Halfling', 'Enano', 'Elfo Silvano', 'Alto Elfo')


def test_roll_profesion_matches_existing_catalog_entry(db, client, regular_user, login_as, make_profession, monkeypatch):
    prof = make_profession(name='Alborotador', type='basic')
    login_as(client, regular_user, 'userpass123')

    # Alborotador is 01-02 for Enano - force the d100 roll deterministically
    # instead of hoping to land on a 2%-wide range within a handful of tries.
    monkeypatch.setattr('app.services.character_creation_service.random.randint', lambda a, b: 1)
    resp = client.post('/personajes/generador/tirar', json={'paso': 'profesion', 'contexto': {'raza': 'Enano'}})
    result = resp.get_json()['result']
    assert result['profession_name'] == 'Alborotador'
    assert result['matched_profession']['id'] == prof.id


def test_roll_caracteristicas_returns_full_profile(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.post('/personajes/generador/tirar', json={'paso': 'caracteristicas', 'contexto': {'raza': 'Humano'}})
    result = resp.get_json()['result']
    for field in ('ws', 'bs', 's_char', 't_char', 'ag', 'int_char', 'wp', 'fel', 'wounds', 'fate_points', 'history_points'):
        assert field in result


def test_roll_peso_requires_altura_context(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.post('/personajes/generador/tirar', json={'paso': 'peso', 'contexto': {'raza': 'Humano', 'altura_cm': 170}})
    assert resp.status_code == 200
    assert 'kg' in resp.get_json()['result']


def test_roll_info_racial(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.post('/personajes/generador/tirar', json={'paso': 'info_racial', 'contexto': {'raza': 'Halfling'}})
    result = resp.get_json()['result']
    assert 'Cotilleo' in result['habilidades']


# ── Save endpoint ────────────────────────────────────────────────────────────

def test_save_requires_login(client):
    resp = client.post('/personajes/generador/guardar', data={'name': 'Gotrek'})
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_save_requires_name(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.post('/personajes/generador/guardar', data={'name': ''}, follow_redirects=True)
    assert resp.status_code == 200
    assert Character.query.count() == 0


def test_save_creates_character_with_full_sheet(db, client, regular_user, login_as, make_skill, make_talent):
    skill = make_skill(name_es='Hablar idioma')
    talent = make_talent(name_es='Resistencia al Caos')
    login_as(client, regular_user, 'userpass123')

    resp = client.post('/personajes/generador/guardar', data={
        'name': 'Bilbo', 'race': 'Halfling', 'gender': 'Masculino',
        'ws': '20', 'bs': '30', 's_char': '15', 't_char': '18',
        'ag': '35', 'int_char': '25', 'wp': '25', 'fel': '32',
        'attacks': '1', 'wounds': '9', 'strength_bonus': '1', 'toughness_bonus': '1',
        'movement': '4', 'magic': '0', 'insanity_points': '0', 'fate_points': '2',
        'signo_astral': 'La bailarina', 'rasgo_personalidad_signo': 'Extrovertido, simpático',
        'altura_cm': '105', 'peso_kg': '45', 'edad': '30', 'edad_grado': '3',
        'color_pelo': 'Castaño', 'color_ojos': 'Marrones', 'mano_dominante': 'Diestro',
        'procedencia': 'La Asamblea', 'situacion_familiar': 'Hijo único',
        'nivel_social': '1', 'dinero_coronas': '25',
        'history_points_total': '2', 'history_points_spent': '1',
        'racial_skills_json': json.dumps(['Hablar idioma (Halfling)']),
        'racial_talents_json': json.dumps(['Resistencia al Caos']),
        'traits_json': json.dumps([{'category': 'personalidad', 'description': 'Curioso'}]),
        'acquaintances_json': json.dumps([{'kind': 'amigo', 'description': 'Amigo de tu profesión'}]),
        'possessions_json': json.dumps([{'name': 'Capa de viaje'}]),
        'magic_items_json': json.dumps([{'category': 'amuleto', 'description': '+5 a Voluntad'}]),
    }, follow_redirects=True)
    assert resp.status_code == 200

    char = Character.query.filter_by(name='Bilbo').first()
    assert char is not None
    assert char.race == 'Halfling'
    assert char.ws == 20
    assert char.altura_cm == 105
    assert char.history_points_total == 2
    assert char.history_points_spent == 1
    assert char.history_points_available == 1

    cs = CharacterSkill.query.filter_by(character_id=char.id).first()
    assert cs.skill_id == skill.id
    assert cs.specialization == 'Halfling'

    ct = CharacterTalent.query.filter_by(character_id=char.id).first()
    assert ct.talent_id == talent.id
    assert ct.specialization is None

    trait = CharacterTrait.query.filter_by(character_id=char.id).first()
    assert trait.category == 'personalidad'
    assert trait.description == 'Curioso'

    acq = CharacterAcquaintance.query.filter_by(character_id=char.id).first()
    assert acq.kind == 'amigo'

    poss = CharacterPossession.query.filter_by(character_id=char.id).first()
    assert poss.name == 'Capa de viaje'

    item = CharacterMagicItem.query.filter_by(character_id=char.id).first()
    assert item.category == 'amuleto'


def test_save_rejects_invalid_race(db, client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.post('/personajes/generador/guardar', data={
        'name': 'Personaje', 'race': 'Orco Salvaje',
    }, follow_redirects=True)
    assert resp.status_code == 200
    char = Character.query.filter_by(name='Personaje').first()
    assert char is not None
    assert char.race is None


def test_save_ignores_racial_skill_without_catalog_match(db, client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.post('/personajes/generador/guardar', data={
        'name': 'SinCatalogo', 'race': 'Humano',
        'racial_skills_json': json.dumps(['Habilidad Que No Existe']),
    }, follow_redirects=True)
    assert resp.status_code == 200
    char = Character.query.filter_by(name='SinCatalogo').first()
    assert CharacterSkill.query.filter_by(character_id=char.id).count() == 0


def test_save_links_matched_profession_via_profession_ids(db, client, regular_user, login_as, make_profession):
    prof = make_profession(name='Cazador', type='basic')
    login_as(client, regular_user, 'userpass123')
    resp = client.post('/personajes/generador/guardar', data={
        'name': 'Talon', 'race': 'Elfo Silvano',
        'profession_ids': [str(prof.id)],
    }, follow_redirects=True)
    assert resp.status_code == 200
    char = Character.query.filter_by(name='Talon').first()
    assert char.professions[0].profession_id == prof.id

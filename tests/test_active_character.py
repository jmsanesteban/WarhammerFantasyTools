"""Tests for the persisted "personaje activo" feature (2026-07-17):
characters.activate (own characters only), the login-time auto-pick/prompt
logic, and the new /perfil page."""


def test_activate_sets_active_character(db, client, regular_user, make_character, login_as):
    char = make_character(regular_user, name='Elegido')
    login_as(client, regular_user, 'userpass123')

    client.post(f'/personajes/{char.id}/activar', data={}, follow_redirects=True)
    db.session.refresh(regular_user)
    assert regular_user.active_character_id == char.id


def test_activate_blocks_other_users_character(client, make_user, make_character, login_as):
    owner = make_user(username='owner1', password='ownerpass123')
    other = make_user(username='other1', password='otherpass123')
    char = make_character(owner)

    login_as(client, other, 'otherpass123')
    resp = client.post(f'/personajes/{char.id}/activar', data={})
    assert resp.status_code == 403


def test_activate_redirects_to_next_url(db, client, regular_user, make_character, login_as):
    char = make_character(regular_user)
    login_as(client, regular_user, 'userpass123')

    resp = client.post(f'/personajes/{char.id}/activar', data={'next_url': '/auth/perfil'})
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/auth/perfil'


def test_login_with_zero_characters_does_not_redirect_to_list(client, make_user):
    make_user(username='sinpersonajes', password='pass12345')
    resp = client.post('/auth/login', data={'username': 'sinpersonajes', 'password': 'pass12345'},
                       follow_redirects=False)
    assert resp.headers['Location'].endswith('/')


def test_login_with_one_character_auto_activates_it(db, client, make_user, make_character):
    user = make_user(username='conunpersonaje', password='pass12345')
    char = make_character(user, name='Único')

    client.post('/auth/login', data={'username': 'conunpersonaje', 'password': 'pass12345'},
               follow_redirects=True)
    db.session.refresh(user)
    assert user.active_character_id == char.id


def test_login_with_multiple_characters_and_none_active_redirects_to_list(db, client, make_user, make_character):
    user = make_user(username='convarios', password='pass12345')
    make_character(user, name='Uno')
    make_character(user, name='Dos')

    resp = client.post('/auth/login', data={'username': 'convarios', 'password': 'pass12345'},
                       follow_redirects=False)
    assert resp.headers['Location'].endswith('/personajes/')
    db.session.refresh(user)
    assert user.active_character_id is None


def test_login_does_not_override_already_active_character(db, client, make_user, make_character,
                                                           set_active_character):
    user = make_user(username='conactivo', password='pass12345')
    char1 = make_character(user, name='Uno')
    char2 = make_character(user, name='Dos')
    set_active_character(user, char2)

    resp = client.post('/auth/login', data={'username': 'conactivo', 'password': 'pass12345'},
                       follow_redirects=False)
    assert resp.headers['Location'].endswith('/')
    db.session.refresh(user)
    assert user.active_character_id == char2.id


def test_login_next_page_takes_priority_over_active_character_prompt(client, make_user, make_character):
    user = make_user(username='conrebote', password='pass12345')
    make_character(user, name='Uno')
    make_character(user, name='Dos')

    resp = client.post('/auth/login?next=/contactos/', data={'username': 'conrebote', 'password': 'pass12345'},
                       follow_redirects=False)
    assert resp.headers['Location'] == '/contactos/'


# ── Perfil ────────────────────────────────────────────────────────────────

def test_profile_requires_login(client):
    resp = client.get('/auth/perfil')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_profile_shows_own_characters(client, regular_user, make_character, login_as):
    make_character(regular_user, name='Bardin')
    login_as(client, regular_user, 'userpass123')

    resp = client.get('/auth/perfil')
    assert resp.status_code == 200
    assert b'Bardin' in resp.data
    assert regular_user.username.encode('utf-8') in resp.data


def test_profile_marks_active_character(client, regular_user, make_character, set_active_character, login_as):
    char = make_character(regular_user, name='Activo')
    set_active_character(regular_user, char)
    login_as(client, regular_user, 'userpass123')

    resp = client.get('/auth/perfil')
    assert b'Activo' in resp.data
    assert 'Activo</span>'.encode() in resp.data or b'bg-success' in resp.data

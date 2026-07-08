"""Tests for authentication: login, registration, logout."""
from app.models.user import User


def test_login_with_valid_credentials_succeeds(client, regular_user):
    resp = client.post('/auth/login', data={'username': 'regular1', 'password': 'userpass123'})
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/'


def test_login_with_wrong_password_fails(client, regular_user):
    resp = client.post('/auth/login', data={'username': 'regular1', 'password': 'wrongpass'},
                       follow_redirects=True)
    assert b'incorrectos' in resp.data


def test_login_with_unknown_username_fails(client):
    resp = client.post('/auth/login', data={'username': 'ghost', 'password': 'whatever123'},
                       follow_redirects=True)
    assert b'incorrectos' in resp.data


def test_login_redirects_to_next_page(client, regular_user):
    resp = client.post('/auth/login?next=/personajes/', data={'username': 'regular1', 'password': 'userpass123'})
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/personajes/'


def test_authenticated_user_visiting_login_is_redirected_home(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/auth/login')
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/'


def test_logout_requires_login(client):
    resp = client.get('/auth/logout')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_logout_ends_session(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    client.get('/auth/logout')
    resp = client.get('/personajes/', follow_redirects=False)
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_register_creates_user_and_logs_in(db, client):
    resp = client.post('/auth/register', data={
        'username': 'newbie', 'email': 'newbie@example.com',
        'password': 'secret123', 'confirm_password': 'secret123',
    }, follow_redirects=True)
    assert resp.status_code == 200
    user = User.query.filter_by(username='newbie').first()
    assert user is not None
    assert user.role == 'user'
    assert user.check_password('secret123')


def test_register_rejects_duplicate_username(client, regular_user):
    resp = client.post('/auth/register', data={
        'username': 'regular1', 'email': 'other@example.com',
        'password': 'secret123', 'confirm_password': 'secret123',
    }, follow_redirects=True)
    assert 'ya está en uso'.encode('utf-8') in resp.data


def test_register_rejects_mismatched_passwords(client):
    resp = client.post('/auth/register', data={
        'username': 'someone', 'email': 'someone@example.com',
        'password': 'secret123', 'confirm_password': 'different123',
    }, follow_redirects=True)
    assert 'no coinciden'.encode('utf-8') in resp.data
    assert User.query.filter_by(username='someone').first() is None


def test_register_rejects_short_password(client):
    resp = client.post('/auth/register', data={
        'username': 'shortpw', 'email': 'shortpw@example.com',
        'password': 'abc', 'confirm_password': 'abc',
    }, follow_redirects=True)
    assert User.query.filter_by(username='shortpw').first() is None


# ── Self-service password change ─────────────────────────────────────────────

def test_change_password_requires_login(client):
    resp = client.get('/auth/cambiar-clave')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_change_password_succeeds(db, client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.post('/auth/cambiar-clave', data={
        'current_password': 'userpass123', 'new_password': 'newpass456', 'confirm_password': 'newpass456',
    }, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(regular_user)
    assert regular_user.check_password('newpass456')
    assert regular_user.must_change_password is False


def test_change_password_rejects_wrong_current_password(db, client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    client.post('/auth/cambiar-clave', data={
        'current_password': 'wrongpass', 'new_password': 'newpass456', 'confirm_password': 'newpass456',
    })
    db.session.refresh(regular_user)
    assert regular_user.check_password('userpass123')


def test_change_password_rejects_mismatched_confirmation(db, client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    client.post('/auth/cambiar-clave', data={
        'current_password': 'userpass123', 'new_password': 'newpass456', 'confirm_password': 'different789',
    })
    db.session.refresh(regular_user)
    assert regular_user.check_password('userpass123')


def test_change_password_rejects_short_new_password(db, client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    client.post('/auth/cambiar-clave', data={
        'current_password': 'userpass123', 'new_password': 'short', 'confirm_password': 'short',
    })
    db.session.refresh(regular_user)
    assert regular_user.check_password('userpass123')


# ── Forced password change (must_change_password) ───────────────────────────

def test_must_change_password_redirects_any_page(client, make_user, login_as):
    user = make_user(username='forced1', password='temporal123', must_change_password=True)
    login_as(client, user, 'temporal123')
    resp = client.get('/personajes/', follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/auth/cambiar-clave'


def test_must_change_password_allows_logout(client, make_user, login_as):
    user = make_user(username='forced2', password='temporal123', must_change_password=True)
    login_as(client, user, 'temporal123')
    resp = client.get('/auth/logout', follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers['Location'] != '/auth/cambiar-clave'


def test_completing_forced_change_restores_normal_access(db, client, make_user, login_as):
    user = make_user(username='forced3', password='temporal123', must_change_password=True)
    login_as(client, user, 'temporal123')

    client.post('/auth/cambiar-clave', data={
        'current_password': 'temporal123', 'new_password': 'newpass456', 'confirm_password': 'newpass456',
    })
    resp = client.get('/personajes/', follow_redirects=False)
    assert resp.status_code == 200

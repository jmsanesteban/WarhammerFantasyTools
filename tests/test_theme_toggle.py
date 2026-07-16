"""Tests for the light/dark theme selector (base.html + custom.css): the
anti-flash inline script is present on every page, and the toggle buttons in
the user menu render with the right data attributes for main.js to hook."""


def test_anti_flash_theme_script_present_on_every_page(client):
    """Even on an anonymous page (e.g. login) the <head> script that reads
    localStorage and sets data-theme must run before first paint."""
    resp = client.get('/auth/login')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    assert "localStorage.getItem('wh-theme')" in body
    assert "document.documentElement.setAttribute('data-theme'" in body


def test_theme_toggle_buttons_in_user_menu(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    assert 'data-wh-theme="dark"' in body
    assert 'data-wh-theme="light"' in body
    assert 'Modo oscuro' in body
    assert 'Modo claro' in body


def test_theme_toggle_not_shown_to_anonymous_users(client):
    resp = client.get('/auth/login')
    assert resp.status_code == 200
    assert b'wh-theme-option' not in resp.data

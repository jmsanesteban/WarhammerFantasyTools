"""Tests for the admin dashboard: renders without BuildError (catches typos in
url_for endpoint names for the export/import links) and exposes all of them,
plus the preprod navbar banner controlled by Config.APP_ENVIRONMENT."""


def test_dashboard_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/admin/')
    assert resp.status_code == 403


def test_dashboard_lists_every_export_import_link(client, admin_user, login_as):
    """Every catalog section should have both an export and an import link on
    the dashboard, even if it also has its own menu elsewhere - the user
    explicitly asked for a one-stop view (Profesiones, Personajes, Vínculos,
    Plantillas de permisos and Sinónimos had neither before this fix)."""
    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/admin/')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')

    for path in [
        '/habilidades/exportar', '/habilidades/importar',
        '/talentos/exportar', '/talentos/importar',
        '/profesiones/exportar', '/profesiones/importar',
        '/equipamiento/exportar', '/equipamiento/importar',
        '/admin/usuarios/exportar', '/admin/usuarios/importar',
        '/admin/contactos/exportar', '/admin/contactos/importar',
        '/admin/vinculos/exportar', '/admin/vinculos/importar',
        '/admin/personajes/exportar', '/admin/personajes/importar',
        '/admin/plantillas/exportar', '/admin/plantillas/importar',
        '/admin/synonyms/exportar', '/admin/synonyms/importar',
    ]:
        assert path in body, f'missing link to {path} on the admin dashboard'


def test_navbar_shows_prepro_banner_when_configured(client, admin_user, login_as):
    client.application.config['APP_ENVIRONMENT'] = 'prepro'
    try:
        login_as(client, admin_user, 'adminpass123')
        resp = client.get('/admin/')
        assert 'Entorno de preproducción'.encode('utf-8') in resp.data
        assert b'wh-navbar-prepro' in resp.data
    finally:
        client.application.config['APP_ENVIRONMENT'] = ''


def test_navbar_hides_prepro_banner_by_default(client, admin_user, login_as):
    assert client.application.config.get('APP_ENVIRONMENT', '') != 'prepro'
    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/admin/')
    assert 'Entorno de preproducción'.encode('utf-8') not in resp.data

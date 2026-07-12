"""Tests for the static_url Jinja global (app/__init__.py): cache-busts
static JS/CSS with a ?v=<mtime> query string, since a fixed asset URL never
changes across a deploy - browsers (and Cloudflare, on wft-prepro) could
otherwise keep serving a stale cached copy for hours after a fix ships."""


def test_static_url_appends_mtime_query_string(app):
    with app.test_request_context():
        url = app.jinja_env.globals['static_url']('js/main.js')
    assert url.startswith('/static/js/main.js?v=')
    version = url.rsplit('=', 1)[1]
    assert version.isdigit() and int(version) > 0


def test_static_url_tolerates_a_missing_file(app):
    """Never breaks page rendering just because an asset went missing."""
    with app.test_request_context():
        url = app.jinja_env.globals['static_url']('js/does-not-exist.js')
    assert url == '/static/js/does-not-exist.js?v=0'


def test_rendered_page_uses_static_url_for_shared_assets(client):
    resp = client.get('/auth/login')
    html = resp.data.decode('utf-8')
    assert '/static/css/custom.css?v=' in html
    assert '/static/js/main.js?v=' in html

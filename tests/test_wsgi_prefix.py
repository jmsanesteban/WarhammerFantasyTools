"""Tests for PrefixMiddleware (app/wsgi_prefix.py), which lets WFT be served
under a URL prefix (e.g. '/wft') behind Cloudflare without touching any
route definition - see the /wft rollout plan."""
import os

from app.wsgi_prefix import PrefixMiddleware


def _fake_wsgi_app(environ, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b'ok:' + environ['PATH_INFO'].encode() + b':' + environ.get('SCRIPT_NAME', '').encode()]


def _call(middleware, path):
    captured = {}
    def start_response(status, headers):
        captured['status'] = status
    body = b''.join(middleware({'PATH_INFO': path}, start_response))
    return captured['status'], body


def test_strips_prefix_and_sets_script_name():
    mw = PrefixMiddleware(_fake_wsgi_app, '/wft')
    status, body = _call(mw, '/wft/profesiones/')
    assert status == '200 OK'
    assert body == b'ok:/profesiones/:/wft'


def test_bare_prefix_becomes_root():
    mw = PrefixMiddleware(_fake_wsgi_app, '/wft')
    status, body = _call(mw, '/wft')
    assert body == b'ok:/:/wft'


def test_passes_through_unprefixed_requests_unchanged():
    """Deliberately tolerant: a direct LAN request without the prefix (e.g.
    a health check) must keep working exactly as before."""
    mw = PrefixMiddleware(_fake_wsgi_app, '/wft')
    status, body = _call(mw, '/profesiones/')
    assert body == b'ok:/profesiones/:'


def test_does_not_match_a_similarly_named_but_different_path():
    """'/wftother' must NOT be treated as prefixed - only '/wft' or '/wft/...'."""
    mw = PrefixMiddleware(_fake_wsgi_app, '/wft')
    status, body = _call(mw, '/wftother/profesiones/')
    assert body == b'ok:/wftother/profesiones/:'


def test_no_prefix_configured_is_a_no_op():
    mw = PrefixMiddleware(_fake_wsgi_app, '')
    status, body = _call(mw, '/profesiones/')
    assert body == b'ok:/profesiones/:'


# ── Integration: a real Flask app generates prefixed URLs end-to-end ───────

def test_url_for_generates_prefixed_urls_end_to_end(monkeypatch):
    monkeypatch.setenv('URL_PREFIX', '/wft')
    from app import create_app
    app = create_app('testing')
    client = app.test_client()

    resp = client.get('/wft/auth/login')
    assert resp.status_code == 200
    assert b'href="/wft/auth/register"' in resp.data

    resp_static = client.get('/wft/static/css/custom.css')
    assert resp_static.status_code == 200


def test_unprefixed_request_still_works_on_the_same_app(monkeypatch):
    """Direct LAN access without the prefix must keep working on the exact
    same running instance - not an either/or with the prefixed path.

    Werkzeug's test client defaults SCRIPT_NAME from APPLICATION_ROOT, which
    a real gunicorn/WSGI request never does - override it here to accurately
    simulate what an actual unprefixed request looks like on the wire."""
    monkeypatch.setenv('URL_PREFIX', '/wft')
    from app import create_app
    app = create_app('testing')
    client = app.test_client()

    resp = client.get('/auth/login', environ_overrides={'SCRIPT_NAME': ''})
    assert resp.status_code == 200
    assert b'href="/auth/register"' in resp.data


def test_session_cookie_path_is_root_not_the_prefix(monkeypatch):
    """A session started via an unprefixed request (LAN access to wft-prepro)
    must still be sent back by the browser on later unprefixed requests.
    Flask defaults the cookie's Path to APPLICATION_ROOT, which would scope
    it to the prefix and make the browser withhold it on exactly the
    unprefixed traffic PrefixMiddleware is meant to keep serving - regression
    caught 2026-07-12 when wft-prepro started using URL_PREFIX for real."""
    monkeypatch.setenv('URL_PREFIX', '/wft_prepro')
    from app import create_app
    app = create_app('testing')
    assert app.config['SESSION_COOKIE_PATH'] == '/'

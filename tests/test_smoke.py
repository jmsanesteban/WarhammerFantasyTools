def test_app_boots_and_serves_home(client):
    resp = client.get('/')
    assert resp.status_code == 200


def test_login_works(client, regular_user, login_as):
    resp = login_as(client, regular_user, 'userpass123')
    assert resp.status_code == 200
    assert b'Bienvenido' in resp.data or b'regular1' in resp.data

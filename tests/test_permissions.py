"""Tests for the permission system: User.has_perm/effective_perm_codes,
and the require_permission/admin_required decorators (via real routes)."""
from app.models.permission import Permission, PermissionTemplate


def test_admin_has_every_permission(db, admin_user):
    assert admin_user.has_perm('professions.edit')
    assert admin_user.has_perm('anything.made.up')
    assert admin_user.effective_perm_codes() == {'*'}


def test_regular_user_has_no_permission_by_default(db, regular_user):
    assert not regular_user.has_perm('professions.edit')
    assert regular_user.effective_perm_codes() == set()


def test_direct_permission_grants_access(db, regular_user):
    perm = db.session.get(Permission, 'professions.edit')
    regular_user.direct_permissions.append(perm)
    db.session.commit()

    assert regular_user.has_perm('professions.edit')
    assert not regular_user.has_perm('skills.edit')
    assert regular_user.effective_perm_codes() == {'professions.edit'}


def test_template_permission_grants_access(db, regular_user):
    template = PermissionTemplate.query.filter_by(name='Editor').first()
    assert template is not None, 'Editor template should be seeded by default'
    regular_user.template = template
    db.session.commit()

    assert regular_user.has_perm('professions.edit')
    assert regular_user.has_perm('skills.edit')
    assert not regular_user.has_perm('users.manage')


def test_direct_and_template_permissions_are_unioned(db, regular_user):
    template = PermissionTemplate.query.filter_by(name='Lector').first()
    regular_user.template = template
    regular_user.direct_permissions.append(db.session.get(Permission, 'skills.edit'))
    db.session.commit()

    codes = regular_user.effective_perm_codes()
    assert 'professions.view' in codes   # from Lector template
    assert 'skills.edit' in codes        # direct grant
    assert 'professions.edit' not in codes


def test_require_permission_redirects_anonymous_to_login(client):
    resp = client.get('/profesiones/nueva')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_require_permission_blocks_user_without_permission(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/profesiones/nueva')
    assert resp.status_code == 403


def test_require_permission_allows_user_with_direct_permission(db, client, regular_user, login_as):
    regular_user.direct_permissions.append(db.session.get(Permission, 'professions.edit'))
    db.session.commit()
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/profesiones/nueva')
    assert resp.status_code == 200


def test_require_permission_allows_admin_unconditionally(client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/profesiones/nueva')
    assert resp.status_code == 200


def test_admin_required_blocks_non_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/admin/')
    assert resp.status_code == 403


def test_admin_required_allows_admin(client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/admin/')
    assert resp.status_code == 200


def test_inactive_user_cannot_log_in(client, make_user):
    make_user(username='disabled1', password='pass123456', active=False)
    resp = client.post('/auth/login', data={'username': 'disabled1', 'password': 'pass123456'},
                       follow_redirects=True)
    assert b'incorrectos' in resp.data

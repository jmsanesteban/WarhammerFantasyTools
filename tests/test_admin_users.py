"""Tests for admin-only user password management: random reset, forcing a
change on next login, and setting a specific password directly."""
from app.models.user import User


def test_reset_password_requires_admin(client, regular_user, make_user, login_as):
    other = make_user(username='other1', password='otherpass123')
    login_as(client, regular_user, 'userpass123')
    resp = client.post(f'/admin/usuarios/{other.id}/restablecer-clave')
    assert resp.status_code == 403


def test_reset_password_sets_random_password_and_forces_change(db, client, admin_user, make_user, login_as):
    other = make_user(username='other1', password='oldpass123')
    login_as(client, admin_user, 'adminpass123')

    client.post(f'/admin/usuarios/{other.id}/restablecer-clave', follow_redirects=True)

    db.session.refresh(other)
    assert not other.check_password('oldpass123')
    assert other.must_change_password is True


def test_force_password_change_requires_admin(client, regular_user, make_user, login_as):
    other = make_user(username='other1', password='otherpass123')
    login_as(client, regular_user, 'userpass123')
    resp = client.post(f'/admin/usuarios/{other.id}/forzar-cambio-clave')
    assert resp.status_code == 403


def test_force_password_change_sets_flag_without_touching_password(db, client, admin_user, make_user, login_as):
    other = make_user(username='other1', password='otherpass123')
    login_as(client, admin_user, 'adminpass123')

    client.post(f'/admin/usuarios/{other.id}/forzar-cambio-clave', follow_redirects=True)

    db.session.refresh(other)
    assert other.must_change_password is True
    assert other.check_password('otherpass123')  # unchanged


def test_set_password_requires_admin(client, regular_user, make_user, login_as):
    other = make_user(username='other1', password='otherpass123')
    login_as(client, regular_user, 'userpass123')
    resp = client.post(f'/admin/usuarios/{other.id}/establecer-clave',
                       data={'password': 'chosenpass456', 'confirm_password': 'chosenpass456'})
    assert resp.status_code == 403


def test_set_password_updates_to_chosen_password(db, client, admin_user, make_user, login_as):
    other = make_user(username='other1', password='otherpass123')
    login_as(client, admin_user, 'adminpass123')

    client.post(f'/admin/usuarios/{other.id}/establecer-clave', data={
        'password': 'chosenpass456', 'confirm_password': 'chosenpass456',
    }, follow_redirects=True)

    db.session.refresh(other)
    assert other.check_password('chosenpass456')
    assert other.must_change_password is False


def test_set_password_can_also_force_change(db, client, admin_user, make_user, login_as):
    other = make_user(username='other1', password='otherpass123')
    login_as(client, admin_user, 'adminpass123')

    client.post(f'/admin/usuarios/{other.id}/establecer-clave', data={
        'password': 'chosenpass456', 'confirm_password': 'chosenpass456', 'force_change': 'on',
    }, follow_redirects=True)

    db.session.refresh(other)
    assert other.check_password('chosenpass456')
    assert other.must_change_password is True


def test_set_password_rejects_short_password(db, client, admin_user, make_user, login_as):
    other = make_user(username='other1', password='otherpass123')
    login_as(client, admin_user, 'adminpass123')

    client.post(f'/admin/usuarios/{other.id}/establecer-clave', data={
        'password': 'short', 'confirm_password': 'short',
    }, follow_redirects=True)

    db.session.refresh(other)
    assert other.check_password('otherpass123')


def test_set_password_rejects_mismatched_confirmation(db, client, admin_user, make_user, login_as):
    other = make_user(username='other1', password='otherpass123')
    login_as(client, admin_user, 'adminpass123')

    client.post(f'/admin/usuarios/{other.id}/establecer-clave', data={
        'password': 'chosenpass456', 'confirm_password': 'different789',
    }, follow_redirects=True)

    db.session.refresh(other)
    assert other.check_password('otherpass123')

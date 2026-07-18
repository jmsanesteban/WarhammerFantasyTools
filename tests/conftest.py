import os
import tempfile

# Must be set before app.routes.admin is imported: it reads PDF_CACHE_DIR at
# module load time to pick the PDF review job/cache directory. Without this,
# tests would fall back to the production default ('/app/pdf_cache'), which
# on Windows resolves to a stray C:\app\pdf_cache instead of a real temp dir.
os.environ.setdefault('PDF_CACHE_DIR', os.path.join(tempfile.gettempdir(), 'wft_test_pdf_cache'))

import pytest

from app import create_app
from app.extensions import db as _db


@pytest.fixture
def app():
    """Fresh app + in-memory SQLite schema for every test - full isolation,
    no cross-test state leakage, no MySQL server needed."""
    application = create_app('testing')
    with application.app_context():
        _db.create_all()
        from app.models.permission import seed_permissions_and_templates
        seed_permissions_and_templates()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def db(app):
    return _db


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def anon_client(app):
    """A definitely-unauthenticated test client - use this (instead of
    `client`) in test files that override `client` to auto-login a user, for
    the specific tests that need to assert anonymous/logged-out behaviour."""
    return app.test_client()


# ── Model factories ──────────────────────────────────────────────────────────

_UNSET = object()


@pytest.fixture
def make_user(db):
    def _make(username='user1', email=None, password='password123',
              role='user', active=True, template=_UNSET, **kwargs):
        """template defaults to the 'Editor' template (view+edit everything
        except user management) - matches the pre-permission-system baseline
        that most of the test suite assumes ("a logged-in user can use every
        feature"). Pass template=None explicitly for a zero-permission user
        (see `bare_user`), or a specific PermissionTemplate/name otherwise."""
        from app.models.user import User
        from app.models.permission import PermissionTemplate
        if template is _UNSET:
            template = PermissionTemplate.query.filter_by(name='Editor').first()
        elif isinstance(template, str):
            template = PermissionTemplate.query.filter_by(name=template).first()
        user = User(
            username=username,
            email=email or f'{username}@example.com',
            role=role,
            active=active,
            template=template,
            **kwargs,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user
    return _make


@pytest.fixture
def admin_user(make_user):
    return make_user(username='admin1', role='admin', password='adminpass123')


@pytest.fixture
def regular_user(make_user):
    """A logged-in user with the default (Editor) permission template - see
    `make_user`. Tests that specifically need a zero-permission user (to test
    the permission system's deny-by-default behaviour) should use `bare_user`
    instead - see test_permissions.py."""
    return make_user(username='regular1', role='user', password='userpass123')


@pytest.fixture
def bare_user(make_user):
    """A logged-in user with zero permissions and no template - for testing
    the permission system's deny-by-default behavior itself."""
    return make_user(username='bare1', role='user', password='userpass123', template=None)


@pytest.fixture
def make_skill(db):
    def _make(name_es='Percepción', name_en=None, is_advanced=False, **kwargs):
        from app.models.skill import Skill
        skill = Skill(name_es=name_es, name_en=name_en, is_advanced=is_advanced, **kwargs)
        db.session.add(skill)
        db.session.commit()
        return skill
    return _make


@pytest.fixture
def make_talent(db):
    def _make(name_es='Ambidiestro', name_en=None, **kwargs):
        from app.models.talent import Talent
        talent = Talent(name_es=name_es, name_en=name_en, **kwargs)
        db.session.add(talent)
        db.session.commit()
        return talent
    return _make


@pytest.fixture
def make_profession(db):
    def _make(name='Alborotador', name_en=None, type='basic', **kwargs):
        from app.models.profession import Profession
        prof = Profession(name=name, name_en=name_en, type=type, **kwargs)
        db.session.add(prof)
        db.session.commit()
        return prof
    return _make


@pytest.fixture
def make_equipment_item(db):
    def _make(name='Daga', category='arma', **kwargs):
        from app.models.equipment import EquipmentItem
        item = EquipmentItem(name=name, category=category, **kwargs)
        db.session.add(item)
        db.session.commit()
        return item
    return _make


@pytest.fixture
def make_character(db):
    def _make(user, name='Test Character', **kwargs):
        from app.models.character import Character
        char = Character(user_id=user.id, name=name, **kwargs)
        db.session.add(char)
        db.session.commit()
        return char
    return _make


@pytest.fixture
def make_contact(db):
    def _make(nombre='Contacto de prueba', is_visible=True, es_untersuchung=False, created_by=None,
              professions=None, **kwargs):
        from app.models.contact import Contact, ContactProfession
        contact = Contact(
            nombre=nombre, is_visible=is_visible, es_untersuchung=es_untersuchung,
            created_by_id=created_by.id if created_by else None, **kwargs
        )
        db.session.add(contact)
        db.session.flush()
        for prof in (professions or []):
            db.session.add(ContactProfession(contact_id=contact.id, profession_id=prof.id))
        db.session.commit()
        return contact
    return _make


@pytest.fixture
def make_contact_link(db):
    def _make(character, contact, **kwargs):
        from app.models.contact_character_link import ContactCharacterLink
        link = ContactCharacterLink(character_id=character.id, contact_id=contact.id, **kwargs)
        db.session.add(link)
        db.session.commit()
        return link
    return _make


@pytest.fixture
def set_active_character(db):
    def _set(user, character):
        user.active_character_id = character.id
        db.session.commit()
    return _set


@pytest.fixture
def make_contact_note(db):
    def _make(contact, character, content='Nota'):
        from app.models.contact_note import ContactNote
        note = ContactNote(contact_id=contact.id, character_id=character.id, content=content)
        db.session.add(note)
        db.session.commit()
        return note
    return _make


# ── Auth helpers ─────────────────────────────────────────────────────────────

def login(client, username, password):
    # Log out first: the login route redirects away without checking
    # credentials when the session is already authenticated (see auth.login),
    # which would silently keep the previous identity if a test (or a
    # per-file `client` fixture override that auto-logs-in a default user)
    # tries to switch to a different user mid-test.
    client.get('/auth/logout')
    return client.post('/auth/login', data={'username': username, 'password': password},
                       follow_redirects=True)


@pytest.fixture
def login_as():
    """Usage: login_as(client, user, 'password123')"""
    def _login(client, user, password):
        return login(client, user.username, password)
    return _login

"""Tests for the admin Synonyms dictionary (Diccionario de sinónimos):
create/edit/delete routes, and a regression check for a template bug where
the "Editar" button's onclick built its arguments with |tojson (double-quoted
JSON) inside a double-quoted onclick="..." attribute - any source/target
value broke the HTML the moment it existed at all, since tojson's own
quoting collided with the attribute delimiter."""
from app.models.synonym import Synonym


def test_synonyms_requires_admin(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/admin/synonyms')
    assert resp.status_code == 403


def test_synonym_create(db, client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    resp = client.post('/admin/synonyms/new', data={
        'source': 'Encanto', 'target': 'Carisma', 'is_prefix': 'on', 'notes': 'nota',
    }, follow_redirects=True)
    assert resp.status_code == 200

    syn = Synonym.query.filter_by(source='encanto').first()
    assert syn is not None
    assert syn.target == 'Carisma'
    assert syn.is_prefix is True
    assert syn.notes == 'nota'


def test_synonym_edit_updates_fields(db, client, admin_user, login_as):
    syn = Synonym(source='viejo', target='nuevo', is_prefix=False)
    db.session.add(syn)
    db.session.commit()
    login_as(client, admin_user, 'adminpass123')

    resp = client.post(f'/admin/synonyms/{syn.id}/edit', data={
        'source': 'viejo', 'target': 'corregido', 'is_prefix': 'on', 'notes': 'actualizado',
    }, follow_redirects=True)
    assert resp.status_code == 200

    db.session.refresh(syn)
    assert syn.target == 'corregido'
    assert syn.is_prefix is True
    assert syn.notes == 'actualizado'


def test_synonym_delete(db, client, admin_user, login_as):
    syn = Synonym(source='borrame', target='x')
    db.session.add(syn)
    db.session.commit()
    syn_id = syn.id
    login_as(client, admin_user, 'adminpass123')

    resp = client.post(f'/admin/synonyms/{syn_id}/delete', follow_redirects=True)
    assert resp.status_code == 200
    assert Synonym.query.get(syn_id) is None


def test_synonyms_page_edit_button_carries_values_via_data_attributes(db, client, admin_user, login_as):
    """A value containing a double quote must not break the row's markup -
    this is exactly the shape that broke every "Editar" button under the old
    |tojson-inside-onclick implementation."""
    syn = Synonym(source='dijo "hola"', target='saludo', notes='con "comillas"')
    db.session.add(syn)
    db.session.commit()
    login_as(client, admin_user, 'adminpass123')

    resp = client.get('/admin/synonyms')
    assert resp.status_code == 200
    html = resp.data.decode()
    assert f'data-syn-id="{syn.id}"' in html
    assert 'onclick="openEdit(this)"' in html
    # The quote must be HTML-escaped (&#34;), not left raw inside the attribute.
    assert 'data-syn-source="dijo &#34;hola&#34;"' in html

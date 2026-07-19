"""Tests for WFRP characters: ownership isolation, CRUD, and profession history."""
import io
import os

from app.models.character import Character, CharacterProfession


def test_list_requires_login(client):
    resp = client.get('/personajes/')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_list_only_shows_own_characters(client, make_user, make_character, login_as):
    owner = make_user(username='owner1', password='ownerpass123')
    other = make_user(username='other1', password='otherpass123')
    make_character(owner, name='Personaje de Owner')
    make_character(other, name='Personaje de Other')

    login_as(client, owner, 'ownerpass123')
    resp = client.get('/personajes/')
    assert 'Personaje de Owner'.encode('utf-8') in resp.data
    assert 'Personaje de Other'.encode('utf-8') not in resp.data


def test_admin_list_shows_every_players_characters(client, admin_user, make_user, make_character, login_as):
    player1 = make_user(username='player1', password='playerpass123')
    player2 = make_user(username='player2', password='playerpass123')
    make_character(player1, name='Personaje de Player1')
    make_character(player2, name='Personaje de Player2')

    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/personajes/')
    assert 'Personaje de Player1'.encode('utf-8') in resp.data
    assert 'Personaje de Player2'.encode('utf-8') in resp.data


def test_detail_blocks_other_users(client, make_user, make_character, login_as):
    owner = make_user(username='owner1', password='ownerpass123')
    other = make_user(username='other1', password='otherpass123')
    char = make_character(owner, name='Personaje de Owner')

    login_as(client, other, 'otherpass123')
    resp = client.get(f'/personajes/{char.id}')
    assert resp.status_code == 403


def test_detail_allows_admin_to_view_any_character(client, admin_user, regular_user, make_character, login_as):
    char = make_character(regular_user, name='Personaje')
    login_as(client, admin_user, 'adminpass123')
    resp = client.get(f'/personajes/{char.id}')
    assert resp.status_code == 200


def test_detail_shows_photo_when_present(db, client, regular_user, make_character, login_as):
    char = make_character(regular_user, name='Con Foto', image_path='personajes/x.jpg')
    login_as(client, regular_user, 'userpass123')
    resp = client.get(f'/personajes/{char.id}')
    assert resp.status_code == 200
    assert b'personajes/x.jpg' in resp.data


def test_detail_shows_placeholder_when_no_photo(client, regular_user, make_character, login_as):
    char = make_character(regular_user, name='Sin Foto')
    login_as(client, regular_user, 'userpass123')
    resp = client.get(f'/personajes/{char.id}')
    assert resp.status_code == 200
    assert 'wh-prof-image-placeholder'.encode('utf-8') in resp.data


def test_list_shows_thumbnail_only_when_photo_present(client, regular_user, make_character, login_as):
    make_character(regular_user, name='Con Foto', image_path='personajes/x.jpg')
    make_character(regular_user, name='Sin Foto')
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/personajes/')
    assert resp.status_code == 200
    assert b'wh-char-avatar' in resp.data
    assert resp.data.count(b'wh-char-avatar') == 1
    # Same hover-zoom + click-to-lightbox system as recipe/equipment photos
    # (main.js wires any .wh-lightbox-trigger element generically).
    assert b'wh-lightbox-trigger' in resp.data


def test_create_character(db, client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.post('/personajes/nuevo', data={
        'name': 'Gotrek', 'race': 'Enano', 'gender': 'Masculino',
    }, follow_redirects=True)
    assert resp.status_code == 200

    char = Character.query.filter_by(name='Gotrek').first()
    assert char is not None
    assert char.user_id == regular_user.id
    assert char.race == 'Enano'


def test_create_character_with_image_upload(app, db, client, regular_user, login_as, tmp_path):
    app.config['UPLOAD_FOLDER'] = str(tmp_path)
    login_as(client, regular_user, 'userpass123')

    resp = client.post('/personajes/nuevo', data={
        'name': 'Con Retrato', 'image': (io.BytesIO(b'fake-png-bytes'), 'retrato.png'),
    }, content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200

    char = Character.query.filter_by(name='Con Retrato').first()
    assert char is not None
    assert char.image_path == os.path.join('personajes', 'retrato.png')
    assert (tmp_path / 'personajes' / 'retrato.png').read_bytes() == b'fake-png-bytes'


def test_create_character_requires_name(client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.post('/personajes/nuevo', data={'name': ''}, follow_redirects=True)
    assert resp.status_code == 200
    assert 'nombre'.encode('utf-8') in resp.data.lower()
    assert Character.query.count() == 0


def test_create_character_with_profession_history(db, client, regular_user, login_as, make_profession):
    prof1 = make_profession(name='Alborotador')
    prof2 = make_profession(name='Ladrón')
    login_as(client, regular_user, 'userpass123')

    resp = client.post('/personajes/nuevo', data={
        'name': 'Gotrek',
        'profession_ids': [str(prof1.id), str(prof2.id)],
    }, follow_redirects=True)
    assert resp.status_code == 200

    char = Character.query.filter_by(name='Gotrek').first()
    ordered = sorted(char.professions, key=lambda cp: cp.order)
    assert [cp.profession_id for cp in ordered] == [prof1.id, prof2.id]
    assert ordered[0].is_current is False
    assert ordered[1].is_current is True


def test_create_character_with_es_untersuchung(db, client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    resp = client.post('/personajes/nuevo', data={
        'name': 'Agente Encubierto', 'es_untersuchung': 'on',
    }, follow_redirects=True)
    assert resp.status_code == 200

    char = Character.query.filter_by(name='Agente Encubierto').first()
    assert char.es_untersuchung is True


def test_create_character_defaults_es_untersuchung_false(db, client, regular_user, login_as):
    login_as(client, regular_user, 'userpass123')
    client.post('/personajes/nuevo', data={'name': 'Civil'}, follow_redirects=True)
    char = Character.query.filter_by(name='Civil').first()
    assert char.es_untersuchung is False


def test_create_character_with_profession_salary(db, client, regular_user, login_as, make_profession):
    prof = make_profession(name='Herrero')
    login_as(client, regular_user, 'userpass123')

    resp = client.post('/personajes/nuevo', data={
        'name': 'Gotrek',
        'profession_ids': [str(prof.id)],
        'tipo_sueldo_list': ['Artesanos'],
        'estado_habilidad_list': ['Buena'],
    }, follow_redirects=True)
    assert resp.status_code == 200

    char = Character.query.filter_by(name='Gotrek').first()
    cp = char.professions[0]
    assert cp.tipo_sueldo == 'Artesanos'
    assert cp.estado_habilidad == 'Buena'


def test_edit_blocks_non_owner(client, make_user, make_character, login_as):
    owner = make_user(username='owner1', password='ownerpass123')
    other = make_user(username='other1', password='otherpass123')
    char = make_character(owner, name='Personaje')

    login_as(client, other, 'otherpass123')
    resp = client.post(f'/personajes/{char.id}/editar', data={'name': 'Hackeado'})
    assert resp.status_code == 403


def test_edit_updates_character(db, client, regular_user, login_as, make_character):
    char = make_character(regular_user, name='Original')
    login_as(client, regular_user, 'userpass123')

    resp = client.post(f'/personajes/{char.id}/editar', data={
        'name': 'Renombrado', 'race': 'Humano',
    }, follow_redirects=True)
    assert resp.status_code == 200

    db.session.refresh(char)
    assert char.name == 'Renombrado'
    assert char.race == 'Humano'


def test_edit_character_uploads_image(app, db, client, regular_user, login_as, make_character, tmp_path):
    app.config['UPLOAD_FOLDER'] = str(tmp_path)
    char = make_character(regular_user, name='Sin Retrato Todavia')
    login_as(client, regular_user, 'userpass123')

    resp = client.post(f'/personajes/{char.id}/editar', data={
        'name': char.name, 'image': (io.BytesIO(b'edited-bytes'), 'nuevo.png'),
    }, content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200

    db.session.refresh(char)
    assert char.image_path == os.path.join('personajes', 'nuevo.png')
    assert (tmp_path / 'personajes' / 'nuevo.png').read_bytes() == b'edited-bytes'


def test_edit_character_without_new_image_keeps_existing(db, client, regular_user, login_as, make_character):
    char = make_character(regular_user, name='Con Retrato Ya', image_path='personajes/viejo.png')
    login_as(client, regular_user, 'userpass123')

    resp = client.post(f'/personajes/{char.id}/editar', data={'name': char.name}, follow_redirects=True)
    assert resp.status_code == 200

    db.session.refresh(char)
    assert char.image_path == 'personajes/viejo.png'


def test_edit_replaces_profession_history(db, client, regular_user, login_as, make_character, make_profession):
    char = make_character(regular_user, name='Gotrek')
    prof1 = make_profession(name='Alborotador')
    db.session.add(CharacterProfession(character_id=char.id, profession_id=prof1.id, order=0, is_current=True))
    db.session.commit()

    prof2 = make_profession(name='Ladrón')
    login_as(client, regular_user, 'userpass123')
    client.post(f'/personajes/{char.id}/editar', data={
        'name': 'Gotrek', 'profession_ids': [str(prof2.id)],
    }, follow_redirects=True)

    db.session.refresh(char)
    prof_ids = [cp.profession_id for cp in char.professions]
    assert prof_ids == [prof2.id]


# ── Nivel de acceso a la carrera de contactos (2026-07-19, admin-only) ─────

def test_admin_can_grant_global_career_level(db, client, admin_user, regular_user, make_character, login_as):
    char = make_character(regular_user, name='Gotrek')
    login_as(client, admin_user, 'adminpass123')

    client.post(f'/personajes/{char.id}/editar', data={
        'name': 'Gotrek', 'carreras_contactos_nivel': 'editar',
    }, follow_redirects=True)

    db.session.refresh(char)
    assert char.carreras_contactos_nivel == 'editar'


def test_admin_can_grant_specific_contact_career_level(db, client, admin_user, regular_user, make_character,
                                                        make_contact, login_as):
    from app.models.contact_career_visibility import ContactCareerVisibility
    char = make_character(regular_user, name='Gotrek')
    contact = make_contact(nombre='Alexius')
    login_as(client, admin_user, 'adminpass123')

    client.post(f'/personajes/{char.id}/editar', data={
        'name': 'Gotrek', 'career_contact_ids': [str(contact.id)], 'career_contact_levels': ['editar'],
    }, follow_redirects=True)

    grants = ContactCareerVisibility.query.filter_by(character_id=char.id).all()
    assert [(g.contact_id, g.nivel) for g in grants] == [(contact.id, 'editar')]


def test_specific_contact_career_grant_defaults_to_ver_on_invalid_level(db, client, admin_user, regular_user,
                                                                        make_character, make_contact, login_as):
    from app.models.contact_career_visibility import ContactCareerVisibility
    char = make_character(regular_user, name='Gotrek')
    contact = make_contact(nombre='Alexius')
    login_as(client, admin_user, 'adminpass123')

    client.post(f'/personajes/{char.id}/editar', data={
        'name': 'Gotrek', 'career_contact_ids': [str(contact.id)], 'career_contact_levels': ['inventado'],
    }, follow_redirects=True)

    grants = ContactCareerVisibility.query.filter_by(character_id=char.id).all()
    assert [(g.contact_id, g.nivel) for g in grants] == [(contact.id, 'ver')]


def test_edit_replaces_career_visibility_grants(db, client, admin_user, regular_user, make_character,
                                                 make_contact, login_as):
    from app.models.contact_career_visibility import ContactCareerVisibility
    char = make_character(regular_user, name='Gotrek')
    old_contact = make_contact(nombre='Viejo')
    new_contact = make_contact(nombre='Nuevo')
    db.session.add(ContactCareerVisibility(character_id=char.id, contact_id=old_contact.id, nivel='ver'))
    db.session.commit()
    login_as(client, admin_user, 'adminpass123')

    client.post(f'/personajes/{char.id}/editar', data={
        'name': 'Gotrek', 'career_contact_ids': [str(new_contact.id)], 'career_contact_levels': ['ver'],
    }, follow_redirects=True)

    grants = ContactCareerVisibility.query.filter_by(character_id=char.id).all()
    assert [g.contact_id for g in grants] == [new_contact.id]


def test_non_admin_cannot_grant_own_career_level(db, client, regular_user, make_character, login_as):
    """A non-admin editing their OWN character can't sneak the admin-only
    fields through, even by crafting the POST directly - the section isn't
    even shown to them in the form."""
    char = make_character(regular_user, name='Gotrek')
    login_as(client, regular_user, 'userpass123')

    client.post(f'/personajes/{char.id}/editar', data={
        'name': 'Gotrek', 'carreras_contactos_nivel': 'editar',
    }, follow_redirects=True)

    db.session.refresh(char)
    assert char.carreras_contactos_nivel is None


def test_edit_form_hides_career_visibility_section_from_non_admin(client, regular_user, make_character, login_as):
    char = make_character(regular_user, name='Gotrek')
    login_as(client, regular_user, 'userpass123')

    resp = client.get(f'/personajes/{char.id}/editar')
    assert b'Visibilidad de la carrera profesional de los contactos' not in resp.data


def test_edit_form_shows_career_visibility_section_to_admin(client, admin_user, regular_user, make_character,
                                                             login_as):
    char = make_character(regular_user, name='Gotrek')
    login_as(client, admin_user, 'adminpass123')

    resp = client.get(f'/personajes/{char.id}/editar')
    assert b'Visibilidad de la carrera profesional de los contactos' in resp.data


def test_delete_blocks_non_owner(db, client, make_user, make_character, login_as):
    owner = make_user(username='owner1', password='ownerpass123')
    other = make_user(username='other1', password='otherpass123')
    char = make_character(owner, name='Personaje')

    login_as(client, other, 'otherpass123')
    resp = client.post(f'/personajes/{char.id}/eliminar')
    assert resp.status_code == 403
    assert db.session.get(Character, char.id) is not None


def test_delete_own_character(db, client, regular_user, login_as, make_character):
    char = make_character(regular_user, name='Gotrek')
    char_id = char.id
    login_as(client, regular_user, 'userpass123')

    resp = client.post(f'/personajes/{char_id}/eliminar', follow_redirects=True)
    assert resp.status_code == 200
    assert db.session.get(Character, char_id) is None


def test_admin_can_delete_any_character(db, client, admin_user, regular_user, make_character, login_as):
    char = make_character(regular_user, name='Gotrek')
    char_id = char.id
    login_as(client, admin_user, 'adminpass123')

    resp = client.post(f'/personajes/{char_id}/eliminar', follow_redirects=True)
    assert resp.status_code == 200
    assert db.session.get(Character, char_id) is None


# ── Searchable profession picker: catalog + career-exits map passed to the template ──

def test_new_character_form_embeds_profession_catalog_and_exits_map(
    db, client, regular_user, login_as, make_profession,
):
    soldado = make_profession(name='Soldado')
    sargento = make_profession(name='Sargento')
    soldado.exits.append(sargento)
    db.session.commit()
    login_as(client, regular_user, 'userpass123')

    resp = client.get('/personajes/nuevo')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    # Full catalog (both professions) must be present for the search widget.
    assert 'Soldado' in body
    assert 'Sargento' in body
    # The exits map keys profession ids (as JSON object keys, i.e. strings) to
    # a list of exit profession ids - confirm Soldado -> [Sargento.id] is there.
    assert f'"{soldado.id}": [{sargento.id}]' in body or f'"{soldado.id}":[{sargento.id}]' in body


def test_edit_character_form_also_embeds_exits_map(
    db, client, regular_user, login_as, make_character, make_profession,
):
    char = make_character(regular_user)
    make_profession(name='Otra profesión')
    login_as(client, regular_user, 'userpass123')

    resp = client.get(f'/personajes/{char.id}/editar')
    assert resp.status_code == 200
    assert b'professions_picker' not in resp.data  # context var name itself never leaks into HTML
    assert b'prof-picker' in resp.data

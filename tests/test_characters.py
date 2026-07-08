"""Tests for WFRP characters: ownership isolation, CRUD, and profession history."""
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

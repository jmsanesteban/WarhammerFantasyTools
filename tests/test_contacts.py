"""Tests for the Contacts feature (reworked 2026-07-16): visibility is now a
single admin-controlled switch (Contact.is_visible, no more per-character
grants), creation/edition of the contact's global data is admin-only, and
each character keeps its own private link (nivel/tipo_relacion/notas) on top
of it. A profession's salary tier is an objective fact set by the admin on
the contact itself (2026-07-17), not a per-character guess. Admin-only
management routes are covered in test_admin_contacts.py."""
from app.models.contact import Contact, ContactProfession
from app.models.contact_note import ContactNote
from app.models.contact_character_link import ContactCharacterLink
from app.services import salary_service


def test_index_requires_login(client):
    resp = client.get('/contactos/')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


# ── Estado ────────────────────────────────────────────────────────────────

def test_index_shows_muerto_badge(client, regular_user, login_as, make_contact):
    make_contact(nombre='Difunto', estado='muerto')
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/contactos/')
    assert b'Muerto' in resp.data


def test_index_shows_desconocido_badge(client, regular_user, login_as, make_contact):
    make_contact(nombre='Fugitivo', estado='desconocido')
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/contactos/')
    assert 'Desconocido'.encode() in resp.data


def test_index_shows_no_badge_when_vivo(client, regular_user, login_as, make_contact):
    make_contact(nombre='Sano y salvo', estado='vivo')
    login_as(client, regular_user, 'userpass123')
    resp = client.get('/contactos/')
    assert resp.status_code == 200


def test_detail_shows_estado(client, regular_user, login_as, make_contact):
    contact = make_contact(nombre='Desaparecida', estado='desconocido')
    login_as(client, regular_user, 'userpass123')
    resp = client.get(f'/contactos/{contact.id}')
    assert resp.status_code == 200
    assert b'Desconocido' in resp.data


def test_detail_shows_raza_and_lugares(client, regular_user, login_as, make_contact):
    contact = make_contact(nombre='Completo', raza='Enano', lugar_descanso='Una posada',
                           lugar_trabajo='La fragua', lugar_ocio='La taberna')
    login_as(client, regular_user, 'userpass123')
    resp = client.get(f'/contactos/{contact.id}')
    assert resp.status_code == 200
    assert b'Enano' in resp.data
    assert 'Una posada'.encode() in resp.data
    assert b'La fragua' in resp.data
    assert b'La taberna' in resp.data


def test_detail_notas_director_only_visible_to_admin(client, admin_user, regular_user, login_as, make_contact):
    contact = make_contact(nombre='Con nota secreta', notas_director='Es un doble agente')
    login_as(client, regular_user, 'userpass123')
    resp = client.get(f'/contactos/{contact.id}')
    assert b'Es un doble agente' not in resp.data

    client.get('/auth/logout')
    login_as(client, admin_user, 'adminpass123')
    resp = client.get(f'/contactos/{contact.id}')
    assert 'Es un doble agente'.encode() in resp.data


# ── Visibilidad (Contact.is_visible es el único interruptor) ────────────────

def test_regular_user_only_sees_visible_contacts(client, regular_user, login_as, make_contact):
    visible = make_contact(nombre='Gotrek Gurnisson', is_visible=True)
    hidden = make_contact(nombre='Espía Oculto', is_visible=False)

    login_as(client, regular_user, 'userpass123')
    resp = client.get('/contactos/')
    assert f'/contactos/{visible.id}'.encode() in resp.data
    assert f'/contactos/{hidden.id}'.encode() not in resp.data


def test_admin_sees_hidden_contacts_too(client, admin_user, login_as, make_contact):
    hidden = make_contact(nombre='Espía Oculto', is_visible=False)

    login_as(client, admin_user, 'adminpass123')
    resp = client.get('/contactos/')
    assert f'/contactos/{hidden.id}'.encode() in resp.data


def test_regular_user_cannot_view_hidden_contact_detail(client, regular_user, login_as, make_contact):
    hidden = make_contact(is_visible=False)
    login_as(client, regular_user, 'userpass123')
    resp = client.get(f'/contactos/{hidden.id}', follow_redirects=True)
    assert resp.status_code == 200
    assert resp.request.path == '/contactos/'


def test_regular_user_can_view_visible_contact_detail(client, regular_user, login_as, make_contact):
    contact = make_contact(is_visible=True)
    login_as(client, regular_user, 'userpass123')
    resp = client.get(f'/contactos/{contact.id}')
    assert resp.status_code == 200


def test_search_filters_by_nombre(client, regular_user, login_as, make_contact):
    c1 = make_contact(nombre='Gotrek Gurnisson')
    c2 = make_contact(nombre='Felix Jaeger')

    login_as(client, regular_user, 'userpass123')
    resp = client.get('/contactos/?q=Gotrek')
    assert f'/contactos/{c1.id}'.encode() in resp.data
    assert f'/contactos/{c2.id}'.encode() not in resp.data


# ── Creación/edición de contactos (admin-only desde el rework) ──────────────

def test_new_contact_requires_permission(db, client, bare_user, login_as):
    login_as(client, bare_user, 'userpass123')
    resp = client.post('/contactos/nuevo', data={'nombre': 'Intento'})
    assert resp.status_code == 403
    assert Contact.query.filter_by(nombre='Intento').first() is None


def test_new_contact_creates_global_fields_only(db, client, admin_user, login_as, make_profession):
    prof = make_profession(name='Herrero')
    login_as(client, admin_user, 'adminpass123')

    resp = client.post('/contactos/nuevo', data={
        'nombre': 'Wilhelm el tabernero', 'raza_choice': 'Humano', 'estado': 'vivo',
        'lugar_trabajo': 'La taberna', 'profession_ids': [str(prof.id)],
    }, follow_redirects=True)
    assert resp.status_code == 200

    contact = Contact.query.filter_by(nombre='Wilhelm el tabernero').first()
    assert contact is not None
    assert contact.raza == 'Humano'
    assert contact.lugar_trabajo == 'La taberna'
    assert [cp.profession_id for cp in contact.professions] == [prof.id]
    assert ContactCharacterLink.query.filter_by(contact_id=contact.id).count() == 0


def test_new_contact_raza_custom_via_nuevo_sentinel(db, client, admin_user, login_as):
    """raza_choice='__nuevo__' reveals raza_custom in the UI - server-side,
    that sentinel means "read the free-text value from raza_custom instead"."""
    login_as(client, admin_user, 'adminpass123')

    client.post('/contactos/nuevo', data={
        'nombre': 'Rata gigante', 'raza_choice': '__nuevo__', 'raza_custom': 'Rata mutante',
    }, follow_redirects=True)

    contact = Contact.query.filter_by(nombre='Rata gigante').first()
    assert contact is not None
    assert contact.raza == 'Rata mutante'


def test_new_contact_requires_nombre(db, client, admin_user, login_as):
    login_as(client, admin_user, 'adminpass123')
    resp = client.post('/contactos/nuevo', data={'nombre': '  '})
    assert resp.status_code == 200
    assert Contact.query.count() == 0


def test_edit_contact_requires_permission(db, client, bare_user, login_as, make_contact):
    contact = make_contact(nombre='Original')
    login_as(client, bare_user, 'userpass123')
    resp = client.post(f'/contactos/{contact.id}/editar', data={'nombre': 'Hackeado'})
    assert resp.status_code == 403
    db.session.refresh(contact)
    assert contact.nombre == 'Original'


def test_edit_contact_toggles_is_visible(db, client, admin_user, login_as, make_contact):
    contact = make_contact(nombre='Precargado', is_visible=False)
    login_as(client, admin_user, 'adminpass123')

    client.post(f'/contactos/{contact.id}/editar', data={
        'nombre': 'Precargado', 'is_visible': 'on',
    }, follow_redirects=True)
    db.session.refresh(contact)
    assert contact.is_visible is True


_PROFESIONES_FACT = b'<dt class="col-sm-4 wh-label">Profesiones</dt>'


def test_professions_always_shown_regardless_of_active_character(client, regular_user, make_character,
                                                                  make_contact, make_profession, login_as):
    """Since the rework, Profesiones is no longer gated by any per-character
    visibility level - it's always shown to whoever can view the contact."""
    char = make_character(regular_user)
    prof = make_profession(name='Herrero')
    contact = make_contact(professions=[prof])
    login_as(client, regular_user, 'userpass123')

    resp = client.get(f'/contactos/{contact.id}?personaje_id={char.id}')
    assert _PROFESIONES_FACT in resp.data
    assert b'Herrero' in resp.data


# ── Vínculo personaje-contacto ───────────────────────────────────────────────

def test_link_save_creates_link_with_nivel_and_tipo_relacion(db, client, regular_user, make_character,
                                                              make_contact, login_as):
    char = make_character(regular_user)
    contact = make_contact()
    login_as(client, regular_user, 'userpass123')

    client.post(f'/contactos/{contact.id}/vinculo', data={
        'personaje_id': str(char.id), 'nivel': '-3', 'tipo_relacion': ['Baza', 'Otra'],
    }, follow_redirects=True)

    link = ContactCharacterLink.query.filter_by(character_id=char.id, contact_id=contact.id).first()
    assert link is not None
    assert link.nivel == -3
    assert set(link.tipo_relacion) == {'Baza', 'Otra'}


def test_link_save_ignores_unknown_tipo_relacion(db, client, regular_user, make_character, make_contact, login_as):
    char = make_character(regular_user)
    contact = make_contact()
    login_as(client, regular_user, 'userpass123')

    client.post(f'/contactos/{contact.id}/vinculo', data={
        'personaje_id': str(char.id), 'tipo_relacion': ['Baza', 'Inventado'],
    }, follow_redirects=True)

    link = ContactCharacterLink.query.filter_by(character_id=char.id, contact_id=contact.id).first()
    assert link.tipo_relacion == ['Baza']


def test_link_save_accepts_unter_tipo_relacion(db, client, regular_user, make_character, make_contact, login_as):
    """2026-07-19: Untersuchung membership moved back to tipo_relacion='Unter'
    (off Contact.es_untersuchung, which no longer exists)."""
    char = make_character(regular_user)
    contact = make_contact()
    login_as(client, regular_user, 'userpass123')

    client.post(f'/contactos/{contact.id}/vinculo', data={
        'personaje_id': str(char.id), 'tipo_relacion': ['Unter', 'Otra'],
    }, follow_redirects=True)

    link = ContactCharacterLink.query.filter_by(character_id=char.id, contact_id=contact.id).first()
    assert set(link.tipo_relacion) == {'Unter', 'Otra'}


def test_link_save_baza_and_unter_are_not_exclusive(db, client, regular_user, make_character, make_contact, login_as):
    """Only Súbdito/Señor are mutually exclusive now - Baza and Unter can both
    apply to the same link (an asset who's also Untersuchung)."""
    char = make_character(regular_user)
    contact = make_contact()
    login_as(client, regular_user, 'userpass123')

    client.post(f'/contactos/{contact.id}/vinculo', data={
        'personaje_id': str(char.id), 'tipo_relacion': ['Baza', 'Unter'],
    }, follow_redirects=True)

    link = ContactCharacterLink.query.filter_by(character_id=char.id, contact_id=contact.id).first()
    assert set(link.tipo_relacion) == {'Baza', 'Unter'}


def test_link_save_deduplicates_subdito_senor_pair(db, client, regular_user, make_character, make_contact, login_as):
    char = make_character(regular_user)
    contact = make_contact()
    login_as(client, regular_user, 'userpass123')

    client.post(f'/contactos/{contact.id}/vinculo', data={
        'personaje_id': str(char.id), 'tipo_relacion': ['Señor', 'Súbdito'],
    }, follow_redirects=True)

    link = ContactCharacterLink.query.filter_by(character_id=char.id, contact_id=contact.id).first()
    assert link.tipo_relacion == ['Súbdito']


def test_detail_own_row_shows_create_form_when_no_link_yet(db, client, regular_user, make_character,
                                                             make_contact, login_as, set_active_character):
    """2026-07-17: 'Vínculo de X'/'Notas de X' are no longer fixed cards - the
    create form for the active character's row (when it has no link yet)
    lives inside the "Personajes con relación" table instead."""
    char = make_character(regular_user, name='Sin vínculo aún')
    contact = make_contact()
    set_active_character(regular_user, char)
    login_as(client, regular_user, 'userpass123')

    resp = client.get(f'/contactos/{contact.id}')
    assert resp.status_code == 200
    assert 'Crear vínculo'.encode() in resp.data
    assert 'name="tipo_relacion" value="Súbdito"'.encode() in resp.data
    assert 'name="tipo_relacion" value="Unter"'.encode() in resp.data
    assert 'name="tipo_relacion" value="Contacto"'.encode() not in resp.data
    assert b'data-exclusive-group="tipo-relacion-pair-0"' in resp.data
    assert b'own-link-panel' in resp.data


def test_detail_own_row_shows_edit_form_when_link_exists(db, client, regular_user, make_character,
                                                           make_contact, make_contact_link, login_as,
                                                           set_active_character):
    char = make_character(regular_user, name='Con vínculo')
    contact = make_contact()
    make_contact_link(char, contact, nivel=2)
    set_active_character(regular_user, char)
    login_as(client, regular_user, 'userpass123')

    resp = client.get(f'/contactos/{contact.id}')
    assert resp.status_code == 200
    assert 'Actualizar vínculo'.encode() in resp.data
    assert 'nota'.encode() in resp.data
    assert b'own-link-panel' in resp.data


def test_link_save_blocks_other_users_character(client, make_user, make_character, make_contact, login_as):
    owner = make_user(username='owner1', password='ownerpass123')
    other = make_user(username='other1', password='otherpass123')
    char = make_character(owner)
    contact = make_contact()

    login_as(client, other, 'otherpass123')
    resp = client.post(f'/contactos/{contact.id}/vinculo', data={'personaje_id': str(char.id), 'nivel': '5'})
    assert resp.status_code == 403


def test_link_delete_removes_link(db, client, regular_user, make_character, make_contact, make_contact_link,
                                  login_as):
    char = make_character(regular_user)
    contact = make_contact()
    make_contact_link(char, contact, nivel=1)
    login_as(client, regular_user, 'userpass123')

    client.post(f'/contactos/{contact.id}/vinculo/eliminar', data={'personaje_id': str(char.id)},
               follow_redirects=True)
    assert ContactCharacterLink.query.filter_by(character_id=char.id, contact_id=contact.id).first() is None


def test_two_characters_have_independent_links_to_same_contact(db, client, make_user, make_character,
                                                                 make_contact, make_contact_link):
    user_a = make_user(username='usera', password='passa12345')
    user_b = make_user(username='userb', password='passb12345')
    char_a = make_character(user_a, name='Personaje A')
    char_b = make_character(user_b, name='Personaje B')
    contact = make_contact()
    make_contact_link(char_a, contact, nivel=5)
    make_contact_link(char_b, contact, nivel=-2)

    link_a = ContactCharacterLink.query.filter_by(character_id=char_a.id, contact_id=contact.id).first()
    link_b = ContactCharacterLink.query.filter_by(character_id=char_b.id, contact_id=contact.id).first()
    assert link_a.nivel == 5
    assert link_b.nivel == -2


# ── Sueldo por profesión (2026-07-17: hecho objetivo del contacto, ya no una
#    creencia por personaje - se fija en new()/edit(), no en una ruta propia) ─

def test_new_contact_saves_profession_with_salary_tier(db, client, admin_user, login_as, make_profession):
    prof = make_profession(name='Herrero')
    login_as(client, admin_user, 'adminpass123')

    client.post('/contactos/nuevo', data={
        'nombre': 'Gorbag', 'profession_ids': [str(prof.id)],
        'tipo_sueldo_list': ['Artesanos'], 'estado_habilidad_list': ['Buena'],
    }, follow_redirects=True)

    contact = Contact.query.filter_by(nombre='Gorbag').first()
    assert contact is not None
    cp = contact.professions[0]
    assert cp.tipo_sueldo == 'Artesanos'
    assert cp.estado_habilidad == 'Buena'


def test_edit_contact_rebuilds_professions_with_salary(db, client, admin_user, login_as, make_contact, make_profession):
    prof = make_profession(name='Herrero')
    contact = make_contact(nombre='Gorbag', professions=[prof])
    login_as(client, admin_user, 'adminpass123')

    client.post(f'/contactos/{contact.id}/editar', data={
        'nombre': 'Gorbag', 'profession_ids': [str(prof.id)],
        'tipo_sueldo_list': ['Especialistas'], 'estado_habilidad_list': ['Excelente'],
    }, follow_redirects=True)

    db.session.refresh(contact)
    cp = contact.professions[0]
    assert cp.tipo_sueldo == 'Especialistas'
    assert cp.estado_habilidad == 'Excelente'


def test_detail_shows_computed_sueldo_for_profession(db, client, admin_user, make_contact, make_profession, login_as):
    prof = make_profession(name='Herrero')
    contact = make_contact(nombre='Gorbag')
    db.session.add(ContactProfession(
        contact_id=contact.id, profession_id=prof.id,
        tipo_sueldo='Artesanos', estado_habilidad='Buena',
    ))
    db.session.commit()
    login_as(client, admin_user, 'adminpass123')

    resp = client.get(f'/contactos/{contact.id}')
    expected_sueldo = salary_service.compute_sueldo('Artesanos', 'Buena')
    assert expected_sueldo.encode() in resp.data


# ── Notas (por personaje) ────────────────────────────────────────────────────

def test_create_note(db, client, regular_user, make_character, make_contact, login_as):
    char = make_character(regular_user)
    contact = make_contact(is_visible=True)
    login_as(client, regular_user, 'userpass123')

    resp = client.post(f'/contactos/{contact.id}/notas',
                       data={'content': 'Interesante tipo', 'personaje_id': str(char.id)},
                       follow_redirects=True)
    assert resp.status_code == 200
    note = ContactNote.query.filter_by(contact_id=contact.id).first()
    assert note is not None
    assert note.character_id == char.id


def test_create_note_rejects_empty_content(client, regular_user, make_character, make_contact, login_as):
    char = make_character(regular_user)
    contact = make_contact(is_visible=True)
    login_as(client, regular_user, 'userpass123')
    client.post(f'/contactos/{contact.id}/notas', data={'content': '  ', 'personaje_id': str(char.id)})
    assert ContactNote.query.filter_by(contact_id=contact.id).count() == 0


def test_note_from_one_character_hidden_from_another_characters_view(
    db, client, regular_user, make_character, make_contact, make_contact_note, login_as,
):
    char_a = make_character(regular_user, name='Personaje A')
    char_b = make_character(regular_user, name='Personaje B')
    contact = make_contact(is_visible=True)
    make_contact_note(contact, char_a, content='Nota de A')

    login_as(client, regular_user, 'userpass123')
    resp = client.get(f'/contactos/{contact.id}?personaje_id={char_b.id}')
    assert 'Nota de A'.encode('utf-8') not in resp.data

    resp = client.get(f'/contactos/{contact.id}?personaje_id={char_a.id}')
    assert 'Nota de A'.encode('utf-8') in resp.data


def test_edit_note_blocks_non_owner_character(client, make_user, make_character, make_contact,
                                              make_contact_note, login_as):
    owner = make_user(username='owner1', password='ownerpass123')
    other = make_user(username='other1', password='otherpass123')
    owner_char = make_character(owner)
    contact = make_contact(is_visible=True)
    note = make_contact_note(contact, owner_char, content='Original')

    login_as(client, other, 'otherpass123')
    resp = client.post(f'/contactos/{contact.id}/notas/{note.id}/editar', data={'content': 'Hackeado'})
    assert resp.status_code == 403


def test_edit_note_allows_owner(db, client, regular_user, make_character, make_contact, make_contact_note, login_as):
    char = make_character(regular_user)
    contact = make_contact(is_visible=True)
    note = make_contact_note(contact, char, content='Original')
    login_as(client, regular_user, 'userpass123')

    client.post(f'/contactos/{contact.id}/notas/{note.id}/editar', data={'content': 'Actualizada'},
               follow_redirects=True)
    db.session.refresh(note)
    assert note.content == 'Actualizada'


def test_delete_note_blocks_non_owner_character(client, make_user, make_character, make_contact,
                                                make_contact_note, login_as):
    owner = make_user(username='owner1', password='ownerpass123')
    other = make_user(username='other1', password='otherpass123')
    owner_char = make_character(owner)
    contact = make_contact(is_visible=True)
    note = make_contact_note(contact, owner_char)

    login_as(client, other, 'otherpass123')
    resp = client.post(f'/contactos/{contact.id}/notas/{note.id}/eliminar')
    assert resp.status_code == 403


def test_delete_note_allows_admin(db, client, admin_user, regular_user, make_character, make_contact,
                                  make_contact_note, login_as):
    char = make_character(regular_user)
    contact = make_contact(is_visible=True)
    note = make_contact_note(contact, char)
    note_id = note.id
    login_as(client, admin_user, 'adminpass123')

    client.post(f'/contactos/{contact.id}/notas/{note_id}/eliminar', follow_redirects=True)
    assert db.session.get(ContactNote, note_id) is None


# ── Personajes con relación (2026-07-17: visible a cualquiera, no solo admin) ──

def test_detail_shows_personajes_con_relacion_to_non_admin(client, regular_user, make_character, make_contact,
                                                            make_contact_link, login_as):
    char = make_character(regular_user, name='Karl-Heinz')
    contact = make_contact(nombre='Wilhelm el tabernero')
    make_contact_link(char, contact, nivel=3, tipo_relacion=['Baza'])
    login_as(client, regular_user, 'userpass123')

    resp = client.get(f'/contactos/{contact.id}')
    assert resp.status_code == 200
    assert b'Personajes con relaci' in resp.data
    assert b'Karl-Heinz' in resp.data
    assert b'Baza' in resp.data


def test_detail_personajes_con_relacion_shows_note_count_not_content(
    client, regular_user, make_user, make_character, make_contact, make_contact_link, make_contact_note, login_as,
):
    """The note belongs to a DIFFERENT character than the viewer's own active
    one - only the "Personajes con relación" summary can leak it, and that
    summary must show just the count, never the content."""
    other = make_user(username='otro_con_nota', password='otropass123')
    other_char = make_character(other, name='Karl-Heinz')
    my_char = make_character(regular_user, name='Mi personaje')
    contact = make_contact(nombre='Wilhelm el tabernero')
    make_contact_link(other_char, contact)
    make_contact_link(my_char, contact)
    make_contact_note(contact, other_char, content='Debe dinero al gremio.')
    login_as(client, regular_user, 'userpass123')

    resp = client.get(f'/contactos/{contact.id}')
    assert b'Debe dinero al gremio.' not in resp.data
    assert b'Personajes con relaci' in resp.data
    assert b'Karl-Heinz' in resp.data


def test_detail_admin_editar_on_own_row_toggles_panel_not_a_dead_reload(
    client, admin_user, make_character, make_contact, make_contact_link, set_active_character, login_as,
):
    """Regression: admin's own row used to also render the ?personaje_id=
    reload link (meant for editing OTHER people's rows) - for the admin's
    own row that's a no-op reload to the same page, which looked broken.
    It must instead toggle the same collapse as the notes-count link."""
    char = make_character(admin_user, name='Personaje del admin')
    contact = make_contact(nombre='Wilhelm el tabernero')
    make_contact_link(char, contact, nivel=1)
    set_active_character(admin_user, char)
    login_as(client, admin_user, 'adminpass123')

    resp = client.get(f'/contactos/{contact.id}')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8')
    own_row_start = html.index('Personaje del admin')
    own_row_end = html.index('</tr>', own_row_start)
    own_row_html = html[own_row_start:own_row_end]
    assert 'data-bs-target="#own-link-panel"' in own_row_html
    assert f'personaje_id={char.id}' not in own_row_html


def test_detail_admin_editar_on_other_row_still_reloads_as_that_character(
    client, admin_user, make_user, make_character, make_contact, make_contact_link, login_as,
):
    other = make_user(username='otro_editable', password='otropass123')
    other_char = make_character(other, name='Personaje ajeno')
    contact = make_contact(nombre='Wilhelm el tabernero')
    make_contact_link(other_char, contact, nivel=1)
    login_as(client, admin_user, 'adminpass123')

    resp = client.get(f'/contactos/{contact.id}')
    assert resp.status_code == 200
    assert f'personaje_id={other_char.id}'.encode() in resp.data

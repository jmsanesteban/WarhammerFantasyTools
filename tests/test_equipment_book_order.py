"""Tests for the `flask set-equipment-book-order` one-off command: sets
EquipmentItem.orden to match the position weapons/armour/clothing have in
their source book PDFs, so catalog listings can sort by book order instead
of alphabetically."""


def test_dry_run_writes_nothing(app, db, make_equipment_item):
    item = make_equipment_item(name='Daga', category='arma', subcategory='cuerpo_a_cuerpo')

    result = app.test_cli_runner().invoke(args=['set-equipment-book-order'])
    assert result.exit_code == 0
    assert 'Dry-run' in result.output

    db.session.refresh(item)
    assert item.orden is None


def test_apply_sets_orden_for_matched_arma_by_name_and_subcategory(app, db, make_equipment_item):
    daga = make_equipment_item(name='Daga', category='arma', subcategory='cuerpo_a_cuerpo')
    espadon = make_equipment_item(name='Espadón', category='arma', subcategory='cuerpo_a_cuerpo')

    result = app.test_cli_runner().invoke(args=['set-equipment-book-order', '--apply'])
    assert result.exit_code == 0

    db.session.refresh(daga)
    db.session.refresh(espadon)
    assert daga.orden is not None
    assert espadon.orden is not None
    assert daga.orden < espadon.orden


def test_apply_disambiguates_same_name_by_subcategory(app, db, make_equipment_item):
    """'Daga' exists twice in the book - once as a cuerpo_a_cuerpo weapon,
    once as a distancia (arrojadiza) one - matching must key off subcategory
    too, not name alone, or the two rows would collide."""
    melee_daga = make_equipment_item(name='Daga', category='arma', subcategory='cuerpo_a_cuerpo')
    thrown_daga = make_equipment_item(name='Daga', category='arma', subcategory='distancia')

    app.test_cli_runner().invoke(args=['set-equipment-book-order', '--apply'])

    db.session.refresh(melee_daga)
    db.session.refresh(thrown_daga)
    assert melee_daga.orden is not None
    assert thrown_daga.orden is not None
    assert melee_daga.orden != thrown_daga.orden


def test_apply_leaves_unmatched_item_orden_none(app, db, make_equipment_item):
    item = make_equipment_item(name='Objeto inventado', category='arma', subcategory='cuerpo_a_cuerpo')

    result = app.test_cli_runner().invoke(args=['set-equipment-book-order', '--apply'])
    assert result.exit_code == 0
    assert 'Objeto inventado' in result.output

    db.session.refresh(item)
    assert item.orden is None


def test_apply_computes_ropa_orden_from_quality_then_subcategory_rank(app, db, make_equipment_item):
    """The book lists everything section by section (all of Harapos, then
    all of Común, then Burguesa, then Noble), repeating the same list of
    clothing types within each section - quality tier is the primary sort
    key, clothing type only breaks ties within the same tier."""
    ropa_harapos = make_equipment_item(name='Ropa', category='ropa', subcategory='ropa', quality='mala')
    ropa_comun = make_equipment_item(name='Ropa', category='ropa', subcategory='ropa', quality='normal')
    ropa_noble = make_equipment_item(name='Ropa', category='ropa', subcategory='ropa', quality='excelente')
    botas_harapos = make_equipment_item(name='Botas', category='ropa', subcategory='botas', quality='mala')

    app.test_cli_runner().invoke(args=['set-equipment-book-order', '--apply'])

    for item in (ropa_harapos, ropa_comun, ropa_noble, botas_harapos):
        db.session.refresh(item)
    # Same type (ropa): quality tier decides order (mala < normal < excelente).
    assert ropa_harapos.orden < ropa_comun.orden < ropa_noble.orden
    # Different type, same tier (mala): 'ropa' sorts before 'botas' within Harapos.
    assert ropa_harapos.orden < botas_harapos.orden
    # Quality tier wins over type: Harapos Botas comes before Común Ropa,
    # even though 'ropa' is an earlier clothing type than 'botas'.
    assert botas_harapos.orden < ropa_comun.orden


def test_apply_is_idempotent(app, db, make_equipment_item):
    item = make_equipment_item(name='Daga', category='arma', subcategory='cuerpo_a_cuerpo')

    runner = app.test_cli_runner()
    runner.invoke(args=['set-equipment-book-order', '--apply'])
    db.session.refresh(item)
    first_orden = item.orden

    runner.invoke(args=['set-equipment-book-order', '--apply'])
    db.session.refresh(item)
    assert item.orden == first_orden


def test_catalog_list_sorts_by_orden_before_name(client, admin_user, login_as, make_equipment_item):
    make_equipment_item(name='Zeta arma', category='arma', subcategory='cuerpo_a_cuerpo', orden=1)
    make_equipment_item(name='Alfa arma', category='arma', subcategory='cuerpo_a_cuerpo', orden=2)
    login_as(client, admin_user, 'adminpass123')

    resp = client.get('/equipamiento/armas')
    assert resp.status_code == 200
    zeta_pos = resp.data.find(b'Zeta arma')
    alfa_pos = resp.data.find(b'Alfa arma')
    assert zeta_pos != -1 and alfa_pos != -1
    assert zeta_pos < alfa_pos


def test_catalog_list_falls_back_to_name_when_orden_unset(client, admin_user, login_as, make_equipment_item):
    make_equipment_item(name='Zeta sin orden', category='arma', subcategory='cuerpo_a_cuerpo')
    make_equipment_item(name='Alfa sin orden', category='arma', subcategory='cuerpo_a_cuerpo')
    login_as(client, admin_user, 'adminpass123')

    resp = client.get('/equipamiento/armas')
    assert resp.status_code == 200
    alfa_pos = resp.data.find(b'Alfa sin orden')
    zeta_pos = resp.data.find(b'Zeta sin orden')
    assert alfa_pos != -1 and zeta_pos != -1
    assert alfa_pos < zeta_pos

"""Tests for the character creation dice-rolling service (WFRP2 house rules).

Focuses on: dice-formula parsing, percentile-table boundary correctness
across every race for every step (a full sweep 1-100 catches gaps in the
JSON data tables), and the race-group indirection (Elfo Silvano/Alto Elfo
sharing the 'Elfo' characteristics/altura/peso/edad tables).
"""
import pytest

from app.services import character_creation_service as svc

RACES = ['Humano', 'Halfling', 'Enano', 'Elfo Silvano', 'Alto Elfo']


# ── Dice formula parsing ─────────────────────────────────────────────────────

def test_roll_dice_plain_number():
    assert svc.roll_dice('4') == 4


def test_roll_dice_base_plus_dice(monkeypatch):
    monkeypatch.setattr(svc.random, 'randint', lambda a, b: 5)
    assert svc.roll_dice('20+2d10') == 30  # 20 + 5 + 5


def test_roll_dice_negative_dice(monkeypatch):
    monkeypatch.setattr(svc.random, 'randint', lambda a, b: 3)
    assert svc.roll_dice('-2d6') == -6


def test_roll_dice_compound_formula(monkeypatch):
    monkeypatch.setattr(svc.random, 'randint', lambda a, b: 2)
    assert svc.roll_dice('15+1d3') == 17
    assert svc.roll_dice('+1d10+1d4') == 4


# ── roll_table ───────────────────────────────────────────────────────────────

def test_roll_table_finds_matching_range():
    table = [{'min': 1, 'max': 5, 'value': 'a'}, {'min': 6, 'max': 10, 'value': 'b'}]
    assert svc.roll_table(table, 3)['value'] == 'a'
    assert svc.roll_table(table, 8)['value'] == 'b'


def test_roll_table_returns_none_when_uncovered():
    table = [{'min': 1, 'max': 5, 'value': 'a'}]
    assert svc.roll_table(table, 50) is None


# ── Race groups ──────────────────────────────────────────────────────────────

def test_characteristics_group_shares_elfo_table():
    assert svc.characteristics_group('Elfo Silvano') == 'Elfo'
    assert svc.characteristics_group('Alto Elfo') == 'Elfo'
    assert svc.characteristics_group('Humano') == 'Humano'


def test_talent_group_merges_human_and_halfling():
    assert svc.talent_group('Humano') == 'Humano-Halfling'
    assert svc.talent_group('Halfling') == 'Humano-Halfling'
    assert svc.talent_group('Enano') == 'Enano'
    assert svc.talent_group('Elfo Silvano') == 'Elfo'


# ── Full 1-100 sweeps: every roll must resolve to something for every race ──

def test_roll_race_covers_all_100_values():
    for roll in range(1, 101):
        entry = svc.roll_table(svc._load('races.json')['race_roll_table'], roll)
        assert entry is not None, f'roll {roll} uncovered'


@pytest.mark.parametrize('race', RACES)
def test_roll_characteristics_never_crashes(race):
    for _ in range(50):
        result = svc.roll_characteristics(race)
        for field in ('ws', 'bs', 's_char', 't_char', 'ag', 'int_char', 'wp', 'fel'):
            assert isinstance(result[field], int)
        assert result['wounds'] > 0
        assert result['fate_points'] >= 0
        assert result['history_points'] >= 0
        assert result['strength_bonus'] <= result['max_bf']
        assert result['toughness_bonus'] <= result['max_br']


@pytest.mark.parametrize('race', RACES)
def test_roll_wounds_fate_points_history_points_independently(race):
    """Standalone rerolls (e.g. "reroll just Heridas") must agree with the
    same tables roll_characteristics uses, without needing the rest of the
    characteristics roll."""
    for _ in range(50):
        wounds = svc.roll_wounds(race)
        assert wounds['value'] > 0
        assert 1 <= wounds['roll'] <= 10

        fate = svc.roll_fate_points(race)
        assert fate['value'] >= 0
        assert 1 <= fate['roll'] <= 10

        history = svc.roll_history_points(race)
        assert history['value'] >= 0
        assert 1 <= history['roll'] <= 10


@pytest.mark.parametrize('race', RACES)
def test_roll_altura_peso_edad_never_crash(race):
    for _ in range(50):
        altura = svc.roll_altura(race)
        assert altura['cm'] > 0
        peso = svc.roll_peso(race, altura['cm'])
        assert isinstance(peso['kg'], int)
        edad = svc.roll_edad(race)
        assert edad['edad'] > 0
        assert 1 <= edad['grado'] <= 5


@pytest.mark.parametrize('race', RACES)
def test_roll_procedencia_never_crashes(race):
    for _ in range(50):
        result = svc.roll_procedencia(race)
        assert result['procedencia']
        assert '__imperio__' not in result['procedencia']


@pytest.mark.parametrize('race', RACES)
def test_roll_situacion_familiar_never_crashes(race):
    for _ in range(50):
        result = svc.roll_situacion_familiar(race)
        assert result['situacion']
        assert isinstance(result['hermanos'], list)


@pytest.mark.parametrize('race', RACES)
def test_roll_talento_aleatorio_never_crashes(race):
    for _ in range(50):
        result = svc.roll_talento_aleatorio(race)
        assert result['talento']


def test_roll_signo_astral_covers_all_100_values():
    for roll in range(1, 101):
        entry = svc.roll_table(svc._load('signo_astral.json'), roll)
        assert entry is not None, f'roll {roll} uncovered'


def test_roll_estetica_personalidad_desventaja_never_crash():
    for _ in range(200):
        assert svc.roll_estetica()['value']
        assert svc.roll_personalidad()['value']
        assert svc.roll_desventaja()['value']


def test_roll_posesiones_never_crashes():
    for _ in range(100):
        result = svc.roll_posesiones()
        assert result['tipo'] in ('dinero', 'objetos', 'titulo')


def test_roll_posesiones_dinero_computes_co():
    result = None
    for _ in range(200):
        r = svc.roll_posesiones()
        if r['tipo'] == 'dinero':
            result = r
            break
    assert result is not None
    assert result['co'] >= 0


def test_roll_objeto_magico_never_crashes():
    for _ in range(200):
        result = svc.roll_objeto_magico()
        assert result['categoria'] in (
            'amuleto', 'bolsa', 'cuerda', 'ropa', 'varita', 'arma', 'armadura',
        )
        assert result['descripcion']


def test_roll_objeto_magico_makes_two_separate_rolls():
    """The rules require two rolls: one for the object type (amulet, weapon,
    armour...) and a second, independent one for the specific property within
    that type - both must be surfaced so the result is auditable."""
    result = svc.roll_objeto_magico()
    assert 1 <= result['tipo_roll'] <= 100
    assert 1 <= result['detail_roll'] <= 100


def test_roll_posesiones_bonus_can_reach_noble_title_entries(monkeypatch):
    """Spending 2 PH instead of 1 rolls with a +2 bonus specifically so a
    1d10 roll can reach entries 11/12 (knight/superior title) - confirm the
    bonus is actually applied to the roll, not just accepted as a no-op."""
    monkeypatch.setattr(svc, 'd10', lambda: 10)
    result = svc.roll_posesiones(bonus=2)
    assert result['roll'] == 12
    assert result['tipo'] == 'titulo'


def test_roll_apariencia_never_crashes():
    for _ in range(50):
        result = svc.roll_apariencia()
        assert result['pelo']
        assert result['ojos']
        assert result['mano_dominante'] in ('Diestro', 'Zurdo')


def test_roll_apariencia_exposes_raw_dice_for_the_roll_log():
    """Every roll must be auditable in the UI's roll log - the raw 1d10 for
    each of pelo/ojos/mano must be returned, not just the resolved value."""
    result = svc.roll_apariencia()
    assert 1 <= result['pelo_roll'] <= 10
    assert 1 <= result['ojos_roll'] <= 10
    assert 1 <= result['mano_roll'] <= 10


def test_get_frontend_tables_has_every_table_for_the_manual_picker_ui():
    tables = svc.get_frontend_tables()
    for key in (
        'raza', 'razas_caracteristicas', 'razas_caracteristicas_group', 'profesion',
        'signo_astral', 'altura', 'peso', 'edad', 'apariencia', 'procedencia',
        'situacion_familiar', 'sucesos_juventud', 'talentos_aleatorios', 'flaws',
        'posesiones', 'objetos_magicos',
    ):
        assert key in tables, f'missing {key}'

    # Spot-check the nested race-group data a manual picker needs for the
    # Heridas/Destino/Puntos-de-Historial sub-tables.
    for group in ('Humano', 'Halfling', 'Enano', 'Elfo'):
        spec = tables['razas_caracteristicas'][group]
        assert spec['wounds_table']
        assert spec['fate_points_table']
        assert spec['history_points_table']

    assert tables['flaws']['estetica']
    assert tables['flaws']['personalidad']
    assert tables['flaws']['desventaja']


def test_roll_sucesos_juventud_returns_requested_count():
    events = svc.roll_sucesos_juventud(4)
    assert len(events) == 4
    for e in events:
        assert 'categoria' in e


def test_roll_sucesos_juventud_zero_returns_empty():
    assert svc.roll_sucesos_juventud(0) == []


def test_roll_sucesos_juventud_never_repeats_narrativo_within_batch(monkeypatch):
    """31-35 is 'Madre muerta' (narrativo), 58-60 is a non-narrativo relacion
    entry. Force the same narrativo roll twice in a row - the second one must
    reroll instead of letting 'Madre muerta' happen twice to one character."""
    calls = iter([33, 33, 60])
    monkeypatch.setattr(svc, 'd100', lambda: next(calls))
    events = svc.roll_sucesos_juventud(2)
    narrativos = [e['value'] for e in events if e['categoria'] == 'narrativo']
    assert narrativos == ['Madre muerta']
    assert len(events) == 2


def test_roll_sucesos_juventud_respects_excluir_from_previous_rolls(monkeypatch):
    calls = iter([33, 33, 33, 60])
    monkeypatch.setattr(svc, 'd100', lambda: next(calls))
    events = svc.roll_sucesos_juventud(1, excluir=['Madre muerta'])
    assert events[0]['roll'] == 60
    assert events[0]['categoria'] != 'narrativo'


def test_roll_talento_aleatorio_never_repeats_when_excluded(monkeypatch):
    table = svc._load('random_talents.json')['Humano-Halfling']
    first_entry, second_entry = table[0], table[1]
    calls = iter([first_entry['min'], second_entry['min']])
    monkeypatch.setattr(svc, 'd100', lambda: next(calls))
    result = svc.roll_talento_aleatorio('Humano', excluir=[first_entry['value']])
    assert result['talento'] == second_entry['value']


def test_horas_sueno_formula():
    assert svc.horas_sueno('Humano', 40) == 11 - 4
    assert svc.horas_sueno('Enano', 55) == 10 - 5


def test_roll_profession_returns_none_for_unreachable_combo():
    """'Espadachín estaliano' has no roll range for any race in the source
    table - confirm the roll function tolerates gaps instead of crashing."""
    for _ in range(300):
        result = svc.roll_profession('Enano')
        assert 'roll' in result


def test_match_profession_to_catalog_exact_and_fuzzy(make_profession, db):
    exact = make_profession(name='Alborotador')
    typo = make_profession(name='Cazarratas')
    professions = [exact, typo]
    assert svc.match_profession_to_catalog('Alborotador', professions).id == exact.id
    assert svc.match_profession_to_catalog('Cazarrata', professions).id == typo.id
    assert svc.match_profession_to_catalog('Profesión Inventada', professions) is None
    assert svc.match_profession_to_catalog(None, professions) is None


def test_race_info_returns_fixed_traits():
    info = svc.race_info('Halfling')
    assert 'Cotilleo' in info['habilidades']
    assert 'Resistencia al Caos' in info['talentos_fijos']


def test_race_info_includes_province_bonus_for_humano():
    info = svc.race_info('Humano', provincia='Reikland')
    assert info['provincia_bonus'] is not None
    assert 'Reikland' in info['provincia_bonus']['regla_especial']


def test_race_info_no_province_bonus_for_non_human():
    info = svc.race_info('Enano', provincia='Reikland')
    assert 'provincia_bonus' not in info


def test_history_point_options_has_expected_shape():
    opts = svc.history_point_options()
    assert opts['max_puntos'] == 4
    ids = {o['id'] for o in opts['opciones']}
    assert 'objeto_magico' in ids
    assert 'talento_aleatorio' in ids

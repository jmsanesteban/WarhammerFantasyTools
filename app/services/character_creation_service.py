"""
Character creation service (WFRP2, house-ruled per "Creación de personajes").

Encodes every random table from the rules doc as JSON under
app/data/character_creation/ and exposes one roll_xxx() function per creation
step. Each function returns plain dicts/primitives - no DB access here except
match_profession_to_catalog(), which needs the Profession table to resolve a
rolled profession name to a real catalog entry.

Races used as dict keys throughout: 'Humano', 'Halfling', 'Enano',
'Elfo Silvano', 'Alto Elfo'. Elfo Silvano and Alto Elfo share the same
characteristics/altura/peso/edad/talentos-aleatorios tables (grouped as
'Elfo') but differ in racial traits, skills and provenance.
"""
import difflib
import json
import os
import random
import re

_DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'character_creation')

_CACHE = {}


def _load(filename: str):
    if filename not in _CACHE:
        path = os.path.join(_DATA_DIR, filename)
        with open(path, encoding='utf-8') as f:
            _CACHE[filename] = json.load(f)
    return _CACHE[filename]


# ---------------------------------------------------------------------------
# Dice / table primitives
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r'(?P<dsign>[+-]?)(?P<dcount>\d*)d(?P<dsides>\d+)|(?P<nsign>[+-]?)(?P<nnum>\d+)(?!d)',
    re.IGNORECASE,
)


def roll_dice(formula: str) -> int:
    """Evaluate a formula like '20+2d10', '-2d6', '15+1d3', '+1d10+1d4'."""
    total = 0
    for m in _TOKEN_RE.finditer(str(formula)):
        if m.group('dsides') is not None:
            sign = -1 if m.group('dsign') == '-' else 1
            count = int(m.group('dcount')) if m.group('dcount') else 1
            sides = int(m.group('dsides'))
            total += sign * sum(random.randint(1, sides) for _ in range(count))
        elif m.group('nnum') is not None:
            sign = -1 if m.group('nsign') == '-' else 1
            total += sign * int(m.group('nnum'))
    return total


def d100() -> int:
    return random.randint(1, 100)


def d10() -> int:
    return random.randint(1, 10)


def d6() -> int:
    return random.randint(1, 6)


def roll_table(table: list, roll: int):
    """Return the first entry whose [min, max] range contains roll, or None."""
    for entry in table:
        if entry['min'] <= roll <= entry['max']:
            return entry
    return None


# ---------------------------------------------------------------------------
# Race groups
# ---------------------------------------------------------------------------

def characteristics_group(race: str) -> str:
    races = _load('races.json')
    return races['characteristics_group'].get(race, race)


def talent_group(race: str) -> str:
    """Maps a race to the key used by random_talents.json / procedencia elf split."""
    group = characteristics_group(race)
    return 'Humano-Halfling' if group in ('Humano', 'Halfling') else group


# ---------------------------------------------------------------------------
# Step 1: Raza
# ---------------------------------------------------------------------------

def roll_race() -> dict:
    races = _load('races.json')
    roll = d100()
    entry = roll_table(races['race_roll_table'], roll)
    return {'roll': roll, 'race': entry['race']}


# ---------------------------------------------------------------------------
# Step 2: Profesión
# ---------------------------------------------------------------------------

_RACE_COL = {'Humano': 'humano', 'Halfling': 'halfling', 'Enano': 'enano',
             'Elfo Silvano': 'elfo', 'Alto Elfo': 'elfo'}


def _parse_percentile_range(raw: str):
    if not raw:
        return None
    raw = raw.strip()
    if '-' in raw:
        lo, hi = raw.split('-', 1)
    else:
        lo = hi = raw
    lo, hi = int(lo), int(hi)
    if hi == 0:
        hi = 100
    if lo == 0:
        lo = 100
    return lo, hi


def roll_profession(race: str) -> dict:
    """Roll a profession name for the given race. Returns None profession_name
    if nothing in the table covers that roll for this race (can happen -
    not every profession is reachable for every race)."""
    table = _load('profession_table.json')
    col = _RACE_COL.get(race, 'humano')
    roll = d100()
    for row in table:
        raw = row.get(col)
        rng = _parse_percentile_range(raw)
        if rng and rng[0] <= roll <= rng[1]:
            return {'roll': roll, 'profession_name': row['name']}
    return {'roll': roll, 'profession_name': None}


def match_profession_to_catalog(name: str, professions: list):
    """Fuzzy-match a rolled profession name against the real Profession
    catalog (case-insensitive, tolerant of minor spelling differences)."""
    if not name:
        return None
    name_map = {p.name.lower(): p for p in professions}
    low = name.lower()
    if low in name_map:
        return name_map[low]
    hits = difflib.get_close_matches(low, name_map.keys(), n=1, cutoff=0.8)
    return name_map[hits[0]] if hits else None


# ---------------------------------------------------------------------------
# Step 3: Características
# ---------------------------------------------------------------------------

def roll_characteristics(race: str) -> dict:
    races = _load('races.json')
    group = characteristics_group(race)
    spec = races['characteristics'][group]

    result = {'movement': spec['movement'], 'attacks': spec['attacks'], 'magic': spec['magic']}
    for field in ('ws', 'bs', 's_char', 't_char', 'ag', 'int_char', 'wp', 'fel'):
        result[field] = roll_dice(spec[field])

    her_roll = d10()
    result['wounds'] = roll_table(spec['wounds_table'], her_roll)['value']

    pd_roll = d10()
    result['fate_points'] = roll_table(spec['fate_points_table'], pd_roll)['value']

    ph_roll = d10()
    result['history_points'] = roll_table(spec['history_points_table'], ph_roll)['value']

    result['strength_bonus'] = min(result['s_char'] // 10, spec['max_bf'])
    result['toughness_bonus'] = min(result['t_char'] // 10, spec['max_br'])
    result['insanity_points'] = 0
    result['max_bf'] = spec['max_bf']
    result['max_br'] = spec['max_br']
    result['rolls'] = {'heridas_d10': her_roll, 'destino_d10': pd_roll, 'historial_d10': ph_roll}
    return result


# ---------------------------------------------------------------------------
# Step 4: Signo astral
# ---------------------------------------------------------------------------

def roll_signo_astral() -> dict:
    table = _load('signo_astral.json')
    roll = d100()
    entry = roll_table(table, roll)
    return {'roll': roll, 'signo': entry['signo'], 'rasgo': entry['rasgo'], 'modificadores': entry['modificadores']}


# ---------------------------------------------------------------------------
# Step 5: Altura / Peso
# ---------------------------------------------------------------------------

def roll_altura(race: str, gender: str = 'Masculino') -> dict:
    data = _load('altura_peso_edad.json')
    group = characteristics_group(race)
    table = data['altura'][group]
    roll = d100()
    entry = roll_table(table, roll)
    base = entry['base'] if gender == 'Masculino' else entry['base_f']
    cm = base + roll_dice(entry['formula'])
    return {'roll': roll, 'cm': cm, 'modificadores': entry.get('modificadores')}


def roll_peso(race: str, altura_cm: int) -> dict:
    data = _load('altura_peso_edad.json')['peso']
    group = characteristics_group(race)
    offset = data['offset_from_altura'][group]
    roll = d100()
    entry = roll_table(data['tramos'], roll)
    kg = altura_cm + offset + roll_dice(entry['formula'])
    return {'roll': roll, 'kg': kg, 'modificadores': entry.get('modificadores')}


# ---------------------------------------------------------------------------
# Step 6: Edad
# ---------------------------------------------------------------------------

def roll_edad(race: str) -> dict:
    data = _load('altura_peso_edad.json')['edad']
    group = characteristics_group(race)
    table = data[group]
    roll = d100()
    entry = roll_table(table, roll)
    edad = roll_dice(entry['formula'])
    grado = entry['grado']
    modificadores = data['grado_modificadores'].get(str(grado))
    return {'roll': roll, 'edad': edad, 'grado': grado, 'modificadores': modificadores}


# ---------------------------------------------------------------------------
# Step 7: Apariencia (pelo/ojos/mano dominante)
# ---------------------------------------------------------------------------

def roll_apariencia() -> dict:
    data = _load('apariencia.json')
    pelo_roll = d10()
    ojos_roll = d10()
    mano_roll = d10()
    return {
        'pelo': roll_table(data['pelo'], pelo_roll)['value'],
        'ojos': roll_table(data['ojos'], ojos_roll)['value'],
        'mano_dominante': roll_table(data['mano_dominante'], mano_roll)['value'],
    }


# ---------------------------------------------------------------------------
# Step 8: Procedencia
# ---------------------------------------------------------------------------

def _roll_humano_imperio() -> str:
    data = _load('procedencia.json')['humano_imperio']
    roll = d100()
    provincia = roll_table(data['provincia_table'], roll)['provincia']
    roll2 = d100()
    poblacion = roll_table(data['poblaciones'][provincia], roll2)['value']
    return f'{provincia} - {poblacion}'


def roll_procedencia(race: str) -> dict:
    data = _load('procedencia.json')
    if race == 'Humano':
        return {'procedencia': _roll_humano_imperio()}
    if race == 'Halfling':
        roll = d10()
        entry = roll_table(data['halfling'], roll)
        value = entry['value']
    elif race == 'Enano':
        roll = d100()
        entry = roll_table(data['enano'], roll)
        value = entry['value']
    elif race == 'Elfo Silvano':
        roll = d10()
        entry = roll_table(data['elfo_silvano'], roll)
        value = entry['value']
    elif race == 'Alto Elfo':
        roll = d10()
        entry = roll_table(data['alto_elfo'], roll)
        value = entry['value']
    else:
        return {'procedencia': _roll_humano_imperio()}

    if value == '__imperio__':
        value = _roll_humano_imperio()
    return {'procedencia': value}


# ---------------------------------------------------------------------------
# Step 9: Situación familiar
# ---------------------------------------------------------------------------

def roll_situacion_familiar(race: str) -> dict:
    fs = _load('family_and_social.json')
    group = characteristics_group(race)
    roll = d10()
    entry = roll_table(fs['situacion_familiar'], roll)

    if entry['value'] != 'hermanos':
        return {'roll': roll, 'situacion': entry['label'], 'hermanos': []}

    num_hermanos = max(0, roll_dice(f"1d{fs['hermanos_dado_base'][group]}") + fs['hermanos_ajuste'][group])
    hermanos = []
    for _ in range(num_hermanos):
        sexo = roll_table(fs['hermano_sexo'], d6())['value']
        rel = roll_table(fs['hermano_edad_relativa'], d6())['value']
        anos = roll_dice('1d6')
        hermanos.append(f'{sexo}, {rel} en {anos} años')
    label = f'{num_hermanos} hermano(s): ' + '; '.join(hermanos) if hermanos else 'Sin hermanos'
    return {'roll': roll, 'situacion': label, 'hermanos': hermanos}


# ---------------------------------------------------------------------------
# Step 10: Sucesos de juventud
# ---------------------------------------------------------------------------

def roll_sucesos_juventud(num_rolls: int) -> list:
    table = _load('youth_events.json')
    events = []
    for _ in range(max(0, num_rolls)):
        roll = d100()
        entry = roll_table(table, roll)
        events.append({'roll': roll, **entry})
    return events


# ---------------------------------------------------------------------------
# Step 11: Talento aleatorio
# ---------------------------------------------------------------------------

def roll_talento_aleatorio(race: str) -> dict:
    table = _load('random_talents.json')[talent_group(race)]
    roll = d100()
    entry = roll_table(table, roll)
    return {'roll': roll, 'talento': entry['value']}


# ---------------------------------------------------------------------------
# Step 12: Estética / Personalidad / Desventaja
# ---------------------------------------------------------------------------

def _roll_flaw_table(key: str) -> dict:
    table = _load('aesthetic_personality_flaws.json')[key]
    roll = d100()
    entry = roll_table(table, roll)
    return {'roll': roll, 'value': entry['value']}


def roll_estetica() -> dict:
    return _roll_flaw_table('estetica')


def roll_personalidad() -> dict:
    return _roll_flaw_table('personalidad')


def roll_desventaja() -> dict:
    return _roll_flaw_table('desventaja')


# ---------------------------------------------------------------------------
# Step 13: Posesiones
# ---------------------------------------------------------------------------

def roll_posesiones(bonus: int = 0) -> dict:
    table = _load('possessions.json')['tabla_posesiones']
    roll = d10() + bonus
    entry = roll_table(table, roll) or table[-1]
    result = {'roll': roll, 'tipo': entry['tipo'], 'descripcion': entry['value']}
    if entry['tipo'] == 'dinero':
        result['co'] = roll_dice(entry['value'].split(' Co')[0].replace('+', ''))
    elif entry['tipo'] == 'objetos':
        result['max_objetos'] = entry['max_objetos']
        result['valor_co'] = entry['valor_co']
    return result


# ---------------------------------------------------------------------------
# Step 14: Objetos mágicos
# ---------------------------------------------------------------------------

def roll_objeto_magico() -> dict:
    data = _load('magic_items.json')
    tipo_roll = d100()
    categoria = roll_table(data['tipo_objeto'], tipo_roll)['value']
    detail_roll = d100()
    entry = roll_table(data[categoria], detail_roll)
    return {'tipo_roll': tipo_roll, 'detail_roll': detail_roll, 'categoria': categoria, 'descripcion': entry['value']}


# ---------------------------------------------------------------------------
# Horas de sueño (fórmula, no tirada)
# ---------------------------------------------------------------------------

def horas_sueno(race: str, resistencia: int) -> int:
    fs = _load('family_and_social.json')
    group = characteristics_group(race)
    base = fs['horas_sueno_base'][group]
    return base - (resistencia // 10)


# ---------------------------------------------------------------------------
# Puntos de historial: catálogo de opciones
# ---------------------------------------------------------------------------

def history_point_options() -> dict:
    return _load('history_points.json')


# ---------------------------------------------------------------------------
# Info racial (rasgos/habilidades/talentos fijos - no es una tirada)
# ---------------------------------------------------------------------------

def race_info(race: str, provincia: str = None) -> dict:
    traits = _load('race_traits.json')
    info = dict(traits.get(race, {}))
    if race == 'Humano' and provincia:
        provincias = traits.get('provincias_imperio', {})
        info['provincia_bonus'] = provincias.get(provincia)
    return info

"""Reference salary table (tipo de sueldo x estado de habilidad) - manually
selected, not computed from any actual skill percentage. Used both by
Contactos (per-profession salary on a ContactProfession) and by
Personajes (per-profession salary on a CharacterProfession)."""
import json
import os
import re
from app.services.currency_service import to_peniques, format_peniques

_DATA_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'salaries.json')

_CACHE = None

_MONEY_RE = re.compile(r'(?:(\d+)CO)?\s*(?:(\d+)c)?\s*(?:(\d+)p)?')


def get_salary_table() -> dict:
    global _CACHE
    if _CACHE is None:
        with open(_DATA_PATH, encoding='utf-8') as f:
            _CACHE = json.load(f)
    return _CACHE


def tipo_choices() -> list:
    return [t['tipo'] for t in get_salary_table()['tipos']]


def estado_choices() -> list:
    return [e['estado'] for e in get_salary_table()['estados_habilidad']]


def compute_sueldo(tipo_sueldo, estado_habilidad):
    """Weekly wage for a tipo_sueldo x estado_habilidad combo, formatted as
    money text - the base sueldo_semanal from the reference table, scaled by
    the estado's multiplicador. Used for Contactos, which (unlike Personajes)
    have no actual skill percentage to weigh it further. None if either
    choice is missing/unrecognized."""
    table = get_salary_table()
    tipo = next((t for t in table['tipos'] if t['tipo'] == tipo_sueldo), None)
    estado = next((e for e in table['estados_habilidad'] if e['estado'] == estado_habilidad), None)
    if not tipo or not estado:
        return None
    match = _MONEY_RE.match(tipo['sueldo_semanal'])
    coronas, chelines, peniques = (int(g) if g else 0 for g in match.groups())
    total = round(to_peniques(coronas, chelines, peniques) * estado['multiplicador'])
    return format_peniques(total)


def sueldo_lookup() -> dict:
    """{tipo: {estado: sueldo formateado}} for every combination in the
    reference table - lets a page show a live-updating computed wage as the
    director picks tipo/estado for a Contacto's profession, without
    reimplementing the money math in JS."""
    table = get_salary_table()
    return {
        t['tipo']: {e['estado']: compute_sueldo(t['tipo'], e['estado']) for e in table['estados_habilidad']}
        for t in table['tipos']
    }

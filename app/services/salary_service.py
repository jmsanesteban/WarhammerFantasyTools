"""Reference salary table (tipo de sueldo x estado de habilidad) - manually
selected, not computed from any actual skill percentage. Used both by
Contactos (per-profession salary on a ContactCharacterSalary) and by
Personajes (per-profession salary on a CharacterProfession)."""
import json
import os

_DATA_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'salaries.json')

_CACHE = None


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

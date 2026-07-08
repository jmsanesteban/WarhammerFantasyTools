"""Money helpers: Corona de oro (Co) / Chelín de plata (C) / Penique (Pe).
1 Co = 20 C = 240 Pe; 1 C = 12 Pe. Everything is stored/computed in peniques
(the smallest unit) to avoid rounding issues, and only formatted for display."""

PENIQUES_POR_CHELIN = 12
PENIQUES_POR_CORONA = 240


def to_peniques(coronas: int = 0, chelines: int = 0, peniques: int = 0) -> int:
    return coronas * PENIQUES_POR_CORONA + chelines * PENIQUES_POR_CHELIN + peniques


def format_peniques(total: int) -> str:
    if total is None:
        return ''
    negative = total < 0
    total = abs(total)
    coronas, resto = divmod(total, PENIQUES_POR_CORONA)
    chelines, peniques = divmod(resto, PENIQUES_POR_CHELIN)
    parts = []
    if coronas:
        parts.append(f'{coronas} Co')
    if chelines:
        parts.append(f'{chelines} C')
    if peniques or not parts:
        parts.append(f'{peniques} Pe')
    text = ' '.join(parts)
    return f'-{text}' if negative else text

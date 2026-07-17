"""Book order for the Armas/Armaduras/Ropa catalog (uploads/*.pdf), used by
the `flask set-equipment-book-order` command to fill in EquipmentItem.orden.

ARMA_ORDEN / ARMADURA_ORDEN: list of (name, subcategory) tuples in the exact
order they appear in "Armas fantastico Revisada.pdf" / "Armaduras Revisada.pdf"
- a name can repeat across subcategories (e.g. "Daga" is both a
cuerpo_a_cuerpo weapon and a distancia/arrojadiza one; "Casco" appears in
several armour families), which is why matching is by (name, subcategory)
pair, never name alone.

ROPA_SUBCATEGORY_ORDEN: Ropa's book ("Ropas revisada.pdf") repeats the same
list of clothing types across 4 quality-tier sections (Harapos/Común/
Burguesa/Noble = mala/normal/buena/excelente) rather than listing distinct
items per tier, so there's nothing to name-match - orden is instead computed
as `type_rank * 10 + quality_rank` (see the command), giving a stable order
without needing a name at all.
"""

ARMA_ORDEN = [
    # Cuerpo a cuerpo (p.2-4)
    ('Daga', 'cuerpo_a_cuerpo'), ('Daga larga', 'cuerpo_a_cuerpo'), ('Espada corta', 'cuerpo_a_cuerpo'),
    ('Espada', 'cuerpo_a_cuerpo'), ('Cimitarra', 'cuerpo_a_cuerpo'), ('Alfanje', 'cuerpo_a_cuerpo'),
    ('Hacha', 'cuerpo_a_cuerpo'), ('Hacha de Batalla', 'cuerpo_a_cuerpo'), ('Espada bastarda', 'cuerpo_a_cuerpo'),
    ('Espadón', 'cuerpo_a_cuerpo'),
    ('Martillo', 'cuerpo_a_cuerpo'), ('Maza', 'cuerpo_a_cuerpo'), ('Maza de guerra', 'cuerpo_a_cuerpo'),
    ('Martillo de guerra', 'cuerpo_a_cuerpo'), ('Estrella de la mañana', 'cuerpo_a_cuerpo'),
    ('Gran hacha', 'cuerpo_a_cuerpo'), ('Flagelo', 'cuerpo_a_cuerpo'), ('Alabarda', 'cuerpo_a_cuerpo'),
    ('Lanza', 'cuerpo_a_cuerpo'), ('Bastón de guerra', 'cuerpo_a_cuerpo'),
    ('Florete', 'cuerpo_a_cuerpo'), ('Ropera', 'cuerpo_a_cuerpo'), ('Lanza de Caballería', 'cuerpo_a_cuerpo'),
    ('Garrote/porra', 'cuerpo_a_cuerpo'), ('Guantalete', 'cuerpo_a_cuerpo'), ('Nudilleras', 'cuerpo_a_cuerpo'),
    ('Vizcaina', 'cuerpo_a_cuerpo'), ('Rompespada', 'cuerpo_a_cuerpo'), ('Puño/patada', 'cuerpo_a_cuerpo'),
    ('Improvisada', 'cuerpo_a_cuerpo'),
    # A distancia: arcos/ballestas/pólvora (p.5), luego arrojadizas/ingeniería (p.6)
    ('Arco Corto', 'distancia'), ('Arco compuesto', 'distancia'), ('Arco largo', 'distancia'),
    ('Ballesta', 'distancia'), ('Ballesta pesada', 'distancia'), ('Arco Elfico', 'distancia'),
    ('Ballesta de repetición', 'distancia'), ('Pistola', 'distancia'), ('Mosquete', 'distancia'),
    ('Trabuco', 'distancia'),
    ('Honda', 'distancia'), ('Jabalina', 'distancia'), ('Daga', 'distancia'), ('Lanza', 'distancia'),
    ('Cuchillo arrojadizo', 'distancia'), ('Improvisada', 'distancia'), ('Rifle largo de Hochland', 'distancia'),
    ('Pistola ballesta', 'distancia'), ('Pistola de repetición', 'distancia'), ('Mosquete de repetición', 'distancia'),
]

ARMADURA_ORDEN = [
    # Acolchada / Gambesón (p.2)
    ('Gorro Acolchado', 'acolchada'), ('Chaqueta Acolchado', 'acolchada'), ('Perneras', 'acolchada'),
    # Armadura de Cuero (p.3)
    ('Justillo', 'cuero'), ('Grebas', 'cuero'), ('Brazales', 'cuero'),
    # Pieles Gruesas (p.4-5)
    ('Gorro', 'pieles'), ('Justillo', 'pieles'), ('Chaqueta', 'pieles'), ('Abrigo', 'pieles'),
    # Cuero Endurecido (p.6-7)
    ('Casco', 'cuero_endurecido'), ('Coraza', 'cuero_endurecido'), ('Grebas', 'cuero_endurecido'),
    ('Brazales', 'cuero_endurecido'),
    # Cota de malla (p.8-9)
    ('Cofia', 'malla'), ('Camisa', 'malla'), ('Camisote', 'malla'), ('Abrigo', 'malla'),
    # Escamas / Lamelar (p.10-11) - el libro da un único "Yelmo" con precio
    # doble ("50/75", sin/con visera); el catálogo lo desdobla en dos filas
    # compradas por separado.
    ('Casco', 'escamas'), ('Yelmo de escamas', 'escamas'), ('Yelmo de escamas con visera', 'escamas'),
    ('Camisa', 'escamas'), ('Camisote', 'escamas'), ('Abrigo', 'escamas'),
    # Placas (p.12-13) - mismo desdoble sin/con visera que en Escamas.
    ('Casco', 'placas'), ('Yelmo de placas', 'placas'), ('Yelmo de placas con visera', 'placas'),
    ('Coraza', 'placas'), ('Grebas', 'placas'), ('Brazales', 'placas'),
    # Escudos (p.14-15)
    ('Rodela', 'escudos'), ('Redondo', 'escudos'), ('Heraldo', 'escudos'), ('Torre', 'escudos'),
]

# Book encounter order of Ropa's clothing types (first appearance across the
# Harapos/Común/Burguesa/Noble sections) - not every type appears in every
# tier (e.g. "Ropa ligera" is Común-only, "Sombrero" skips Harapos), but the
# type itself always sorts the same regardless of which tiers it has rows in.
ROPA_SUBCATEGORY_ORDEN = [
    'ropa', 'ropa_ligera', 'ropa_invernal', 'ropa_veraniega', 'gorro', 'sombrero',
    'zapatos_botines', 'botas', 'abrigo', 'manto_capa', 'sobretodo', 'guantes',
    'tahali', 'adorno', 'sobrevesta',
]

from datetime import datetime
from app.extensions import db


class Synonym(db.Model):
    """
    Translation / normalization dictionary for PDF import.

    source   — wrong or alternate form (lower-case, as it appears in GTranslate output)
    target   — correct official WFRP2 Spanish name
    is_prefix — when True, also matches 'source (specialization)' → 'target (specialization)'
                (used for skills like 'sabiduría académica', 'hablar idioma', etc.)
    notes    — optional explanation for admins
    """
    __tablename__ = 'synonyms'

    id         = db.Column(db.Integer,     primary_key=True)
    source     = db.Column(db.String(200), nullable=False, unique=True, index=True)
    target     = db.Column(db.String(200), nullable=False)
    is_prefix  = db.Column(db.Boolean,     nullable=False, default=False)
    notes      = db.Column(db.String(500))
    created_at = db.Column(db.DateTime,    default=datetime.utcnow)

    def __repr__(self):
        return f'<Synonym {self.source!r} → {self.target!r}>'


# Default entries seeded on first run
DEFAULT_SYNONYMS = [
    # (source, target, is_prefix, notes)
    ('conocimiento académico', 'sabiduría académica', True,  'GTranslate ES → WFRP2 ES (con prefijo para especializaciones)'),
    ('conocimiento común',     'sabiduría popular',   True,  'GTranslate ES → WFRP2 ES (con prefijo para especializaciones)'),
    ('hablar idioma',          'hablar idioma',        True,  'Mismo término; prefijo activo para detectar "hablar idioma (X)"'),
    ('encanto',                'carisma',              False, 'GTranslate usa "encanto" en lugar del término oficial "carisma"'),
    ('chisme',                 'cotilleo',             False, 'GTranslate usa "chisme" en lugar del término oficial "cotilleo"'),
    ('curación',               'curar',                False, 'GTranslate usa "curación" en lugar del término oficial "curar"'),
    ('ocultación',             'esconderse',           False, 'GTranslate usa "ocultación" en lugar de "esconderse"'),
    ('lectura/escritura',      'leer/escribir',        False, 'Variante de separador'),
    ('leer / escribir',        'leer/escribir',        False, 'Variante con espacios alrededor del separador'),
    ('cuidado de animales',    'criar animales',       False, 'Traducción aproximada de "Animal Care"'),
    ('adiestramiento animal',  'adiestrar animales',   False, 'Traducción aproximada de "Animal Training"'),
    ('sangre fría',            'sangre fría',          False, 'Identidad — reservado para coherencia interna'),
    ('blather',                'disparatar',           False, 'Inglés → español oficial WFRP2'),
    ('franqueza',              'contundente',          False, 'GTranslate aproximación de "Bluntness" / "Surehanded"'),
]

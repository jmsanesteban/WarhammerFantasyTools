from app.extensions import db

# ── Association tables ────────────────────────────────────────────────────────

user_permissions = db.Table(
    'user_permissions',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    db.Column('permission_code', db.String(50), db.ForeignKey('permissions.code', ondelete='CASCADE'), primary_key=True),
)

template_permissions = db.Table(
    'template_permissions',
    db.Column('template_id', db.Integer, db.ForeignKey('permission_templates.id', ondelete='CASCADE'), primary_key=True),
    db.Column('permission_code', db.String(50), db.ForeignKey('permissions.code', ondelete='CASCADE'), primary_key=True),
)


# ── Models ────────────────────────────────────────────────────────────────────

class Permission(db.Model):
    __tablename__ = 'permissions'

    code        = db.Column(db.String(50),  primary_key=True)
    name        = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255))
    module      = db.Column(db.String(50),  nullable=False, index=True)

    def __repr__(self):
        return f'<Permission {self.code}>'


class PermissionTemplate(db.Model):
    __tablename__ = 'permission_templates'

    id          = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name        = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(255))

    permissions = db.relationship(
        'Permission',
        secondary='template_permissions',
        lazy='select',
        order_by='Permission.module, Permission.code',
    )

    def __repr__(self):
        return f'<PermissionTemplate {self.name}>'


# ── Seed data ─────────────────────────────────────────────────────────────────

# Ordered list of all permissions the app supports.
# Add new entries here as the app grows; seed_permissions() is idempotent.
ALL_PERMISSIONS = [
    # (code, name, description, module)
    ('professions.view',   'Ver profesiones',        'Consultar listado y detalle de profesiones',              'professions'),
    ('professions.edit',   'Editar profesiones',     'Crear, editar y eliminar profesiones',                    'professions'),
    ('professions.import', 'Importar desde PDF',     'Importar profesiones desde un PDF',                       'professions'),
    ('skills.view',        'Ver habilidades',        'Consultar habilidades y talentos',                        'skills'),
    ('skills.edit',        'Editar habilidades',     'Crear, editar y eliminar habilidades y talentos',         'skills'),
    ('pathfinder.use',     'Buscador de caminos',    'Buscar rutas entre profesiones',                          'pathfinder'),
    ('characters.view',    'Ver personajes',         'Consultar personajes propios',                            'characters'),
    ('characters.edit',    'Editar personajes',      'Crear y editar personajes propios',                       'characters'),
    ('contacts.view',      'Ver contactos',          'Consultar listado y ficha de contactos visibles',         'contacts'),
    ('contacts.edit',      'Editar contactos',       'Crear, editar y eliminar contactos (no incluye el vínculo propio de personaje)', 'contacts'),
    ('contacts.import',    'Importar contactos',     'Importar/exportar contactos desde Excel',                 'contacts'),
    ('contacts.vinculos',  'Vínculos con contactos', 'Ver/editar el vínculo y notas propias de un personaje con un contacto, y la pantalla Vínculos', 'contacts'),
    ('users.manage',       'Gestionar usuarios',     'Asignar plantillas y permisos a otros usuarios (no convertir en admin)', 'admin'),
    ('equipment.view',     'Ver equipamiento',       'Consultar catálogo de armas, armaduras, ropas y objetos especiales', 'equipment'),
    ('equipment.edit',     'Editar equipamiento',    'Crear, editar y eliminar objetos del catálogo de equipamiento', 'equipment'),
    ('equipment.import',   'Importar equipamiento',  'Importar/exportar el catálogo de equipamiento en JSON',    'equipment'),
    ('food.view',          'Ver comida y bebida',    'Consultar bebidas, recetas, ingredientes, métodos de cocina y normas', 'food'),
    ('food.propose',       'Proponer recetas',       'Proponer recetas propias y consultar su estado',          'food'),
]

# Default templates seeded on first run.
DEFAULT_TEMPLATES = [
    # (name, description, [permission_codes])
    (
        'Jugador',
        'Plantilla por defecto para usuarios nuevos: personajes propios y contactos visibles',
        ['characters.view', 'characters.edit', 'contacts.view', 'contacts.vinculos'],
    ),
    (
        'Lector',
        'Acceso de solo consulta a todas las secciones públicas',
        ['professions.view', 'skills.view', 'pathfinder.use', 'characters.view', 'contacts.view',
         'contacts.vinculos', 'equipment.view', 'food.view'],
    ),
    (
        'Editor',
        'Consulta y edición de contenido del juego',
        ['professions.view', 'professions.edit', 'professions.import',
         'skills.view', 'skills.edit', 'pathfinder.use',
         'characters.view', 'characters.edit',
         'contacts.view', 'contacts.edit', 'contacts.import', 'contacts.vinculos',
         'equipment.view', 'equipment.edit', 'equipment.import',
         'food.view', 'food.propose'],
    ),
    (
        'Gestor',
        'Editor con capacidad de gestionar permisos de otros usuarios',
        ['professions.view', 'professions.edit', 'professions.import',
         'skills.view', 'skills.edit', 'pathfinder.use',
         'characters.view', 'characters.edit',
         'contacts.view', 'contacts.edit', 'contacts.import', 'contacts.vinculos',
         'equipment.view', 'equipment.edit', 'equipment.import',
         'food.view', 'food.propose', 'users.manage'],
    ),
]


def seed_permissions_and_templates():
    """Idempotent: insert any missing permissions, keep existing ones' name/
    description in sync, create default templates, and backfill newly-added
    permission codes into already-existing default templates (additive only -
    never removes a code an admin may have deliberately unchecked)."""
    for code, name, description, module in ALL_PERMISSIONS:
        existing = db.session.get(Permission, code)
        if not existing:
            db.session.add(Permission(
                code=code, name=name, description=description, module=module
            ))
        elif existing.name != name or existing.description != description:
            existing.name = name
            existing.description = description
    db.session.flush()

    for t_name, t_desc, codes in DEFAULT_TEMPLATES:
        template = PermissionTemplate.query.filter_by(name=t_name).first()
        perms = [db.session.get(Permission, c) for c in codes]
        perms = [p for p in perms if p]
        if not template:
            db.session.add(PermissionTemplate(
                name=t_name, description=t_desc, permissions=perms
            ))
        else:
            existing_codes = {p.code for p in template.permissions}
            for p in perms:
                if p.code not in existing_codes:
                    template.permissions.append(p)
    db.session.commit()

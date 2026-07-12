import logging
import os
import click
from flask import Flask, flash, redirect, url_for, request, jsonify
from app.config import config_by_name
from app.extensions import db, login_manager, bcrypt, migrate, csrf


def create_app(config_name='default'):
    app = Flask(__name__)
    app.config.from_object(config_by_name[config_name])

    url_prefix = os.environ.get('URL_PREFIX', '').rstrip('/')
    if url_prefix:
        from app.wsgi_prefix import PrefixMiddleware
        app.config['APPLICATION_ROOT'] = url_prefix
        # Flask derives the session cookie's Path from APPLICATION_ROOT unless
        # told otherwise - that would scope every cookie to the prefix even
        # for the unprefixed requests PrefixMiddleware deliberately still
        # answers (LAN access to wft-prepro, health checks), making the
        # browser withhold the cookie on those and silently drop the session.
        # Pin it to '/' so login works the same whether a request arrives
        # prefixed (via the Cloudflare Tunnel) or not.
        app.config['SESSION_COOKIE_PATH'] = '/'
        app.wsgi_app = PrefixMiddleware(app.wsgi_app, url_prefix)

    db.init_app(app)
    login_manager.init_app(app)
    bcrypt.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Register blueprints
    from app.routes.auth import auth_bp
    from app.routes.main import main_bp
    from app.routes.professions import professions_bp
    from app.routes.skills_talents import skills_talents_bp
    from app.routes.pathfinder import pathfinder_bp
    from app.routes.characters import characters_bp
    from app.routes.contacts import contacts_bp
    from app.routes.admin import admin_bp
    from app.routes.food import food_bp
    from app.routes.equipment import equipment_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(main_bp)
    app.register_blueprint(professions_bp, url_prefix='/profesiones')
    app.register_blueprint(skills_talents_bp)
    app.register_blueprint(pathfinder_bp, url_prefix='/buscador')
    app.register_blueprint(characters_bp, url_prefix='/personajes')
    app.register_blueprint(contacts_bp, url_prefix='/contactos')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(food_bp, url_prefix='/comida')
    app.register_blueprint(equipment_bp, url_prefix='/equipamiento')

    # Import models so Flask-Migrate detects them
    from app.models import (  # noqa: F401
        user, permission, profession, skill, talent, character, synonym,
        contact, contact_character_link, contact_note, food, equipment,
    )

    from app.services.currency_service import format_peniques
    app.jinja_env.filters['food_money'] = format_peniques
    app.jinja_env.filters['money'] = format_peniques

    _register_cli_commands(app)
    _register_error_handlers(app)
    _register_security_headers(app)
    _register_password_change_enforcement(app)

    return app


def _register_security_headers(app):
    @app.after_request
    def _set_security_headers(response):
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response


def _register_password_change_enforcement(app):
    """A user with must_change_password=True can't reach anything else -
    every request gets redirected to the change-password page until they
    pick a new one. Allowlist: the change-password page itself, logout, and
    static assets (otherwise the page's own CSS/JS would 404-loop)."""
    _ALLOWED_ENDPOINTS = {'auth.change_password', 'auth.logout', 'static'}

    @app.before_request
    def _enforce_password_change():
        from flask_login import current_user
        if (
            current_user.is_authenticated
            and current_user.must_change_password
            and request.endpoint not in _ALLOWED_ENDPOINTS
        ):
            return redirect(url_for('auth.change_password'))


def _wants_json() -> bool:
    """True when the request is an AJAX/fetch call expecting a JSON response
    (checked by content-type/accept header, not a hardcoded path list - any
    current or future fetch()-based endpoint gets a parseable JSON error
    instead of an HTML redirect that breaks `await resp.json()` client-side)."""
    if request.is_json:
        return True
    accept = request.headers.get('Accept', '')
    return 'application/json' in accept and 'text/html' not in accept


def _register_error_handlers(app):
    from werkzeug.exceptions import RequestEntityTooLarge
    from flask_wtf.csrf import CSRFError
    logger = logging.getLogger(__name__)

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        logger.warning(
            'CSRFError on %s %s: %s', request.method, request.path, e.description,
        )
        message = ('Tu sesión ha caducado o la petición no es válida '
                   '(token de seguridad expirado). Recarga la página e inténtalo de nuevo.')

        # AJAX endpoints (e.g. the PDF uploader, the character generator's roll
        # endpoint) expect JSON, not an HTML error page - returning HTML here
        # breaks their fetch/XHR response parsing and surfaces as a confusing
        # generic "HTTP 400" / silently-hung request client-side.
        if (request.path == '/admin/pdf' and request.method == 'POST') or _wants_json():
            return jsonify({'error': message}), 400

        flash(message, 'warning')
        return redirect(request.referrer or url_for('main.index'))

    @app.errorhandler(RequestEntityTooLarge)
    def handle_file_too_large(e):
        max_mb = app.config.get('MAX_CONTENT_LENGTH', 104857600) // (1024 * 1024)
        content_length = request.content_length
        size_mb = f'{content_length / (1024 * 1024):.1f}' if content_length else '?'
        message = f'El archivo ({size_mb} MB) supera el tamaño máximo permitido ({max_mb} MB).'
        logger.warning(
            'RequestEntityTooLarge on %s %s: content_length=%s max=%s',
            request.method, request.path, content_length, app.config.get('MAX_CONTENT_LENGTH'),
        )

        # AJAX endpoints (e.g. the PDF uploader) expect JSON, not an HTML redirect -
        # returning HTML here breaks their fetch/XHR response parsing and surfaces
        # as a confusing generic "network error" client-side.
        if (request.path == '/admin/pdf' and request.method == 'POST') or _wants_json():
            return jsonify({'error': message}), 413

        flash(message, 'danger')
        referrer = request.referrer
        if referrer and '/admin/pdf' in referrer:
            return redirect(url_for('admin.pdf_upload')), 302
        return redirect(url_for('main.index')), 302


def _register_cli_commands(app):
    @app.cli.command('init-db')
    def init_db_cmd():
        """Create all database tables and apply incremental column additions."""
        with app.app_context():
            db.create_all()
            from sqlalchemy import text, inspect as sa_inspect
            inspector = sa_inspect(db.engine)
            skill_cols = {c['name'] for c in inspector.get_columns('skills')}
            with db.engine.begin() as conn:
                if 'caracteristicas' not in skill_cols:
                    conn.execute(text('ALTER TABLE skills ADD COLUMN caracteristicas VARCHAR(300) NULL'))
                    click.echo('  Added skills.caracteristicas')
                if 'talentos_asociados' not in skill_cols:
                    conn.execute(text('ALTER TABLE skills ADD COLUMN talentos_asociados VARCHAR(500) NULL'))
                    click.echo('  Added skills.talentos_asociados')
            # profession_skills / profession_talents: add id PK + specialization
            for tbl in ('profession_skills', 'profession_talents'):
                tbl_cols = {c['name'] for c in inspector.get_columns(tbl)}
                with db.engine.begin() as conn:
                    if 'id' not in tbl_cols:
                        try:
                            # MySQL blocks DROP PRIMARY KEY when the PK index is the only
                            # index covering a FK column. Add an explicit index on profession_id
                            # first so the FK constraint remains satisfied after PK removal.
                            existing_indexes = {
                                row[2] for row in conn.execute(
                                    text(f'SHOW INDEX FROM {tbl}')
                                ).fetchall()
                            }
                            if 'idx_prof_id' not in existing_indexes:
                                conn.execute(text(
                                    f'ALTER TABLE {tbl} '
                                    f'ADD INDEX idx_prof_id (profession_id)'
                                ))
                            conn.execute(text(f'ALTER TABLE {tbl} DROP PRIMARY KEY'))
                            conn.execute(text(
                                f'ALTER TABLE {tbl} '
                                f'ADD COLUMN id INT NOT NULL AUTO_INCREMENT PRIMARY KEY FIRST'
                            ))
                            click.echo(f'  Migrated {tbl}: composite PK → id PK')
                        except Exception as e:
                            click.echo(f'  Warning ({tbl} PK migration): {e}')
                    if 'specialization' not in tbl_cols:
                        try:
                            conn.execute(text(
                                f'ALTER TABLE {tbl} ADD COLUMN specialization VARCHAR(150) NULL'
                            ))
                            click.echo(f'  Added {tbl}.specialization')
                        except Exception as e:
                            click.echo(f'  Warning ({tbl} specialization): {e}')

            # Incremental column: users.template_id (FK to permission_templates)
            user_cols = {c['name'] for c in inspector.get_columns('users')}
            with db.engine.begin() as conn:
                if 'template_id' not in user_cols:
                    conn.execute(text(
                        'ALTER TABLE users ADD COLUMN template_id INT NULL '
                        'REFERENCES permission_templates(id) ON DELETE SET NULL'
                    ))
                    click.echo('  Added users.template_id')
                if 'must_change_password' not in user_cols:
                    conn.execute(text(
                        'ALTER TABLE users ADD COLUMN must_change_password '
                        'BOOLEAN NOT NULL DEFAULT FALSE'
                    ))
                    click.echo('  Added users.must_change_password')
                if 'created_by_id' not in user_cols:
                    conn.execute(text(
                        'ALTER TABLE users ADD COLUMN created_by_id INT NULL '
                        'REFERENCES users(id) ON DELETE SET NULL'
                    ))
                    click.echo('  Added users.created_by_id')
                if 'puede_anadir_equipo_sin_coste' not in user_cols:
                    conn.execute(text(
                        'ALTER TABLE users ADD COLUMN puede_anadir_equipo_sin_coste '
                        'BOOLEAN NOT NULL DEFAULT FALSE'
                    ))
                    click.echo('  Added users.puede_anadir_equipo_sin_coste')

            # Incremental columns: characters (character creation wizard)
            char_cols = {c['name'] for c in inspector.get_columns('characters')}
            char_new_columns = [
                ('ws', 'INT NULL'), ('bs', 'INT NULL'), ('s_char', 'INT NULL'), ('t_char', 'INT NULL'),
                ('ag', 'INT NULL'), ('int_char', 'INT NULL'), ('wp', 'INT NULL'), ('fel', 'INT NULL'),
                ('attacks', 'INT NULL'), ('wounds', 'INT NULL'),
                ('strength_bonus', 'INT NULL'), ('toughness_bonus', 'INT NULL'),
                ('movement', 'INT NULL'), ('magic', 'INT NULL'),
                ('insanity_points', 'INT NULL'), ('fate_points', 'INT NULL'),
                ('signo_astral', 'VARCHAR(100) NULL'), ('rasgo_personalidad_signo', 'VARCHAR(150) NULL'),
                ('altura_cm', 'INT NULL'), ('peso_kg', 'INT NULL'),
                ('edad', 'INT NULL'), ('edad_grado', 'INT NULL'),
                ('color_pelo', 'VARCHAR(50) NULL'), ('color_ojos', 'VARCHAR(50) NULL'),
                ('mano_dominante', 'VARCHAR(20) NULL'),
                ('procedencia', 'VARCHAR(150) NULL'), ('situacion_familiar', 'VARCHAR(255) NULL'),
                ('nivel_social', 'INT NULL DEFAULT 1'), ('dinero_coronas', 'INT NULL DEFAULT 0'),
                ('dinero_peniques_extra', 'INT NOT NULL DEFAULT 0'),
                ('history_points_total', 'INT NOT NULL DEFAULT 0'),
                ('history_points_spent', 'INT NOT NULL DEFAULT 0'),
            ]
            with db.engine.begin() as conn:
                for col_name, col_def in char_new_columns:
                    if col_name not in char_cols:
                        conn.execute(text(f'ALTER TABLE characters ADD COLUMN {col_name} {col_def}'))
                        click.echo(f'  Added characters.{col_name}')

            # Incremental column: specialization on character_skills / character_talents
            for tbl in ('character_skills', 'character_talents'):
                tbl_cols = {c['name'] for c in inspector.get_columns(tbl)}
                with db.engine.begin() as conn:
                    if 'specialization' not in tbl_cols:
                        conn.execute(text(f'ALTER TABLE {tbl} ADD COLUMN specialization VARCHAR(150) NULL'))
                        click.echo(f'  Added {tbl}.specialization')

            # Incremental column: characters.es_untersuchung
            char_cols = {c['name'] for c in inspector.get_columns('characters')}
            with db.engine.begin() as conn:
                if 'es_untersuchung' not in char_cols:
                    conn.execute(text(
                        'ALTER TABLE characters ADD COLUMN es_untersuchung '
                        'BOOLEAN NOT NULL DEFAULT FALSE'
                    ))
                    click.echo('  Added characters.es_untersuchung')

            # Incremental columns: character_professions salary (tabla de sueldos,
            # aplica también a la carrera del propio personaje, no solo a Contactos)
            cp_cols = {c['name'] for c in inspector.get_columns('character_professions')}
            with db.engine.begin() as conn:
                if 'tipo_sueldo' not in cp_cols:
                    conn.execute(text('ALTER TABLE character_professions ADD COLUMN tipo_sueldo VARCHAR(30) NULL'))
                    click.echo('  Added character_professions.tipo_sueldo')
                if 'estado_habilidad' not in cp_cols:
                    conn.execute(text('ALTER TABLE character_professions ADD COLUMN estado_habilidad VARCHAR(20) NULL'))
                    click.echo('  Added character_professions.estado_habilidad')

            # Contactos: rediseño de esquema (de EAV genérico a columnas fijas).
            # nombre/es_untersuchung son nuevas en `contacts`; se rellenan a partir
            # de los datos EAV antiguos si existían, y las tablas EAV/persona,
            # ya sin uso, se eliminan.
            contact_cols = {c['name'] for c in inspector.get_columns('contacts')}
            with db.engine.begin() as conn:
                if 'nombre' not in contact_cols:
                    conn.execute(text('ALTER TABLE contacts ADD COLUMN nombre VARCHAR(150) NULL'))
                    click.echo('  Added contacts.nombre')
                if 'es_untersuchung' not in contact_cols:
                    conn.execute(text(
                        'ALTER TABLE contacts ADD COLUMN es_untersuchung BOOLEAN NOT NULL DEFAULT FALSE'
                    ))
                    click.echo('  Added contacts.es_untersuchung')

            if inspector.has_table('field_definitions') and inspector.has_table('contact_values'):
                with db.engine.begin() as conn:
                    rows = conn.execute(text(
                        "SELECT cv.contact_id, fd.name, cv.value FROM contact_values cv "
                        "JOIN field_definitions fd ON fd.id = cv.field_id "
                        "WHERE fd.name IN ('nombre', 'apellidos')"
                    )).fetchall()
                    by_contact = {}
                    for contact_id, field_name, value in rows:
                        by_contact.setdefault(contact_id, {})[field_name] = value
                    for contact_id, parts in by_contact.items():
                        nombre = ' '.join(v for v in (parts.get('nombre'), parts.get('apellidos')) if v).strip()
                        if nombre:
                            conn.execute(
                                text('UPDATE contacts SET nombre = :nombre WHERE id = :id'),
                                {'nombre': nombre, 'id': contact_id},
                            )
                    if by_contact:
                        click.echo(f'  Backfilled contacts.nombre for {len(by_contact)} legacy row(s)')

            with db.engine.begin() as conn:
                conn.execute(text(
                    "UPDATE contacts SET nombre = CONCAT('Contacto #', id) WHERE nombre IS NULL OR nombre = ''"
                ))
                conn.execute(text('ALTER TABLE contacts MODIFY nombre VARCHAR(150) NOT NULL'))

            for legacy_tbl in ('contact_values', 'field_definitions', 'contact_persona_links', 'contact_personas'):
                if inspector.has_table(legacy_tbl):
                    with db.engine.begin() as conn:
                        conn.execute(text(f'DROP TABLE {legacy_tbl}'))
                        click.echo(f'  Dropped legacy table {legacy_tbl}')

            # contact_notes changed shape (author_id/is_global -> character_id) as part
            # of the same redesign; db.create_all() only creates missing tables, so an
            # existing old-shape table needs dropping before it can be recreated fresh.
            note_cols = {c['name'] for c in inspector.get_columns('contact_notes')}
            if 'character_id' not in note_cols:
                with db.engine.begin() as conn:
                    conn.execute(text('DROP TABLE contact_notes'))
                    click.echo('  Dropped legacy-shape contact_notes (recreating with character_id)')
                db.create_all()

            # drinks.sabor changed meaning (base category instead of descriptor+parens)
            # and gained sabor_variante. It's a closed catalog seeded only from JSON
            # (never user-edited), so a shape change just drops and reseeds it rather
            # than migrating rows in place.
            if inspector.has_table('drinks'):
                drink_cols = {c['name'] for c in inspector.get_columns('drinks')}
                if 'sabor_variante' not in drink_cols:
                    with db.engine.begin() as conn:
                        conn.execute(text('DROP TABLE drinks'))
                        click.echo('  Dropped legacy-shape drinks table (recreating with sabor_variante)')
                    db.create_all()

            # Incremental columns: recipes (Fase 2 - propuestas de usuarios en revisión)
            if inspector.has_table('recipes'):
                recipe_cols = {c['name'] for c in inspector.get_columns('recipes')}
                recipe_new_columns = [
                    ('complejidad', 'INT NULL'),
                    ('status', "VARCHAR(20) NOT NULL DEFAULT 'aprobada'"),
                    ('image_path', 'VARCHAR(300) NULL'),
                    ('created_by_id', 'INT NULL REFERENCES users(id) ON DELETE SET NULL'),
                    ('requested_at', 'DATETIME NULL'),
                    ('approved_by_id', 'INT NULL REFERENCES users(id) ON DELETE SET NULL'),
                    ('approved_at', 'DATETIME NULL'),
                    ('rejection_reason', 'TEXT NULL'),
                ]
                with db.engine.begin() as conn:
                    for col_name, col_def in recipe_new_columns:
                        if col_name not in recipe_cols:
                            conn.execute(text(f'ALTER TABLE recipes ADD COLUMN {col_name} {col_def}'))
                            click.echo(f'  Added recipes.{col_name}')

            # Incremental columns: equipment_items.precio_peniques (normalized
            # numeric price for the character purchase flow) and
            # precio_escala_clase_social (Noble ropa: "36c (base *
            # (Clase-2))" - price scales with the BUYING character's
            # nivel_social, computed at purchase time). Both backfills use
            # raw SQL (not the EquipmentItem ORM query) since an ORM SELECT
            # pulls every mapped column - including ones this same migration
            # hasn't added yet on a fresh database - and would 1054 before
            # the later block runs.
            if inspector.has_table('equipment_items'):
                equip_cols = {c['name'] for c in inspector.get_columns('equipment_items')}
                from app.models.equipment import parse_price_text, is_clase_social_scaled, parse_price_units

                if 'precio_peniques' not in equip_cols:
                    with db.engine.begin() as conn:
                        conn.execute(text('ALTER TABLE equipment_items ADD COLUMN precio_peniques INT NULL'))
                    click.echo('  Added equipment_items.precio_peniques')
                    with db.engine.begin() as conn:
                        rows = conn.execute(text(
                            'SELECT id, price_text FROM equipment_items WHERE price_text IS NOT NULL'
                        )).fetchall()
                        backfilled = 0
                        for row_id, price_text in rows:
                            peniques = parse_price_text(price_text)
                            if peniques is not None:
                                conn.execute(
                                    text('UPDATE equipment_items SET precio_peniques = :p WHERE id = :id'),
                                    {'p': peniques, 'id': row_id},
                                )
                                backfilled += 1
                    click.echo(f'  Backfilled precio_peniques for {backfilled} equipment item(s)')

                if 'precio_escala_clase_social' not in equip_cols:
                    with db.engine.begin() as conn:
                        conn.execute(text(
                            'ALTER TABLE equipment_items ADD COLUMN '
                            'precio_escala_clase_social BOOLEAN NOT NULL DEFAULT FALSE'
                        ))
                    click.echo('  Added equipment_items.precio_escala_clase_social')
                    with db.engine.begin() as conn:
                        rows = conn.execute(text(
                            'SELECT id, price_text, precio_peniques FROM equipment_items WHERE price_text IS NOT NULL'
                        )).fetchall()
                        flagged = 0
                        for row_id, price_text, precio_peniques in rows:
                            if is_clase_social_scaled(price_text):
                                flagged += 1
                                # Fixes rows migrated by an earlier version of
                                # this parser (before it understood the
                                # Clase-2 suffix) left NULL on a prior deploy.
                                new_peniques = precio_peniques if precio_peniques is not None else parse_price_text(price_text)
                                conn.execute(
                                    text('UPDATE equipment_items SET precio_escala_clase_social = TRUE, '
                                         'precio_peniques = :p WHERE id = :id'),
                                    {'p': new_peniques, 'id': row_id},
                                )
                    click.echo(f'  Flagged {flagged} equipment item(s) as Clase-social-scaled')

                if 'unidades_por_precio' not in equip_cols:
                    with db.engine.begin() as conn:
                        conn.execute(text(
                            'ALTER TABLE equipment_items ADD COLUMN '
                            'unidades_por_precio INT NOT NULL DEFAULT 1'
                        ))
                    click.echo('  Added equipment_items.unidades_por_precio')
                    with db.engine.begin() as conn:
                        # Ammo prices like "1C (5)" never matched the old
                        # parser (no support for a trailing batch size), so
                        # every ammo row was left with precio_peniques NULL -
                        # only rows still unparsed are touched here.
                        rows = conn.execute(text(
                            'SELECT id, price_text FROM equipment_items '
                            'WHERE price_text IS NOT NULL AND precio_peniques IS NULL'
                        )).fetchall()
                        backfilled = 0
                        for row_id, price_text in rows:
                            base_text, units = parse_price_units(price_text)
                            peniques = parse_price_text(base_text)
                            if peniques is not None:
                                conn.execute(
                                    text('UPDATE equipment_items SET precio_peniques = :p, '
                                         'unidades_por_precio = :u, precio_escala_clase_social = :c '
                                         'WHERE id = :id'),
                                    {'p': peniques, 'u': units, 'c': is_clase_social_scaled(base_text), 'id': row_id},
                                )
                                backfilled += 1
                    click.echo(f'  Backfilled batch pricing for {backfilled} equipment item(s)')

                if 'peso' not in equip_cols:
                    with db.engine.begin() as conn:
                        conn.execute(text('ALTER TABLE equipment_items ADD COLUMN peso FLOAT NULL'))
                    click.echo('  Added equipment_items.peso')

            # Incremental column: character_inventory_items.condition
            # (placeholder JSON for the future wear/damage/repair phase - unused today)
            if inspector.has_table('character_inventory_items'):
                inv_cols = {c['name'] for c in inspector.get_columns('character_inventory_items')}
                if 'condition' not in inv_cols:
                    with db.engine.begin() as conn:
                        conn.execute(text('ALTER TABLE character_inventory_items ADD COLUMN `condition` JSON NULL'))
                    click.echo('  Added character_inventory_items.condition')

            click.echo('Database tables created/verified.')

            # Seed permissions and default templates (idempotent)
            from app.models.permission import seed_permissions_and_templates
            seed_permissions_and_templates()
            click.echo('  Permissions and templates seeded.')

            # Seed default synonyms (idempotent — adds any new default entries
            # introduced in later releases without touching admin-edited rows)
            from app.models.synonym import Synonym, DEFAULT_SYNONYMS
            existing_sources = {s.source for s in Synonym.query.all()}
            added = 0
            for source, target, is_prefix, notes in DEFAULT_SYNONYMS:
                if source not in existing_sources:
                    db.session.add(Synonym(
                        source=source, target=target,
                        is_prefix=is_prefix, notes=notes or None,
                    ))
                    added += 1
            if added:
                db.session.commit()
                click.echo(f'  Seeded {added} new default synonym(s).')

            # Seed the Comida y bebida catalog (idempotent)
            from app.services.food_seed_service import seed_food_catalog
            food_added = seed_food_catalog()
            if food_added:
                click.echo(f'  Seeded {food_added} new comida/bebida catalog row(s).')

    @app.cli.command('create-admin')
    def create_admin_cmd():
        """Create the default admin user from environment config."""
        with app.app_context():
            from app.utils import create_default_admin
            create_default_admin()
            click.echo('Admin creation complete.')

    @app.cli.command('normalize-catalog-casing')
    def normalize_catalog_casing_cmd():
        """One-off fix: the Habilidades/Talentos catalog was originally loaded
        with name_es in ALL CAPS. The PDF-import review page canonicalizes
        matched chips to the catalog's exact name_es, so ALL-CAPS catalog
        entries made matched chips look inconsistent next to the Title-Case
        text extracted from the book. Rewrites each known ALL-CAPS name_es to
        its correct accented Spanish Title Case. Matches by exact current
        value, so it is safe to re-run (a no-op once already normalized)."""
        from app.models.skill import Skill
        from app.models.talent import Talent
        from app.data.catalog_casing import SKILL_CASING, TALENT_CASING

        with app.app_context():
            updated = 0
            for skill in Skill.query.all():
                new_name = SKILL_CASING.get(skill.name_es)
                if new_name and new_name != skill.name_es:
                    skill.name_es = new_name
                    updated += 1
            for talent in Talent.query.all():
                new_name = TALENT_CASING.get(talent.name_es)
                if new_name and new_name != talent.name_es:
                    talent.name_es = new_name
                    updated += 1
            if updated:
                db.session.commit()
            click.echo(f'Normalized casing for {updated} catalog entr{"y" if updated == 1 else "ies"}.')

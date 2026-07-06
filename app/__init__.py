import logging
import os
import click
from flask import Flask, flash, redirect, url_for, request, jsonify
from app.config import config_by_name
from app.extensions import db, login_manager, bcrypt, migrate, csrf


def create_app(config_name='default'):
    app = Flask(__name__)
    app.config.from_object(config_by_name[config_name])

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

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(main_bp)
    app.register_blueprint(professions_bp, url_prefix='/profesiones')
    app.register_blueprint(skills_talents_bp)
    app.register_blueprint(pathfinder_bp, url_prefix='/buscador')
    app.register_blueprint(characters_bp, url_prefix='/personajes')
    app.register_blueprint(contacts_bp, url_prefix='/contactos')
    app.register_blueprint(admin_bp, url_prefix='/admin')

    # Import models so Flask-Migrate detects them
    from app.models import (  # noqa: F401
        user, permission, profession, skill, talent, character, synonym,
        contact, contact_persona, contact_note,
    )

    _register_cli_commands(app)
    _register_error_handlers(app)
    _register_security_headers(app)

    return app


def _register_security_headers(app):
    @app.after_request
    def _set_security_headers(response):
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response


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
        return redirect('/'), 302


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

    @app.cli.command('create-admin')
    def create_admin_cmd():
        """Create the default admin user from environment config."""
        with app.app_context():
            from app.utils import create_default_admin
            create_default_admin()
            click.echo('Admin creation complete.')

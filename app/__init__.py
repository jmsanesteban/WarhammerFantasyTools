import os
import click
from flask import Flask
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
    from app.routes.admin import admin_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(main_bp)
    app.register_blueprint(professions_bp, url_prefix='/profesiones')
    app.register_blueprint(skills_talents_bp)
    app.register_blueprint(pathfinder_bp, url_prefix='/buscador')
    app.register_blueprint(characters_bp, url_prefix='/personajes')
    app.register_blueprint(admin_bp, url_prefix='/admin')

    # Import models so Flask-Migrate detects them
    from app.models import user, profession, skill, talent, character  # noqa: F401

    _register_cli_commands(app)

    return app


def _register_cli_commands(app):
    @app.cli.command('init-db')
    def init_db_cmd():
        """Create all database tables (idempotent, safe to re-run)."""
        with app.app_context():
            db.create_all()
            click.echo('Database tables created/verified.')

    @app.cli.command('create-admin')
    def create_admin_cmd():
        """Create the default admin user from environment config."""
        with app.app_context():
            from app.utils import create_default_admin
            create_default_admin()
            click.echo('Admin creation complete.')

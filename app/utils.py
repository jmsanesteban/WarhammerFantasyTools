import io
import json
import secrets
import string
from functools import wraps
from flask import abort, current_app, redirect, url_for, request, flash, send_file
from flask_login import current_user
from markupsafe import Markup


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


def require_permission(code: str):
    """Decorator: allow access only if the user has the given permission code.
    Admins bypass all permission checks. Unauthenticated users are redirected to login.
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login', next=request.url))
            if not current_user.has_perm(code):
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator


def generate_secure_password(length=16):
    """Generate a cryptographically secure random password."""
    alphabet = string.ascii_letters + string.digits + '!@#$%^&*'
    while True:
        password = ''.join(secrets.choice(alphabet) for _ in range(length))
        has_upper = any(c.isupper() for c in password)
        has_lower = any(c.islower() for c in password)
        has_digit = any(c.isdigit() for c in password)
        has_special = any(c in '!@#$%^&*' for c in password)
        if has_upper and has_lower and has_digit and has_special:
            return password


def allowed_file(filename):
    return (
        '.' in filename
        and filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']
    )


def json_download_response(data, filename):
    """Send a Python object as a downloadable .json file - used by every
    backup export route in app/services/backup_service.py."""
    buffer = io.BytesIO(json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'))
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/json')


def flash_import_summary(summary):
    """Flash a standard 'created/updated/skipped (+ warnings)' message for a
    backup_service import_* summary dict. Shared by every backup import route."""
    flash(
        f"Importación completada: {summary['created']} creadas, "
        f"{summary['updated']} actualizadas, {summary['skipped']} omitidas.",
        'success',
    )
    warnings = summary.get('warnings') or []
    if warnings:
        shown = warnings[:20]
        more = '' if len(warnings) <= 20 else f' (+{len(warnings) - 20} más)'
        flash(Markup('<strong>Avisos:</strong> {}{}').format('; '.join(shown), more), 'warning')
    passwords = summary.get('generated_passwords') or {}
    if passwords:
        detail = '; '.join(f'{u}: {p}' for u, p in passwords.items())
        flash(Markup('<strong>Contraseñas temporales asignadas:</strong> {}').format(detail), 'warning')


def create_default_admin():
    from app.extensions import db, bcrypt
    from app.models.user import User

    username = current_app.config['ADMIN_USERNAME']
    email = current_app.config['ADMIN_EMAIL']
    password = current_app.config['ADMIN_PASSWORD']

    if not User.query.filter_by(role='admin').first():
        admin = User(
            username=username,
            email=email,
            role='admin',
        )
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        current_app.logger.info(f"Default admin created: {username}")
    else:
        current_app.logger.info("Admin user already exists, skipping seed.")

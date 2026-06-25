from functools import wraps
from flask import abort, current_app
from flask_login import current_user


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


def allowed_file(filename):
    return (
        '.' in filename
        and filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']
    )


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

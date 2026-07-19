from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db
from app.models.user import User
from app.models.character import Character
from app.models.permission import PermissionTemplate

auth_bp = Blueprint('auth', __name__, template_folder='../templates')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = bool(request.form.get('remember'))

        user = User.find_by_username(username)
        if user and user.check_password(password) and user.active:
            login_user(user, remember=remember)
            next_page = request.args.get('next')
            flash(f'¡Bienvenido, {user.username}!', 'success')

            # Personaje activo (2026-07-17): si no hay uno marcado, con un
            # único personaje se fija sin preguntar; con varios y ninguno
            # marcado, se manda una vez al listado de Personajes a elegir -
            # pero solo cuando el login no venía de un rebote @login_required
            # con destino explícito (next_page), que siempre tiene prioridad.
            if not next_page and user.active_character_id is None:
                own_chars = user.characters.all()
                if len(own_chars) == 1:
                    user.active_character_id = own_chars[0].id
                    db.session.commit()
                elif len(own_chars) > 1:
                    flash('Elige con qué personaje vas a jugar.', 'info')
                    return redirect(url_for('characters.list_characters'))

            return redirect(next_page or url_for('main.index'))

        flash('Usuario o contraseña incorrectos.', 'danger')

    return render_template('auth/login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        error = None
        if not username or len(username) < 3:
            error = 'El nombre de usuario debe tener al menos 3 caracteres.'
        elif not email or '@' not in email:
            error = 'Introduce un email válido.'
        elif len(password) < 6:
            error = 'La contraseña debe tener al menos 6 caracteres.'
        elif password != confirm:
            error = 'Las contraseñas no coinciden.'
        elif User.find_by_username(username):
            error = 'Ese nombre de usuario ya está en uso.'
        elif User.query.filter_by(email=email).first():
            error = 'Ese email ya está registrado.'

        if error:
            flash(error, 'danger')
        else:
            user = User(username=username, email=email, role='user')
            user.set_password(password)
            user.template = PermissionTemplate.query.filter_by(name='Jugador').first()
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash('¡Cuenta creada correctamente!', 'success')
            return redirect(url_for('main.index'))

    return render_template('auth/register.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Has cerrado sesión.', 'info')
    return redirect(url_for('main.index'))


@auth_bp.route('/perfil')
@login_required
def profile():
    own_chars = current_user.characters.order_by(Character.name).all()
    return render_template('auth/profile.html', characters=own_chars)


@auth_bp.route('/cambiar-clave', methods=['GET', 'POST'])
@login_required
def change_password():
    forced = current_user.must_change_password

    if request.method == 'POST':
        current = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')

        error = None
        if not current_user.check_password(current):
            error = 'La contraseña actual no es correcta.'
        elif len(new_password) < 8:
            error = 'La nueva contraseña debe tener al menos 8 caracteres.'
        elif new_password != confirm:
            error = 'Las contraseñas nuevas no coinciden.'

        if error:
            flash(error, 'danger')
        else:
            current_user.set_password(new_password)
            current_user.must_change_password = False
            db.session.commit()
            flash('Contraseña actualizada correctamente.', 'success')
            return redirect(url_for('main.index'))

    return render_template('auth/change_password.html', forced=forced)

from datetime import datetime
from flask_login import UserMixin
from app.extensions import db, bcrypt, login_manager


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80),  unique=True, nullable=False, index=True)
    email         = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role          = db.Column(db.String(20),  nullable=False, default='user')  # 'admin' | 'user'
    active        = db.Column(db.Boolean,     default=True, nullable=False)
    created_at    = db.Column(db.DateTime,    default=datetime.utcnow)
    template_id   = db.Column(db.Integer, db.ForeignKey('permission_templates.id'), nullable=True)
    must_change_password = db.Column(db.Boolean, default=False, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    # Admin-controlled, per-user: lets this player add equipment straight to
    # a character's inventory at 0 cost (see CharacterPurchase) - meant for
    # regularizing a character's already-owned gear when migrating to the
    # shop, not for everyday free purchases.
    puede_anadir_equipo_sin_coste = db.Column(db.Boolean, default=False, nullable=False)
    # Personaje "activo" del usuario (2026-07-17): sustituye al viejo patrón
    # de elegir personaje por query-string (?personaje_id=) en cada página de
    # Contactos - un único valor persistido, editable desde el perfil o el
    # listado de Personajes. ON DELETE SET NULL: si se borra el personaje,
    # simplemente deja de haber uno activo, no falla el borrado.
    active_character_id = db.Column(db.Integer, db.ForeignKey('characters.id', ondelete='SET NULL'),
                                     nullable=True)

    # Relationships
    characters = db.relationship('Character', backref='owner', lazy='dynamic',
                                  foreign_keys='Character.user_id')
    active_character = db.relationship('Character', foreign_keys=[active_character_id])
    template   = db.relationship('PermissionTemplate', foreign_keys=[template_id], lazy='select')
    direct_permissions = db.relationship(
        'Permission',
        secondary='user_permissions',
        lazy='select',
    )
    created_by = db.relationship('User', remote_side=[id], foreign_keys=[created_by_id],
                                  backref='created_users')

    # ── Properties ───────────────────────────────────────────────────────────

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_active(self):
        return self.active

    # ── Permission helpers ────────────────────────────────────────────────────

    def has_perm(self, code: str) -> bool:
        """True if the user holds the given permission. Admins bypass all checks."""
        if not self.is_authenticated:
            return False
        if self.is_admin:
            return True
        if any(p.code == code for p in self.direct_permissions):
            return True
        if self.template and any(p.code == code for p in self.template.permissions):
            return True
        return False

    def effective_perm_codes(self) -> set:
        """Return the set of all effective permission codes for this user."""
        if self.is_admin:
            return {'*'}
        codes = {p.code for p in self.direct_permissions}
        if self.template:
            codes |= {p.code for p in self.template.permissions}
        return codes

    # ── Lookup helpers ───────────────────────────────────────────────────────

    @staticmethod
    def find_by_username(username: str):
        """Case-insensitive username lookup - usernames are stored with
        whatever casing the user typed (for display), but "Juanma", "juanma"
        and "JUANMA" must all resolve to the same account for login,
        registration, and admin user-creation duplicate checks."""
        if not username:
            return None
        return User.query.filter(db.func.lower(User.username) == username.lower()).first()

    # ── Auth helpers ──────────────────────────────────────────────────────────

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

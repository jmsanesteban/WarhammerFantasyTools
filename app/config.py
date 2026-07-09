import os


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-prod')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads'))
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 104857600))  # 100 MB
    ALLOWED_EXTENSIONS = {'pdf'}
    WTF_CSRF_ENABLED = True

    # Admin seed credentials
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@example.com')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'changeme123')

    # Purely cosmetic: set to 'prepro' on the preproduction VM's .env so the
    # navbar visually differs from production (avoids confusing the two when
    # switching tabs). Empty/anything else = normal (production-looking) navbar.
    APP_ENVIRONMENT = os.environ.get('APP_ENVIRONMENT', '')


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'mysql+pymysql://wftuser:wftpassword@localhost:3306/wft'
    )


class ProductionConfig(Config):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    WTF_CSRF_SSL_STRICT = False


class TestingConfig(Config):
    """Used by the test suite (see tests/conftest.py). SQLite in-memory -
    no MySQL server needed to run tests. CSRF is off by default so tests can
    POST forms without wiring a token everywhere; tests that specifically
    exercise CSRF behavior turn it back on via app.config override."""
    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'testing-secret-key'
    ADMIN_USERNAME = 'admin'
    ADMIN_EMAIL = 'admin@example.com'
    ADMIN_PASSWORD = 'testpassword123'


config_by_name = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig,
}

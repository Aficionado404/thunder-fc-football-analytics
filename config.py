"""
config.py — Thunder FC
Environment-based configuration. Never hardcode secrets here.

Usage:
  export FLASK_ENV=production
  export SECRET_KEY=your-secret-here
  python app.py
"""

import os
import secrets as _secrets

def _load_or_create_secret():
    """Load secret key from env, then from file, else generate + persist."""
    if os.environ.get('SECRET_KEY'):
        return os.environ['SECRET_KEY']
    key_file = os.path.join('data', '.secret_key')
    os.makedirs('data', exist_ok=True)
    if os.path.exists(key_file):
        with open(key_file) as f:
            key = f.read().strip()
            if key:
                return key
    key = _secrets.token_hex(32)
    with open(key_file, 'w') as f:
        f.write(key)
    return key


class BaseConfig:
    TEAM_NAME        = os.environ.get('TEAM_NAME', 'Thunder FC')
    DATABASE         = os.environ.get('DATABASE',  'data/soccer.db')
    UPLOAD_FOLDER    = 'uploads'
    MODELS_FOLDER    = 'models'
    SECRET_KEY       = _load_or_create_secret()
    WTF_CSRF_ENABLED = True
    # Login rate limiting
    LOGIN_MAX_ATTEMPTS   = 5
    LOGIN_LOCKOUT_MINUTES = 10
    # Pagination
    MATCHES_PER_PAGE = 20


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    TESTING = False


class ProductionConfig(BaseConfig):
    DEBUG   = False
    TESTING = False
    # In production force HTTPS cookies
    SESSION_COOKIE_SECURE   = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE   = True


class TestingConfig(BaseConfig):
    TESTING          = True
    DEBUG            = True
    WTF_CSRF_ENABLED = False
    DATABASE         = 'data/test_soccer.db'


_config_map = {
    'development': DevelopmentConfig,
    'production':  ProductionConfig,
    'testing':     TestingConfig,
}


def get_config():
    env = os.environ.get('FLASK_ENV', 'development')
    return _config_map.get(env, DevelopmentConfig)
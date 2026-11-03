import os
from io import StringIO
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from django.core.management.utils import get_random_secret_key
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / '.env'
if ENV_FILE.exists():
    env_content = ENV_FILE.read_bytes()
    env_encoding = 'utf-16' if env_content.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
    supported_env_keys = {
        'DJANGO_DEBUG', 'DEBUG', 'DJANGO_SECRET_KEY', 'SECRET_KEY',
        'DJANGO_ALLOWED_HOSTS', 'ALLOWED_HOSTS', 'DJANGO_CSRF_TRUSTED_ORIGINS',
        'EMAIL_HOST', 'EMAIL_PORT', 'EMAIL_USE_TLS', 'EMAIL_HOST_USER',
        'EMAIL_HOST_PASSWORD', 'DEFAULT_FROM_EMAIL', 'EMAIL_BACKUP_TO',
    }
    valid_env_lines = [
        line
        for line in env_content.decode(env_encoding).splitlines()
        if '=' in line and line.partition('=')[0].strip() in supported_env_keys
    ]
    load_dotenv(stream=StringIO('\n'.join(valid_env_lines)))

DEBUG = os.environ.get('DJANGO_DEBUG', os.environ.get('DEBUG', 'true')).strip().lower() in {
    '1', 'true', 'yes', 'on',
}
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY') or os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('Set DJANGO_SECRET_KEY when DEBUG is disabled.')
    SECRET_KEY = get_random_secret_key()

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get(
        'DJANGO_ALLOWED_HOSTS',
        os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver'),
    ).split(',')
    if host.strip()
]


DATA_UPLOAD_MAX_NUMBER_FIELDS = 10000 
DATA_UPLOAD_MAX_MEMORY_SIZE = 2621440

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'crispy_forms',
    'crispy_bootstrap5',
    'apps.accounts',
    'apps.dashboard',
    'apps.customers',
    'apps.products',
    'apps.deliveries',
    'apps.payments',
    'apps.cylinders',
    'apps.notifications', 
    'apps.fbr',  
    'apps.suppliers',
    'apps.earnings',
]

# CSRF Settings
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = False
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        'DJANGO_CSRF_TRUSTED_ORIGINS',
        'http://127.0.0.1:8000,http://localhost:8000',
    ).split(',')
    if origin.strip()
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Karachi'  # Pakistan Standard Time
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/auth/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/auth/login/'

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'true').strip().lower() in {
    '1', 'true', 'yes', 'on',
}
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER)
EMAIL_BACKUP_TO = os.environ.get('EMAIL_BACKUP_TO', 'gbms-backups@example.invalid')

# ============================================================
# SESSION SETTINGS - Keep users signed in until they explicitly log out
# ============================================================

SESSION_COOKIE_AGE = 315360000  # 10 years (seconds)
SESSION_SAVE_EVERY_REQUEST = True  # Refresh the session on every request
SESSION_EXPIRE_AT_BROWSER_CLOSE = False  # Keep the session after closing the browser

# Optional security settings
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_NAME = 'gbms_session'
SESSION_COOKIE_SECURE = not DEBUG

CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap5'
CRISPY_TEMPLATE_PACK = 'bootstrap5'

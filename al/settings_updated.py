"""
GHAT-GUARDIAN Django Settings
Full-stack IoT vehicle safety system for mountain roads
Patent-level configuration — PostGIS + Redis + Django Channels
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ─── SECURITY ────────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get('SECRET_KEY', 'change-this-in-production')
DEBUG = os.environ.get('DEBUG', 'True') == 'True'
ALLOWED_HOSTS = ['*']  # Replit needs this — restrict in production

# ─── APPS ────────────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.gis',          # PostGIS spatial support
    'rest_framework',              # Django REST Framework
    'channels',                    # WebSocket support
    'corsheaders',                 # Allow frontend to connect
    'vehicles',                    # Our main app
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',  # Must be first
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'ghat_guardian.urls'
WSGI_APPLICATION = 'ghat_guardian.wsgi.application'
ASGI_APPLICATION = 'ghat_guardian.asgi.application'  # For WebSockets

# ─── TEMPLATES ───────────────────────────────────────────────────────────────
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

# ─── DATABASE — PostgreSQL + PostGIS ─────────────────────────────────────────
# On Replit: set DATABASE_URL in Secrets tab
# Format: postgis://user:password@host:port/dbname
DATABASES = {
    'default': {
        'ENGINE': 'django.contrib.gis.db.backends.postgis',
        'NAME': os.environ.get('DB_NAME', 'ghat_guardian'),
        'USER': os.environ.get('DB_USER', 'postgres'),
        'PASSWORD': os.environ.get('DB_PASSWORD', ''),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
    }
}

# ─── REDIS + DJANGO CHANNELS ─────────────────────────────────────────────────
# On Replit: set REDIS_URL in Secrets tab
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379')

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [REDIS_URL],
            'capacity': 1500,       # Max messages in buffer
            'expiry': 3,            # Messages expire after 3s (V2V TTL)
        },
    },
}

# ─── CORS — Allow Leaflet.js dashboard and React Native to connect ────────────
CORS_ALLOW_ALL_ORIGINS = True  # Restrict to your domain in production
CORS_ALLOW_CREDENTIALS = True

# ─── REST FRAMEWORK ──────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '120/min',   # Max 2 ESP32 updates/sec per vehicle
    }
}

# ─── STATIC FILES ────────────────────────────────────────────────────────────
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# ─── MISC ────────────────────────────────────────────────────────────────────
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_TZ = True

# ─── EMERGENCY ALERT SETTINGS ────────────────────────────────────────────────
# Set all of these in Replit Secrets tab — never hardcode credentials

# MSG91 (India SMS — recommended)
MSG91_AUTH_KEY    = os.environ.get('MSG91_AUTH_KEY',    '')
MSG91_SENDER_ID   = os.environ.get('MSG91_SENDER_ID',   'GHATGD')
MSG91_TEMPLATE_ID = os.environ.get('MSG91_TEMPLATE_ID', '')

# Twilio (fallback SMS)
TWILIO_ACCOUNT_SID  = os.environ.get('TWILIO_ACCOUNT_SID',  '')
TWILIO_AUTH_TOKEN   = os.environ.get('TWILIO_AUTH_TOKEN',   '')
TWILIO_FROM_NUMBER  = os.environ.get('TWILIO_FROM_NUMBER',  '')

# WhatsApp via Meta Cloud API
WHATSAPP_TOKEN    = os.environ.get('WHATSAPP_TOKEN',    '')
WHATSAPP_PHONE_ID = os.environ.get('WHATSAPP_PHONE_ID', '')

# Fallback numbers — always alerted regardless of nearest unit
# Format: comma-separated e.g. "+919876543210,+918765432109"
ALERT_PHONE_NUMBERS = os.environ.get('ALERT_PHONE_NUMBERS', '')

# ─── CELERY ──────────────────────────────────────────────────────────────────
CELERY_BROKER_URL        = os.environ.get('REDIS_URL', 'redis://localhost:6379')
CELERY_RESULT_BACKEND    = os.environ.get('REDIS_URL', 'redis://localhost:6379')
CELERY_TASK_SERIALIZER   = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT    = ['json']
CELERY_TIMEZONE          = 'Asia/Kolkata'

import os
from pathlib import Path
from datetime import timedelta

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

DEV_SECRET_KEY = 'careflow-dev-only-secret-key-please-change-before-production-2026-01'
SECRET_KEY = os.getenv('SECRET_KEY', DEV_SECRET_KEY)
DEBUG = os.getenv('DEBUG', 'true').lower() == 'true'
ALLOWED_HOSTS = [h for h in os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver').split(',') if h]
CSRF_TRUSTED_ORIGINS = [o for o in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if o]

if not DEBUG and SECRET_KEY == DEV_SECRET_KEY:
    raise ImproperlyConfigured('Set SECRET_KEY in environment for production deployments.')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework.authtoken',
    'drf_spectacular',
    'corsheaders',
    'api',
]

MIDDLEWARE = [
    # First = outermost layer, so its post-`get_response` code sees the
    # final response status after every other middleware/view/exception
    # handler has run. See `api/middleware.py` docstring.
    'api.middleware.MetricsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'careflow.urls'

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

WSGI_APPLICATION = 'careflow.wsgi.application'
ASGI_APPLICATION = 'careflow.asgi.application'

# Database
#
# `DATABASE_SSL_REQUIRE` is deliberately its own setting rather than derived
# from `DEBUG` (as `ssl_require=not DEBUG` previously did). Whether a
# Postgres connection needs to be encrypted is a property of *where the
# database actually lives* (a managed Render Postgres reachable over the
# public internet needs SSL; a Postgres container on the same Docker
# network or in a CI service container does not support or need it), which
# is orthogonal to `DEBUG`. The previous coupling meant every non-DEBUG
# Postgres target — including docker-compose's own local `db` service and
# CI's Postgres service container, both of which run with `DEBUG=false` —
# would try `sslmode=require` against a database that doesn't speak SSL and
# fail to connect outright. `render.yaml` sets `DATABASE_SSL_REQUIRE=true`
# explicitly for the one target that actually needs it.
DATABASE_URL = os.getenv('DATABASE_URL')
DATABASE_SSL_REQUIRE = os.getenv('DATABASE_SSL_REQUIRE', 'false').lower() == 'true'
if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.parse(DATABASE_URL, conn_max_age=600, ssl_require=DATABASE_SSL_REQUIRE)
    }
    DATABASES['default']['CONN_HEALTH_CHECKS'] = True
else:
    if DEBUG:
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': BASE_DIR / 'db.sqlite3',
            }
        }
    else:
        raise ImproperlyConfigured('DATABASE_URL must be set when DEBUG=false')

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = os.getenv('TIMEZONE', 'UTC')
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Redis URL, shared by the cache backend (careflow/settings.py CACHES) and
# the Celery broker/result backend below. Unset in local dev/CI, which is
# what makes both fall back to single-process-safe defaults (LocMemCache,
# Celery eager mode) with zero extra infrastructure required to run this
# project locally.
REDIS_URL = os.getenv('REDIS_URL', '')

# DRF
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    # `Resilient*` wrappers (api/throttling.py) rather than DRF's stock
    # `AnonRateThrottle`/`UserRateThrottle` directly: the stock classes read
    # and write the rate-limit counter straight through `django.core.cache`
    # with no exception handling, so a Redis outage (the `CACHES` backend
    # whenever `REDIS_URL` is set — see below) previously propagated an
    # unhandled `ConnectionError` out of every single throttled request,
    # taking down the entire API surface rather than just degrading rate
    # limiting. See `api/throttling.py` module docstring for the full
    # rationale and confirmed reproduction.
    'DEFAULT_THROTTLE_CLASSES': (
        'api.throttling.ResilientAnonRateThrottle',
        'api.throttling.ResilientUserRateThrottle',
    ),
    'DEFAULT_THROTTLE_RATES': {
        'anon': os.getenv('DRF_THROTTLE_ANON', '60/minute'),
        'user': os.getenv('DRF_THROTTLE_USER', '300/minute'),
    },
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=30),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'SIGNING_KEY': os.getenv('JWT_SECRET', SECRET_KEY),
}

# Celery
#
# Why `CELERY_TASK_ALWAYS_EAGER` defaults to True when `REDIS_URL` is unset:
# local dev and CI never run a Celery broker or worker process, and
# shouldn't need to just to exercise domain-event-driven behavior (triage
# alerts, auto-referrals, etc.) in tests. "Eager" mode executes tasks
# synchronously in-process the moment `.delay()` is called — functionally
# equivalent to the previous purely-synchronous `auto_process=True` behavior
# this replaces (see `api/services/workflow_engine.py::emit_domain_event`)
# — so the test suite and a laptop `runserver` both keep working with zero
# extra infrastructure. In docker-compose/production, `REDIS_URL` is set,
# eager mode turns off, and `emit_domain_event` genuinely dispatches to a
# separate `celery worker` process via the shared Redis broker, which is the
# actual fix for PERF-03 (synchronous in-request workflow processing).
# `process_pending_domain_events` remains available as the retry/backoff
# path for anything that fails or falls through (e.g. a worker outage).
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', REDIS_URL or 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', CELERY_BROKER_URL)
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TASK_ALWAYS_EAGER = os.getenv(
    'CELERY_TASK_ALWAYS_EAGER', 'false' if REDIS_URL else 'true'
).lower() == 'true'
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_TIME_LIMIT = int(os.getenv('CELERY_TASK_TIME_LIMIT', '60'))
CELERY_WORKER_MAX_TASKS_PER_CHILD = 200
# Belt-and-suspenders retry path: even with a healthy worker fleet, a
# scheduled beat process (optional; see docker-compose `beat` service) can
# periodically sweep any event a worker crashed while processing.
CELERY_BEAT_SCHEDULE = {
    'process-pending-domain-events': {
        'task': 'api.process_pending_domain_events',
        'schedule': int(os.getenv('CELERY_BEAT_SWEEP_SECONDS', '300')),
    },
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'CareFlow API',
    'DESCRIPTION': 'Predictive Healthcare API',
    'VERSION': '1.0.0',
    'ENUM_NAME_OVERRIDES': {
        'AppointmentStatusEnum': [
            ('scheduled', 'Scheduled'),
            ('completed', 'Completed'),
            ('cancelled', 'Cancelled'),
            ('no_show', 'No Show'),
        ],
        'AlertSeverityEnum': [
            ('medium', 'Medium'),
            ('high', 'High'),
            ('critical', 'Critical'),
        ],
        'ReferralStatusEnum': [
            ('recommended', 'Recommended'),
            ('contacted', 'Contacted'),
            ('enrolled', 'Enrolled'),
            ('completed', 'Completed'),
            ('declined', 'Declined'),
        ],
        'AdmissionStatusEnum': [
            ('admitted', 'Admitted'),
            ('discharged', 'Discharged'),
            ('transferred', 'Transferred'),
        ],
        'MedicationOrderStatusEnum': [
            ('active', 'Active'),
            ('completed', 'Completed'),
            ('stopped', 'Stopped'),
        ],
        'LabOrderStatusEnum': [
            ('ordered', 'Ordered'),
            ('in_progress', 'In Progress'),
            ('completed', 'Completed'),
            ('cancelled', 'Cancelled'),
        ],
    },
}

# CORS
CORS_ALLOWED_ORIGINS = [o for o in os.getenv('CORS_ALLOWED_ORIGINS', '').split(',') if o]
CORS_ALLOW_ALL_ORIGINS = not CORS_ALLOWED_ORIGINS

# Security in production
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', 'true').lower() == 'true'
    USE_X_FORWARDED_HOST = True
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    CSRF_COOKIE_SECURE = True
    CSRF_COOKIE_HTTPONLY = True
    SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
    X_FRAME_OPTIONS = 'DENY'

# Logging
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {
            'format': '[{levelname}] {asctime} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': LOG_LEVEL,
    },
}

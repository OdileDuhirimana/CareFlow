import os
from pathlib import Path
from datetime import timedelta

import dj_database_url
import sentry_sdk
from django.core.exceptions import ImproperlyConfigured
from sentry_sdk.integrations.django import DjangoIntegration

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
    'rest_framework_simplejwt.token_blacklist',
    'drf_spectacular',
    'corsheaders',
    'django_extensions',
    'django_filters',
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

# Cache
#
# Why Redis-backed when available, LocMemCache otherwise: `LocMemCache` is
# per-process. The Dockerfile/docker-compose run Gunicorn with 3 worker
# processes, so a per-process cache means DRF's throttle counters (and, once
# added below, the analytics response cache) are only correct *within a
# single worker* — a client can be routed to a different worker on each
# request and effectively get 3x the intended rate limit / see stale-but-
# inconsistent cached analytics across workers. Pointing `CACHES` at a
# shared Redis instance (via `django-redis`) fixes both problems at once
# with one setting, which is why the same `REDIS_URL` also backs Celery
# (see `CELERY_BROKER_URL` below). Local dev and CI do not set `REDIS_URL`
# and fall back to `LocMemCache`, which is correct for a single-process
# `runserver`/test-runner and requires no extra infrastructure to run this
# project locally.
REDIS_URL = os.getenv('REDIS_URL', '')
if REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': REDIS_URL,
            'OPTIONS': {'CLIENT_CLASS': 'django_redis.client.DefaultClient'},
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'careflow-locmem',
        }
    }

# DRF
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
    ),
    # `Resilient*` wrappers (api/throttling.py) rather than DRF's stock
    # `AnonRateThrottle`/`UserRateThrottle` directly: the stock classes read
    # and write the rate-limit counter straight through `django.core.cache`
    # with no exception handling, so a Redis outage (the `CACHES` backend
    # whenever `REDIS_URL` is set — see above) previously propagated an
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
        # Scoped throttles for the two classic abuse targets that a blanket
        # anon/user rate does not adequately protect: the public prediction
        # endpoint (scraping/model-abuse) and the JWT token endpoints
        # (credential stuffing / brute force). See `api/views.py`
        # `PredictHealthRiskView`, `ThrottledTokenObtainPairView`,
        # `ThrottledTokenRefreshView`.
        'predict_health_risk': os.getenv('DRF_THROTTLE_PREDICT', '20/minute'),
        'token_obtain': os.getenv('DRF_THROTTLE_TOKEN', '10/minute'),
    },
    # DEFAULT_PAGINATION_CLASS + PAGE_SIZE: every list endpoint now returns
    # bounded pages ({"count", "next", "previous", "results"}) instead of
    # the full unbounded table. Without this, patient/appointment/lab-order
    # collections would grow unboundedly slow as demo/production data
    # accumulates — this was the single biggest scalability gap identified
    # in the code review.
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': int(os.getenv('DRF_PAGE_SIZE', '25')),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    # Normalizes every DRF-raised exception (ValidationError, PermissionDenied,
    # NotAuthenticated, Throttled, etc.) into one consistent
    # {"detail": ..., "errors": {...}} envelope. See `api/exceptions.py` for
    # the full rationale.
    'EXCEPTION_HANDLER': 'api.exceptions.careflow_exception_handler',
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=30),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'SIGNING_KEY': os.getenv('JWT_SECRET', SECRET_KEY),
    # BLACKLIST_AFTER_ROTATION only matters if ROTATE_REFRESH_TOKENS is
    # enabled (it isn't here); left explicit for clarity since the
    # token_blacklist app is now installed for the logout endpoint
    # (`POST /api/auth/logout/`, see `api/views.py::LogoutView`).
    'BLACKLIST_AFTER_ROTATION': False,
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

# Analytics response caching
#
# `CareAnalyticsView`/`ImpactAnalyticsView`/`HospitalFlowAnalyticsView`
# (api/views.py) recompute several aggregate queries from scratch on every
# request. A short TTL (default 60s) is enough to absorb dashboard-polling
# traffic without ever showing meaningfully stale KPIs — see README "Known
# Tradeoffs" for why a longer TTL or invalidation-on-write was deliberately
# not pursued for a portfolio-scale project. Uses the same `CACHES` backend
# configured above (LocMemCache locally, Redis in production), so this is
# consistent across Gunicorn workers wherever `REDIS_URL` is set.
ANALYTICS_CACHE_TTL_SECONDS = int(os.getenv('ANALYTICS_CACHE_TTL_SECONDS', '60'))

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
#
# Structured JSON logging (via python-json-logger) instead of a plain-text
# formatter. Why: this app emits domain-significant events (alert creation,
# workflow-rule execution, audit access/export, login/logout) that a real
# deployment would need to search/filter/alert on — "why didn't this
# high-risk triage trigger an alert?" is a question you answer by grepping
# structured fields (event_type, patient_id, rule_id), not by parsing
# freeform text. JSON output is also what every log aggregation platform
# (CloudWatch, Datadog, Loki, etc.) expects natively.
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
            'format': '%(asctime)s %(levelname)s %(name)s %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'json',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': LOG_LEVEL,
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        'careflow': {
            'handlers': ['console'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
    },
}

# Error tracking + performance tracing (Sentry)
#
# No-op unless SENTRY_DSN is set in the environment — local dev and CI never
# send anything anywhere. When set (typically only in production), this
# gives visibility into unhandled exceptions that would otherwise only
# surface as an opaque 500 with no external record, which is a meaningful
# gap for an app handling clinical workflows.
#
# `traces_sample_rate` defaults to 0.2 (20% of requests) rather than the
# previous 0.0: with `SENTRY_DSN` set, this project had error tracking but
# zero performance tracing, so a real production slowdown would show up as
# "no errors, mysteriously slow" with no trace data to diagnose it from.
# 20% is a deliberately conservative default for a low/demo-traffic
# portfolio deployment (full 100% tracing on real production traffic would
# be a cost/volume decision for whoever operates that deployment); it is
# fully overridable via `SENTRY_TRACES_SAMPLE_RATE`. This has zero effect
# unless `SENTRY_DSN` is configured, so local dev/CI behavior is unchanged.
SENTRY_DSN = os.getenv('SENTRY_DSN', '')
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        traces_sample_rate=float(os.getenv('SENTRY_TRACES_SAMPLE_RATE', '0.2')),
        send_default_pii=False,
        environment=os.getenv('SENTRY_ENVIRONMENT', 'production' if not DEBUG else 'development'),
    )

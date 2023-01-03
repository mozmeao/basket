import os
import platform
import socket
import struct
import sys
from datetime import timedelta
from pathlib import Path

import dj_database_url
import django_cache_url
import sentry_sdk
from decouple import Csv, UndefinedValueError, config
from sentry_processor import DesensitizationProcessor
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import ignore_logger

# Application version.
VERSION = (0, 1)

# ROOT path of the project. A pathlib.Path object.
ROOT_PATH = Path(__file__).resolve().parents[1]
ROOT = str(ROOT_PATH)


def path(*args):
    return str(ROOT_PATH.joinpath(*args))


DEBUG = config("DEBUG", default=False, cast=bool)

ADMINS = (
    # ('Your Name', 'your_email@domain.com'),
)

MANAGERS = ADMINS
# avoids a warning from django
TEST_RUNNER = "django.test.runner.DiscoverRunner"

# DB read-only, API can still read-write to backend
READ_ONLY_MODE = config("READ_ONLY_MODE", False, cast=bool)
# Disables the API and changes redirects
ADMIN_ONLY_MODE = config("ADMIN_ONLY_MODE", False, cast=bool)
BASKET_RW_URL = config(
    "BASKET_RW_URL",
    default="https://prod-oregon-b.basket.moz.works",
)

REDIS_URL = config("REDIS_URL", None)
if REDIS_URL:
    REDIS_URL = REDIS_URL.rstrip("/0")
    # use redis for celery and cache
    os.environ["CELERY_BROKER_URL"] = REDIS_URL + "/" + config("REDIS_CELERY_DB", "0")
    os.environ["CACHE_URL"] = REDIS_URL + "/" + config("REDIS_CACHE_DB", "1")

# Production uses MySQL, but Sqlite should be sufficient for local development.
# Our CI server tests against MySQL.
DATABASES = {
    "default": config(
        "DATABASE_URL",
        default="sqlite:///basket.db",
        cast=dj_database_url.parse,
    ),
}
if DATABASES["default"]["ENGINE"] == "django.db.backends.mysql":
    DATABASES["default"]["OPTIONS"] = {
        "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
    }
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

CACHES = {
    "default": config("CACHE_URL", default="locmem://", cast=django_cache_url.parse),
    "bad_message_ids": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "TIMEOUT": 12 * 60 * 60,  # 12 hours
    },
    "email_block_list": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "TIMEOUT": 60 * 60,  # 1 hour
    },
    "product_details": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}

if CACHES["default"]["BACKEND"].startswith("django_redis"):
    options = CACHES["default"].setdefault("OPTIONS", {})
    options["PARSER_CLASS"] = "redis.connection.HiredisParser"

default_email_backend = (
    "django.core.mail.backends.console.EmailBackend"
    if DEBUG
    else "django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_BACKEND = config("EMAIL_BACKEND", default=default_email_backend)
EMAIL_HOST = config("EMAIL_HOST", default="localhost")
EMAIL_PORT = config("EMAIL_PORT", default=25, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=False, cast=bool)
EMAIL_SUBJECT_PREFIX = config("EMAIL_SUBJECT_PREFIX", default="[basket] ")
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")

ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    default=".allizom.org, .moz.works, basket.mozmar.org, "
    "basket.mozilla.com, basket.mozilla.org",
    cast=Csv(),
)
ALLOWED_CIDR_NETS = config("ALLOWED_CIDR_NETS", default="", cast=Csv())
ENFORCE_HOSTNAME = config("ENFORCE_HOSTNAME", default="", cast=Csv())
USE_X_FORWARDED_HOST = True

SESSION_COOKIE_SECURE = config("SESSION_COOKIE_SECURE", not DEBUG, cast=bool)
SESSION_ENGINE = config(
    "SESSION_ENGINE",
    default="django.contrib.sessions.backends.cache",
)
CSRF_COOKIE_SECURE = config("CSRF_COOKIE_SECURE", not DEBUG, cast=bool)
DISABLE_ADMIN = config("DISABLE_ADMIN", READ_ONLY_MODE, cast=bool)
STORE_TASK_FAILURES = config("STORE_TASK_FAILURES", not READ_ONLY_MODE, cast=bool)
# if DISABLE_ADMIN is True redirect /admin/ to this URL
ADMIN_REDIRECT_URL = config(
    "ADMIN_REDIRECT_URL",
    "https://admin.basket.moz.works/admin/",
)

TIME_ZONE = "UTC"
USE_TZ = True
SITE_ID = 1
USE_I18N = False

STATIC_ROOT = path("static")
STATIC_URL = "/static/"
if not DEBUG:
    STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

try:
    # Make this unique, and don't share it with anybody.
    SECRET_KEY = config("SECRET_KEY")
except UndefinedValueError:
    raise UndefinedValueError(
        "The SECRET_KEY environment variable is required. "
        "Move env-dist to .env if you want the defaults.",
    )

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": ["templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.request",
                "django.contrib.messages.context_processors.messages",
                "basket.news.context_processors.settings",
            ],
        },
    },
]

MIDDLEWARE = (
    "allow_cidr.middleware.AllowCIDRMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "basket.news.middleware.EnforceHostnameMiddleware",
    "basket.news.middleware.HostnameMiddleware",
    "django.middleware.common.CommonMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "basket.news.middleware.GraphiteViewHitCountMiddleware",
    "django_statsd.middleware.GraphiteRequestTimingMiddleware",
    "django_statsd.middleware.GraphiteMiddleware",
    "ratelimit.middleware.RatelimitMiddleware",
)

ROOT_URLCONF = "basket.urls"

INSTALLED_APPS = (
    "basket.news",
    "basket.base",
    "corsheaders",
    "product_details",
    "django_extensions",
    "mozilla_django_oidc",
    "watchman",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.messages",
    "django.contrib.admin",
    "django.contrib.staticfiles",
)

# SecurityMiddleware settings
SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default="0", cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_BROWSER_XSS_FILTER = config("SECURE_BROWSER_XSS_FILTER", default=True, cast=bool)
SECURE_CONTENT_TYPE_NOSNIFF = config(
    "SECURE_CONTENT_TYPE_NOSNIFF",
    default=True,
    cast=bool,
)
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=False, cast=bool)
SECURE_REDIRECT_EXEMPT = [
    r"^healthz/$",
    r"^readiness/$",
]
if config("USE_SECURE_PROXY_HEADER", default=SECURE_SSL_REDIRECT, cast=bool):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# watchman
WATCHMAN_DISABLE_APM = True
WATCHMAN_CHECKS = (
    "watchman.checks.caches",
    "watchman.checks.databases",
)


ACOUSTIC_CLIENT_ID = config("ACOUSTIC_CLIENT_ID", None)
ACOUSTIC_CLIENT_SECRET = config("ACOUSTIC_CLIENT_SECRET", None)
ACOUSTIC_REFRESH_TOKEN = config("ACOUSTIC_REFRESH_TOKEN", None)
ACOUSTIC_SERVER_NUMBER = config("ACOUSTIC_SERVER_NUMBER", None)
ACOUSTIC_FXA_TABLE_ID = config("ACOUSTIC_FXA_TABLE_ID", None)
ACOUSTIC_FXA_LOG_ENABLED = config("ACOUSTIC_FXA_LOG_ENABLED", True, cast=bool)

ACOUSTIC_TX_CLIENT_ID = config("ACOUSTIC_TX_CLIENT_ID", None)
ACOUSTIC_TX_CLIENT_SECRET = config("ACOUSTIC_TX_CLIENT_SECRET", None)
ACOUSTIC_TX_REFRESH_TOKEN = config("ACOUSTIC_TX_REFRESH_TOKEN", None)
ACOUSTIC_TX_SERVER_NUMBER = config("ACOUSTIC_TX_SERVER_NUMBER", None)
# Send confirmation messages via Acoustic Transact
SEND_CONFIRM_MESSAGES = config("SEND_CONFIRM_MESSAGES", False, cast=bool)

# Mozilla CTMS
CTMS_ENV = config("CTMS_ENV", "").lower()
CTMS_ENABLED = config("CTMS_ENABLED", False, cast=bool)
if CTMS_ENV == "stage":
    default_url = "https://ctms.stage.mozilla-ess.mozit.cloud"
elif CTMS_ENV == "prod":
    default_url = "https://ctms.prod.mozilla-ess.mozit.cloud"
else:
    default_url = ""
CTMS_URL = config("CTMS_URL", default_url)
CTMS_CLIENT_ID = config("CTMS_CLIENT_ID", None)
CTMS_CLIENT_SECRET = config("CTMS_CLIENT_SECRET", None)

CORS_ORIGIN_ALLOW_ALL = True
CORS_URLS_REGEX = r"^/(news/|subscribe)"

# view rate limiting
RATELIMIT_VIEW = "basket.news.views.ratelimited"

KOMBU_FERNET_KEY = config("KOMBU_FERNET_KEY", None)
# for key rotation
KOMBU_FERNET_KEY_PREVIOUS = config("KOMBU_FERNET_KEY_PREVIOUS", None)
CELERY_TASK_ALWAYS_EAGER = config("CELERY_TASK_ALWAYS_EAGER", DEBUG, cast=bool)
CELERY_TASK_SERIALIZER = "json"
CELERY_TASK_ACKS_LATE = config("CELERY_TASK_ACKS_LATE", True, cast=bool)
CELERY_TASK_REJECT_ON_WORKER_LOST = False
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_MAX_RETRY_DELAY_MINUTES = 2048
CELERY_BROKER_TRANSPORT_OPTIONS = {
    "visibility_timeout": CELERY_MAX_RETRY_DELAY_MINUTES * 60,
}
CELERY_BROKER_URL = config("CELERY_BROKER_URL", None)
CELERY_REDIS_MAX_CONNECTIONS = config("CELERY_REDIS_MAX_CONNECTIONS", 2, cast=int)
CELERY_WORKER_DISABLE_RATE_LIMITS = True
CELERY_TASK_IGNORE_RESULT = True
CELERY_WORKER_PREFETCH_MULTIPLIER = config(
    "CELERY_WORKER_PREFETCH_MULTIPLIER",
    1,
    cast=int,
)
CELERY_TASK_COMPRESSION = "gzip"
CELERY_TASK_ROUTES = {
    "basket.news.tasks.snitch": {"queue": "snitch"},
}

# size in kb
CELERY_WORKER_MAX_MEMORY_PER_CHILD = config(
    "CELERY_WORKER_MAX_MEMORY_PER_CHILD",
    200000,
    cast=int,
)

SNITCH_ID = config("SNITCH_ID", None)

CELERY_BEAT_SCHEDULE = {}

if SNITCH_ID:
    CELERY_BEAT_SCHEDULE["snitch"] = {
        "task": "basket.news.tasks.snitch",
        "schedule": timedelta(minutes=5),
    }

if not READ_ONLY_MODE:
    CELERY_BEAT_SCHEDULE["common-voice"] = {
        "task": "basket.news.tasks.process_common_voice_batch",
        "schedule": timedelta(hours=1),
    }


# via http://stackoverflow.com/a/6556951/107114
def get_default_gateway_linux():
    """Read the default gateway directly from /proc."""
    try:
        with open("/proc/net/route") as fh:
            for line in fh:
                fields = line.strip().split()
                if fields[1] != "00000000" or not int(fields[3], 16) & 2:
                    continue

                return socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))
    except IOError:
        return "localhost"


HOSTNAME = platform.node()
CLUSTER_NAME = config("CLUSTER_NAME", default=None)
K8S_NAMESPACE = config("K8S_NAMESPACE", default=None)
K8S_POD_NAME = config("K8S_POD_NAME", default=None)

# Data scrubbing before Sentry
# https://github.com/laiyongtao/sentry-processor
SENSITIVE_FIELDS_TO_MASK_ENTIRELY = [
    "amo_id",
    "custom_id",
    "email",
    "first_name",
    "fxa_id",
    "id",
    "ip_address",
    "last_name",
    "mobile_number",
    "payee_id",
    "primary_email",
    "remote_addr",
    "remoteaddresschain",
    "token",
    "uid",
    "user",
    "x-forwarded-for",
]

SENSITIVE_FIELDS_TO_MASK_PARTIALLY = []


def before_send(event, hint):
    processor = DesensitizationProcessor(
        with_default_keys=True,
        sensitive_keys=SENSITIVE_FIELDS_TO_MASK_ENTIRELY,
        # partial_keys=SENSITIVE_FIELDS_TO_MASK_PARTIALLY,
        # mask_position=POSITION.LEFT,  # import from sentry_processor if you need it
        # off_set=3,
    )
    event = processor.process(event, hint)
    return event


sentry_sdk.init(
    dsn=config("SENTRY_DSN", None),
    release=config("GIT_SHA", None),
    server_name=".".join(x for x in [K8S_NAMESPACE, CLUSTER_NAME, HOSTNAME] if x),
    integrations=[CeleryIntegration(), DjangoIntegration()],
    before_send=before_send,
)

STATSD_HOST = config("STATSD_HOST", get_default_gateway_linux())
STATSD_PORT = config("STATSD_PORT", 8125, cast=int)
STATSD_PREFIX = config("STATSD_PREFIX", K8S_NAMESPACE)
STATSD_CLIENT = config("STATSD_CLIENT", "django_statsd.clients.null")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "root": {
        "level": config("DJANGO_LOG_LEVEL", default="WARNING"),
        "handlers": ["console"],
    },
    "formatters": {
        "verbose": {"format": "%(levelname)s %(asctime)s %(module)s %(message)s"},
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "null": {"class": "logging.NullHandler"},
    },
    "loggers": {
        "django.db.backends": {
            "level": "ERROR",
            "handlers": ["console"],
            "propagate": False,
        },
        "suds.client": {"level": "ERROR", "handlers": ["console"], "propagate": False},
    },
}

# DisallowedHost gets a lot of action thanks to scans/bots/scripts,
# but we need not take any action because it's already HTTP 400-ed.
# Note that we ignore at the Sentry client level

ignore_logger("django.security.DisallowedHost")

PROD_DETAILS_CACHE_NAME = "product_details"
PROD_DETAILS_CACHE_TIMEOUT = None

RECOVER_MSG_LANGS = config("RECOVER_MSG_LANGS", "en", cast=Csv())
# language codes that we support and send through to backend
# regardless of their existence in the DB
EXTRA_SUPPORTED_LANGS = config("EXTRA_SUPPORTED_LANGS", "", cast=Csv())

SYNC_KEY = config("SYNC_KEY", None)
TESTING_EMAIL_DOMAINS = config(
    "TESTING_EMAIL_DOMAINS",
    "restmail.net,restmail.lcip.org,example.com",
    cast=Csv(),
)

MAINTENANCE_MODE = config("MAINTENANCE_MODE", False, cast=bool)
QUEUE_BATCH_SIZE = config("QUEUE_BATCH_SIZE", 500, cast=int)
# can we read user data in maintenance mode
MAINTENANCE_READ_ONLY = config("MAINTENANCE_READ_ONLY", False, cast=bool)

USE_SANDBOX_BACKEND = config("USE_SANDBOX_BACKEND", False, cast=bool)

TASK_LOCK_TIMEOUT = config("TASK_LOCK_TIMEOUT", 60, cast=int)
TASK_LOCKING_ENABLE = config("TASK_LOCKING_ENABLE", False, cast=bool)

DONATE_ACCESS_KEY_ID = config("DONATE_ACCESS_KEY_ID", default="")
DONATE_SECRET_ACCESS_KEY = config("DONATE_SECRET_ACCESS_KEY", default="")
DONATE_QUEUE_REGION = config("DONATE_QUEUE_REGION", default="")
DONATE_QUEUE_URL = config("DONATE_QUEUE_URL", default="")
DONATE_QUEUE_WAIT_TIME = config("DONATE_QUEUE_WAIT_TIME", cast=int, default=10)
# turn this on to consume the queue but ignore the messages
# needed so that donate.m.o can run continuous tests w/o filling the backend sandbox
DONATE_QUEUE_IGNORE_MODE = config("DONATE_QUEUE_IGNORE_MODE", cast=bool, default=False)
DONATE_SEND_RECEIPTS = config("DONATE_SEND_RECEIPTS", cast=bool, default=False)
DONATE_RECEIPTS_BCC = config("DONATE_RECEIPTS_BCC", "", cast=Csv())
DONATE_OPP_RECORD_TYPE = config("DONATE_OPP_RECORD_TYPE", default="")
DONATE_CONTACT_RECORD_TYPE = config("DONATE_CONTACT_RECORD_TYPE", default="")
DONATE_SNITCH_ID = config("DONATE_SNITCH_ID", default="")
DONATE_NOTIFY_EMAIL = config("DONATE_NOTIFY_EMAIL", default="")
DONATE_UPDATE_FAIL_DE = config("DONATE_UPDATE_FAIL_DE", default="Donation_Diff")

FXA_EVENTS_QUEUE_ENABLE = config("FXA_EVENTS_QUEUE_ENABLE", cast=bool, default=False)
FXA_EVENTS_QUEUE_IGNORE_MODE = config(
    "FXA_EVENTS_QUEUE_IGNORE_MODE",
    cast=bool,
    default=False,
)
FXA_EVENTS_ACCESS_KEY_ID = config("FXA_EVENTS_ACCESS_KEY_ID", default="")
FXA_EVENTS_SECRET_ACCESS_KEY = config("FXA_EVENTS_SECRET_ACCESS_KEY", default="")
FXA_EVENTS_QUEUE_REGION = config("FXA_EVENTS_QUEUE_REGION", default="")
FXA_EVENTS_QUEUE_URL = config("FXA_EVENTS_QUEUE_URL", default="")
FXA_EVENTS_QUEUE_WAIT_TIME = config("FXA_EVENTS_QUEUE_WAIT_TIME", cast=int, default=10)
FXA_EVENTS_SNITCH_ID = config("FXA_EVENTS_SNITCH_ID", default="")

# stable, stage, or production
# https://github.com/mozilla/PyFxA/blob/master/fxa/constants.py
FXA_OAUTH_SERVER_ENV = config("FXA_OAUTH_SERVER_ENV", default="stable")
FXA_CLIENT_ID = config("FXA_CLIENT_ID", default="")
FXA_CLIENT_SECRET = config("FXA_CLIENT_SECRET", default="")
FXA_OAUTH_TOKEN_TTL = config("FXA_OAUTH_TOKEN_TTL", default=300, cast=int)  # 5 minutes

FXA_EMAIL_PREFS_DOMAIN = config("FXA_EMAIL_PREFS_DOMAIN", default="www.mozilla.org")
FXA_REGISTER_NEWSLETTER = config(
    "FXA_REGISTER_NEWSLETTER",
    default="firefox-accounts-journey",
)
FXA_REGISTER_SOURCE_URL = config(
    "FXA_REGISTER_SOURCE_URL",
    default="https://accounts.firefox.com/",
)
# TODO move this to the DB
FXA_LOGIN_CAMPAIGNS = {
    "fxa-embedded-form-moz": "mozilla-welcome",
    "fxa-embedded-form-fx": "firefox-welcome",
    "membership-idealo": "member-idealo",
    "membership-comm": "member-comm",
    "membership-tech": "member-tech",
    "membership-tk": "member-tk",
}

COMMON_VOICE_NEWSLETTER = config("COMMON_VOICE_NEWSLETTER", default="common-voice")
COMMON_VOICE_BATCH_UPDATES = config(
    "COMMON_VOICE_BATCH_UPDATES",
    default=False,
    cast=bool,
)
COMMON_VOICE_BATCH_PROCESSING = config(
    "COMMON_VOICE_BATCH_PROCESSING",
    default=False,
    cast=bool,
)
COMMON_VOICE_BATCH_CHUNK_SIZE = config(
    "COMMON_VOICE_BATCH_CHUNK_SIZE",
    default=1000,
    cast=int,
)

OIDC_ENABLE = config("OIDC_ENABLE", default=False, cast=bool)
if OIDC_ENABLE:
    AUTHENTICATION_BACKENDS = ("basket.base.authentication.OIDCModelBackend",)
    OIDC_OP_AUTHORIZATION_ENDPOINT = config("OIDC_OP_AUTHORIZATION_ENDPOINT")
    OIDC_OP_TOKEN_ENDPOINT = config("OIDC_OP_TOKEN_ENDPOINT")
    OIDC_OP_USER_ENDPOINT = config("OIDC_OP_USER_ENDPOINT")

    OIDC_RP_CLIENT_ID = config("OIDC_RP_CLIENT_ID")
    OIDC_RP_CLIENT_SECRET = config("OIDC_RP_CLIENT_SECRET")
    OIDC_CREATE_USER = config("OIDC_CREATE_USER", default=False, cast=bool)
    MIDDLEWARE += ("basket.news.middleware.OIDCSessionRefreshMiddleware",)
    LOGIN_REDIRECT_URL = "/admin/"

if (
    sys.argv[0].endswith("py.test")
    or sys.argv[0].endswith("pytest")
    or (len(sys.argv) > 1 and sys.argv[1] == "test")
):
    # stuff that's absolutely required for a test run
    CELERY_TASK_ALWAYS_EAGER = True
    TESTING_EMAIL_DOMAINS = []

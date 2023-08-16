import os
import platform
import re
import socket
import struct
import sys
from pathlib import Path

import dj_database_url
import django_cache_url
import markus
import sentry_sdk
from decouple import Csv, UndefinedValueError, config
from sentry_processor import DesensitizationProcessor
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import ignore_logger
from sentry_sdk.integrations.redis import RedisIntegration
from sentry_sdk.integrations.rq import RqIntegration

# Application version.
VERSION = (0, 1)

# ROOT path of the project. A pathlib.Path object.
ROOT_PATH = Path(__file__).resolve().parents[1]
ROOT = str(ROOT_PATH)


def path(*args):
    return str(ROOT_PATH.joinpath(*args))


LOCAL_DEV = config("LOCAL_DEV", False, cast=bool)
DEBUG = config("DEBUG", default=False, cast=bool)
UNITTEST = config("UNITTEST", default=False, cast=bool)

# If we forget to set a `UNITTEST` env var by are running `pytest`, set it.
if sys.argv[0].endswith(("py.test", "pytest")):
    UNITTEST = True

ADMINS = (
    # ('Your Name', 'your_email@domain.com'),
)

MANAGERS = ADMINS
# avoids a warning from django
TEST_RUNNER = "django.test.runner.DiscoverRunner"

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

# CACHE_URL and RQ_URL are derived from REDIS_URL.
REDIS_URL = config("REDIS_URL", None)
if REDIS_URL:
    REDIS_URL = REDIS_URL.rstrip("/0")
    HIREDIS_URL = REDIS_URL.replace("redis://", "hiredis://")
    # Use Redis for cache and rq.
    # Note: We save the URL in the environment so `config` can pull from it below.
    os.environ["CACHE_URL"] = HIREDIS_URL + "/" + config("REDIS_CACHE_DB", "1")
    RQ_URL = REDIS_URL + "/" + config("REDIS_RQ_DB", "2")

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

default_email_backend = "django.core.mail.backends.console.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend"
EMAIL_BACKEND = config("EMAIL_BACKEND", default=default_email_backend)
EMAIL_HOST = config("EMAIL_HOST", default="localhost")
EMAIL_PORT = config("EMAIL_PORT", default=25, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=False, cast=bool)
EMAIL_SUBJECT_PREFIX = config("EMAIL_SUBJECT_PREFIX", default="[basket] ")
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")

ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    default=".allizom.org, .moz.works, basket.mozmar.org, basket.mozilla.com, basket.mozilla.org",
    cast=Csv(),
)
ALLOWED_CIDR_NETS = config("ALLOWED_CIDR_NETS", default="", cast=Csv())
USE_X_FORWARDED_HOST = True

SESSION_COOKIE_SECURE = config("SESSION_COOKIE_SECURE", not DEBUG, cast=bool)
SESSION_ENGINE = config(
    "SESSION_ENGINE",
    default="django.contrib.sessions.backends.cache",
)
CSRF_COOKIE_SECURE = config("CSRF_COOKIE_SECURE", not DEBUG, cast=bool)

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
except UndefinedValueError as exc:
    raise UndefinedValueError(
        "The SECRET_KEY environment variable is required. Move env-dist to .env if you want the defaults.",
    ) from exc

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
    "basket.base.middleware.HostnameMiddleware",
    "django.middleware.common.CommonMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "basket.base.middleware.MetricsViewTimingMiddleware",
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

# RQ configuration.
RQ_RESULT_TTL = config("RQ_RESULT_TTL", default=0, cast=int)  # Ignore results.
RQ_MAX_RETRY_DELAY = config("RQ_MAX_RETRY_DELAY", default=34 * 60 * 60, cast=int)  # 34 hours in seconds.
RQ_MAX_RETRIES = 0 if UNITTEST else config("RQ_MAX_RETRIES", default=12, cast=int)
RQ_EXCEPTION_HANDLERS = ["basket.base.rq.store_task_exception_handler"]
RQ_IS_ASYNC = False if UNITTEST else config("RQ_IS_ASYNC", default=True, cast=bool)

SNITCH_ID = config("SNITCH_ID", None)


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
    integrations=[DjangoIntegration(signals_spans=False), RedisIntegration(), RqIntegration()],
    before_send=before_send,
)

STATSD_HOST = config("STATSD_HOST", get_default_gateway_linux())
STATSD_PORT = config("STATSD_PORT", 8125, cast=int)
STATSD_PREFIX = config("STATSD_PREFIX", K8S_NAMESPACE)

if LOCAL_DEV:
    MARKUS_BACKENDS = [
        {"class": "markus.backends.logging.LoggingMetrics", "options": {"logger_name": "metrics"}},
    ]
else:
    MARKUS_BACKENDS = [
        {
            "class": "markus.backends.datadog.DatadogMetrics",
            "options": {
                "statsd_host": STATSD_HOST,
                "statsd_port": STATSD_PORT,
                "statsd_namespace": STATSD_PREFIX,
            },
        },
    ]

markus.configure(backends=MARKUS_BACKENDS)

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

# language codes that we support and send through to backend
# regardless of their existence in the DB
EXTRA_SUPPORTED_LANGS = config("EXTRA_SUPPORTED_LANGS", "", cast=Csv())

if UNITTEST:
    TESTING_EMAIL_DOMAINS = []
else:
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

OIDC_ENABLE = config("OIDC_ENABLE", default=False, cast=bool)
if OIDC_ENABLE:
    AUTHENTICATION_BACKENDS = ("basket.base.authentication.OIDCModelBackend",)
    OIDC_OP_AUTHORIZATION_ENDPOINT = config("OIDC_OP_AUTHORIZATION_ENDPOINT")
    OIDC_OP_TOKEN_ENDPOINT = config("OIDC_OP_TOKEN_ENDPOINT")
    OIDC_OP_USER_ENDPOINT = config("OIDC_OP_USER_ENDPOINT")

    OIDC_RP_CLIENT_ID = config("OIDC_RP_CLIENT_ID")
    OIDC_RP_CLIENT_SECRET = config("OIDC_RP_CLIENT_SECRET")
    OIDC_CREATE_USER = config("OIDC_CREATE_USER", default=False, cast=bool)
    LOGIN_REDIRECT_URL = "/admin/"
    OIDC_EXEMPT_URLS = [
        "/",
        "/fxa/",
        "/fxa/callback/",
        re.compile(r"^/news/*"),
        "/subscribe/",
        "/subscribe.json",
        # Health checks.
        "/healthz/",
        "/readiness/",
        "/watchman/",
    ]

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
from corsheaders.defaults import default_headers
from everett.manager import ChoiceOf, ConfigManager, ConfigurationMissingError, ListOf
from sentry_processor import DesensitizationProcessor
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import ignore_logger
from sentry_sdk.integrations.redis import RedisIntegration
from sentry_sdk.integrations.rq import RqIntegration

# The `basic_config` manager searches in this order:
#   1. environment variables
#   2. .env file
#   3. `default` keyword argument
config = ConfigManager.basic_config()

# Application version.
VERSION = (0, 1)

# ROOT path of the project. A pathlib.Path object.
ROOT_PATH = Path(__file__).resolve().parents[1]
ROOT = str(ROOT_PATH)


def path(*args):
    return str(ROOT_PATH.joinpath(*args))


LOCAL_DEV = config("LOCAL_DEV", parser=bool, default="false")
DEBUG = config("DEBUG", parser=bool, default="false")
UNITTEST = config("UNITTEST", parser=bool, default="false")

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
db_default_url = config("DATABASE_URL", default="sqlite:///basket.db")
DATABASES = {
    "default": dj_database_url.parse(db_default_url),
}
if DATABASES["default"]["ENGINE"] == "django.db.backends.mysql":
    DATABASES["default"]["OPTIONS"] = {
        "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
    }
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

# CACHE_URL and RQ_URL are derived from REDIS_URL.
REDIS_URL = config("REDIS_URL", default="")
if REDIS_URL:
    REDIS_URL = REDIS_URL.rstrip("/0")
    # Use Redis for cache and rq.
    # Note: We save the URL in the environment so `config` can pull from it below.
    os.environ["CACHE_URL"] = f"{REDIS_URL}/{config('REDIS_CACHE_DB', default='1')}"
    RQ_URL = f"{REDIS_URL}/{config('REDIS_RQ_DB', default='2')}"

CACHES = {
    "default": config("CACHE_URL", parser=django_cache_url.parse, default="locmem://"),
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
EMAIL_PORT = config("EMAIL_PORT", parser=int, default="25")
EMAIL_USE_TLS = config("EMAIL_USE_TLS", parser=bool, default="false")
EMAIL_SUBJECT_PREFIX = config("EMAIL_SUBJECT_PREFIX", default="[basket] ")
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")

ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    parser=ListOf(str, allow_empty=False),
    default="basket-dev.allizom.org,basket.allizom.org,basket.mozilla.org",
)
ALLOWED_CIDR_NETS = config(
    "ALLOWED_CIDR_NETS",
    parser=ListOf(str, allow_empty=False),
    default="",
)
USE_X_FORWARDED_HOST = True

SESSION_COOKIE_SECURE = config("SESSION_COOKIE_SECURE", parser=bool, default=str(not DEBUG))
SESSION_ENGINE = config("SESSION_ENGINE", default="django.contrib.sessions.backends.cache")
CSRF_COOKIE_SECURE = config("CSRF_COOKIE_SECURE", parser=bool, default=str(not DEBUG))

TIME_ZONE = "UTC"
USE_TZ = True
SITE_ID = 1
USE_I18N = False

SITE_URL = config("SITE_URL", default="https://basket.mozilla.org")

STATIC_ROOT = path("static")
STATIC_URL = "/static/"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if (DEBUG or UNITTEST)
        else "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

try:
    # Make this unique, and don't share it with anybody.
    SECRET_KEY = config("SECRET_KEY")
except ConfigurationMissingError as exc:
    raise ValueError(
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
    "django_ratelimit.middleware.RatelimitMiddleware",
)

ROOT_URLCONF = "basket.urls"

INSTALLED_APPS = (
    "basket.base",
    "basket.news",
    "corsheaders",
    "product_details",
    "mozilla_django_oidc",
    "watchman",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.messages",
    "basket.apps.BasketAdminConfig",
    "django.contrib.staticfiles",
)

# SecurityMiddleware settings
SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", parser=int, default="0")
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_BROWSER_XSS_FILTER = config("SECURE_BROWSER_XSS_FILTER", parser=bool, default="true")
SECURE_CONTENT_TYPE_NOSNIFF = config("SECURE_CONTENT_TYPE_NOSNIFF", parser=bool, default="true")
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", parser=bool, default="false")
SECURE_REDIRECT_EXEMPT = [
    r"^healthz/$",
    r"^readiness/$",
]
if config("USE_SECURE_PROXY_HEADER", parser=bool, default=str(SECURE_SSL_REDIRECT)):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# watchman
WATCHMAN_DISABLE_APM = True
WATCHMAN_CHECKS = (
    "watchman.checks.caches",
    "watchman.checks.databases",
)

# Send confirmation messages
SEND_CONFIRM_MESSAGES = config("SEND_CONFIRM_MESSAGES", parser=bool, default="false")

BRAZE_API_KEY = config("BRAZE_API_KEY", default="")
BRAZE_BASE_API_URL = config("BRAZE_BASE_API_URL", default="https://rest.iad-05.braze.com")
# Map of Braze message IDs to the actual message IDs.
# This is intended for older messages that are hard to change.
BRAZE_MESSAGE_ID_MAP = {
    "download-firefox-mobile-whatsnew": "download-firefox-mobile",
    "firefox-mobile-welcome": "download-firefox-mobile",
}

BRAZE_DELETE_USER_ENABLE = config("BRAZE_DELETE_USER_ENABLE", parser=bool, default="false")

BRAZE_PARALLEL_WRITE_ENABLE = config("BRAZE_PARALLEL_WRITE_ENABLE", parser=bool, default="false")
BRAZE_ONLY_WRITE_ENABLE = config("BRAZE_ONLY_WRITE_ENABLE", parser=bool, default="false")
BRAZE_READ_WITH_FALLBACK_ENABLE = config("BRAZE_READ_WITH_FALLBACK_ENABLE", parser=bool, default="false")
BRAZE_ONLY_READ_ENABLE = config("BRAZE_ONLY_READ_ENABLE", parser=bool, default="false")

# Mozilla CTMS
CTMS_ENV = config("CTMS_ENV", default="").lower()
CTMS_ENABLED = config("CTMS_ENABLED", parser=bool, default="false")
if CTMS_ENV == "stage":
    default_url = "https://ctms.stage.mozilla-ess.mozit.cloud"
elif CTMS_ENV == "prod":
    default_url = "https://ctms.prod.mozilla-ess.mozit.cloud"
else:
    default_url = ""
CTMS_URL = config("CTMS_URL", default=default_url)
CTMS_CLIENT_ID = config("CTMS_CLIENT_ID", default="") if not UNITTEST else "test"
CTMS_CLIENT_SECRET = config("CTMS_CLIENT_SECRET", default="") if not UNITTEST else "test"

CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_HEADERS = (*default_headers, "x-api-key")
CORS_URLS_REGEX = r"^/(api/|news/|subscribe)"

# view rate limiting
RATELIMIT_VIEW = "basket.news.views.ratelimited"
EMAIL_SUBSCRIBE_RATE_LIMIT = config("EMAIL_SUBSCRIBE_RATE_LIMIT", default="4/5m")

# RQ configuration.
RQ_RESULT_TTL = config("RQ_RESULT_TTL", parser=int, default="0")  # Ignore results.
RQ_MAX_RETRY_DELAY = config("RQ_MAX_RETRY_DELAY", parser=int, default=str(34 * 60 * 60))  # 34 hours in seconds.
RQ_MAX_RETRIES = 0 if UNITTEST else config("RQ_MAX_RETRIES", parser=int, default="12")
RQ_EXCEPTION_HANDLERS = ["basket.base.rq.store_task_exception_handler"]
RQ_IS_ASYNC = False if UNITTEST else config("RQ_IS_ASYNC", parser=bool, default="true")
RQ_DEFAULT_QUEUE = "testqueue" if UNITTEST else config("RQ_DEFAULT_QUEUE", default="") or None

SNITCH_ID = config("SNITCH_ID", default="")


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
    except OSError:
        return "localhost"


HOSTNAME = platform.node()
CLUSTER_NAME = config("CLUSTER_NAME", default="")
K8S_NAMESPACE = config("K8S_NAMESPACE", default="")
K8S_POD_NAME = config("K8S_POD_NAME", default="")

# Data scrubbing before Sentry
# https://github.com/laiyongtao/sentry-processor
SENSITIVE_FIELDS_TO_MASK_ENTIRELY = [
    "amo_id",
    "custom_id",
    "email",
    "first_name",
    "fxa_id",
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

SENTRY_IGNORE_ERRORS = (
    BrokenPipeError,
    ConnectionResetError,
)


def before_send(event, hint):
    if hint and "exc_info" in hint:
        exc_type, exc_value, tb = hint["exc_info"]
        if isinstance(exc_value, SENTRY_IGNORE_ERRORS):
            return None

    processor = DesensitizationProcessor(
        with_default_keys=True,
        sensitive_keys=SENSITIVE_FIELDS_TO_MASK_ENTIRELY,
        # partial_keys=SENSITIVE_FIELDS_TO_MASK_PARTIALLY,
        # mask_position=POSITION.LEFT,  # import from sentry_processor if you need it
        # off_set=3,
    )
    event = processor.process(event, hint)
    return event


if not UNITTEST:
    sentry_sdk.init(
        dsn=config("SENTRY_DSN", default=""),
        release=config("GIT_SHA", default=""),
        server_name=".".join(x for x in [K8S_NAMESPACE, CLUSTER_NAME, HOSTNAME] if x),
        integrations=[DjangoIntegration(signals_spans=False), RedisIntegration(), RqIntegration()],
        before_send=before_send,
    )

STATSD_HOST = config("STATSD_HOST", default=get_default_gateway_linux())
STATSD_PORT = config("STATSD_PORT", parser=int, default="8125")
STATSD_PREFIX = config("STATSD_PREFIX", default=K8S_NAMESPACE)

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

LOG_LEVEL = config(
    "DJANGO_LOG_LEVEL",
    parser=ChoiceOf(
        str,
        ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    ),
    default="WARNING",
)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "root": {
        "level": LOG_LEVEL,
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
EXTRA_SUPPORTED_LANGS = config(
    "EXTRA_SUPPORTED_LANGS",
    parser=ListOf(str, allow_empty=False),
    default="",
)

if UNITTEST:
    TESTING_EMAIL_DOMAINS = []
else:
    TESTING_EMAIL_DOMAINS = config(
        "TESTING_EMAIL_DOMAINS",
        parser=ListOf(str, allow_empty=False),
        default="restmail.net,example.com",
    )

# FIXME: MAINTENANCE_MODE is considered broken and needs to be fixed before use.
MAINTENANCE_MODE = config("MAINTENANCE_MODE", parser=bool, default="false")
QUEUE_BATCH_SIZE = config("QUEUE_BATCH_SIZE", parser=int, default="500")
# can we read user data in maintenance mode
MAINTENANCE_READ_ONLY = config("MAINTENANCE_READ_ONLY", parser=bool, default="false")

USE_SANDBOX_BACKEND = config("USE_SANDBOX_BACKEND", parser=bool, default="false")

FXA_EVENTS_QUEUE_ENABLE = config("FXA_EVENTS_QUEUE_ENABLE", parser=bool, default="false")
FXA_EVENTS_QUEUE_IGNORE_MODE = config("FXA_EVENTS_QUEUE_IGNORE_MODE", parser=bool, default="false")
FXA_EVENTS_ACCESS_KEY_ID = config("FXA_EVENTS_ACCESS_KEY_ID", default="")
FXA_EVENTS_SECRET_ACCESS_KEY = config("FXA_EVENTS_SECRET_ACCESS_KEY", default="")
FXA_EVENTS_QUEUE_REGION = config("FXA_EVENTS_QUEUE_REGION", default="")
FXA_EVENTS_QUEUE_URL = config("FXA_EVENTS_QUEUE_URL", default="")
FXA_EVENTS_QUEUE_WAIT_TIME = config("FXA_EVENTS_QUEUE_WAIT_TIME", parser=int, default="10")
FXA_EVENTS_SNITCH_ID = config("FXA_EVENTS_SNITCH_ID", default="")

# stage or production
# https://github.com/mozilla/PyFxA/blob/main/fxa/constants.py
FXA_OAUTH_SERVER_ENV = config("FXA_OAUTH_SERVER_ENV", default="production")
FXA_CLIENT_ID = config("FXA_CLIENT_ID", default="")
FXA_CLIENT_SECRET = config("FXA_CLIENT_SECRET", default="")
FXA_OAUTH_TOKEN_TTL = config("FXA_OAUTH_TOKEN_TTL", parser=int, default="300")  # 5 minutes

FXA_EMAIL_PREFS_DOMAIN = config("FXA_EMAIL_PREFS_DOMAIN", default="www.mozilla.org")
FXA_REGISTER_NEWSLETTER = config("FXA_REGISTER_NEWSLETTER", default="firefox-accounts-journey")
FXA_REGISTER_SOURCE_URL = config("FXA_REGISTER_SOURCE_URL", default="https://accounts.firefox.com/")
FXA_EMAIL_PREFS_URL = f"https://{FXA_EMAIL_PREFS_DOMAIN}/newsletter/existing"
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

LOGIN_URL = "/admin/"
LOGIN_REDIRECT_URL = "/admin/"

OIDC_ENABLE = config("OIDC_ENABLE", parser=bool, default="false")
if OIDC_ENABLE:
    AUTHENTICATION_BACKENDS = ("basket.base.authentication.OIDCModelBackend",)
    OIDC_OP_AUTHORIZATION_ENDPOINT = config("OIDC_OP_AUTHORIZATION_ENDPOINT", default="")
    OIDC_OP_TOKEN_ENDPOINT = config("OIDC_OP_TOKEN_ENDPOINT", default="")
    OIDC_OP_USER_ENDPOINT = config("OIDC_OP_USER_ENDPOINT", default="")

    OIDC_RP_CLIENT_ID = config("OIDC_RP_CLIENT_ID", default="")
    OIDC_RP_CLIENT_SECRET = config("OIDC_RP_CLIENT_SECRET", default="")
    OIDC_CREATE_USER = config("OIDC_CREATE_USER", parser=bool, default="false")
    OIDC_EXEMPT_URLS = [
        "/",
        "/fxa/",
        "/fxa/callback/",
        re.compile(r"^/news/*"),
        "/subscribe/",
        "/subscribe.json",
        # API
        re.compile(r"^/api/*"),
        # Health checks.
        "/healthz/",
        "/readiness/",
        "/watchman/",
    ]

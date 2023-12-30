import os
import platform
import re
from functools import partialmethod
from pathlib import Path

import markus
import sentry_sdk
from configurations import Configuration, values
from sentry_processor import DesensitizationProcessor
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import ignore_logger
from sentry_sdk.integrations.redis import RedisIntegration
from sentry_sdk.integrations.rq import RqIntegration

# ROOT path of the project. A pathlib.Path object.
ROOT_PATH = Path(__file__).resolve().parents[1]


# Set the default value of `environ_prefix` to `None` so that we can use `environ_name` without a prefix.
values.Value.__init__ = partialmethod(values.Value.__init__, environ_prefix=None)


def path(*args):
    return str(ROOT_PATH.joinpath(*args))


class SentryConfigurationMixin:
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
    SENTRY_IGNORE_ERRORS = (
        BrokenPipeError,
        ConnectionResetError,
    )

    @classmethod
    def before_send(cls, event, hint):
        if hint and "exc_info" in hint:
            exc_type, exc_value, tb = hint["exc_info"]
            if isinstance(exc_value, cls.SENTRY_IGNORE_ERRORS):
                return None

        processor = DesensitizationProcessor(
            with_default_keys=True,
            sensitive_keys=cls.SENSITIVE_FIELDS_TO_MASK_ENTIRELY,
            # partial_keys=cls.SENSITIVE_FIELDS_TO_MASK_PARTIALLY,
            # mask_position=POSITION.LEFT,  # import from sentry_processor if you need it
            # off_set=3,
        )
        event = processor.process(event, hint)
        return event

    @classmethod
    def post_setup(cls):
        """Sentry initialization"""
        super().post_setup()

        # DisallowedHost gets a lot of action thanks to scans/bots/scripts,
        # but we need not take any action because it's already HTTP 400-ed.
        # Note that we ignore at the Sentry client level
        ignore_logger("django.security.DisallowedHost")

        sentry_sdk.init(
            dsn=values.Value("", environ_name="SENTRY_DSN"),
            release=values.Value("", environ_name="GIT_SHA"),
            server_name=".".join(x for x in [cls.K8S_NAMESPACE, cls.CLUSTER_NAME, cls.HOSTNAME] if x),
            integrations=[DjangoIntegration(signals_spans=False), RedisIntegration(), RqIntegration()],
            before_send=cls.before_send,
        )


class Base(Configuration):
    ADMINS = (
        # ('Your Name', 'your_email@domain.com'),
    )
    MANAGERS = ADMINS

    SECRET_KEY = values.SecretValue(environ_name="SECRET_KEY")

    # Default to sqlite for local development.
    DATABASES = values.DatabaseURLValue("sqlite:///basket.db", environ=False)
    DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

    # CACHE_URL and RQ_URL are derived from REDIS_URL.
    REDIS_URL = values.Value(None, environ_name="REDIS_URL")
    if REDIS_URL:
        # Strip the Redis database number from the end of the URL.
        REDIS_URL = REDIS_URL.rstrip("/0")
        REDIS_CACHE_DB = values.IntegerValue(1, environ_name="REDIS_CACHE_DB")
        REDIS_RQ_DB = values.IntegerValue(2, environ_name="REDIS_RQ_DB")
        # Use Redis for cache and rq.
        # Note: We save the URL in the environment so it can be used below.
        os.environ["CACHE_URL"] = f"{REDIS_URL}/{REDIS_CACHE_DB}"
        RQ_URL = f"{REDIS_URL}/{REDIS_RQ_DB}"

    CACHES = values.CacheURLValue("locmem://").value
    CACHES.update(
        {
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
    )
    SITE_URL = values.Value("https://basket.mozilla.org", environ_name="SITE_URL")
    STATIC_ROOT = path("static")
    STATIC_URL = "/static/"

    TIME_ZONE = "UTC"
    USE_TZ = True
    SITE_ID = 1
    USE_I18N = False

    HOSTNAME = platform.node()
    CLUSTER_NAME = values.Value("", environ_name="CLUSTER_NAME")
    K8S_NAMESPACE = values.Value("", environ_name="K8S_NAMESPACE")
    K8S_POD_NAME = values.Value("", environ_name="K8S_POD_NAME")

    INSTALLED_APPS = (
        "basket.base",
        "basket.news",
        "basket.petition",
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
    LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "root": {
            "level": values.Value("WARNING", environ_name="DJANGO_LOG_LEVEL"),
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

    ACOUSTIC_CLIENT_ID = values.Value(None, environ_name="ACOUSTIC_CLIENT_ID")
    ACOUSTIC_CLIENT_SECRET = values.Value(None, environ_name="ACOUSTIC_CLIENT_SECRET")
    ACOUSTIC_REFRESH_TOKEN = values.Value(None, environ_name="ACOUSTIC_REFRESH_TOKEN")
    ACOUSTIC_SERVER_NUMBER = values.Value(None, environ_name="ACOUSTIC_SERVER_NUMBER")
    ACOUSTIC_FXA_TABLE_ID = values.Value(None, environ_name="ACOUSTIC_FXA_TABLE_ID")
    ACOUSTIC_FXA_LOG_ENABLED = values.BooleanValue(False, environ_name="ACOUSTIC_FXA_LOG_ENABLED")

    ACOUSTIC_TX_CLIENT_ID = values.Value(None, environ_name="ACOUSTIC_TX_CLIENT_ID")
    ACOUSTIC_TX_CLIENT_SECRET = values.Value(None, environ_name="ACOUSTIC_TX_CLIENT_SECRET")
    ACOUSTIC_TX_REFRESH_TOKEN = values.Value(None, environ_name="ACOUSTIC_TX_REFRESH_TOKEN")
    ACOUSTIC_TX_SERVER_NUMBER = values.Value(None, environ_name="ACOUSTIC_TX_SERVER_NUMBER")
    # Send confirmation messages via Acoustic Transact
    SEND_CONFIRM_MESSAGES = values.BooleanValue(False, environ_name="SEND_CONFIRM_MESSAGES")

    # Mozilla CTMS
    CTMS_ENV = values.Value("", environ_name="CTMS_ENV").lower()
    CTMS_ENABLED = values.BooleanValue(False, environ_name="CTMS_ENABLED")
    if CTMS_ENV == "stage":
        default_url = "https://ctms.stage.mozilla-ess.mozit.cloud"
    elif CTMS_ENV == "prod":
        default_url = "https://ctms.prod.mozilla-ess.mozit.cloud"
    else:
        default_url = ""
    CTMS_URL = values.Value(default_url, environ_name="CTMS_URL")
    CTMS_CLIENT_ID = values.Value("", environ_name="CTMS_CLIENT_ID")
    CTMS_CLIENT_SECRET = values.Value("", environ_name="CTMS_CLIENT_SECRET")

    CORS_ORIGIN_ALLOW_ALL = True
    CORS_URLS_REGEX = r"^/(news/|subscribe)"

    # Security settings
    USE_X_FORWARDED_HOST = True
    SESSION_COOKIE_SECURE = True
    SESSION_ENGINE = "django.contrib.sessions.backends.cache"
    CSRF_COOKIE_SECURE = True

    RATELIMIT_VIEW = "basket.news.views.ratelimited"

    RQ_RESULT_TTL = values.IntegerValue(0, environ_name="RQ_RESULT_TTL")  # Ignore results.
    RQ_MAX_RETRY_DELAY = values.IntegerValue(34 * 60 * 60, environ_name="RQ_MAX_RETRY_DELAY")  # 34 hours in seconds.
    RQ_MAX_RETRIES = values.IntegerValue(12, environ_name="RQ_MAX_RETRIES")
    RQ_EXCEPTION_HANDLERS = ["basket.base.rq.store_task_exception_handler"]
    RQ_IS_ASYNC = values.BooleanValue(True, environ_name="RQ_IS_ASYNC")

    SNITCH_ID = values.Value(None, environ_name="SNITCH_ID")

    TESTING_EMAIL_DOMAINS = values.ListValue(
        ["restmail.net", "restmail.lcip.org", "example.com"],
        environ_name="TESTING_EMAIL_DOMAINS",
    )

    # language codes we support and send to backend regardless if they exist in the DB
    EXTRA_SUPPORTED_LANGS = values.ListValue([], environ_name="EXTRA_SUPPORTED_LANGS")

    PROD_DETAILS_CACHE_NAME = "product_details"
    PROD_DETAILS_CACHE_TIMEOUT = None

    MAINTENANCE_MODE = values.BooleanValue(False, environ_name="MAINTENANCE_MODE")
    QUEUE_BATCH_SIZE = values.IntegerValue(500, environ_name="QUEUE_BATCH_SIZE")
    # can we read user data in maintenance mode
    MAINTENANCE_READ_ONLY = values.BooleanValue(False, environ_name="MAINTENANCE_READ_ONLY")
    USE_SANDBOX_BACKEND = values.BooleanValue(False, environ_name="USE_SANDBOX_BACKEND")

    FXA_EVENTS_QUEUE_ENABLE = values.BooleanValue(False, environ_name="FXA_EVENTS_QUEUE_ENABLE")
    FXA_EVENTS_QUEUE_IGNORE_MODE = values.BooleanValue(False, environ_name="FXA_EVENTS_QUEUE_IGNORE_MODE")
    FXA_EVENTS_ACCESS_KEY_ID = values.Value("", environ_name="FXA_EVENTS_ACCESS_KEY_ID")
    FXA_EVENTS_SECRET_ACCESS_KEY = values.Value("", environ_name="FXA_EVENTS_SECRET_ACCESS_KEY")
    FXA_EVENTS_QUEUE_REGION = values.Value("", environ_name="FXA_EVENTS_QUEUE_REGION")
    FXA_EVENTS_QUEUE_URL = values.Value("", environ_name="FXA_EVENTS_QUEUE_URL")
    FXA_EVENTS_QUEUE_WAIT_TIME = values.IntegerValue(10, environ_name="FXA_EVENTS_QUEUE_WAIT_TIME")
    FXA_EVENTS_SNITCH_ID = values.Value("", environ_name="FXA_EVENTS_SNITCH_ID")

    # stable, stage, or production
    # https://github.com/mozilla/PyFxA/blob/master/fxa/constants.py
    FXA_OAUTH_SERVER_ENV = values.Value("stable", environ_name="FXA_OAUTH_SERVER_ENV")
    FXA_CLIENT_ID = values.Value("", environ_name="FXA_CLIENT_ID")
    FXA_CLIENT_SECRET = values.Value("", environ_name="FXA_CLIENT_SECRET")
    FXA_OAUTH_TOKEN_TTL = values.IntegerValue(300, environ_name="FXA_OAUTH_TOKEN_TTL")  # 5 minutes

    FXA_EMAIL_PREFS_DOMAIN = values.Value("www.mozilla.org", environ_name="FXA_EMAIL_PREFS_DOMAIN")
    FXA_REGISTER_NEWSLETTER = values.Value("firefox-accounts-journey", environ_name="FXA_REGISTER_NEWSLETTER")
    FXA_REGISTER_SOURCE_URL = values.Value("https://accounts.firefox.com/", environ_name="FXA_REGISTER_SOURCE_URL")
    # TODO move this to the DB
    FXA_LOGIN_CAMPAIGNS = {
        "fxa-embedded-form-moz": "mozilla-welcome",
        "fxa-embedded-form-fx": "firefox-welcome",
        "membership-idealo": "member-idealo",
        "membership-comm": "member-comm",
        "membership-tech": "member-tech",
        "membership-tk": "member-tk",
    }
    COMMON_VOICE_NEWSLETTER = values.Value("common-voice", environ_name="COMMON_VOICE_NEWSLETTER")

    OIDC_ENABLE = values.BooleanValue(False, environ_name="OIDC_ENABLE")
    if OIDC_ENABLE:
        AUTHENTICATION_BACKENDS = ("basket.base.authentication.OIDCModelBackend",)
        OIDC_OP_AUTHORIZATION_ENDPOINT = values.Value("", environ_name="OIDC_OP_AUTHORIZATION_ENDPOINT")
        OIDC_OP_TOKEN_ENDPOINT = values.Value("", environ_name="OIDC_OP_TOKEN_ENDPOINT")
        OIDC_OP_USER_ENDPOINT = values.Value("", environ_name="OIDC_OP_USER_ENDPOINT")

        OIDC_RP_CLIENT_ID = values.Value("", environ_name="OIDC_RP_CLIENT_ID")
        OIDC_RP_CLIENT_SECRET = values.Value("", environ_name="OIDC_RP_CLIENT_SECRET")
        OIDC_CREATE_USER = values.BooleanValue(False, environ_name="OIDC_CREATE_USER")
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

    PETITION_CORS_URL = values.Value("https://open.mozilla.org", environ_name="PETITION_CORS_URL")
    PETITION_LETTER_URL = values.Value("https://open.mozilla.org/letter", environ_name="PETITION_LETTER_URL")
    PETITION_THANKS_URL = values.Value("https://open.mozilla.org/letter/thanks", environ_name="PETITION_THANKS_URL")
    PETITION_BUILD_HOOK_URL = values.Value("", environ_name="PETITION_BUILD_HOOK_URL")


class Local(Base):
    DEBUG = values.BooleanValue(True)
    TEMPLATE_DEBUG = DEBUG
    MARKUS_BACKENDS = [
        {"class": "markus.backends.logging.LoggingMetrics", "options": {"logger_name": "metrics"}},
    ]
    markus.configure(backends=MARKUS_BACKENDS)


class Testing(Local):
    DATABASES = values.DatabaseURLValue("mysql://root@db/basket", environ=False)
    RQ_IS_ASYNC = False
    RQ_MAX_RETRIES = 0
    TESTING_EMAIL_DOMAINS = []


class Production(Base, SentryConfigurationMixin):
    DEBUG = False
    TEMPLATE_DEBUG = DEBUG

    DATABASES = values.DatabaseURLValue().value
    if DATABASES["default"]["ENGINE"] == "django.db.backends.mysql":
        DATABASES["default"]["OPTIONS"] = {
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        }

    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = values.Value("localhost", environ_name="EMAIL_HOST")
    EMAIL_PORT = values.IntegerValue(25, environ_name="EMAIL_PORT")
    EMAIL_HOST_USER = values.Value("", environ_name="EMAIL_HOST_USER")
    EMAIL_HOST_PASSWORD = values.Value("", environ_name="EMAIL_HOST_PASSWORD")
    EMAIL_USE_TLS = values.BooleanValue(False, environ_name="EMAIL_USE_TLS")
    EMAIL_SUBJECT_PREFIX = values.Value("[basket] ", environ_name="EMAIL_SUBJECT_PREFIX")

    ALLOWED_HOSTS = values.ListValue(
        [".allizom.org", ".moz.works", "basket.mozmar.org", "basket.mozilla.com", "basket.mozilla.org"],
        environ_name="ALLOWED_HOSTS",
    )
    ALLOWED_CIDR_NETS = values.ListValue([], environ_name="ALLOWED_CIDR_NETS")
    STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

    # Security middleware settings
    SECURE_HSTS_SECONDS = 0
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_SSL_REDIRECT = values.BooleanValue(False, environ_name="SECURE_SSL_REDIRECT")
    SECURE_REDIRECT_EXEMPT = [
        r"^healthz/$",
        r"^readiness/$",
    ]
    if SECURE_SSL_REDIRECT:
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

    WATCHMAN_DISABLE_APM = True
    WATCHMAN_CHECKS = (
        "watchman.checks.caches",
        "watchman.checks.databases",
    )

    STATSD_HOST = values.Value("localhost", environ_name="STATSD_HOST")
    STATSD_PORT = values.IntegerValue(8125, environ_name="STATSD_PORT")
    STATSD_PREFIX = values.Value(Base.K8S_NAMESPACE, environ_name="STATSD_PREFIX")

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

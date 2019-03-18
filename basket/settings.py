import os
import platform
import socket
import struct
import sys
from datetime import timedelta

import dj_database_url
import django_cache_url
from decouple import config, Csv, UndefinedValueError
from pathlib2 import Path

# Application version.
VERSION = (0, 1)

# ROOT path of the project. A pathlib.Path object.
ROOT_PATH = Path(__file__).resolve().parents[1]
ROOT = str(ROOT_PATH)


def path(*args):
    return str(ROOT_PATH.joinpath(*args))


DEBUG = config('DEBUG', default=False, cast=bool)

ADMINS = (
    # ('Your Name', 'your_email@domain.com'),
)

MANAGERS = ADMINS
# avoids a warning from django
TEST_RUNNER = 'django.test.runner.DiscoverRunner'

# DB read-only, API can still read-write to Salesforce
READ_ONLY_MODE = config('READ_ONLY_MODE', False, cast=bool)
# Disables the API and changes redirects
ADMIN_ONLY_MODE = config('ADMIN_ONLY_MODE', False, cast=bool)

REDIS_URL = config('REDIS_URL', None)
if REDIS_URL:
    REDIS_URL = REDIS_URL.rstrip('/0')
    # use redis for celery and cache
    os.environ['BROKER_URL'] = REDIS_URL + '/' + config('REDIS_CELERY_DB', '0')
    os.environ['CACHE_URL'] = REDIS_URL + '/' + config('REDIS_CACHE_DB', '1')

# Production uses MySQL, but Sqlite should be sufficient for local development.
# Our CI server tests against MySQL. See travis.py in this directory
# for an example if you'd like to run MySQL locally, and add that to your
# local.py.
DATABASES = {
    'default': config('DATABASE_URL',
                      default='sqlite:///basket.db',
                      cast=dj_database_url.parse),
}
if DATABASES['default']['ENGINE'] == 'django.db.backends.mysql':
    DATABASES['default']['OPTIONS'] = {'init_command': 'SET storage_engine=InnoDB'}

CACHES = {
    'default': config('CACHE_URL',
                      default='locmem://',
                      cast=django_cache_url.parse),
    'bad_message_ids': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'TIMEOUT': 12 * 60 * 60,  # 12 hours
    },
    'email_block_list': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'TIMEOUT': 60 * 60,  # 1 hour
    },
    'product_details': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    },
}

if CACHES['default']['BACKEND'].startswith('django_redis'):
    options = CACHES['default'].setdefault('OPTIONS', {})
    options['PARSER_CLASS'] = 'redis.connection.HiredisParser'

default_email_backend = ('django.core.mail.backends.console.EmailBackend' if DEBUG else
                         'django.core.mail.backends.smtp.EmailBackend')
EMAIL_BACKEND = config('EMAIL_BACKEND', default=default_email_backend)
EMAIL_HOST = config('EMAIL_HOST', default='localhost')
EMAIL_PORT = config('EMAIL_PORT', default=25, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=False, cast=bool)
EMAIL_SUBJECT_PREFIX = config('EMAIL_SUBJECT_PREFIX', default='[basket] ')
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')

ALLOWED_HOSTS = config('ALLOWED_HOSTS',
                       default='.allizom.org, .moz.works, basket.mozmar.org, '
                               'basket.mozilla.com, basket.mozilla.org',
                       cast=Csv())
ALLOWED_CIDR_NETS = config('ALLOWED_CIDR_NETS', default='', cast=Csv())
ENFORCE_HOSTNAME = config('ENFORCE_HOSTNAME', default='', cast=Csv())
USE_X_FORWARDED_HOST = True

SESSION_COOKIE_SECURE = config('SESSION_COOKIE_SECURE', not DEBUG, cast=bool)
CSRF_COOKIE_SECURE = config('CSRF_COOKIE_SECURE', not DEBUG, cast=bool)
DISABLE_ADMIN = config('DISABLE_ADMIN', READ_ONLY_MODE, cast=bool)
STORE_TASK_FAILURES = config('STORE_TASK_FAILURES', not READ_ONLY_MODE, cast=bool)
# if DISABLE_ADMIN is True redirect /admin/ to this URL
ADMIN_REDIRECT_URL = config('ADMIN_REDIRECT_URL',
                            'https://admin.basket.moz.works/admin/')

TIME_ZONE = 'America/Los_Angeles'
USE_TZ = True
SITE_ID = 1
USE_I18N = False

STATIC_ROOT = path('static')
STATIC_URL = '/static/'
if not DEBUG:
    STATICFILES_STORAGE = 'whitenoise.django.GzipManifestStaticFilesStorage'

try:
    # Make this unique, and don't share it with anybody.
    SECRET_KEY = config('SECRET_KEY')
except UndefinedValueError:
    raise UndefinedValueError('The SECRET_KEY environment varialbe is required. '
                              'Move env-dist to .env if you want the defaults.')

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': ['templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.contrib.auth.context_processors.auth',
                'django.template.context_processors.request',
                'django.contrib.messages.context_processors.messages',
                'basket.news.context_processors.settings',
            ],
        },
    },
]

MIDDLEWARE = (
    'allow_cidr.middleware.AllowCIDRMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'basket.news.middleware.EnforceHostnameMiddleware',
    'basket.news.middleware.HostnameMiddleware',
    'django.middleware.common.CommonMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'basket.news.middleware.GraphiteViewHitCountMiddleware',
    'django_statsd.middleware.GraphiteRequestTimingMiddleware',
    'django_statsd.middleware.GraphiteMiddleware',
    'ratelimit.middleware.RatelimitMiddleware',
)

ROOT_URLCONF = 'basket.urls'

INSTALLED_APPS = (
    'basket.news',
    'basket.base',

    'corsheaders',
    'product_details',
    'raven.contrib.django.raven_compat',
    'django_extensions',
    'mozilla_django_oidc',
    'watchman',

    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.sites',
    'django.contrib.messages',
    'django.contrib.admin',
    'django.contrib.staticfiles',
)

# SecurityMiddleware settings
SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default='0', cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_BROWSER_XSS_FILTER = config('SECURE_BROWSER_XSS_FILTER', default=True, cast=bool)
SECURE_CONTENT_TYPE_NOSNIFF = config('SECURE_CONTENT_TYPE_NOSNIFF', default=True, cast=bool)
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=False, cast=bool)
SECURE_REDIRECT_EXEMPT = [
    r'^healthz/$',
    r'^readiness/$',
]
if config('USE_SECURE_PROXY_HEADER', default=SECURE_SSL_REDIRECT, cast=bool):
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# watchman
WATCHMAN_DISABLE_APM = True
WATCHMAN_CHECKS = (
    'watchman.checks.caches',
    'watchman.checks.databases',
)

# legacy name
EXACTTARGET_USE_SANDBOX = config('EXACTTARGET_USE_SANDBOX', False, cast=bool)
USE_SANDBOX_BACKEND = config('USE_SANDBOX_BACKEND', EXACTTARGET_USE_SANDBOX, cast=bool)
ET_CLIENT_ID = config('ET_CLIENT_ID', None)
ET_CLIENT_SECRET = config('ET_CLIENT_SECRET', None)

if USE_SANDBOX_BACKEND:
    auth_url = 'https://auth-test.exacttargetapis.com/v1/requestToken?legacy=1'
    wsdl_loc = 'etframework.test.wsdl'
else:
    auth_url = 'https://auth.exacttargetapis.com/v1/requestToken?legacy=1'
    wsdl_loc = 'etframework.wsdl'

SFMC_DEBUG = config('SFMC_DEBUG', DEBUG, cast=bool)
SFMC_SETTINGS = {
    'authenticationurl': auth_url,
    'wsdl_file_local_loc': path('basket', 'news', 'backends', wsdl_loc),
}
if ET_CLIENT_ID and ET_CLIENT_SECRET:
    SFMC_SETTINGS['clientid'] = ET_CLIENT_ID
    SFMC_SETTINGS['clientsecret'] = ET_CLIENT_SECRET

# Salesforce.com
SFDC_SETTINGS = {
    'username': config('SFDC_USERNAME', None),
    'password': config('SFDC_PASSWORD', None),
    'security_token': config('SFDC_SEC_TOKEN', None),
    'sandbox': config('SFDC_USE_SANDBOX', USE_SANDBOX_BACKEND, cast=bool),
}
# default SFDC sessions timeout after 2 hours of inactivity. so they never timeout on
# prod. Let's make it every 4 hours by default.
SFDC_SESSION_TIMEOUT = config('SFDC_SESSION_TIMEOUT', 60 * 60 * 4, cast=int)
SFDC_REQUEST_TIMEOUT = config('SFDC_REQUEST_TIMEOUT', 10, cast=int)


CORS_ORIGIN_ALLOW_ALL = True
CORS_URLS_REGEX = r'^/(news/|subscribe)'

# view rate limiting
RATELIMIT_VIEW = 'basket.news.views.ratelimited'

CELERY_ALWAYS_EAGER = config('CELERY_ALWAYS_EAGER', DEBUG, cast=bool)
BROKER_URL = config('BROKER_URL', None)
CELERY_REDIS_MAX_CONNECTIONS = config('CELERY_REDIS_MAX_CONNECTIONS', 2, cast=int)
CELERY_DISABLE_RATE_LIMITS = True
CELERY_IGNORE_RESULT = True
CELERYD_PREFETCH_MULTIPLIER = config('CELERYD_PREFETCH_MULTIPLIER', 1, cast=int)
CELERY_MESSAGE_COMPRESSION = 'gzip'
CELERY_ROUTES = {
    'basket.news.tasks.snitch': {'queue': 'snitch'},
}

SNITCH_ID = config('SNITCH_ID', None)

CELERYBEAT_SCHEDULE = {}

if SNITCH_ID:
    CELERYBEAT_SCHEDULE['snitch'] = {
        'task': 'basket.news.tasks.snitch',
        'schedule': timedelta(minutes=5),
    }


# via http://stackoverflow.com/a/6556951/107114
def get_default_gateway_linux():
    """Read the default gateway directly from /proc."""
    try:
        with open("/proc/net/route") as fh:
            for line in fh:
                fields = line.strip().split()
                if fields[1] != '00000000' or not int(fields[3], 16) & 2:
                    continue

                return socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))
    except IOError:
        return 'localhost'


HOSTNAME = platform.node()
DEIS_APP = config('DEIS_APP', default=None)
DEIS_DOMAIN = config('DEIS_DOMAIN', default=None)
DEIS_RELEASE = config('DEIS_RELEASE', default=None)

RAVEN_CONFIG = {
    'dsn': config('SENTRY_DSN', None),
    'site': '.'.join(x for x in [DEIS_APP, DEIS_DOMAIN] if x),
    'release': config('GIT_SHA', None),
}

STATSD_HOST = config('STATSD_HOST', get_default_gateway_linux())
STATSD_PORT = config('STATSD_PORT', 8125, cast=int)
STATSD_PREFIX = config('STATSD_PREFIX', DEIS_APP)
STATSD_CLIENT = config('STATSD_CLIENT', 'django_statsd.clients.null')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'root': {
        'level': config('DJANGO_LOG_LEVEL', default='WARNING'),
        'handlers': ['console'],
    },
    'formatters': {
        'verbose': {
            'format': '%(levelname)s %(asctime)s %(module)s %(message)s'
        },
    },
    'handlers': {
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose'
        }
    },
    'loggers': {
        'django.db.backends': {
            'level': 'ERROR',
            'handlers': ['console'],
            'propagate': False,
        },
    },
}

PROD_DETAILS_CACHE_NAME = 'product_details'
PROD_DETAILS_CACHE_TIMEOUT = None

RECOVER_MSG_LANGS = config('RECOVER_MSG_LANGS', 'en', cast=Csv())
# language codes that we support and send through to SFDC
# regardless of their existence in the DB
EXTRA_SUPPORTED_LANGS = config('EXTRA_SUPPORTED_LANGS', '', cast=Csv())

SYNC_KEY = config('SYNC_KEY', None)
TESTING_EMAIL_DOMAINS = config('TESTING_EMAIL_DOMAINS',
                               'restmail.net,restmail.lcip.org,example.com',
                               cast=Csv())

MAINTENANCE_MODE = config('MAINTENANCE_MODE', False, cast=bool)
QUEUE_BATCH_SIZE = config('QUEUE_BATCH_SIZE', 500, cast=int)
# can we read user data in maintenance mode
MAINTENANCE_READ_ONLY = config('MAINTENANCE_READ_ONLY', False, cast=bool)

TASK_LOCK_TIMEOUT = config('TASK_LOCK_TIMEOUT', 60, cast=int)
TASK_LOCKING_ENABLE = config('TASK_LOCKING_ENABLE', False, cast=bool)

DONATE_ACCESS_KEY_ID = config('DONATE_ACCESS_KEY_ID', default='')
DONATE_SECRET_ACCESS_KEY = config('DONATE_SECRET_ACCESS_KEY', default='')
DONATE_QUEUE_REGION = config('DONATE_QUEUE_REGION', default='')
DONATE_QUEUE_URL = config('DONATE_QUEUE_URL', default='')
DONATE_QUEUE_WAIT_TIME = config('DONATE_QUEUE_WAIT_TIME', cast=int, default=10)
# turn this on to consume the queue but ignore the messages
# needed so that donate.m.o can run continuous tests w/o filling the SFDC sandbox
DONATE_QUEUE_IGNORE_MODE = config('DONATE_QUEUE_IGNORE_MODE', cast=bool, default=False)
DONATE_OPP_RECORD_TYPE = config('DONATE_OPP_RECORD_TYPE', default='')
DONATE_CONTACT_RECORD_TYPE = config('DONATE_CONTACT_RECORD_TYPE', default='')
DONATE_SNITCH_ID = config('DONATE_SNITCH_ID', default='')
DONATE_NOTIFY_EMAIL = config('DONATE_NOTIFY_EMAIL', default='')
DONATE_UPDATE_FAIL_DE = config('DONATE_UPDATE_FAIL_DE', default='Donation_Diff')

FXA_EVENTS_QUEUE_ENABLE = config('FXA_EVENTS_QUEUE_ENABLE', cast=bool, default=False)
FXA_EVENTS_ACCESS_KEY_ID = config('FXA_EVENTS_ACCESS_KEY_ID', default='')
FXA_EVENTS_SECRET_ACCESS_KEY = config('FXA_EVENTS_SECRET_ACCESS_KEY', default='')
FXA_EVENTS_QUEUE_REGION = config('FXA_EVENTS_QUEUE_REGION', default='')
FXA_EVENTS_QUEUE_URL = config('FXA_EVENTS_QUEUE_URL', default='')
FXA_EVENTS_QUEUE_WAIT_TIME = config('FXA_EVENTS_QUEUE_WAIT_TIME', cast=int, default=10)
FXA_EVENTS_SNITCH_ID = config('FXA_EVENTS_SNITCH_ID', default='')

FXA_ACCESS_KEY_ID = config('FXA_ACCESS_KEY_ID', default='')
FXA_SECRET_ACCESS_KEY = config('FXA_SECRET_ACCESS_KEY', default='')
FXA_S3_BUCKET = config('FXA_S3_BUCKET', default='')
FXA_SFMC_DE = config('FXA_SFMC_DE', default='FXA_Logins')
FXA_SNITCH_URL = config('FXA_SNITCH_URL', default='')
# stable, stage, or production
# https://github.com/mozilla/PyFxA/blob/master/fxa/constants.py
FXA_OAUTH_SERVER_ENV = config('FXA_OAUTH_SERVER_ENV', default='stable')

FXA_REGISTER_NEWSLETTER = config('FXA_REGISTER_NEWSLETTER', default='firefox-accounts-journey')
FXA_REGISTER_SOURCE_URL = config('FXA_REGISTER_SOURCE_URL', default='https://accounts.firefox.com/')
# TODO move this to the DB
FXA_LOGIN_CAMPAIGNS = {
    'fxa-embedded-form-moz': 'mozilla-welcome',
    'fxa-embedded-form-fx': 'firefox-welcome',
    'membership-idealo': 'member-idealo',
    'membership-comm': 'member-comm',
    'membership-tech': 'member-tech',
    'membership-tk': 'member-tk',
}

OIDC_ENABLE = config('OIDC_ENABLE', default=False, cast=bool)
if OIDC_ENABLE:
    AUTHENTICATION_BACKENDS = (
        'basket.base.authentication.OIDCModelBackend',
    )
    OIDC_OP_AUTHORIZATION_ENDPOINT = config('OIDC_OP_AUTHORIZATION_ENDPOINT')
    OIDC_OP_TOKEN_ENDPOINT = config('OIDC_OP_TOKEN_ENDPOINT')
    OIDC_OP_USER_ENDPOINT = config('OIDC_OP_USER_ENDPOINT')

    OIDC_RP_CLIENT_ID = config('OIDC_RP_CLIENT_ID')
    OIDC_RP_CLIENT_SECRET = config('OIDC_RP_CLIENT_SECRET')
    OIDC_CREATE_USER = config('OIDC_CREATE_USER', default=False, cast=bool)
    MIDDLEWARE = MIDDLEWARE + \
        ('mozilla_django_oidc.middleware.RefreshIDToken',)
    LOGIN_REDIRECT_URL = '/admin/'

if sys.argv[0].endswith('py.test') or (len(sys.argv) > 1 and sys.argv[1] == 'test'):
    # stuff that's absolutely required for a test run
    CELERY_ALWAYS_EAGER = True
    SFDC_SETTINGS.pop('username', None)
    SFDC_SETTINGS.pop('password', None)
    SFMC_SETTINGS.pop('clientid', None)
    SFMC_SETTINGS.pop('clientsecret', None)
    TESTING_EMAIL_DOMAINS = []

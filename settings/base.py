from os.path import abspath

import dj_database_url
import django_cache_url
from decouple import config, Csv
from pathlib import Path

# Application version.
VERSION = (0, 1)

# ROOT path of the project. A pathlib.Path object.
ROOT_PATH = Path(__file__).resolve().parents[1]
ROOT = str(ROOT_PATH)


def path(*args):
    return abspath(str(ROOT_PATH.joinpath(*args)))


DEBUG = config('DEBUG', default=False, cast=bool)
TEMPLATE_DEBUG = DEBUG

ADMINS = (
    # ('Your Name', 'your_email@domain.com'),
)

MANAGERS = ADMINS
# avoids a warning from django
TEST_RUNNER = 'django.test.runner.DiscoverRunner'

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
                      cast=django_cache_url.parse)
}

ALLOWED_HOSTS = config('ALLOWED_HOSTS',
                       default='.allizom.org, basket.mozilla.com, basket.mozilla.org',
                       cast=Csv())
SESSION_COOKIE_SECURE = config('SESSION_COOKIE_SECURE', True, cast=bool)
CSRF_COOKIE_SECURE = config('CSRF_COOKIE_SECURE', True, cast=bool)

TIME_ZONE = 'America/Los_Angeles'
USE_TZ = True
SITE_ID = 1
USE_I18N = False

STATIC_ROOT = path('static')
STATIC_URL = '/static/'

# Make this unique, and don't share it with anybody.
SECRET_KEY = config('SECRET_KEY')

# List of callables that know how to import templates from various sources.
TEMPLATE_LOADERS = (
    'django.template.loaders.filesystem.Loader',
    'django.template.loaders.app_directories.Loader',
)

TEMPLATE_CONTEXT_PROCESSORS = (
    'django.contrib.auth.context_processors.auth',
    'django.core.context_processors.request',
    'django.contrib.messages.context_processors.messages',
    'csrf_context.csrf',
)

MIDDLEWARE_CLASSES = (
    'sslifyadmin.middleware.SSLifyAdminMiddleware',
    'django.middleware.common.CommonMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'news.middleware.GraphiteViewHitCountMiddleware',
    'django_statsd.middleware.GraphiteMiddleware',
    'ratelimit.middleware.RatelimitMiddleware',
)

ROOT_URLCONF = 'urls'

TEMPLATE_DIRS = (
    path('templates'),
)

INSTALLED_APPS = (
    'news',

    'corsheaders',
    'djcelery',
    'raven.contrib.django.raven_compat',
    'product_details',

    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.sites',
    'django.contrib.messages',
    'django.contrib.admin',
    'django.contrib.staticfiles',
)

# Default newsletter welcome message ID for HTML format.
# There must also exist a text-format message with the same
# ID with "_T" appended, e.g. "39_T"
DEFAULT_WELCOME_MESSAGE_ID = '39'

# Name of the database where we put someone's token when they confirm
EXACTTARGET_CONFIRMATION = config('EXACTTARGET_CONFIRMATION', None)
EXACTTARGET_INTERESTS = config('EXACTTARGET_INTERESTS', None)
EXACTTARGET_USE_SANDBOX = config('EXACTTARGET_USE_SANDBOX', False, cast=bool)
EXACTTARGET_USER = config('EXACTTARGET_USER', None)
EXACTTARGET_PASS = config('EXACTTARGET_PASS', None)
EXACTTARGET_DATA = config('EXACTTARGET_DATA', None)
EXACTTARGET_OPTIN_STAGE = config('EXACTTARGET_OPTIN_STAGE', None)
SUPERTOKEN = config('SUPERTOKEN')
ET_CLIENT_ID = config('ET_CLIENT_ID', None)
ET_CLIENT_SECRET = config('ET_CLIENT_SECRET', None)

CORS_ORIGIN_ALLOW_ALL = True
CORS_URLS_REGEX = r'^/news/.*$'

# view rate limiting
RATELIMIT_VIEW = 'news.views.ratelimited'

# Uncomment these to use Celery, use eager for local dev
CELERY_ALWAYS_EAGER = config('CELERY_ALWAYS_EAGER', DEBUG, cast=bool)
BROKER_HOST = config('BROKER_HOST', 'localhost')
BROKER_PORT = config('BROKER_PORT', 5672, cast=int)
BROKER_USER = config('BROKER_USER', 'basket')
BROKER_PASSWORD = config('BROKER_PASSWORD', 'basket')
BROKER_VHOST = config('BROKER_VHOST', 'basket')
CELERY_DISABLE_RATE_LIMITS = True
CELERY_IGNORE_RESULT = True

STATSD_HOST = config('STATSD_HOST', 'localhost')
STATSD_PORT = config('STATSD_PORT', 8125, cast=int)
STATSD_PREFIX = config('STATSD_PREFIX', None)

import djcelery  # noqa
djcelery.setup_loader()

LOGGING = {
    'version': 1,
    'disable_existing_loggers': True,
    'root': {
        'level': 'WARNING',
        'handlers': ['sentry'],
    },
    'formatters': {
        'verbose': {
            'format': '%(levelname)s %(asctime)s %(module)s %(message)s'
        },
    },
    'handlers': {
        'sentry': {
            'level': 'ERROR',
            'class': 'raven.contrib.django.raven_compat.handlers.SentryHandler',
        },
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
        'raven': {
            'level': 'WARNING',
            'handlers': ['console'],
            'propagate': False,
        },
        'sentry.errors': {
            'level': 'WARNING',
            'handlers': ['console'],
            'propagate': False,
        },
    },
}

# Tells the product_details module where to find our local JSON files.
# This ultimately controls how LANGUAGES are constructed.
PROD_DETAILS_DIR = path('libs/product_details_json')

import os

# Application version.
VERSION = (0, 1)

# Make filepaths relative to settings.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def path(*args):
    # makes flake8 happier than a lambda
    return os.path.join(ROOT, *args)


DEBUG = True
TEMPLATE_DEBUG = DEBUG

ADMINS = (
    # ('Your Name', 'your_email@domain.com'),
)

MANAGERS = ADMINS

# Production uses MySQL, but Sqlite should be sufficient for local development.
# Our CI server tests against MySQL. See travis.py in this directory
# for an example if you'd like to run MySQL locally, and add that to your
# local.py.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': 'basket.db',
    }
}

ALLOWED_HOSTS = [
    '.allizom.org',
    'basket.mozilla.com',
    'basket.mozilla.org',
]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

TIME_ZONE = 'America/Los_Angeles'
USE_TZ = True
SITE_ID = 1
USE_I18N = False

STATIC_ROOT = path('static')
STATIC_URL = '/static/'

# Make this unique, and don't share it with anybody.
SECRET_KEY = '0D8AE44F-5714-40EF-9AC8-4AC6EB556161'

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
EXACTTARGET_CONFIRMATION = 'Confirmation'
EXACTTARGET_INTERESTS = 'GET_INVOLVED'
EXACTTARGET_USE_SANDBOX = False

# This is a token that bypasses the news app auth in certain ways to
# make debugging easier
# SUPERTOKEN = <token>

CORS_ORIGIN_ALLOW_ALL = True
CORS_URLS_REGEX = r'^/news/.*$'

# view rate limiting
RATELIMIT_VIEW = 'news.views.ratelimited'

# Uncomment these to use Celery, use eager for local dev
CELERY_ALWAYS_EAGER = False
BROKER_HOST = 'localhost'
BROKER_PORT = 5672
BROKER_USER = 'basket'
BROKER_PASSWORD = 'basket'
BROKER_VHOST = 'basket'
CELERY_DISABLE_RATE_LIMITS = True
CELERY_IGNORE_RESULT = True

import djcelery  # noqa
djcelery.setup_loader()

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    },
}

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

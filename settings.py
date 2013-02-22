import os
import logging

# Application version.
VERSION = (0, 1)

# Make filepaths relative to settings.
ROOT = os.path.dirname(os.path.abspath(__file__))
path = lambda *a: os.path.join(ROOT, *a)

DEBUG = True
TEMPLATE_DEBUG = DEBUG

ADMINS = (
    # ('Your Name', 'your_email@domain.com'),
)

MANAGERS = ADMINS

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',  # Add 'postgresql_psycopg2', 'postgresql', 'mysql', 'sqlite3' or 'oracle'.
        'NAME': '',                      # Or path to database file if using sqlite3.
        'USER': '',                      # Not used with sqlite3.
        'PASSWORD': '',                  # Not used with sqlite3.
        'HOST': '',                      # Set to empty string for localhost. Not used with sqlite3.
        'PORT': '',                      # Set to empty string for default. Not used with sqlite3.
        'OPTIONS':  {'init_command': 'SET storage_engine=InnoDB'},
    }
}

ALLOWED_HOSTS = [
    '.allizom.org',
    'basket.mozilla.com',
    'basket.mozilla.org',
]

TIME_ZONE = 'America/Chicago'
LANGUAGE_CODE = 'en-us'
SITE_ID = 1
USE_I18N = True

MEDIA_ROOT = path('media')
MEDIA_URL = '/media/'
ADMIN_MEDIA_PREFIX = '/admin-media/'

# Make this unique, and don't share it with anybody.
SECRET_KEY = '0D8AE44F-5714-40EF-9AC8-4AC6EB556161'

# List of callables that know how to import templates from various sources.
TEMPLATE_LOADERS = (
    'django.template.loaders.filesystem.Loader',
    'django.template.loaders.app_directories.Loader',
)

TEMPLATE_CONTEXT_PROCESSORS = (
    'django.core.context_processors.auth',
    'django.core.context_processors.request',
    'csrf_context.csrf',
)

MIDDLEWARE_CLASSES = (
    'django.middleware.common.CommonMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
)

ROOT_URLCONF = 'basket.urls'

TEMPLATE_DIRS = (
    path('templates'),
)

INSTALLED_APPS = (
    'basketauth',
    'emailer',
    'nagios',
    'subscriptions',
    'vars',
    'news',

    'fixture_magic',
    'piston',
    'tower',
    'djcelery',
    'django_nose',

    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.sites',
    #'django.contrib.messages',
    'django.contrib.admin',
)

# This is broken for now
# TODO: Fix this
#TEST_RUNNER = 'test_utils.runner.RadicalTestSuiteRunner'

LANGUAGES = (
    'af','ak','ast-ES','ar','as','be','bg','bn-BD','bn-IN','br-FR',
    'ca','ca-valencia','cs','cy','da','de','de-AT','de-CH','de-DE',
    'dsb','el','en-AU','en-CA','en-GB','en-NZ','en-US','en-ZA','eo',
    'es','es-AR','es-CL','es-ES','es-MX','et','eu','fa','fi','fj-FJ',
    'fr','fur-IT','fy-NL','ga','ga-IE','gl','gu-IN','he','hi','hi-IN',
    'hr','hsb','hu','hy-AM','id','is','it','ja','ja-jp','ja-JP-mac','ka','kk',
    'kn','ko','ku','la','lt','lv','mg','mi','mk','ml','mn','mr','nb-NO',
    'ne-NP','nn-NO','nl','nr','nso','oc','or','pa-IN','pl','pt-BR','pt-PT',
    'ro','rm','ru','rw','si','sk','sl','sq','sr','sr-Latn','ss','st',
    'sv-SE','ta','ta-IN','ta-LK','te','th','tn','tr','ts','tt-RU','uk','ur',
    've','vi','wo','xh','zh-CN','zh-TW','zu',)
LANGUAGES_LOWERED = [x.lower() for x in LANGUAGES]

DEFAULT_FROM_EMAIL = 'basket@mozilla.com'
DEFAULT_FROM_NAME = 'Mozilla'

# Logging
LOG_LEVEL = logging.INFO
HAS_SYSLOG = True  # syslog is used if HAS_SYSLOG and NOT DEBUG.
SYSLOG_TAG = "http_app_basket"
# See PEP 391 and log_settings.py for formatting help.  Each section of LOGGING
# will get merged into the corresponding section of log_settings.py.
# Handlers and log levels are set up automatically based on LOG_LEVEL and DEBUG
# unless you set them here.  Messages will not propagate through a logger
# unless propagate: True is set.
LOGGING = {
    'version': 1,
    'loggers': {},
}
# LDAP
LDAP = {
    'host': '',
    'port': '',
    'user': '',
    'password': '',
    'search_base': 'o=com,dc=mozilla',
}

EMAIL_BACKEND = 'mysmtp.EmailBackend'
EMAIL_BACKLOG_TOLERANCE = 200
SYNC_UNSUBSCRIBE_LIMIT = 1000
LDAP_TIMEOUT = 2

def JINJA_CONFIG():
    import jinja2
    from django.conf import settings
    config = {'extensions': ['tower.template.i18n',
                             'jinja2.ext.with_', 'jinja2.ext.loopcontrols'],
              'finalize': lambda x: x if x is not None else ''}
    return config

RESPONSYS_USER = 'MOZILLA_API'
RESPONSYS_PASS = ''
RESPONSYS_FOLDER = '!MasterData'
RESPONSYS_LIST = 'TEST_CONTACTS_LIST'

# This is a token that bypasses the news app auth in certain ways to
# make debugging easier
# SUPERTOKEN = <token>

# Uncomment these to use Celery, use eager for local dev
CELERY_ALWAYS_EAGER = True
# BROKER_HOST = 'localhost'
# BROKER_PORT = 5672
# BROKER_USER = 'basket'
# BROKER_PASSWORD = 'basket'
# BROKER_VHOST = '/'
# CELERY_RESULT_BACKEND = 'amqp'

import djcelery
djcelery.setup_loader()

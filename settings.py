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

# Local time zone for this installation. Choices can be found here:
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# although not all choices may be available on all operating systems.
# If running in a Windows environment this must be set to the same as your
# system time zone.
TIME_ZONE = 'America/Chicago'

# Language code for this installation. All choices can be found here:
# http://www.i18nguy.com/unicode/language-identifiers.html
LANGUAGE_CODE = 'en-us'

SITE_ID = 1

# If you set this to False, Django will make some optimizations so as not
# to load the internationalization machinery.
USE_I18N = True

# Absolute path to the directory that holds media.
# Example: "/home/media/media.lawrence.com/"
MEDIA_ROOT = path('media')

# URL that handles the media served from MEDIA_ROOT. Make sure to use a
# trailing slash if there is a path component (optional in other cases).
# Examples: "http://media.lawrence.com", "http://example.com/media/"
MEDIA_URL = '/media/'

# URL prefix for admin media -- CSS, JavaScript and images. Make sure to use a
# trailing slash.
# Examples: "http://foo.com/media/", "/media/".
ADMIN_MEDIA_PREFIX = '/admin-media/'

# Make this unique, and don't share it with anybody.
SECRET_KEY = ''

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

    'fixture_magic',
    'piston',
    'tower',

    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.sites',
    #'django.contrib.messages',
    'django.contrib.admin',
)

# tests
TEST_RUNNER = 'test_utils.runner.RadicalTestSuiteRunner'

LANGUAGES = (
    'af','ak','ast-ES','ar','as','be','bg','bn-BD','bn-IN','br-FR',
    'ca','ca-valencia','cs','cy','da','de','de-AT','de-CH','de-DE',
    'dsb','el','en-AU','en-CA','en-GB','en-NZ','en-US','en-ZA','eo',
    'es','es-AR','es-CL','es-ES','es-MX','et','eu','fa','fi','fj-FJ',
    'fr','fur-IT','fy-NL','ga','ga-IE','gl','gu-IN','he','hi','hi-IN',
    'hr','hsb','hu','hy-AM','id','is','it','ja','ja-JP-mac','ka','kk',
    'kn','ko','ku','la','lt','lv','mg','mi','mk','ml','mn','mr','nb-NO',
    'ne-NP','nn-NO','nl','nr','nso','oc','or','pa-IN','pl','pt-BR','pt-PT',
    'ro','rm','ru','rw','si','sk','sl','sq','sr','sr-Latn','ss','st',
    'sv-SE','ta','ta-IN','ta-LK','te','th','tn','tr','ts','tt-RU','uk','ur',
    've','vi','wo','xh','zh-CN','zh-TW','zu',)
LANGUAGES_LOWERED = [x.lower() for x in LANGUAGES]

DEFAULT_FROM_EMAIL = 'basket@mozilla.com'
DEFAULT_FROM_NAME = 'Mozilla'

# Logging
LOG_LEVEL = logging.DEBUG
HAS_SYSLOG = True  # syslog is used if HAS_SYSLOG and NOT DEBUG.
SYSLOG_TAG = "http_app_basket"
# See PEP 391 and log_settings.py for formatting help.  Each section of LOGGING
# will get merged into the corresponding section of log_settings.py.
# Handlers and log levels are set up automatically based on LOG_LEVEL and DEBUG
# unless you set them here.  Messages will not propagate through a logger
# unless propagate: True is set.
LOGGING = {
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

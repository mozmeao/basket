from settings import *

DATABASES = {
    'default': {
        # Add 'postgresql_psycopg2', 'postgresql', 'mysql', 'sqlite3'
        # or 'oracle'.
        'ENGINE': 'django.db.backends.mysql',
        'NAME': '',        # Or path to database file if using sqlite3.
        'USER': '',                      # Not used with sqlite3.
        'PASSWORD': '',                  # Not used with sqlite3.
        'HOST': '',  # Set to empty string for localhost. Not used with sqlite3
        'PORT': '',  # Set to empty string for default. Not used with sqlite3.
        'OPTIONS': {'init_command': 'SET storage_engine=InnoDB'},
    }
}

SUPERTOKEN = 'change me to something unique and do not share'

# Make this unique, and don't share it with anybody.
SECRET_KEY = ''

# Email settings
# cf. http://docs.djangoproject.com/en/dev/ref/settings/ -> EMAIL_*
DEFAULT_FROM_EMAIL = 'basket@mozilla.com'
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'mail.example.com'
EMAIL_PORT = 25
EMAIL_HOST_USER = 'johndoe'
EMAIL_HOST_PASSWORD = 'secret'

# For production environments
DEBUG = False
TEMPLATE_DEBUG = False

DEBUG_PROPAGATE_EXCEPTIONS = DEBUG
CELERY_ALWAYS_EAGER = True

# LDAP
LDAP = {
    'host': '',
    'port': '',
    'user': '',
    'password': '',
    'search_base': 'o=com,dc=mozilla',
}

#: Credentials for Exact Target account
EXACTTARGET_USER = ''
EXACTTARGET_PASS = ''
#: Name of the database of people who have confirmed
EXACTTARGET_DATA = ''
#: Name of the database of people waiting for confirmation
EXACTTARGET_OPTIN_STAGE = ''
# Name of the database where we put someone's token when they confirm
EXACTTARGET_CONFIRMATION = 'Confirmation'

LOGGING['root'] = {
    'level': 'DEBUG',
    'handlers': ['console'],
}

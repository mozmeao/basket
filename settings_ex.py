from settings import *

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql', # Add 'postgresql_psycopg2', 'postgresql', 'mysql', 'sqlite3' or 'oracle'.
        'NAME': '',                      # Or path to database file if using sqlite3.
        'USER': '',                      # Not used with sqlite3.
        'PASSWORD': '',                  # Not used with sqlite3.
        'HOST': '',                      # Set to empty string for localhost. Not used with sqlite3.
        'PORT': '',                      # Set to empty string for default. Not used with sqlite3.
        'OPTIONS':  {'init_command': 'SET storage_engine=InnoDB'},
    }
}

# Make this unique, and don't share it with anybody.
SECRET_KEY = ''

# Email settings
# cf. http://docs.djangoproject.com/en/dev/ref/settings/ -> EMAIL_*
DEFAULT_FROM_EMAIL = 'basket@example.com'
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'mail.example.com'
EMAIL_PORT = 25
EMAIL_HOST_USER = 'johndoe'
EMAIL_HOST_PASSWORD = 'secret'

# For production environments
DEBUG = False
TEMPLATE_DEBUG = False

LOG_LEVEL = logging.WARNING

DEBUG_PROPAGATE_EXCEPTIONS = DEBUG

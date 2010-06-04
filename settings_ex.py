from settings import *

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql', # Add 'postgresql_psycopg2', 'postgresql', 'mysql', 'sqlite3' or 'oracle'.
        'NAME': '',                      # Or path to database file if using sqlite3.
        'USER': '',                      # Not used with sqlite3.
        'PASSWORD': '',                  # Not used with sqlite3.
        'HOST': '',                      # Set to empty string for localhost. Not used with sqlite3.
        'PORT': '',                      # Set to empty string for default. Not used with sqlite3.
    }
}

# Make this unique, and don't share it with anybody.
SECRET_KEY = ''

# For production environments
DEBUG = False
TEMPLATE_DEBUG = False

# Remove any apps that are only needed for development.
INSTALLED_APPS = tuple(app for app in INSTALLED_APPS if app not in DEV_APPS)

LOG_LEVEL = logging.WARNING

DEBUG_PROPAGATE_EXCEPTIONS = DEBUG

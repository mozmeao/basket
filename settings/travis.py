from .base import *  # noqa

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'basket',
        'USER': 'travis',
        'OPTIONS': {'init_command': 'SET storage_engine=InnoDB'},
    }
}

SUPERTOKEN = 'change me to something unique and do not share'

# Make this unique, and don't share it with anybody.
SECRET_KEY = 'ssssssssshhhhhhhhhhhh'

DEBUG = False
TEMPLATE_DEBUG = DEBUG

DEBUG_PROPAGATE_EXCEPTIONS = DEBUG
CELERY_ALWAYS_EAGER = True

EXACTTARGET_USER = 'user'
EXACTTARGET_PASS = 'pass'
EXACTTARGET_DATA = 'et_data'
EXACTTARGET_OPTIN_STAGE = 'optin_stage'

import os
import sys

if os.getenv('TRAVIS', False):
    from settings.travis import *  # noqa
else:
    try:
        from settings.local import *  # noqa
    except ImportError:
        try:
            from settings.base import *  # noqa
        except ImportError:
            sys.stderr.write(
                "Error: Tried importing 'settings.local' and 'settings.base' "
                "but neither could be found (or they're throwing an "
                "ImportError). Please fix and try again.")
            raise


CACHES['bad_message_ids'] = {
    'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    'TIMEOUT': 12 * 60 * 60,  # 12 hours
}

CACHES['email_block_list'] = {
    'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    'TIMEOUT': 60 * 60,  # 1 hour
}

if len(sys.argv) > 1 and sys.argv[1] == 'test':
    # stuff that's absolutely required for a test run
    CELERY_ALWAYS_EAGER = True
    INSTALLED_APPS += ('django_nose',)

# flake8: noqa

import os

# set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'basket.settings')

from django.conf import settings
from django.utils.encoding import force_bytes

from celery import Celery as CeleryBase
from cryptography.fernet import Fernet, MultiFernet, InvalidToken
from django_statsd.clients import statsd
from kombu import serialization
from kombu.utils import json
from raven.contrib.celery import register_signal, register_logger_signal
from raven.contrib.django.raven_compat.models import client


FERNET = None

if settings.KOMBU_FERNET_KEY:
    FERNET = Fernet(settings.KOMBU_FERNET_KEY)
    if settings.KOMBU_FERNET_KEY_PREVIOUS:
        # this will try both keys. for key rotation.
        FERNET = MultiFernet([FERNET, Fernet(settings.KOMBU_FERNET_KEY_PREVIOUS)])


def fernet_dumps(message):
    statsd.incr('basket.news.celery.fernet_dumps')
    message = json.dumps(message)
    return FERNET.encrypt(force_bytes(message))


def fernet_loads(encoded_message):
    statsd.incr('basket.news.celery.fernet_loads')
    encoded_message = FERNET.decrypt(force_bytes(encoded_message))
    return json.loads(encoded_message)


serialization.register('fernet_json', fernet_dumps, fernet_loads, 'application/x-fernet-json')


class Celery(CeleryBase):
    def on_configure(self):
        # register a custom filter to filter out duplicate logs
        register_logger_signal(client)

        # hook into the Celery error handler
        register_signal(client)


app = Celery('basket')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')
# Load task modules from all registered Django app configs.
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    print('Request: {0!r}'.format(self.request))

# flake8: noqa

import os

# set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "basket.settings")

from django.conf import settings
from django.utils.encoding import force_bytes

from celery import Celery
from cryptography.fernet import Fernet, MultiFernet, InvalidToken
from django_statsd.clients import statsd
from kombu import serialization
from kombu.utils import json


FERNET = None

if settings.KOMBU_FERNET_KEY:
    FERNET = Fernet(settings.KOMBU_FERNET_KEY)
    if settings.KOMBU_FERNET_KEY_PREVIOUS:
        # this will try both keys. for key rotation.
        FERNET = MultiFernet([FERNET, Fernet(settings.KOMBU_FERNET_KEY_PREVIOUS)])


def fernet_dumps(message):
    statsd.incr("basket.news.celery.fernet_dumps")
    message = json.dumps(message)
    if FERNET:
        statsd.incr("basket.news.celery.fernet_dumps.encrypted")
        return FERNET.encrypt(force_bytes(message))

    statsd.incr("basket.news.celery.fernet_dumps.unencrypted")
    return message


def fernet_loads(encoded_message):
    statsd.incr("basket.news.celery.fernet_loads")
    if FERNET:
        try:
            encoded_message = FERNET.decrypt(force_bytes(encoded_message))
        except InvalidToken:
            statsd.incr("basket.news.celery.fernet_loads.unencrypted")
        else:
            statsd.incr("basket.news.celery.fernet_loads.encrypted")
    else:
        statsd.incr("basket.news.celery.fernet_loads.unencrypted")

    return json.loads(encoded_message)


serialization.unregister("json")
serialization.register(
    "json", fernet_dumps, fernet_loads, content_type="application/json", content_encoding="utf-8",
)


app = Celery("basket")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")
# Load task modules from all registered Django app configs.
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    print("Request: {0!r}".format(self.request))

import json
import logging
import sys
from time import time

from django.conf import settings
from django.core.management import BaseCommand, CommandError

import boto3
import requests
import sentry_sdk

from basket import metrics
from basket.news.tasks import (
    fxa_delete,
    fxa_email_changed,
    fxa_login,
    fxa_newsletters_update,
    fxa_verified,
)

FXA_EVENT_TYPES = {
    "delete": fxa_delete,
    "login": fxa_login,
    "newsletters-update": fxa_newsletters_update,
    "primaryEmailChanged": fxa_email_changed,
    "verified": fxa_verified,
}
log = logging.getLogger(__name__)


class Command(BaseCommand):
    snitch_delay = 300  # 5 min
    snitch_last_timestamp = 0
    snitch_id = settings.FXA_EVENTS_SNITCH_ID

    def snitch(self):
        if not self.snitch_id:
            return

        time_since = int(time() - self.snitch_last_timestamp)
        if time_since > self.snitch_delay:
            requests.post(f"https://nosnch.in/{self.snitch_id}")
            self.snitch_last_timestamp = time()

    def handle(self, *args, **options):
        if not settings.FXA_EVENTS_ACCESS_KEY_ID:
            raise CommandError("AWS SQS Credentials not configured")

        if not settings.FXA_EVENTS_QUEUE_ENABLE:
            raise CommandError("FxA Events Queue is not enabled")

        sqs = boto3.resource(
            "sqs",
            region_name=settings.FXA_EVENTS_QUEUE_REGION,
            aws_access_key_id=settings.FXA_EVENTS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.FXA_EVENTS_SECRET_ACCESS_KEY,
        )
        queue = sqs.Queue(settings.FXA_EVENTS_QUEUE_URL)

        try:
            # Poll for messages indefinitely.
            while True:
                self.snitch()
                msgs = queue.receive_messages(
                    WaitTimeSeconds=settings.FXA_EVENTS_QUEUE_WAIT_TIME,
                    MaxNumberOfMessages=10,
                )
                for msg in msgs:
                    if not (msg and msg.body):
                        continue

                    if settings.FXA_EVENTS_QUEUE_IGNORE_MODE:
                        metrics.incr("fxa.events.message", tags=["info:ignored_mode"])
                        msg.delete()
                        continue

                    try:
                        data = json.loads(msg.body)
                        event = json.loads(data["Message"])
                    except ValueError:
                        # body was not JSON
                        metrics.incr("fxa.events.message", tags=["info:json_error"])
                        with sentry_sdk.isolation_scope() as scope:
                            scope.set_extra("msg.body", msg.body)
                            sentry_sdk.capture_exception()

                        msg.delete()
                        continue

                    event_type = event.get("event", "__NONE__").replace(":", "-")
                    metrics.incr("fxa.events.message", tags=["info:received", f"event:{event_type}"])
                    if event_type not in FXA_EVENT_TYPES:
                        metrics.incr("fxa.events.message", tags=["info:ignored_excluded", f"event:{event_type}"])
                        log.debug(f"IGNORED: {event}")
                        # we can safely remove from the queue message types we
                        # don't need this keeps the queue from filling up with
                        # old messages
                        msg.delete()
                        continue

                    try:
                        FXA_EVENT_TYPES[event_type].delay(event)
                    except Exception:
                        # something's wrong with the queue. try again.
                        metrics.incr("fxa.events.message", tags=["info:queue_error", f"event:{event_type}"])
                        with sentry_sdk.isolation_scope() as scope:
                            scope.set_tag("action", "retried")
                            sentry_sdk.capture_exception()

                        continue

                    metrics.incr("fxa.events.message", tags=["info:success", f"event:{event_type}"])
                    msg.delete()
        except KeyboardInterrupt:
            sys.exit("\nBuh bye")

import json
import sys
from time import time

from django.conf import settings
from django.core.management import BaseCommand, CommandError

import boto3
import requests
import sentry_sdk
from django_statsd.clients import statsd

from basket.news.tasks import (
    process_donation,
    process_donation_event,
    process_donation_receipt,
    process_newsletter_subscribe,
    process_petition_signature,
)


EVENT_TYPES = {
    "donation": process_donation,
    "crm_petition_data": process_petition_signature,
    "newsletter_signup_data": process_newsletter_subscribe,
    "DEFAULT": process_donation_event,
}


class Command(BaseCommand):
    snitch_delay = 300  # 5 min
    snitch_last_timestamp = 0
    snitch_id = settings.DONATE_SNITCH_ID

    def snitch(self):
        if not self.snitch_id:
            return

        time_since = int(time() - self.snitch_last_timestamp)
        if time_since > self.snitch_delay:
            requests.post("https://nosnch.in/{}".format(self.snitch_id))
            self.snitch_last_timestamp = time()

    def handle(self, *args, **options):
        if not settings.DONATE_ACCESS_KEY_ID:
            raise CommandError("AWS SQS Credentials not configured")

        sqs = boto3.resource(
            "sqs",
            region_name=settings.DONATE_QUEUE_REGION,
            aws_access_key_id=settings.DONATE_ACCESS_KEY_ID,
            aws_secret_access_key=settings.DONATE_SECRET_ACCESS_KEY,
        )
        queue = sqs.Queue(settings.DONATE_QUEUE_URL)

        try:
            # Poll for messages indefinitely.
            while True:
                self.snitch()
                msgs = queue.receive_messages(
                    WaitTimeSeconds=settings.DONATE_QUEUE_WAIT_TIME,
                    MaxNumberOfMessages=10,
                )
                for msg in msgs:
                    if not (msg and msg.body):
                        continue

                    if settings.DONATE_QUEUE_IGNORE_MODE:
                        statsd.incr("mofo.donations.message.ignored")
                        msg.delete()
                        continue

                    statsd.incr("mofo.donations.message.received")
                    try:
                        data = json.loads(msg.body)
                    except ValueError:
                        # body was not JSON
                        statsd.incr("mofo.donations.message.json_error")
                        with sentry_sdk.configure_scope() as scope:
                            scope.set_extra("msg.body", msg.body)
                            sentry_sdk.capture_exception()

                        msg.delete()
                        continue

                    try:
                        etype = data["data"].setdefault("event_type", "donation")
                        statsd.incr("mofo.donations.message.received.{}".format(etype))
                        processor = EVENT_TYPES.get(etype, EVENT_TYPES["DEFAULT"])
                        processor.delay(data["data"])
                        if etype == "donation" and settings.DONATE_SEND_RECEIPTS:
                            process_donation_receipt.delay(data["data"])
                    except Exception:
                        # something's wrong with the queue. try again.
                        statsd.incr("mofo.donations.message.queue_error")
                        with sentry_sdk.configure_scope() as scope:
                            scope.set_tag("action", "retried")
                            sentry_sdk.capture_exception()

                        continue

                    statsd.incr("mofo.donations.message.success")
                    msg.delete()
        except KeyboardInterrupt:
            sys.exit("\nBuh bye")

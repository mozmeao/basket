from __future__ import print_function, unicode_literals

import json
import sys
from time import time

from django.conf import settings
from django.core.management import BaseCommand, CommandError

import boto3
import requests
from django_statsd.clients import statsd
from raven.contrib.django.raven_compat.models import client as sentry_client

from basket.news.tasks import process_donation, process_donation_event


class Command(BaseCommand):
    snitch_delay = 300  # 5 min
    snitch_last_timestamp = 0
    snitch_id = settings.DONATE_SNITCH_ID

    def snitch(self):
        if not self.snitch_id:
            return

        time_since = int(time() - self.snitch_last_timestamp)
        if time_since > self.snitch_delay:
            requests.post('https://nosnch.in/{}'.format(self.snitch_id))
            self.snitch_last_timestamp = time()

    def handle(self, *args, **options):
        if not settings.DONATE_ACCESS_KEY_ID:
            raise CommandError('AWS SQS Credentials not configured')

        sqs = boto3.resource('sqs',
                             region_name=settings.DONATE_QUEUE_REGION,
                             aws_access_key_id=settings.DONATE_ACCESS_KEY_ID,
                             aws_secret_access_key=settings.DONATE_SECRET_ACCESS_KEY)
        queue = sqs.Queue(settings.DONATE_QUEUE_URL)

        try:
            # Poll for messages indefinitely.
            while True:
                self.snitch()
                msgs = queue.receive_messages(WaitTimeSeconds=settings.DONATE_QUEUE_WAIT_TIME,
                                              MaxNumberOfMessages=10)
                for msg in msgs:
                    if not (msg and msg.body):
                        continue

                    statsd.incr('mofo.donations.message.received')
                    try:
                        data = json.loads(msg.body)
                    except ValueError as e:
                        # body was not JSON
                        statsd.incr('mofo.donations.message.json_error')
                        sentry_client.captureException(data={'extra': {'msg.body': msg.body}})
                        print('ERROR:', e, '::', msg.body)
                        msg.delete()
                        continue

                    try:
                        etype = data['data'].setdefault('event_type', 'donation')
                        if etype == 'donation':
                            process_donation.delay(data['data'])
                        else:
                            process_donation_event.delay(data['data'])
                    except Exception:
                        # something's wrong with the queue. try again.
                        statsd.incr('mofo.donations.message.queue_error')
                        sentry_client.captureException(tags={'action': 'retried'})
                        continue

                    statsd.incr('mofo.donations.message.success')
                    msg.delete()
        except KeyboardInterrupt:
            sys.exit('\nBuh bye')

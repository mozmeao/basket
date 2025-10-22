import json
import logging

from django.conf import settings
from django.core.management import BaseCommand

import boto3

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
    def add_arguments(self, parser):
        parser.add_argument("-b", "--body", type=str, default="{}", help="JSON body to process")
        parser.add_argument(
            "-e",
            "--event",
            type=str,
            default="event",
            help="Payload event",
        )

    def handle(self, *args, **options):
        message = json.loads(options.get("body"))
        event = options.get("event")

        sqs = boto3.resource(
            "sqs",
            region_name=settings.FXA_EVENTS_QUEUE_REGION,
            aws_access_key_id=settings.FXA_EVENTS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.FXA_EVENTS_SECRET_ACCESS_KEY,
            endpoint_url=settings.FXA_EVENTS_ENDPOINT_URL,
        )

        queue = sqs.Queue(settings.FXA_EVENTS_QUEUE_URL)

        queue.send_message(MessageBody=json.dumps({"Message": json.dumps({"event": event, **message})}))

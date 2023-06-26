from time import time

from django.core.management.base import BaseCommand

from basket.base.tasks import snitch


class Command(BaseCommand):
    def handle(self, *args, **options):
        snitch.delay(time())

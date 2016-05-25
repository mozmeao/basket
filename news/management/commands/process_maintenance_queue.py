from django.conf import settings
from django.core.management import BaseCommand, CommandError

from news.models import QueuedTask


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            '-n', '--num-tasks',
            type=int,
            default=settings.QUEUE_BATCH_SIZE,
            help='Number of tasks to process ({})'.format(settings.QUEUE_BATCH_SIZE))

    def handle(self, *args, **options):
        if settings.MAINTENANCE_MODE:
            raise CommandError('Command unavailable in maintenance mode')

        count = 0
        for task in QueuedTask.objects.all()[:settings.QUEUE_BATCH_SIZE]:
            task.retry()
            count += 1

        print '{} processed. {} remaining.'.format(count, QueuedTask.objects.count())

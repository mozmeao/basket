import sys

from django.core.management.base import BaseCommand

from basket.base.rq import get_worker


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "-b",
            "--burst",
            action="store_true",
            dest="burst",
            default=False,
            help="Run worker in burst mode and quit when queues are empty. Default: False",
        )
        parser.add_argument(
            "-s",
            "--with-scheduler",
            action="store_true",
            dest="with_scheduler",
            default=False,
            help="Run worker with scheduler enabled. Default: False",
        )

    def handle(self, *args, **options):
        kwargs = {
            "burst": options.get("burst", False),
            "with_scheduler": options.get("with_scheduler", False),
        }
        try:
            worker = get_worker()
            worker.work(**kwargs)
        except ConnectionError as e:
            self.stderr.write(str(e))
            sys.exit(1)

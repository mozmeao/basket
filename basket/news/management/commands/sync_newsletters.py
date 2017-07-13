from django.conf import settings
from django.core.management import BaseCommand

from synctool.functions import sync_data

from basket.news.newsletters import clear_newsletter_cache, clear_sms_cache


DEFAULT_SYNC_DOMAIN = 'basket.mozilla.org'


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('-d', '--domain',
                            default=getattr(settings, 'SYNC_DOMAIN', DEFAULT_SYNC_DOMAIN),
                            help='Domain of the Basket from which to sync')
        parser.add_argument('-k', '--key',
                            default=settings.SYNC_KEY,
                            help='Auth key for the sync')
        parser.add_argument('-c', '--clean', action='store_true',
                            help='Delete all Newsletter data before sync')

    def handle(self, *args, **options):
        sync_data(url='https://{}/news/sync/'.format(options['domain']),
                  clean=options['clean'],
                  api_token=options['key'])
        clear_newsletter_cache()
        clear_sms_cache()

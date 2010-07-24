from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import commonware.log

from ldaputils import subscription_has_account
from subscriptions.models import Subscription
from utils import locked
import vars


log = commonware.log.getLogger('basket')
limit = settings.SYNC_UNSUBSCRIBE_LIMIT


class Command(BaseCommand):
    """
    Unsubscribe users from the Firefox Home campaign, when they have a Sync account.
    """ 

    help = 'Unsubscribe users from Firefox Home emails when they have a sync account.'

    @locked('sync_unsubscribe')
    def handle(self, **options):
        """
        Locked command handler to avoid running this command more than once
        simultaneously.
        """

        try:
            targets = Subscription.objects.filter(campaign='firefox-home-instructions', active=True).order_by('id')

            start = int(vars.get('sync_unsubscribe_index', 0))
            log.info(start)
            end = start + limit
            targets = targets[start:end]
            count = targets.count()

            log.info("Found %d targets" % count)

            unsub_count = 0
            for target in targets:
                if subscription_has_account(target):
                    target.active = False
                    target.save()
                    unsub_count += 1
            log.info("Unsubscribed %d" % unsub_count)

            if count < limit:
                vars.set('sync_unsubscribe_index', 0)
            else:
                vars.set('sync_unsubscribe_index', start + (count - unsub_count))
                     
        except Exception, e:
            raise CommandError(e)

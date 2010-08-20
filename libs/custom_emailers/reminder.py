"""Custom emailer for sending a reminder email."""
import datetime

from emailer import Emailer

class ReminderEmailer(Emailer):
    """
    Send email to subscribers, only after a week has passed since subscribing.
    """

    delay = datetime.timedelta(weeks=1)

    def get_subscriptions(self):
        subscriptions = super(ReminderEmailer, self).get_subscriptions()
        subscriptions = subscriptions.exclude(
            created__gte=datetime.datetime.now()-self.delay)
        return subscriptions

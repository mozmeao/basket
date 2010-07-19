"""Custom emailer for sending a reminder email."""
import datetime

from emailer.base import BaseEmailer

class ReminderEmailer(BaseEmailer):
    """
    Send email to subscribers, only after a week has passed since subscribing.
    """

    delay = datetime.timedelta(weeks=1)

    def get_recipients(self):
        recipients = super(ReminderEmailer, self).get_recipients()
        recipients = recipients.exclude(
            subscriptions__created__gte=datetime.datetime.now()-self.delay)
        return recipients

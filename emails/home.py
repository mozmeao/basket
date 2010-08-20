from tower import ugettext_lazy as _

from emailer import Email


class Initial(Email):
    id = 'firefox-home-instructions-initial'
    subject = _('Set Up Firefox Home On Your iPhone')
    from_name = _('Firefox Home Account Setup')
    from_email = 'firefox-home-support@mozilla.com'
    reply_email = 'firefox-home-support@mozilla.com'
    template = 'firefox-home-instructions-initial'

class Reminder(Initial):
    id = 'firefox-home-instructions-reminder'
    template = 'firefox-home-instructions-reminder'
    emailer_class='custom_emailers.reminder.ReminderEmailer'

from optparse import make_option

from django.core.management.base import LabelCommand, CommandError

from emailer import Email
from utils import locked


class Command(LabelCommand):
    option_list = LabelCommand.option_list + (
        make_option('--force', '-f', dest='force', action='store_true',
                    default=False,
                    help='Send email even to prior recipients.'),
        make_option('--email', '-e', dest='email',
                    help='Name of email to be sent (required).'),
    )
    help = 'Send an email to the subscribers to a campaign.'
    args = '<campaign campaign ...>'
    label = 'campaign'

    @locked('sendmail')
    def handle_label(self, label, **options):
        """
        Locked command handler to avoid running this command more than once
        simultaneously.
        """
        email = getattr(self, 'email', None)
        if not email:
            email_name = options.get('email', None)
            if not email_name:
                raise CommandError('--email option is required.')
            try:
                email = Email.get(email_name)
                self.email = email
            except (ImportError, AttributeError), e:
                raise CommandError(e)

        force = options.get('force', False)
        emailer = email.emailer(campaign=label, email=email,
                                force=force)

        emailer.send_email()

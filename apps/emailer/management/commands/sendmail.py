import functools
import logging
from optparse import make_option
import os
import tempfile

import lockfile

from django.core.management.base import LabelCommand, CommandError
from django.core.urlresolvers import get_callable

from emailer.models import Email


LOCKFILE_PREFIX = 'basket_emailer_lock'


def locked(f):
    """
    Decorator that only allows one instance of the same sendmail command to run
    at a time.
    """
    @functools.wraps(f)
    def wrapper(self, label, **options):
        name = '_'.join((LOCKFILE_PREFIX, f.__name__, options.get(
            'template', None), label))
        file = os.path.join(tempfile.gettempdir(), name)
        lock = lockfile.FileLock(file)
        try:
            # Try to acquire the lock without blocking.
            lock.acquire(0)
        except lockfile.LockError:
            logging.debug('Aborting %s; lock acquisition failed.' % name)
            return 0
        else:
            # We have the lock, call the function.
            try:
                return f(self, label, **options)
            finally:
                lock.release()
    return wrapper


class Command(LabelCommand):
    option_list = LabelCommand.option_list + (
        make_option('--force', '-f', dest='force', action='store_true',
                    default=False, help='Send email even to prior recipients.'),
        make_option('--template', '-t', dest='template',
                    help='Template name of email to be sent (required).'),
    )
    help='Send an email to the subscribers to a campaign.'
    args='<campaign campaign ...>'
    label='campaign'

    @locked
    def handle_label(self, label, **options):
        """
        Locked command handler to avoid running this command more than once
        simultaneously.
        """
        template = getattr(self, 'template', None)
        if not template:
            template_name = options.get('template', None)
            if not template_name:
                raise CommandError('--template option is required.')
            try:
                self.template = template = Email.objects.get(name=template_name)
            except Email.DoesNotExist:
                raise CommandError('No email template %s found.' % template_name)

        # Use custom emailer if defined, default otherwise
        emailer_class = getattr(self, 'emailer_class', None)
        if not emailer_class:
            try:
                self.emailer_class = emailer_class = get_callable(
                    template.emailer_class or 'emailer.base.BaseEmailer')
            except ImportError, e:
                raise CommandError(e)

        emailer = emailer_class(campaign=label, email=template,
                                force=options['force'])
        try:
            emailer.send_email()
        except Exception, e:
            raise CommandError(e)

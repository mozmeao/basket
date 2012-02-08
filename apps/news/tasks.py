import uuid
from email.utils import formatdate
import datetime
from time import mktime
from datetime import date
from urllib2 import URLError

from django.conf import settings
from celery.task import task

from backends.exacttarget import (ExactTargetDataExt, NewsletterException,
                                  UnauthorizedException)
from models import Subscriber
from newsletters import *


# A few constants to indicate the type of action to take
# on a user with a list of newsletters
SUBSCRIBE=1
UNSUBSCRIBE=2
SET=3


def gmttime():
    d = datetime.datetime.now() + datetime.timedelta(minutes=10)
    stamp = mktime(d.timetuple())
    return formatdate(timeval=stamp, localtime=False, usegmt=True)


def parse_newsletters(record, type, newsletters):
    """Utility function to take a list of newsletters and according
    the type of action (subscribe, unsubscribe, and set) set the
    appropriate flags in `record` which is a dict of parameters that
    will be sent to the email provider."""

    newsletters = [x.strip() for x in newsletters.split(',')]

    if type == SUBSCRIBE or type == SET:
        # Subscribe the user to these newsletters
        for nl in newsletters:
            name = newsletter_field(nl)
            if name:
                record['%s_FLG' % name] = 'Y'
                record['%s_DATE' % name] = date.today().strftime('%Y-%m-%d')

    
    if type == UNSUBSCRIBE or type == SET:
        # Unsubscribe the user to these newsletters
        unsubs = newsletters

        if type == SET:
            # Unsubscribe to the inversion of these newsletters
            subs = set(newsletters)
            all = set(newsletter_names())
            unsubs = all.difference(subs)

        for nl in unsubs:
            name = newsletter_field(nl)
            if name:
                record['%s_FLG' % name] = 'N'
                record['%s_DATE' % name] = date.today().strftime('%Y-%m-%d')


@task(default_retry_delay=60)  # retry in 1 minute on failure
def update_user(data, authed_email, type, optin):
    """Task for updating user's preferences and newsletters.

    ``authed_email`` is the email for the user pulled from the database
    with their token, if exists."""

    log = update_user.get_logger()

    # Validate parameters
    if not authed_email and 'email' not in data:
        log.error('No user or email provided')
 
    # Parse the parameters
    record = {'EMAIL_ADDRESS_': data['email'],
              'EMAIL_PERMISSION_STATUS_': 'I'}
    
    extra_fields = {
        'format': 'EMAIL_FORMAT_',
        'country': 'COUNTRY_',
        'lang': 'LANGUAGE_ISO2',
        'source_url': 'SOURCE_URL'
    }

    # Optionally add more fields
    for field in extra_fields.keys():
        if field in data:
            record[extra_fields[field]] = data[field]

    # Set the newsletter flags in the record
    parse_newsletters(record, type, data.get('newsletters', ''))

    # Get the user or create them
    (sub, created) = Subscriber.objects.get_or_create(email=record['EMAIL_ADDRESS_'])

    # Update the token if it's a new user or they aren't simply
    # subscribing from a newsletter form (tokens are one-time use)
    if created or type != SUBSCRIBE:
        sub.token = str(uuid.uuid4())
        record['TOKEN'] = sub.token
        record['CREATED_DATE_'] = gmttime()
        sub.save()
    else:
        record['TOKEN'] = sub.token

    # Submit the final data to the service
    try:
        et = ExactTarget(settings.EXACTTARGET_USER, settings.EXACTTARGET_PASS)
        record['MODIFIED_DATE_'] = gmttime()
        
        if not optin:
            et.data_ext().add_record('Double_Opt_In', record.keys(), record.values())
            et.trigger_send('ConfirmEmail',
                            record['EMAIL_ADDRESS_'],
                            record['TOKEN'],
                            record['EMAIL_FORMAT_'])
        else:
            et.data_ext().add_record(settings.EXACTTARGET_DATA, record.keys(), record.values())
            if data.get('trigger_welcome', False) == 'Y':
                # Trigger the welcome event unless it is suppressed
                et.trigger_send('WelcomeEmail', 
                                record['EMAIL_ADDRESS_'],
                                record['TOKEN'],
                                record['EMAIL_FORMAT_'])

    except URLError, e:
        # URL timeout, try again
        update_user.retry(exc=e)
    except NewsletterException, e:
        log.error('NewsletterException: %s' % e.message)
    except UnauthorizedException, e:
        log.error('Email service provider auth failure')

@task(default_retry_delay=60)
def confirm_user(token):
    try:
        ext = ExactTargetDataExt(settings.EXACTTARGET_USER, settings.EXACTTARGET_PASS)
        ext.add_record('TokenOptinOrSomething', ['TOKEN'], [token]);
    except URLError, e:
        # URL timeout, try again
        update_user.retry(exc=e)
    except NewsletterException, e:
        log.error('NewsletterException: %s' % e.message)
    except UnauthorizedException, e:
        log.error('Email service provider auth failure')

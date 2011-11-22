import uuid
from datetime import date
from urllib2 import URLError

from django.conf import settings
from celery.task import task

from responsys import Responsys, NewsletterException, UnauthorizedException
from models import Subscriber
from newsletters import *


# A few constants to indicate the type of action to take
# on a user with a list of newsletters
SUBSCRIBE=1
UNSUBSCRIBE=2
SET=3


def parse_newsletters(record, type, newsletters):
    """Utility function to take a list of newsletters and according
    the type of action (subscribe, unsubscribe, and set) set the
    appropriate flags in `record` which is a dict of parameters that
    will be sent to Responsys."""

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
def update_user(data, authed_email, type):
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
        'locale': 'LANG_LOCALE',
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
        sub.save()

    # Submit the final data to responsys
    try:
        rs = Responsys()
        rs.login(settings.RESPONSYS_USER, settings.RESPONSYS_PASS)

        if authed_email and record['EMAIL_ADDRESS_'] != authed_email:
            # Email has changed, we need to delete the previous user
            rs.delete_list_members(authed_email,
                                   settings.RESPONSYS_FOLDER,
                                   settings.RESPONSYS_LIST)

        rs.merge_list_members(settings.RESPONSYS_FOLDER,
                              settings.RESPONSYS_LIST,
                              record.keys(),
                              record.values())
        
        # Trigger the welcome event unless it is suppressed
        if data.get('trigger_welcome', False) == 'Y':
            rs.trigger_custom_event(record['EMAIL_ADDRESS_'],
                                    settings.RESPONSYS_FOLDER,
                                    settings.RESPONSYS_LIST,
                                    'New_Signup_Welcome')

        rs.logout()
    except URLError, e:
        # URL timeout, try again
        update_user.retry(exc=e)
    except NewsletterException, e:
        log.error('NewsletterException: %s' % e.message)
    except UnauthorizedException, e:
        log.error('Responsys auth failure')


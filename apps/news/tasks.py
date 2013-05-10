import datetime
from functools import wraps
import logging
from datetime import date
from email.utils import formatdate
from time import mktime
from urllib2 import URLError

from django.conf import settings
from django_statsd.clients import statsd

from celery.task import Task, task

from backends.exacttarget import (ExactTarget, ExactTargetDataExt,
                                  NewsletterException)
from .models import Newsletter
from .newsletters import newsletter_field


log = logging.getLogger(__name__)

# A few constants to indicate the type of action to take
# on a user with a list of newsletters
SUBSCRIBE = 1
UNSUBSCRIBE = 2
SET = 3

# Double optin-in languages
CONFIRM_SENDS = {
    'es': 'es_confirmation_email',
    'es-ES': 'es_confirmation_email',
    'de': 'de_confirmation_email',
    'fr': 'fr_confirmation_email',
    'id': 'id_confirmation_email',
    'pt': 'pt_br_confirmation_email',
    'pt-BR': 'pt_br_confirmation_email',
    'ru': 'ru_confirmation_email_2',
    'pl': 'pl_confirmation_email',
}
SMS_MESSAGES = (
    'SMS_Android',
)
PHONEBOOK_GROUPS = (
    'SYSTEMS_ADMINISTRATION',
    'BOOT2GECKO',
    'LOCALIZATION',
    'QUALITY_ASSURANCE',
    'CREATIVE',
    'METRICS',
    'MARKETING',
    'POLICY',
    'WEB_DEVELOPMENT',
    'CODING',
    'SUPPORT',
    'UX',
    'COMMUNICATIONS',
    'PROGRAM_MANAGEMENT',
    'LABS',
    'WEBFWD',
    'SECURITY',
    'DEVELOPER_DOCUMENTATION',
    'DEVELOPER_TOOLS',
    'MOBILE',
    'THUNDERBIRD',
    'APPS',
    'EVANGELISM',
    'GRAPHICS',
    'LEGAL',
    'ADD-ONS',
    'AUTOMATION',
    'RECRUITING',
    'PERSONA',
    'BUSINESS_DEVELOPMENT',
    'PEOPLE',
    'ACCESSIBILITY',
    'FUNDRAISING',
)


class ETTask(Task):
    abstract = True
    default_retry_delay = 60 * 5  # 5 minutes
    max_retries = 6  # ~ 30 min

    def on_success(self, *args, **kwargs):
        statsd.incr(self.name + '.success')

    def on_failure(self, *args, **kwargs):
        statsd.incr(self.name + '.failure')

    def on_retry(self, *args, **kwargs):
        statsd.incr(self.name + '.retry')


def et_task(func):
    """Decorator to standardize ET Celery tasks."""
    @task(base=ETTask)
    @wraps(func)
    def wrapped(*args, **kwargs):
        statsd.incr(wrapped.name + '.total')
        try:
            return func(*args, **kwargs)
        except URLError as e:
            # connection issue. try again later.
            # raises retry exception or e after max
            wrapped.retry(exc=e)

    return wrapped


def gmttime():
    d = datetime.datetime.now() + datetime.timedelta(minutes=10)
    stamp = mktime(d.timetuple())
    return formatdate(timeval=stamp, localtime=False, usegmt=True)


def parse_newsletters(record, type, newsletters, cur_newsletters):
    """Utility function to take a list of newsletters and according
    the type of action (subscribe, unsubscribe, and set) set the
    appropriate flags in `record` which is a dict of parameters that
    will be sent to the email provider.

    Parameters are only set for the newsletters whose subscription
    status needs to change, so that we don't unnecessarily update the
    last modification timestamp of newsletters.

    :param dict record: Parameters that will be sent to ET
    :param integer type: SUBSCRIBE means add these newsletters to the
        user's subscriptions if not already there, UNSUBSCRIBE means remove
        these newsletters from the user's subscriptions if there, and SET
        means change the user's subscriptions to exactly this set of
        newsletters.
    :param list newsletters: List of the slugs of the newsletters to be
        subscribed, unsubscribed, or set.
    :param set cur_newsletters: Set of the slugs of the newsletters that
        the user is currently subscribed to.
    """

    if type == SUBSCRIBE or type == SET:
        # Subscribe the user to these newsletters if not already
        for nl in newsletters:
            name = newsletter_field(nl)
            if name and nl not in cur_newsletters:
                record['%s_FLG' % name] = 'Y'
                record['%s_DATE' % name] = date.today().strftime('%Y-%m-%d')

    if type == UNSUBSCRIBE or type == SET:
        # Unsubscribe the user to these newsletters

        if type == SET:
            # Unsubscribe from the newsletters currently subscribed to
            # but not in the new list
            unsubs = cur_newsletters - set(newsletters)
        else:  # type == UNSUBSCRIBE
            # unsubscribe from the specified newsletters
            unsubs = newsletters

        for nl in unsubs:
            # Unsubscribe from any unsubs that the user is currently subbed to
            name = newsletter_field(nl)
            if name and nl in cur_newsletters:
                record['%s_FLG' % name] = 'N'
                record['%s_DATE' % name] = date.today().strftime('%Y-%m-%d')


@et_task
def update_phonebook(data, email, token):
    record = {
        'EMAIL_ADDRESS': email,
        'TOKEN': token,
    }
    if 'city' in data:
        record['CITY'] = data['city']
    if 'country' in data:
        record['COUNTRY'] = data['country']

    record.update((k, v) for k, v in data.items() if k in PHONEBOOK_GROUPS)

    et = ExactTarget(settings.EXACTTARGET_USER, settings.EXACTTARGET_PASS)
    et.data_ext().add_record('PHONEBOOK', record.keys(), record.values())


@et_task
def update_student_ambassadors(data, email, token):
    data['EMAIL_ADDRESS'] = email
    data['TOKEN'] = token
    et = ExactTarget(settings.EXACTTARGET_USER, settings.EXACTTARGET_PASS)
    et.data_ext().add_record('Student_Ambassadors', data.keys(), data.values())


@et_task
def update_user(data, email, token, created, type, optin):
    """Task for updating user's preferences and newsletters.

    ``authed_email`` is the email for the user pulled from the database
    with their token, if exists."""

    # Parse the parameters
    record = {
        'EMAIL_ADDRESS_': email,
        'TOKEN': token,
        'EMAIL_PERMISSION_STATUS_': 'I',
        'MODIFIED_DATE_': gmttime(),
    }
    if created:
        record['CREATED_DATE_'] = gmttime()

    extra_fields = {
        'country': 'COUNTRY_',
        'lang': 'LANGUAGE_ISO2',
        'source_url': 'SOURCE_URL',
    }

    # Optionally add more fields
    for field in extra_fields:
        if field in data:
            record[extra_fields[field]] = data[field]

    fmt = 'T' if data.get('format', 'H').upper().startswith('T') else 'H'

    # From here on, fmt is either 'H' or 'T', preferring 'H'

    record['EMAIL_FORMAT_'] = fmt

    newsletters = [x.strip() for x in data.get('newsletters', '').split(',')]

    # Can't import this earlier, circular import
    from .views import get_user_data

    # Get the user's current settings
    user_data = get_user_data(token=token)
    cur_newsletters = set(user_data['newsletters'])

    # Set the newsletter flags in the record
    parse_newsletters(record, type, newsletters, cur_newsletters)

    # Submit the final data to the service
    et = ExactTarget(settings.EXACTTARGET_USER, settings.EXACTTARGET_PASS)
    lang = record.get('LANGUAGE_ISO2', None)

    target_et = settings.EXACTTARGET_DATA
    welcome = None

    if lang in CONFIRM_SENDS and type == SUBSCRIBE:
        # This lang requires double opt-in and a different welcome
        # email
        target_et = settings.EXACTTARGET_OPTIN_STAGE
        welcome = CONFIRM_SENDS[lang]
        record['SubscriberKey'] = record['TOKEN']
        record['EmailAddress'] = record['EMAIL_ADDRESS_']
    elif data.get('trigger_welcome', 'Y') == 'Y' and type == SUBSCRIBE:
        # Otherwise, send this welcome email unless its suppressed
        if 'welcome_message' in data:
            welcome = data['welcome_message']
        elif len(newsletters) == 1:
            # If just one newsletter, use its welcome message;
            newsletter = Newsletter.objects.get(slug=newsletters[0])
            welcome = newsletter.welcome_id
        else:
            # otherwise, just send one copy of the default welcome.
            welcome = settings.DEFAULT_WELCOME_MESSAGE_ID

    try:
        et.data_ext().add_record(target_et, record.keys(), record.values())
    except NewsletterException, e:
        return attempt_fix(target_et, record, update_user, e)

    # This is a separate try because the above one might recover, and
    # we still need to send the welcome email
    if welcome:
        # If user preferred text, send welcome in text
        if fmt == 'T':
            welcome += "_T"

        et.trigger_send(welcome, {
            'EMAIL_ADDRESS_': record['EMAIL_ADDRESS_'],
            'TOKEN': record['TOKEN'],
            'EMAIL_FORMAT_': fmt,
        })


@et_task
def confirm_user(token):
    ext = ExactTargetDataExt(settings.EXACTTARGET_USER,
                             settings.EXACTTARGET_PASS)
    ext.add_record('Confirmation', ['TOKEN'], [token])


@et_task
def add_sms_user(send_name, mobile_number, optin):
    if send_name not in SMS_MESSAGES:
        return
    et = ExactTarget(settings.EXACTTARGET_USER, settings.EXACTTARGET_PASS)
    et.trigger_send_sms(send_name, mobile_number)
    if optin:
        record = {'Phone': mobile_number, 'SubscriberKey': mobile_number}
        et.data_ext().add_record('Mobile_Subscribers',
                                 record.keys(),
                                 record.values())


@et_task
def update_custom_unsub(token, reason):
    """Record a user's custom unsubscribe reason."""
    ext = ExactTargetDataExt(settings.EXACTTARGET_USER,
                             settings.EXACTTARGET_PASS)
    ext.add_record(settings.EXACTTARGET_DATA,
                   ['TOKEN', 'UNSUBSCRIBE_REASON'],
                   [token, reason])


def attempt_fix(ext_name, record, task, e):
    # Sometimes a user is in basket's database but not in
    # ExactTarget because the API failed or something. If that's
    # the case, any future API call will error because basket
    # won't add the required CREATED_DATE field. Try to add them
    # with it here.
    if e.message.find('CREATED_DATE_') != -1:
        record['CREATED_DATE_'] = gmttime()
        ext = ExactTargetDataExt(settings.EXACTTARGET_USER,
                                 settings.EXACTTARGET_PASS)
        ext.add_record(ext_name, record.keys(), record.values())
    else:
        raise e

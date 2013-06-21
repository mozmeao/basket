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

from .backends.exacttarget import (ExactTarget, ExactTargetDataExt)
from .models import Newsletter
from .newsletters import newsletter_field, newsletter_slugs


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


# Vendor IDs for Firefox OS and Firefox & You:
FFOS_VENDOR_ID = 'FIREFOX_OS'
FFAY_VENDOR_ID = 'MOZILLA_AND_YOU'


class RetryTask(Exception):
    """Tasks should raise this to signal the et_task wrapper to retry.
    Before raising it, tasks should log details of what went wrong.
    They should also include a string describing the error, so that
    if retries are exhausted and this exception gets re-raised, something
    useful will be logged.
    """
    def __init__(self, msg):
        super(RetryTask, self).__init__(msg)


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
        except (URLError, RetryTask) as e:
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
        the user is currently subscribed to. None if there was an error.
    :returns: (to_subscribe, to_unsubscribe) - lists of slugs of the
        newsletters that we will request new subscriptions to, or request
        unsubscription from, respectively.
    """

    to_subscribe = []
    to_unsubscribe = []
    if type == SUBSCRIBE or type == SET:
        # Subscribe the user to these newsletters if not already
        for nl in newsletters:
            name = newsletter_field(nl)
            if name and (cur_newsletters is None or
                         nl not in cur_newsletters):
                record['%s_FLG' % name] = 'Y'
                record['%s_DATE' % name] = date.today().strftime('%Y-%m-%d')
                to_subscribe.append(nl)

    if type == UNSUBSCRIBE or type == SET:
        # Unsubscribe the user to these newsletters

        if type == SET:
            # Unsubscribe from the newsletters currently subscribed to
            # but not in the new list
            if cur_newsletters is not None:
                unsubs = cur_newsletters - set(newsletters)
            else:
                subs = set(newsletters)
                all = set(newsletter_slugs())
                unsubs = all - subs
        else:  # type == UNSUBSCRIBE
            # unsubscribe from the specified newsletters
            unsubs = newsletters

        for nl in unsubs:
            # Unsubscribe from any unsubs that the user is currently subbed to
            name = newsletter_field(nl)
            if name and (cur_newsletters is None or nl in cur_newsletters):
                record['%s_FLG' % name] = 'N'
                record['%s_DATE' % name] = date.today().strftime('%Y-%m-%d')
                to_unsubscribe.append(nl)
    return to_subscribe, to_unsubscribe


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


# Return codes for update_user
UU_ALREADY_CONFIRMED = 1
UU_EXEMPT_PENDING = 2
UU_EXEMPT_NEW = 3
UU_MUST_CONFIRM_PENDING = 4
UU_MUST_CONFIRM_NEW = 5


@et_task
def update_user(data, email, token, created, type, optin):
    """Task for updating user's preferences and newsletters.

    :param dict data: POST data from the form submission
    :param string email: User's email address
    :param string token: User's token
    :param boolean created: Whether a new user was created in Basket
    :param int type: What kind of API call it was. Could be
        SUBSCRIBE, UNSUBSCRIBE, or SET.
    :param boolean optin: whether the POST had an OPTIN parameter
        with value "Y".  (Unused)

    :returns: One of the return codes UU_ALREADY_CONFIRMED,
        etc. (see code) to indicate what case we figured out we were
        doing.  (These are primarily for tests to use.)
    :raises: RetryTask if there are any errors that would be worth retrying.
        Our task wrapper will retry in that case.
    """

    # Parse the parameters
    # `record` will contain the data we send to ET in the format they want.
    record = {
        'EMAIL_ADDRESS_': email,
        'TOKEN': token,
        'EMAIL_PERMISSION_STATUS_': 'I',
        'MODIFIED_DATE_': gmttime(),
    }

    extra_fields = {
        'country': 'COUNTRY_',
        'lang': 'LANGUAGE_ISO2',
        'source_url': 'SOURCE_URL',
    }

    # Optionally add more fields
    for field in extra_fields:
        if field in data:
            record[extra_fields[field]] = data[field]

    lang = record.get('LANGUAGE_ISO2', None)

    # Can't import this earlier, circular import
    from .views import get_user_data

    # Get the user's current settings from ET, if any
    user_data = get_user_data(token=token)
    # If we don't find the user, get_user_data returns None. Create
    # a minimal dictionary to use going forward. This will happen
    # often due to new people signing up.
    if user_data is None:
        user_data = {
            'email': email,
            'token': token,
            'master': False,
            'pending': False,
            'confirmed': False,
            'lang': lang,
            'status': 'ok',
        }
    elif user_data.get('status', 'error') != 'ok':
        # Error talking to ET - raise so we retry later
        msg = "Some error with Exact Target: %r" % user_data
        log.error(msg)
        raise RetryTask(msg)

    if lang:
        # User asked for a language change. Use the new language from
        # here on.
        user_data['lang'] = lang
    else:
        # Use `lang` as a shorter reference to user_data['lang']
        lang = user_data['lang']

    # We need an HTML/Text format choice for sending welcome messages, and
    # optionally to update their ET record
    if 'format' in data:  # Submitted in call
        fmt = 'T' if data.get('format', 'H').upper().startswith('T') else 'H'
        # We only set the format in ET if the call asked us to
        record['EMAIL_FORMAT_'] = fmt
    elif 'format' in user_data:  # Existing user preference
        fmt = user_data['format']
    else:  # Default to 'H'
        fmt = 'H'
    # From here on, fmt is either 'H' or 'T', preferring 'H'

    newsletters = [x.strip() for x in data.get('newsletters', '').split(',')]

    cur_newsletters = user_data.get('newsletters', None)
    if cur_newsletters is not None:
        cur_newsletters = set(cur_newsletters)

    # Set the newsletter flags in the record by comparing to their
    # current subscriptions.
    to_subscribe, to_unsubscribe = parse_newsletters(record, type,
                                                     newsletters,
                                                     cur_newsletters)

    # Are they subscribing to any newsletters that don't require confirmation?
    newsletter_objects = Newsletter.objects.filter(slug__in=to_subscribe)
    any_newsletter_doesnt_require_confirmation = newsletter_objects.filter(
        requires_double_optin=False).exists()
    # When signing up in English, or including any newsletter that does not
    # require confirmation, user gets a pass on confirming and goes straight
    # to confirmed.
    exempt_from_confirmation = lang is None\
        or lang == ''\
        or lang.lower().startswith('en') \
        or any_newsletter_doesnt_require_confirmation

    MASTER = settings.EXACTTARGET_DATA
    OPT_IN = settings.EXACTTARGET_OPTIN_STAGE

    if user_data['confirmed']:
        # The user is already confirmed.
        # Just add any new subs to whichever of master or optin list is
        # appropriate, and send welcomes.
        target_et = MASTER if user_data['master'] else OPT_IN
        apply_updates(target_et, record)
        send_welcomes(user_data, to_subscribe, fmt)
        return_code = UU_ALREADY_CONFIRMED
    elif exempt_from_confirmation:
        # This user is not confirmed, but they
        # qualify to be excepted from confirmation.
        if user_data['pending']:
            # We were waiting for them to confirm.  Update the data in
            # their record (currently in the Opt-in table), then go
            # ahead and confirm them. This will also send welcomes.
            apply_updates(OPT_IN, record)
            confirm_user(user_data['token'], user_data)
            return_code = UU_EXEMPT_PENDING
        else:
            # Brand new user: Add them directly to master subscriber DB
            # and send welcomes.
            record['CREATED_DATE_'] = gmttime()
            apply_updates(MASTER, record)
            send_welcomes(user_data, to_subscribe, fmt)
            return_code = UU_EXEMPT_NEW
    else:
        # This user must confirm
        if user_data['pending']:
            return_code = UU_MUST_CONFIRM_PENDING
        else:
            # Creating a new record, need a couple more fields
            record['CREATED_DATE_'] = gmttime()
            record['SubscriberKey'] = record['TOKEN']
            record['EmailAddress'] = record['EMAIL_ADDRESS_']
            return_code = UU_MUST_CONFIRM_NEW
        # Create or update OPT_IN record and send email telling them (or
        # reminding them) to confirm.
        apply_updates(OPT_IN, record)
        send_confirm_notice(email, token, lang, fmt)
    return return_code


def apply_updates(target_et, record):
    """Send the record data to ET to update the database named
    target_et.

    :param str target_et: Target database, e.g. settings.EXACTTARGET_DATA
        or settings.EXACTTARGET_CONFIRMATION.
    :param dict record: Data to send
    """
    et = ExactTarget(settings.EXACTTARGET_USER, settings.EXACTTARGET_PASS)
    et.data_ext().add_record(target_et, record.keys(), record.values())


def send_message(message_id, email, token, format):
    """
    Ask ET to send a message.

    :param str message_id: ID of the message in ET
    :param str email: email to send it to
    :param str token: token of the email user
    :param str format: 'H' or 'T' - whether to send in HTML or Text
       (message_id should also be for a message in matching format)
    """
    log.info("Sending message %s to %s %s in %s" %
             (message_id, email, token, format))
    et = ExactTarget(settings.EXACTTARGET_USER, settings.EXACTTARGET_PASS)
    et.trigger_send(
        message_id,
        {
            'EMAIL_ADDRESS_': email,
            'TOKEN': token,
            'EMAIL_FORMAT_': format,
        }
    )


def send_confirm_notice(email, token, lang, format):
    """
    Send email to user with link to confirm their subscriptions.
    """
    # Confirmation notices are language-dependent. Try first
    # to see if we have their exact language; if not, try the
    # first two chars.
    if lang not in CONFIRM_SENDS and lang[:2] not in CONFIRM_SENDS:
        log.error("Cannot send confirmation request to user %s %s because "
                  "no confirmation message defined for lang=%r" %
                  (email, token, lang))
        return

    welcome = CONFIRM_SENDS[lang] if lang in CONFIRM_SENDS \
        else CONFIRM_SENDS[lang[:2]]
    send_message(welcome, email, token, format)


def send_welcomes(user_data, newsletter_slugs, format):
    """
    Send welcome messages to the user for the specified newsletters.
    Don't send any duplicates.

    Also, if the newsletters listed include
    FIREFOX_OS, then send that welcome but not the firefox & you
    welcome.

    """
    if not newsletter_slugs:
        log.debug("send_welcomes(%r) called with no newsletters, returning"
                  % user_data)
        return

    newsletters = Newsletter.objects.filter(
        slug__in=newsletter_slugs
    )

    # If newsletters include FIREFOX_OS, then remove FIREFOX & YOU
    # from the list so we don't send its welcome.
    if newsletters.filter(vendor_id=FFOS_VENDOR_ID).exists():
        newsletters = newsletters.exclude(vendor_id=FFAY_VENDOR_ID)

    # We don't want any duplicate welcome messages, so make a set
    # of the ones to send, then send them
    welcomes_to_send = set()
    for nl in newsletters:
        welcome = nl.welcome or settings.DEFAULT_WELCOME_MESSAGE_ID
        if format == 'T':
            welcome += '_T'
        if ',' in nl.languages:
            # Newsletter supports multiple languages, so we want to send
            # the welcome message in the right language for this user
            lang_code = user_data.get('lang', 'en')[:2]
            welcome = "%s_%s" % (lang_code.lower(), welcome)
        welcomes_to_send.add(welcome)
    # Note: it's okay not to send a welcome if none of the newsletters
    # have one configured.
    for welcome in welcomes_to_send:
        log.info("Sending welcome %s to user %s %s" %
                 (welcome, user_data['email'], user_data['token']))
        send_message(welcome, user_data['email'], user_data['token'],
                     format)


@et_task
def confirm_user(token, user_data):
    """
    Confirm any pending subscriptions for the user with this token.

    If any of the subscribed newsletters have welcome messages,
    send them.

    :param token: User's token
    :param user_data: Dictionary with user's data from Exact Target,
        as returned by get_user_data(), or None if that wasn't available
        when this was called.
    """
    # Get user data if we don't already have it
    if user_data is None:
        from .views import get_user_data   # Avoid circular import
        user_data = get_user_data(token=token)
    if user_data is None:
        log.error("in confirm_user, unable to find user for token %s" % token)
        return
    if user_data['status'] == 'error':
        msg = "error getting user data for %s: %s" % \
              (token, user_data['desc'])
        log.error(msg)
        raise RetryTask(msg)
    if user_data['confirmed']:
        log.info("In confirm_user, user with token %s "
                 "is already confirmed" % token)
        return

    # Add user's token to the confirmation database at ET. A nightly
    # task will somehow do something about it.
    apply_updates(settings.EXACTTARGET_CONFIRMATION, {'TOKEN': token})

    # Now, if they're subscribed to any newsletters with confirmation
    # welcome messages, send those.
    send_welcomes(user_data, user_data['newsletters'],
                  user_data.get('format', 'H'))


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

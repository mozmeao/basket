from __future__ import absolute_import, unicode_literals

import datetime
import logging
from email.utils import formatdate
from functools import wraps
from hashlib import sha256
from time import mktime, time

from django.conf import settings
from django.core.cache import cache, get_cache

import requests
import simple_salesforce as sfapi
import user_agents
from celery.signals import task_failure, task_retry, task_success
from django_statsd.clients import statsd
from raven.contrib.django.raven_compat.models import client as sentry_client

from news.backends.common import NewsletterException, NewsletterNoResultsException
from news.backends.sfdc import sfdc
from news.backends.sfmc import sfmc
from news.celery import app as celery_app
from news.models import FailedTask, Newsletter, Interest, QueuedTask, TransactionalEmailMessage
from news.newsletters import get_sms_messages, get_transactional_message_ids
from news.utils import (generate_token, get_user_data,
                        parse_newsletters, parse_newsletters_csv, SUBSCRIBE, UNSUBSCRIBE)


log = logging.getLogger(__name__)

BAD_MESSAGE_ID_CACHE = get_cache('bad_message_ids')

# Base message ID for confirmation email
CONFIRMATION_MESSAGE = "confirmation_email"

# This is prefixed with the 2-letter language code + _ before sending,
# e.g. 'en_recovery_message', and '_T' if text, e.g. 'en_recovery_message_T'.
RECOVERY_MESSAGE_ID = 'SFDC_Recovery'
FXACCOUNT_WELCOME = 'FxAccounts_Welcome'

# don't propagate and don't retry if these are the error messages
IGNORE_ERROR_MSGS = [
    'InvalidEmailAddress',
    'An invalid phone number was provided',
]
# don't propagate after max retries if these are the error messages
IGNORE_ERROR_MSGS_POST_RETRY = [
    'There are no valid subscribers',
]
# tasks exempt from maintenance mode queuing
MAINTENANCE_EXEMPT = [
    'news.tasks.add_fxa_activity',
    'news.tasks.add_sms_user',
    'news.tasks.add_sms_user_optin',
]


def ignore_error(exc, to_ignore=IGNORE_ERROR_MSGS):
    msg = str(exc)
    for ignore_msg in to_ignore:
        if ignore_msg in msg:
            return True

    return False


def ignore_error_post_retry(exc):
    return ignore_error(exc, IGNORE_ERROR_MSGS_POST_RETRY)


def get_lock(key, prefix='task'):
    """Get a lock for a specific key (usually email address)

    Needs to be done with a timeout because SFDC needs some time to populate its
    indexes before the duplicate protection works and queries will return results.
    Releasing the lock right after the task was run still allowed dupes.

    Does nothing if you get the lock, and raises RetryTask if not.
    """
    if not settings.TASK_LOCKING_ENABLE:
        return

    lock_key = 'basket-{}-{}'.format(prefix, key)
    lock_key = sha256(lock_key).hexdigest()
    got_lock = cache.add(lock_key, True, settings.TASK_LOCK_TIMEOUT)
    if not got_lock:
        statsd.incr('news.tasks.get_lock.no_lock_retry')
        raise RetryTask('Could not acquire lock')


class BasketError(Exception):
    """Tasks can raise this when an error happens that we should not retry.
    E.g. if the error indicates we're passing bad parameters.
    (As opposed to an error connecting to ExactTarget at the moment,
    where we'd typically raise NewsletterException.)
    """
    def __init__(self, msg):
        super(BasketError, self).__init__(msg)


class RetryTask(Exception):
    """an exception to raise within a task if you just want to retry"""


@task_failure.connect
def on_task_failure(sender, task_id, exception, einfo, args, kwargs, **skwargs):
    statsd.incr(sender.name + '.failure')
    if not sender.name.endswith('snitch'):
        statsd.incr('news.tasks.failure_total')
        if settings.STORE_TASK_FAILURES:
            FailedTask.objects.create(
                task_id=task_id,
                name=sender.name,
                args=args,
                kwargs=kwargs,
                exc=repr(exception),
                # str() gives more info than repr() on celery.datastructures.ExceptionInfo
                einfo=str(einfo),
            )


@task_retry.connect
def on_task_retry(sender, **kwargs):
    statsd.incr(sender.name + '.retry')
    if not sender.name.endswith('snitch'):
        statsd.incr('news.tasks.retry_total')


@task_success.connect
def on_task_success(sender, **kwargs):
    statsd.incr(sender.name + '.success')
    if not sender.name.endswith('snitch'):
        statsd.incr('news.tasks.success_total')


def et_task(func):
    """Decorator to standardize ET Celery tasks."""
    @celery_app.task(bind=True,
                     default_retry_delay=300,  # 5 min
                     max_retries=8)
    @wraps(func)
    def wrapped(self, *args, **kwargs):
        start_time = kwargs.pop('start_time', None)
        if start_time and not self.request.retries:
            total_time = int((time() - start_time) * 1000)
            statsd.timing(self.name + '.timing', total_time)
        statsd.incr(self.name + '.total')
        statsd.incr('news.tasks.all_total')
        if settings.MAINTENANCE_MODE and self.name not in MAINTENANCE_EXEMPT:
            if not settings.READ_ONLY_MODE:
                # record task for later
                QueuedTask.objects.create(
                    name=self.name,
                    args=args,
                    kwargs=kwargs,
                )
                statsd.incr(self.name + '.queued')
            else:
                statsd.incr(self.name + '.not_queued')

            return

        try:
            return func(*args, **kwargs)
        except (IOError, NewsletterException, requests.RequestException,
                sfapi.SalesforceError, RetryTask) as e:
            # These could all be connection issues, so try again later.
            # IOError covers URLError and SSLError.
            if ignore_error(e):
                return

            try:
                if not (isinstance(e, RetryTask) or ignore_error_post_retry(e)):
                    sentry_client.captureException(tags={'action': 'retried'})

                raise self.retry(countdown=2 ** (self.request.retries + 1) * 60)
            except self.MaxRetriesExceededError:
                statsd.incr(self.name + '.retry_max')
                statsd.incr('news.tasks.retry_max_total')
                # don't bubble certain errors
                if ignore_error_post_retry(e):
                    return

                raise e

    return wrapped


def gmttime():
    d = datetime.datetime.now() + datetime.timedelta(minutes=10)
    stamp = mktime(d.timetuple())
    return formatdate(timeval=stamp, localtime=False, usegmt=True)


@et_task
def add_fxa_activity(data):
    user_agent = user_agents.parse(data['user_agent'])
    device_type = 'D'
    if user_agent.is_mobile:
        device_type = 'M'
    elif user_agent.is_tablet:
        device_type = 'T'

    apply_updates('Sync_Device_Logins', {
        'FXA_ID': data['fxa_id'],
        'LOGIN_DATE': gmttime(),
        'FIRST_DEVICE': 'y' if data.get('first_device') else 'n',
        'OS': user_agent.os.family,
        'OS_VERSION': user_agent.os.version_string,
        'BROWSER': '{0} {1}'.format(user_agent.browser.family,
                                    user_agent.browser.version_string),
        'DEVICE_NAME': user_agent.device.family,
        'DEVICE_TYPE': device_type,
    })


@et_task
def update_fxa_info(email, lang, fxa_id):
    try:
        apply_updates('Firefox_Account_ID', {
            'EMAIL_ADDRESS_': email,
            'CREATED_DATE_': gmttime(),
            'FXA_ID': fxa_id,
            'FXA_LANGUAGE_ISO2': lang,
        })
    except NewsletterException as e:
        # don't report these errors to sentry until retries exhausted
        raise RetryTask(str(e))


@et_task
def update_get_involved(interest_id, lang, name, email, country, email_format,
                        subscribe, message, source_url):
    """Send a user contribution information. Should be removed soon."""
    try:
        interest = Interest.objects.get(interest_id=interest_id)
    except Interest.DoesNotExist:
        # invalid request; no need to raise exception and retry
        return

    interest.notify_stewards(name, email, lang, message)


FSA_FIELDS = {
    'EMAIL_ADDRESS': 'email',
    'TOKEN': 'token',
    'FIRST_NAME': 'first_name',
    'LAST_NAME': 'last_name',
    'COUNTRY_': 'country',
    'STUDENTS_SCHOOL': 'fsa_school',
    'STUDENTS_GRAD_YEAR': 'fsa_grad_year',
    'STUDENTS_MAJOR': 'fsa_major',
    'STUDENTS_CITY': 'fsa_city',
    'STUDENTS_CURRENT_STATUS': 'fsa_current_status',
    'STUDENTS_ALLOW_SHARE': 'fsa_allow_share',
}


@et_task
def update_student_ambassadors(data, token):
    key = data.get('EMAIL_ADDRESS') or token
    get_lock(key)
    user_data = get_user_data(token=token)
    if not user_data:
        # try again later after user has been added
        raise RetryTask('User not found')

    update_data = {}
    for k, fn in FSA_FIELDS.items():
        if k in data:
            update_data[fn] = data[k]
            if k == 'STUDENTS_ALLOW_SHARE':
                # convert to boolean
                update_data[fn] = update_data[fn].lower().startswith('y')

    sfdc.update(user_data, update_data)


@et_task
def upsert_user(api_call_type, data):
    """
    Update or insert (upsert) a contact record in SFDC

    @param int api_call_type: What kind of API call it was. Could be
        SUBSCRIBE, UNSUBSCRIBE, or SET.
    @param dict data: POST data from the form submission
    @return:
    """
    key = data.get('email') or data.get('token')
    get_lock(key)
    upsert_contact(api_call_type, data,
                   get_user_data(data.get('token'), data.get('email'),
                                 extra_fields=['id']))


def upsert_contact(api_call_type, data, user_data):
    """
    Update or insert (upsert) a contact record in SFDC

    @param int api_call_type: What kind of API call it was. Could be
        SUBSCRIBE, UNSUBSCRIBE, or SET.
    @param dict data: POST data from the form submission
    @param dict user_data: existing contact data from SFDC
    @return: token, created
    """
    update_data = data.copy()
    forced_optin = data.pop('optin', False)
    if 'format' in data:
        update_data['format'] = 'T' if data['format'].upper().startswith('T') else 'H'

    newsletters = parse_newsletters_csv(data.get('newsletters'))

    if user_data:
        cur_newsletters = user_data.get('newsletters', None)
    else:
        cur_newsletters = None

    # check for and remove transactional newsletters
    if api_call_type == SUBSCRIBE:
        all_transactionals = set(get_transactional_message_ids())
        newsletters_set = set(newsletters)
        transactionals = newsletters_set & all_transactionals
        if transactionals:
            newsletters = list(newsletters_set - transactionals)
            send_transactional_messages(update_data, user_data, list(transactionals))
            if not newsletters:
                # no regular newsletters
                return None, None

    # Set the newsletter flags in the record by comparing to their
    # current subscriptions.
    update_data['newsletters'] = parse_newsletters(api_call_type, newsletters, cur_newsletters)

    if api_call_type != UNSUBSCRIBE and not (forced_optin or
                                             (user_data and user_data.get('optin'))):
        # Are they subscribing to any newsletters that don't require confirmation?
        # When including any newsletter that does not
        # require confirmation, user gets a pass on confirming and goes straight
        # to confirmed.
        to_subscribe = [nl for nl, sub in update_data['newsletters'].iteritems() if sub]
        if to_subscribe:
            exempt_from_confirmation = Newsletter.objects \
                .filter(slug__in=to_subscribe, requires_double_optin=False) \
                .exists()
            if exempt_from_confirmation:
                update_data['optin'] = True

    if user_data is None:
        # no user found. create new one.
        update_data['token'] = generate_token()
        if settings.MAINTENANCE_MODE:
            sfdc_add_update.delay(update_data)
        else:
            # don't catch exceptions here. SalesforceError subclasses will retry.
            sfdc.add(update_data)

        return update_data['token'], True

    if forced_optin and not user_data.get('optin'):
        update_data['optin'] = True

    # they opted out of email before, but are subscribing again
    # clear the optout flag
    if api_call_type != UNSUBSCRIBE and user_data.get('optout'):
        update_data['optout'] = False

    # update record
    if user_data and user_data.get('token'):
        token = user_data['token']
    else:
        token = update_data['token'] = generate_token()

    if settings.MAINTENANCE_MODE:
        sfdc_add_update.delay(update_data, user_data)
    else:
        sfdc.update(user_data, update_data)

    return token, False


@et_task
def sfdc_add_update(update_data, user_data=None):
    # for use with maintenance mode only
    # TODO remove after maintenance is over and queue is processed
    if user_data:
        sfdc.update(user_data, update_data)
    else:
        try:
            sfdc.add(update_data)
        except sfapi.SalesforceMalformedRequest as e:  # noqa
            # possibly a duplicate email. try the update below.
            user_data = get_user_data(email=update_data['email'], extra_fields=['id'])
            if user_data:
                # we have a user, delete generated token
                # and continue with an update
                update_data.pop('token', None)
                sfdc.update(user_data, update_data)
            else:
                # still no user, try the add one more time
                sfdc.add(update_data)


def send_transactional_messages(data, user_data, transactionals):
    email = data['email']
    lang_code = data.get('lang', 'en')[:2].lower()
    msgs = TransactionalEmailMessage.objects.filter(message_id__in=transactionals)
    if user_data and 'id' in user_data:
        sfdc_id = user_data['id']
    else:
        sfdc_id = None

    for tm in msgs:
        languages = [lang[:2].lower() for lang in tm.language_list]
        if lang_code not in languages:
            # Newsletter does not support their preferred language, so
            # it doesn't have a welcome in that language either. Settle
            # for English, same as they'll be getting the newsletter in.
            lang_code = 'en'

        msg_id = mogrify_message_id(tm.vendor_id, lang_code, 'H')
        send_message.delay(msg_id, email, sfdc_id or email)


def apply_updates(database, record):
    """Send the record data to ET to update the database named
    target_et.

    :param str database: Target database, e.g. 'Firefox_Account_ID'
    :param dict record: Data to send
    """
    sfmc.upsert_row(database, record)


@et_task
def send_message(message_id, email, subscriber_key, format=None, token=None):
    """
    Ask ET to send a message.

    @param str message_id: ID of the message in ET
    @param str email: email to send it to
    @param str subscriber_key: id of the email user (email or SFDC id)
    @param token: optional token when sending recovery
    @param format: vestigial argument so that old style tasks on the queue
                   at deployment don't fail
                   TODO remove after initial deployment

    @raises: NewsletterException for retryable errors, BasketError for
        fatal errors.
    """
    if BAD_MESSAGE_ID_CACHE.get(message_id, False):
        return

    try:
        sfmc.send_mail(message_id, email, subscriber_key, token)
        statsd.incr('news.tasks.send_message.' + message_id)
    except NewsletterException as e:
        # Better error messages for some cases. Also there's no point in
        # retrying these
        if 'Invalid Customer Key' in e.message:
            # remember it's a bad message ID so we don't try again during this process.
            BAD_MESSAGE_ID_CACHE.set(message_id, True)
            return
        # we should retry
        raise


def mogrify_message_id(message_id, lang, format):
    """Given a bare message ID, a language code, and a format (T or H),
    return a message ID modified to specify that language and format.

    E.g. on input ('MESSAGE', 'fr', 'T') it returns 'fr_MESSAGE_T',
    or on input ('MESSAGE', 'pt', 'H') it returns 'pt_MESSAGE'

    If `lang` is None or empty, it skips prefixing the language.
    """
    if lang:
        result = "%s_%s" % (lang.lower()[:2], message_id)
    else:
        result = message_id
    if format == 'T':
        result += "_T"
    return result


DOI_FLAGS_MAP = {
    'ABOUT_MOBILE': 'mobile',
    'ABOUT_MOZILLA': 'about-mozilla',
    'APP_DEV': 'app-dev',
    'CONNECTED_DEVICES': 'connected-devices',
    'DEV_EVENTS': 'developer-events',
    'FIREFOX_ACCOUNTS_JOURNEY': 'firefox-accounts-journey',
    'FIREFOX_DESKTOP': 'firefox-desktop',
    'FIREFOX_FRIENDS': 'firefox-friends',
    'FIREFOX_IOS': 'firefox-ios',
    'FOUNDATION': 'mozilla-foundation',
    'GAMEDEV_CONF': 'game-developer-conference',
    'GET_INVOLVED': 'get-involved',
    'MAKER_PARTY': 'maker-party',
    'MOZFEST': 'mozilla-festival',
    'MOZILLA_AND_YOU': 'mozilla-and-you',
    'MOZILLA_GENERAL': 'mozilla-general',
    'MOZILLA_PHONE': 'mozilla-phone',
    'MOZ_LEARN': 'mozilla-learning-network',
    'SHAPE_WEB': 'shape-web',
    'STUDENT_AMBASSADORS': 'ambassadors',
    'VIEW_SOURCE_GLOBAL': 'view-source-conference-global',
    'VIEW_SOURCE_NA': 'view-source-conference-north-america',
    'WEBMAKER': 'webmaker',
    'TEST_PILOT': 'test-pilot',
    'IOS_TEST_FLIGHT': 'ios-beta-test-flight',
}
DOI_FIELDS_MAP = {
    'EMAIL_FORMAT_': 'format',
    'EMAIL_ADDRESS_': 'email',
    'LANGUAGE_ISO2': 'lang',
    'SOURCE_URL': 'source_url',
    'FIRST_NAME': 'first_name',
    'LAST_NAME': 'last_name',
    'COUNTRY_': 'country',
}


# TODO remove this and the data above a few months after SFDC deployment
def get_sfmc_doi_user(token):
    nl_flags = ['{}_FLG'.format(f) for f in DOI_FLAGS_MAP]
    try:
        row = sfmc.get_row('Double_Opt_In', nl_flags + DOI_FIELDS_MAP.keys(), token=token)
    except NewsletterNoResultsException:
        return None

    newsletters = []
    for sfmc_id, slug in DOI_FLAGS_MAP.items():
        val = (row.get('{}_FLG'.format(sfmc_id)) or 'n').lower()
        if val == 'y':
            newsletters.append(slug)

    record = {}
    for sfmc_id, fid in DOI_FIELDS_MAP.items():
        val = row.get(sfmc_id)
        if val:
            record[fid] = val

    record['newsletters'] = newsletters
    record['token'] = token

    return record


@et_task
def confirm_user(token):
    """
    Confirm any pending subscriptions for the user with this token.

    If any of the subscribed newsletters have welcome messages,
    send them.

    :param token: User's token
    :param user_data: Dictionary with user's data from Exact Target,
        as returned by get_user_data(), or None if that wasn't available
        when this was called.
    :raises: BasketError for fatal errors, NewsletterException for retryable
        errors.
    """
    get_lock(token)
    user_data = get_user_data(token=token)

    if user_data is None:
        user = get_sfmc_doi_user(token)
        if user and user.get('email'):
            get_lock(user['email'])
            user['optin'] = True
            try:
                sfdc.add(user)
            except sfapi.SalesforceMalformedRequest:
                # probably already know the email address
                sfdc.update({'email': user['email']}, user)
            statsd.incr('news.tasks.confirm_user.moved_from_sfmc')
        else:
            statsd.incr('news.tasks.confirm_user.confirm_user_not_found')

        return

    if user_data['optin']:
        # already confirmed
        return

    if not ('email' in user_data and user_data['email']):
        raise BasketError('token has no email in ET')

    sfdc.update(user_data, {'optin': True})


@et_task
def add_sms_user(send_name, mobile_number, optin):
    messages = get_sms_messages()
    if send_name not in messages:
        return

    sfmc.send_sms([mobile_number], messages[send_name])
    if optin:
        add_sms_user_optin.delay(mobile_number)


@et_task
def add_sms_user_optin(mobile_number):
    record = {'Phone': mobile_number, 'SubscriberKey': mobile_number}
    sfmc.add_row('Mobile_Subscribers', record)


@et_task
def update_custom_unsub(token, reason):
    """Record a user's custom unsubscribe reason."""
    get_lock(token)
    try:
        sfdc.update({'token': token}, {'reason': reason})
    except sfapi.SalesforceMalformedRequest:
        # likely the record can't be found. try the DoI DE.
        user = get_sfmc_doi_user(token)
        if user and user.get('email'):
            get_lock(user['email'])
            user['reason'] = reason
            try:
                sfdc.add(user)
            except sfapi.SalesforceMalformedRequest:
                # probably already know the email address
                sfdc.update({'email': user['email']}, user)


@et_task
def send_recovery_message_task(email):
    user_data = get_user_data(email=email, extra_fields=['id'])
    if not user_data:
        log.debug("In send_recovery_message_task, email not known: %s" % email)
        return

    # make sure we have a language and format, no matter what ET returned
    lang = user_data.get('lang', 'en') or 'en'
    format = user_data.get('format', 'H') or 'H'

    if lang not in settings.RECOVER_MSG_LANGS:
        lang = 'en'

    message_id = mogrify_message_id(RECOVERY_MESSAGE_ID, lang, format)
    send_message.delay(message_id, email, user_data['id'], token=user_data['token'])


@celery_app.task()
def snitch(start_time=None):
    if start_time is None:
        snitch.delay(time())
        return

    snitch_id = settings.SNITCH_ID
    totalms = int((time() - start_time) * 1000)
    statsd.timing('news.tasks.snitch.timing', totalms)
    requests.post('https://nosnch.in/{}'.format(snitch_id), data={
        'm': totalms,
    })

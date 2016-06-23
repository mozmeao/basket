from __future__ import absolute_import
import datetime
import logging
from email.utils import formatdate
from functools import wraps
from time import mktime, time

from django.conf import settings
from django.core.cache import get_cache
from django_statsd.clients import statsd

import requests
import user_agents
import simple_salesforce as sfapi
from celery import Task
from raven.contrib.django.raven_compat.models import client as sentry_client

from news.backends.common import NewsletterException
from news.backends.sfdc import sfdc
from news.backends.sfmc import sfmc
from news.celery import app as celery_app
from news.models import FailedTask, Newsletter, Interest, QueuedTask, TransactionalEmailMessage
from news.newsletters import (get_sms_messages, get_transactional_message_ids,
                              is_supported_newsletter_language)
from news.utils import (generate_token, get_user_data, MSG_USER_NOT_FOUND,
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


class BasketError(Exception):
    """Tasks can raise this when an error happens that we should not retry.
    E.g. if the error indicates we're passing bad parameters.
    (As opposed to an error connecting to ExactTarget at the moment,
    where we'd typically raise NewsletterException.)
    """
    def __init__(self, msg):
        super(BasketError, self).__init__(msg)


class ETTask(Task):
    abstract = True
    default_retry_delay = 60 * 5  # 5 minutes
    max_retries = 8  # ~ 30 min

    def on_success(self, retval, task_id, args, kwargs):
        """Success handler.

        Run by the worker if the task executes successfully.

        :param retval: The return value of the task.
        :param task_id: Unique id of the executed task.
        :param args: Original arguments for the executed task.
        :param kwargs: Original keyword arguments for the executed task.

        The return value of this handler is ignored.

        """
        statsd.incr(self.name + '.success')
        statsd.incr('news.tasks.success_total')

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Error handler.

        This is run by the worker when the task fails.

        :param exc: The exception raised by the task.
        :param task_id: Unique id of the failed task.
        :param args: Original arguments for the task that failed.
        :param kwargs: Original keyword arguments for the task
                       that failed.

        :keyword einfo: :class:`~celery.datastructures.ExceptionInfo`
                        instance, containing the traceback.

        The return value of this handler is ignored.

        """
        statsd.incr(self.name + '.failure')
        statsd.incr('news.tasks.failure_total')
        if settings.STORE_TASK_FAILURES:
            FailedTask.objects.create(
                task_id=task_id,
                name=self.name,
                args=args,
                kwargs=kwargs,
                exc=repr(exc),
                einfo=str(einfo),  # str() gives more info than repr() on celery.datastructures.ExceptionInfo
            )

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Retry handler.

        This is run by the worker when the task is to be retried.

        :param exc: The exception sent to :meth:`retry`.
        :param task_id: Unique id of the retried task.
        :param args: Original arguments for the retried task.
        :param kwargs: Original keyword arguments for the retried task.

        :keyword einfo: :class:`~celery.datastructures.ExceptionInfo`
                        instance, containing the traceback.

        The return value of this handler is ignored.

        """
        statsd.incr(self.name + '.retry')
        statsd.incr('news.tasks.retry_total')


def et_task(func):
    """Decorator to standardize ET Celery tasks."""
    @celery_app.task(base=ETTask)
    @wraps(func)
    def wrapped(*args, **kwargs):
        start_time = kwargs.pop('start_time', None)
        if start_time:
            total_time = int((time() - start_time) * 1000)
            statsd.timing(wrapped.name + '.timing', total_time)
        statsd.incr(wrapped.name + '.total')
        statsd.incr('news.tasks.all_total')
        if settings.MAINTENANCE_MODE and wrapped.name not in MAINTENANCE_EXEMPT:
            if not settings.READ_ONLY_MODE:
                # record task for later
                QueuedTask.objects.create(
                    name=wrapped.name,
                    args=args,
                    kwargs=kwargs,
                )
                statsd.incr(wrapped.name + '.queued')
            else:
                statsd.incr(wrapped.name + '.not_queued')

            return

        try:
            return func(*args, **kwargs)
        except (IOError, NewsletterException, requests.RequestException,
                sfapi.SalesforceError) as e:
            # These could all be connection issues, so try again later.
            # IOError covers URLError and SSLError.
            exc_msg = str(e)
            # but don't retry for certain error messages
            for ignore_msg in IGNORE_ERROR_MSGS:
                if ignore_msg in exc_msg:
                    return

            try:
                sentry_client.captureException(tags={'action': 'retried'})
                wrapped.retry(args=args, kwargs=kwargs,
                              countdown=(2 ** wrapped.request.retries) * 60)
            except wrapped.MaxRetriesExceededError:
                statsd.incr(wrapped.name + '.retry_max')
                statsd.incr('news.tasks.retry_max_total')
                # don't bubble certain errors
                for ignore_msg in IGNORE_ERROR_MSGS_POST_RETRY:
                    if ignore_msg in exc_msg:
                        return

                raise e

    return wrapped


def gmttime():
    d = datetime.datetime.now() + datetime.timedelta(minutes=10)
    stamp = mktime(d.timetuple())
    return formatdate(timeval=stamp, localtime=False, usegmt=True)


@et_task
def add_fxa_activity(data):
    record = {
        'FXA_ID': data['fxa_id'],
        'LOGIN_DATE': gmttime(),
        'FIRST_DEVICE': 'y' if data.get('first_device') else 'n',
    }
    if 'user_agent' in data:
        user_agent = user_agents.parse(data['user_agent'])
        device_type = 'D'
        if user_agent.is_mobile:
            device_type = 'M'
        elif user_agent.is_tablet:
            device_type = 'T'

        record.update({
            'OS': user_agent.os.family,
            'OS_VERSION': user_agent.os.version_string,
            'BROWSER': '{0} {1}'.format(user_agent.browser.family,
                                        user_agent.browser.version_string),
            'DEVICE_NAME': user_agent.device.family,
            'DEVICE_TYPE': device_type,
        })

    apply_updates('Sync_Device_Logins', record)


@et_task
def update_fxa_info(email, lang, fxa_id, **kwargs):
    # TODO can remove kwargs after deployment. only here for backward compat
    #      with tasks that may be on the queue when first deployed.
    apply_updates('Firefox_Account_ID', {
        'EMAIL_ADDRESS_': email,
        'CREATED_DATE_': gmttime(),
        'FXA_ID': fxa_id,
        'FXA_LANGUAGE_ISO2': lang,
    })


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
    user_data = {'token': token}
    update_data = {}
    for k, fn in FSA_FIELDS.items():
        if k in data:
            update_data[fn] = data[k]
            if k == 'STUDENTS_ALLOW_SHARE':
                # convert to boolean
                update_data[fn] = update_data[fn].lower().startswith('y')

    sfdc.update(user_data, update_data)


@et_task
def update_user(data, email, token, api_call_type, optin):
    """Legacy Task for updating user's preferences and newsletters.

    @param dict data: POST data from the form submission
    @param string email: User's email address
    @param string token: User's token. If None, the token will be
        looked up, and if no token is found, one will be created for the
        given email.
    @param int api_call_type: What kind of API call it was. Could be
        SUBSCRIBE, UNSUBSCRIBE, or SET.
    @param boolean optin: legacy option. it is now included in data. may be removed after
        initial deployment (required so that existing tasks in the queue won't fail for having
        too many arguments).

    @returns: None
    @raises: NewsletterException if there are any errors that would be
        worth retrying. Our task wrapper will retry in that case.

    TODO remove after initial deployment
    """
    # backward compat with existing items on the queue when deployed.
    if optin is not None:
        data['optin'] = optin

    upsert_contact(api_call_type, data, get_user_data(email=email, token=token,
                                                      extra_fields=['id']))


@et_task
def upsert_user(api_call_type, data):
    """
    Update or insert (upsert) a contact record in SFDC

    @param int api_call_type: What kind of API call it was. Could be
        SUBSCRIBE, UNSUBSCRIBE, or SET.
    @param dict data: POST data from the form submission
    @return:
    """
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

    lang = data.get('lang', 'en')[:2].lower()
    if is_supported_newsletter_language(lang):
        update_data['lang'] = lang
    else:
        # use our default language (English) if we don't support the language
        update_data['lang'] = 'en'

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
        try:
            if settings.MAINTENANCE_MODE:
                sfdc_add_update.delay(update_data)
            else:
                sfdc.add(update_data)

            return update_data['token'], True
        except sfapi.SalesforceMalformedRequest as e:  # noqa
            # possibly a duplicate email. try the update below.
            user_data = get_user_data(email=data['email'], extra_fields=['id'])
            if user_data:
                # we have a user, delete generated token
                # and continue with an update
                del update_data['token']
            else:
                # still no user, try the add one more time
                if settings.MAINTENANCE_MODE:
                    sfdc_add_update.delay(update_data)
                else:
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
    user_data = get_user_data(token=token)

    if user_data is None:
        raise BasketError(MSG_USER_NOT_FOUND)

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
    sfdc.update({'token': token}, {'reason': reason})


def attempt_fix(database, record, task, e):
    # Sometimes a user is in basket's database but not in
    # ExactTarget because the API failed or something. If that's
    # the case, any future API call will error because basket
    # won't add the required CREATED_DATE field. Try to add them
    # with it here.
    if e.message.find('CREATED_DATE_') != -1:
        record['CREATED_DATE_'] = gmttime()
        sfmc.add_row(database, record)
    else:
        raise e


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

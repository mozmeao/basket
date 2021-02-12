import json
import logging
from copy import deepcopy
from datetime import datetime, timedelta
from email.utils import formatdate
from functools import wraps
from hashlib import sha256
from time import mktime, time
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache, caches
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.timezone import now

import requests
import sentry_sdk
import simple_salesforce as sfapi
import user_agents
from celery.signals import task_failure, task_retry, task_success
from celery.utils.time import get_exponential_backoff_interval
from dateutil.parser import isoparse
from django_statsd.clients import statsd

from basket.base.utils import email_is_testing
from basket.news.backends.common import NewsletterException
from basket.news.backends.sfdc import sfdc
from basket.news.backends.sfmc import sfmc
from basket.news.celery import app as celery_app
from basket.news.models import (
    FailedTask,
    Newsletter,
    Interest,
    QueuedTask,
    TransactionalEmailMessage,
    CommonVoiceUpdate,
)
from basket.news.newsletters import (
    get_sms_vendor_id,
    get_transactional_message_ids,
    newsletter_map,
    newsletter_languages,
)
from basket.news.utils import (
    generate_token,
    get_accept_languages,
    get_best_language,
    get_user_data,
    iso_format_unix_timestamp,
    parse_newsletters,
    parse_newsletters_csv,
    SUBSCRIBE,
    UNSUBSCRIBE,
    get_best_supported_lang,
)

log = logging.getLogger(__name__)

BAD_MESSAGE_ID_CACHE = caches["bad_message_ids"]

# Base message ID for confirmation email
CONFIRMATION_MESSAGE = "confirmation_email"

# This is prefixed with the 2-letter language code + _ before sending,
# e.g. 'en_recovery_message', and '_T' if text, e.g. 'en_recovery_message_T'.
RECOVERY_MESSAGE_ID = "SFDC_Recovery"
FXACCOUNT_WELCOME = "FxAccounts_Welcome"

# don't propagate and don't retry if these are the error messages
IGNORE_ERROR_MSGS = [
    "INVALID_EMAIL_ADDRESS",
    "InvalidEmailAddress",
    "An invalid phone number was provided",
    "No valid subscribers were provided",
    "There are no valid subscribers",
]
# don't propagate after max retries if these are the error messages
IGNORE_ERROR_MSGS_POST_RETRY = []
# tasks exempt from maintenance mode queuing
MAINTENANCE_EXEMPT = [
    "news.tasks.add_sms_user",
    "news.tasks.add_sms_user_optin",
]


def exponential_backoff(retries):
    """
    Return a number of seconds to delay the next task attempt using
    an exponential back-off algorithm with jitter.

    See https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/

    :param retries: Number of retries so far
    :return: number of seconds to delay the next try
    """
    backoff_minutes = get_exponential_backoff_interval(
        factor=2,
        retries=retries,
        maximum=settings.CELERY_MAX_RETRY_DELAY_MINUTES,
        full_jitter=True,
    )
    # wait for a minimum of 1 minute
    return max(1, backoff_minutes) * 60


def ignore_error(exc, to_ignore=IGNORE_ERROR_MSGS):
    msg = str(exc)
    for ignore_msg in to_ignore:
        if ignore_msg in msg:
            return True

    return False


def ignore_error_post_retry(exc):
    return ignore_error(exc, IGNORE_ERROR_MSGS_POST_RETRY)


def get_lock(key, prefix="task"):
    """Get a lock for a specific key (usually email address)

    Needs to be done with a timeout because SFDC needs some time to populate its
    indexes before the duplicate protection works and queries will return results.
    Releasing the lock right after the task was run still allowed dupes.

    Does nothing if you get the lock, and raises RetryTask if not.
    """
    if not settings.TASK_LOCKING_ENABLE:
        return

    lock_key = "basket-{}-{}".format(prefix, key)
    lock_key = sha256(lock_key.encode()).hexdigest()
    got_lock = cache.add(lock_key, True, settings.TASK_LOCK_TIMEOUT)
    if not got_lock:
        statsd.incr("news.tasks.get_lock.no_lock_retry")
        raise RetryTask("Could not acquire lock")


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
    statsd.incr(sender.name + ".failure")
    if not sender.name.endswith("snitch"):
        statsd.incr("news.tasks.failure_total")
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
    statsd.incr(sender.name + ".retry")
    if not sender.name.endswith("snitch"):
        statsd.incr("news.tasks.retry_total")


@task_success.connect
def on_task_success(sender, **kwargs):
    statsd.incr(sender.name + ".success")
    if not sender.name.endswith("snitch"):
        statsd.incr("news.tasks.success_total")


def et_task(func):
    """Decorator to standardize ET Celery tasks."""
    full_task_name = "news.tasks.%s" % func.__name__

    # continue to use old names regardless of new layout
    @celery_app.task(
        name=full_task_name,
        bind=True,
        default_retry_delay=300,
        max_retries=12,  # 5 min
    )
    @wraps(func)
    def wrapped(self, *args, **kwargs):
        start_time = kwargs.pop("start_time", None)
        if start_time and not self.request.retries:
            total_time = int((time() - start_time) * 1000)
            statsd.timing(self.name + ".timing", total_time)
        statsd.incr(self.name + ".total")
        statsd.incr("news.tasks.all_total")
        if settings.MAINTENANCE_MODE and self.name not in MAINTENANCE_EXEMPT:
            if not settings.READ_ONLY_MODE:
                # record task for later
                QueuedTask.objects.create(
                    name=self.name, args=args, kwargs=kwargs,
                )
                statsd.incr(self.name + ".queued")
            else:
                statsd.incr(self.name + ".not_queued")

            return

        try:
            return func(*args, **kwargs)
        except (
            IOError,
            NewsletterException,
            requests.RequestException,
            RetryTask,
            sfapi.SalesforceExpiredSession,
            sfapi.SalesforceGeneralError,
            sfapi.SalesforceRefusedRequest,
            sfapi.SalesforceResourceNotFound,
            sfapi.SalesforceAuthenticationFailed,
            sfapi.SalesforceMalformedRequest,
        ) as e:
            # These could all be connection issues, so try again later.
            # IOError covers URLError and SSLError.
            if ignore_error(e):
                return

            try:
                if not (isinstance(e, RetryTask) or ignore_error_post_retry(e)):
                    with sentry_sdk.configure_scope() as scope:
                        scope.set_tag("action", "retried")
                        sentry_sdk.capture_exception()

                # ~68 hr at 11 retries
                statsd.incr(f"{self.name}.retries.{self.request.retries}")
                statsd.incr(f"news.tasks.retries.{self.request.retries}")
                raise self.retry(countdown=exponential_backoff(self.request.retries))
            except self.MaxRetriesExceededError:
                statsd.incr(self.name + ".retry_max")
                statsd.incr("news.tasks.retry_max_total")
                # don't bubble certain errors
                if ignore_error_post_retry(e):
                    return

                sentry_sdk.capture_exception()

    return wrapped


def gmttime(basetime=None):
    if basetime is None:
        basetime = datetime.now()
    d = basetime + timedelta(minutes=10)
    stamp = mktime(d.timetuple())
    return formatdate(timeval=stamp, localtime=False, usegmt=True)


def fxa_source_url(metrics):
    source_url = settings.FXA_REGISTER_SOURCE_URL
    query = {k: v for k, v in metrics.items() if k.startswith("utm_")}
    if query:
        source_url = "?".join((source_url, urlencode(query)))

    return source_url


@et_task
def fxa_email_changed(data):
    ts = data["ts"]
    fxa_id = data["uid"]
    email = data["email"]
    cache_key = "fxa_email_changed:%s" % fxa_id
    prev_ts = float(cache.get(cache_key, 0))
    if prev_ts and prev_ts > ts:
        # message older than our last update for this UID
        return

    # Update SFDC
    user_data = get_user_data(fxa_id=fxa_id, extra_fields=["id"])
    if user_data:
        sfdc.update(user_data, {"fxa_primary_email": email})
    else:
        # FxA record not found, try email
        user_data = get_user_data(email=email, extra_fields=["id"])
        if user_data:
            sfdc.update(user_data, {"fxa_id": fxa_id, "fxa_primary_email": email})
        else:
            # No matching record for Email or FxA ID. Create one.
            sfdc.add({"email": email, "fxa_id": fxa_id, "fxa_primary_email": email})
            statsd.incr("news.tasks.fxa_email_changed.user_not_found")

    sfmc.upsert_row("FXA_EmailUpdated", {"FXA_ID": fxa_id, "NewEmailAddress": email})

    cache.set(cache_key, ts, 7200)  # 2 hr


def fxa_direct_update_contact(fxa_id, data):
    """Set some small data for a contact with an FxA ID

    Ignore if contact with FxA ID can't be found
    """
    try:
        sfdc.contact.update(f"FxA_Id__c/{fxa_id}", data)
    except sfapi.SalesforceMalformedRequest as e:
        if e.content[0]["errorCode"] == "REQUIRED_FIELD_MISSING":
            # couldn't find the fxa_id and tried to create a record but doesn't
            # have the required data to do so. We can drop this one.
            return
        else:
            # otherwise it's something else and we should potentially retry
            raise


@et_task
def fxa_last_login(fxa_id, timestamp):
    fxa_direct_update_contact(
        fxa_id,
        {"FxA_Last_Login__c": iso_format_unix_timestamp(timestamp, date_only=True)},
    )


@et_task
def fxa_delete(data):
    fxa_direct_update_contact(data["uid"], {"FxA_Account_Deleted__c": True})


@et_task
def fxa_verified(data):
    """Add new FxA users to SFDC"""
    # if we're not using the sandbox ignore testing domains
    if email_is_testing(data["email"]):
        return

    lang = get_best_language(get_accept_languages(data.get("locale")))
    if not lang or lang not in newsletter_languages():
        lang = "other"

    email = data["email"]
    fxa_id = data["uid"]
    create_date = data.get("createDate", data.get("ts"))
    newsletters = data.get("newsletters")
    metrics = data.get("metricsContext", {})
    new_data = {
        "email": email,
        "source_url": fxa_source_url(metrics),
        "country": data.get("countryCode", ""),
        "fxa_lang": data.get("locale"),
        "fxa_service": data.get("service", ""),
        "fxa_id": fxa_id,
        "optin": True,
        "format": "H",
    }
    if create_date:
        new_data["fxa_create_date"] = iso_format_unix_timestamp(create_date)

    newsletters = newsletters or []
    newsletters.append(settings.FXA_REGISTER_NEWSLETTER)
    new_data["newsletters"] = newsletters

    user_data = get_fxa_user_data(fxa_id, email)
    # don't overwrite the user's language if already set
    if not (user_data and user_data.get("lang")):
        new_data["lang"] = lang

    upsert_contact(SUBSCRIBE, new_data, user_data)


@et_task
def fxa_newsletters_update(data):
    email = data["email"]
    fxa_id = data["uid"]
    new_data = {
        "email": email,
        "newsletters": data["newsletters"],
        "source_url": settings.FXA_REGISTER_SOURCE_URL,
        "country": data.get("countryCode", ""),
        "fxa_lang": data.get("locale"),
        "fxa_id": fxa_id,
        "optin": True,
        "format": "H",
    }
    upsert_contact(SUBSCRIBE, new_data, get_fxa_user_data(fxa_id, email))


@et_task
def fxa_login(data):
    email = data["email"]
    # if we're not using the sandbox ignore testing domains
    if email_is_testing(email):
        return

    ua = data.get("userAgent")
    if ua:
        new_data = {
            "user_agent": ua,
            "fxa_id": data["uid"],
            "first_device": data["deviceCount"] == 1,
            "service": data.get("service", ""),
        }
        _add_fxa_activity(new_data)

    metrics = data.get("metricsContext", {})
    newsletter = settings.FXA_LOGIN_CAMPAIGNS.get(metrics.get("utm_campaign"))
    if newsletter:
        upsert_user.delay(
            SUBSCRIBE,
            {
                "email": email,
                "newsletters": newsletter,
                "source_url": fxa_source_url(metrics),
                "country": data.get("countryCode", ""),
            },
        )


def _add_fxa_activity(data):
    user_agent = user_agents.parse(data["user_agent"])
    device_type = "D"
    if user_agent.is_mobile:
        device_type = "M"
    elif user_agent.is_tablet:
        device_type = "T"

    apply_updates(
        "Sync_Device_Logins",
        {
            "FXA_ID": data["fxa_id"],
            "SERVICE": data["service"],
            "LOGIN_DATE": gmttime(),
            "FIRST_DEVICE": "y" if data.get("first_device") else "n",
            "OS": user_agent.os.family,
            "OS_VERSION": user_agent.os.version_string,
            "BROWSER": "{0} {1}".format(
                user_agent.browser.family, user_agent.browser.version_string,
            ),
            "DEVICE_NAME": user_agent.device.family,
            "DEVICE_TYPE": device_type,
        },
    )


@et_task
def update_get_involved(
    interest_id,
    lang,
    name,
    email,
    country,
    email_format,
    subscribe,
    message,
    source_url,
):
    """Send a user contribution information. Should be removed soon."""
    try:
        interest = Interest.objects.get(interest_id=interest_id)
    except Interest.DoesNotExist:
        # invalid request; no need to raise exception and retry
        return

    interest.notify_stewards(name, email, lang, message)


@et_task
def update_user_meta(token, data):
    """Update a user's metadata, not newsletters"""
    sfdc.update({"token": token}, data)


@et_task
def upsert_user(api_call_type, data):
    """
    Update or insert (upsert) a contact record in SFDC

    @param int api_call_type: What kind of API call it was. Could be
        SUBSCRIBE, UNSUBSCRIBE, or SET.
    @param dict data: POST data from the form submission
    @return:
    """
    key = data.get("email") or data.get("token")
    get_lock(key)
    upsert_contact(
        api_call_type,
        data,
        get_user_data(
            token=data.get("token"), email=data.get("email"), extra_fields=["id"],
        ),
    )


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
    forced_optin = data.pop("optin", False)
    if "format" in data:
        update_data["format"] = "T" if data["format"].upper().startswith("T") else "H"

    newsletters = parse_newsletters_csv(data.get("newsletters"))

    if user_data:
        cur_newsletters = user_data.get("newsletters", None)
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
    update_data["newsletters"] = parse_newsletters(
        api_call_type, newsletters, cur_newsletters,
    )

    if api_call_type != UNSUBSCRIBE:
        # Are they subscribing to any newsletters that don't require confirmation?
        # When including any newsletter that does not
        # require confirmation, user gets a pass on confirming and goes straight
        # to confirmed.
        to_subscribe = [nl for nl, sub in update_data["newsletters"].items() if sub]
        if to_subscribe and not (
            forced_optin or (user_data and user_data.get("optin"))
        ):
            exempt_from_confirmation = Newsletter.objects.filter(
                slug__in=to_subscribe, requires_double_optin=False,
            ).exists()
            if exempt_from_confirmation:
                update_data["optin"] = True

        # record source URL
        nl_map = newsletter_map()
        source_url = update_data.get("source_url")
        email = update_data.get("email")
        if not email:
            email = user_data.get("email") if user_data else None

        if email:
            # send all newsletters whether already subscribed or not
            # bug 1308971
            # if api_call_type == SET this is pref center, so only send new subscriptions
            nl_list = newsletters if api_call_type == SUBSCRIBE else to_subscribe
            for nlid in nl_list:
                if nlid in nl_map:
                    record_source_url.delay(email, source_url, nl_map[nlid])

    if user_data is None:
        # no user found. create new one.
        update_data["token"] = generate_token()
        if settings.MAINTENANCE_MODE:
            sfdc_add_update.delay(update_data)
        else:
            # don't catch exceptions here. SalesforceError subclasses will retry.
            sfdc.add(update_data)

        return update_data["token"], True

    if forced_optin and not user_data.get("optin"):
        update_data["optin"] = True

    # they opted out of email before, but are subscribing again
    # clear the optout flag
    if api_call_type != UNSUBSCRIBE and user_data.get("optout"):
        update_data["optout"] = False

    # update record
    if user_data and user_data.get("token"):
        token = user_data["token"]
    else:
        token = update_data["token"] = generate_token()

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
            user_data = get_user_data(email=update_data["email"], extra_fields=["id"])
            if user_data:
                # we have a user, delete generated token
                # and continue with an update
                update_data.pop("token", None)
                sfdc.update(user_data, update_data)
            else:
                # still no user, try the add one more time
                sfdc.add(update_data)


def send_transactional_messages(data, user_data, transactionals):
    email = data["email"]
    lang_code = data.get("lang", "en")[:2].lower()
    msgs = TransactionalEmailMessage.objects.filter(message_id__in=transactionals)
    if user_data and "id" in user_data:
        sfdc_id = user_data["id"]
    else:
        sfdc_id = None

    for tm in msgs:
        languages = [lang[:2].lower() for lang in tm.language_list]
        if lang_code not in languages:
            # Newsletter does not support their preferred language, so
            # it doesn't have a welcome in that language either. Settle
            # for English, same as they'll be getting the newsletter in.
            lang_code = "en"

        msg_id = mogrify_message_id(tm.vendor_id, lang_code, "H")
        send_message.delay(msg_id, email, sfdc_id or email)


def apply_updates(database, record):
    """Send the record data to ET to update the database named
    target_et.

    :param str database: Target database, e.g. 'Firefox_Account_ID'
    :param dict record: Data to send
    """
    sfmc.upsert_row(database, record)


@et_task
def send_message(message_id, email, subscriber_key, token=None):
    """
    Ask ET to send a message.

    @param str message_id: ID of the message in ET
    @param str email: email to send it to
    @param str subscriber_key: id of the email user (email or SFDC id)
    @param token: optional token when sending recovery

    @raises: NewsletterException for retryable errors, BasketError for
        fatal errors.
    """
    if BAD_MESSAGE_ID_CACHE.get(message_id, False):
        return

    try:
        sfmc.send_mail(message_id, email, subscriber_key, token)
        statsd.incr("news.tasks.send_message." + message_id)
    except NewsletterException as e:
        # Better error messages for some cases. Also there's no point in
        # retrying these
        if "Invalid Customer Key" in str(e):
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
    if format == "T":
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
    get_lock(token)
    user_data = get_user_data(token=token)

    if user_data is None:
        statsd.incr("news.tasks.confirm_user.confirm_user_not_found")
        return

    if user_data["optin"]:
        # already confirmed
        return

    if not ("email" in user_data and user_data["email"]):
        raise BasketError("token has no email in ET")

    sfdc.update(user_data, {"optin": True})


@et_task
def add_sms_user(send_name, mobile_number, optin, vendor_id=None):
    # Adding vendor_id as optional to avoid issues with deployment.
    # Old tasks with the old sitnature will be on the queue when this is first deployed.
    # TODO change the task signature to replace send_name with vendor_id
    if not vendor_id:
        vendor_id = get_sms_vendor_id(send_name)
        if not vendor_id:
            return

    sfmc.send_sms(mobile_number, vendor_id)
    if optin:
        add_sms_user_optin.delay(mobile_number)


@et_task
def add_sms_user_optin(mobile_number):
    record = {"Phone": mobile_number, "SubscriberKey": mobile_number}
    sfmc.add_row("Mobile_Subscribers", record)


@et_task
def update_custom_unsub(token, reason):
    """Record a user's custom unsubscribe reason."""
    get_lock(token)
    try:
        sfdc.update({"token": token}, {"reason": reason})
    except sfapi.SalesforceMalformedRequest:
        # likely the record can't be found. nothing to do.
        pass


@et_task
def send_recovery_message_task(email):
    user_data = get_user_data(email=email, extra_fields=["id"])
    if not user_data:
        log.debug("In send_recovery_message_task, email not known: %s" % email)
        return

    # make sure we have a language and format, no matter what ET returned
    lang = user_data.get("lang", "en") or "en"
    format = user_data.get("format", "H") or "H"

    if lang not in settings.RECOVER_MSG_LANGS:
        lang = "en"

    message_id = mogrify_message_id(RECOVERY_MESSAGE_ID, lang, format)
    send_message.delay(message_id, email, user_data["id"], token=user_data["token"])


@et_task
def record_common_voice_goals(data):
    # send currently queued tasks to the DB for processing
    # TODO delete once we're done
    CommonVoiceUpdate.objects.create(data=data)


@et_task
def record_common_voice_update(data):
    # do not change the sent data in place. A retry will use the changed data.
    dcopy = data.copy()
    email = dcopy.pop("email")
    user_data = get_user_data(email=email, extra_fields=["id"])
    new_data = {
        "source_url": "https://voice.mozilla.org",
        "newsletters": [settings.COMMON_VOICE_NEWSLETTER],
    }
    for k, v in dcopy.items():
        new_data["cv_" + k] = v

    if user_data:
        sfdc.update(user_data, new_data)
    else:
        new_data.update({"email": email, "token": generate_token()})
        sfdc.add(new_data)


@celery_app.task()
def process_common_voice_batch():
    if not settings.COMMON_VOICE_BATCH_PROCESSING:
        return

    updates = CommonVoiceUpdate.objects.filter(ack=False)[
        : settings.COMMON_VOICE_BATCH_CHUNK_SIZE
    ]
    per_user = {}
    for update in updates:
        # last_active_date is when the update was sent basically, so we can use it for ordering
        data = update.data
        last_active = isoparse(data["last_active_date"])
        if (
            data["email"] in per_user
            and per_user[data["email"]]["last_active"] > last_active
        ):
            continue

        per_user[data["email"]] = {
            "last_active": last_active,
            "data": data,
        }

    for info in per_user.values():
        record_common_voice_update.delay(info["data"])

    for update in updates:
        # do them one at a time to ensure that we don't ack new ones that have
        # come in since we started
        update.ack = True
        update.save()

    statsd.incr("news.tasks.process_common_voice_batch.all_updates", len(updates))
    # delete ack'd updates more than 24 hours old
    when = now() - timedelta(hours=24)
    deleted, _ = CommonVoiceUpdate.objects.filter(ack=True, when__lte=when).delete()
    statsd.incr("news.tasks.process_common_voice_batch.deleted", deleted)
    statsd.gauge(
        "news.tasks.process_common_voice_batch.queue_volume",
        CommonVoiceUpdate.objects.filter(ack=False).count(),
    )


@et_task
def record_fxa_concerts_rsvp(email, is_firefox, campaign_id):
    sfmc.add_row(
        "FxAccounts_Concert_RSVP",
        {
            "Email": email,
            "Firefox": is_firefox,
            "Campaign_ID": campaign_id,
            "RSVP_Time": gmttime(),
        },
    )


@et_task
def record_source_url(email, source_url, newsletter_id):
    if not source_url:
        source_url = "__NONE__"
    else:
        source_url = source_url[:1000]

    sfmc.add_row(
        "NEWSLETTER_SOURCE_URLS",
        {
            "Email": email,
            "Signup_Source_URL__c": source_url,
            "Newsletter_Field_Name": newsletter_id,
            "Newsletter_Date": gmttime(),
        },
    )


@et_task
def process_donation_event(data):
    """Process a followup event on a donation"""
    etype = data["event_type"]
    txn_id = data["transaction_id"]
    status = data.get("status")
    statsd.incr("news.tasks.process_donation_event.{}".format(etype))
    if status:
        statsd.incr("news.tasks.process_donation_event.{}.{}".format(etype, status))

    if etype.startswith("charge.dispute."):
        if status not in ["charge_refunded", "won", "lost"]:
            # only care about the above statuses
            statsd.incr("news.tasks.process_donation_event.{}.IGNORED".format(etype))
            return
    elif etype == "charge.refunded":
        if status not in ["succeeded", "failed", "cancelled"]:
            # don't care about pending statuses
            statsd.incr("news.tasks.process_donation_event.{}.IGNORED".format(etype))
            return

    if "reason" in data:
        reason_lost = data["reason"]
    else:
        reason_lost = data["failure_code"]

    try:
        # will raise a SalesforceMalformedRequest if not found
        sfdc.opportunity.update(
            "PMT_Transaction_ID__c/{}".format(txn_id),
            {
                "PMT_Type_Lost__c": etype,
                "PMT_Reason_Lost__c": reason_lost,
                "StageName": "Closed Lost",
            },
        )
    except sfapi.SalesforceMalformedRequest as e:
        statsd.incr("news.tasks.process_donation_event.not_found")
        with sentry_sdk.configure_scope() as scope:
            scope.set_tag("action", "ignored")
            sentry_sdk.capture_exception()
        # we don't know about this tx_id. Let someone know.
        do_notify = cache.add("donate-notify-{}".format(txn_id), 1, 86400)
        if do_notify and settings.DONATE_UPDATE_FAIL_DE:
            sfmc.add_row(
                settings.DONATE_UPDATE_FAIL_DE,
                {
                    "PMT_Transaction_ID__c": txn_id,
                    "Payment_Type__c": etype,
                    "PMT_Reason_Lost__c": reason_lost,
                    "Error_Text": str(e)[:4000],
                    "Date": gmttime(),
                },
            )

        if do_notify and settings.DONATE_NOTIFY_EMAIL:
            # don't notify about a transaction more than once per day
            first_mail = cache.add("donate-notify-{}".format(txn_id), 1, 86400)
            if first_mail:
                body = render_to_string(
                    "news/donation_notify_email.txt",
                    {
                        "txn_id": txn_id,
                        "type_lost": etype,
                        "reason_lost": reason_lost,
                        "server_name": settings.STATSD_PREFIX,
                    },
                )
                send_mail(
                    "Donation Record Not Found",
                    body,
                    "noreply@mozilla.com",
                    [settings.DONATE_NOTIFY_EMAIL],
                )

        # uncomment below to retry
        # raise


# all strings and truncated at 2000 chars
DONATION_OPTIONAL_FIELDS = {
    "SourceURL__c": "source_url",
    "Donation_Form_URL__c": "donation_url",
    "Project__c": "project",
    "PMT_Subscription_ID__c": "subscription_id",
    "Credit_Card_Type__c": "card_type",
}
# Add these fields as optional for now as some messages
# could still come through without them. Mix of string
# and numerical data.
DONATION_NEW_FIELDS = {
    "Donation_Locale__c": "locale",
    "Processors_Fee__c": "transaction_fee",
    "Net_Amount__c": "net_amount",
    "Conversion_Amount__c": "conversion_amount",
    "Last_4_Digits__c": "last_4",
}


@et_task
def process_donation(data):
    get_lock(data["email"])
    # tells the backend to leave the "subscriber" flag alone
    contact_data = {"_set_subscriber": False}
    # do "or ''" because data can contain None values
    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()
    if first_name and last_name:
        contact_data["first_name"] = first_name
        contact_data["last_name"] = last_name
    elif first_name:
        contact_data["first_name"] = first_name
    elif last_name:
        names = data["last_name"].rsplit(None, 1)
        if len(names) == 2:
            first, last = names
        else:
            first, last = "", names[0]
        if first:
            contact_data["first_name"] = first
        if last:
            contact_data["last_name"] = last

    user_data = get_user_data(email=data["email"], extra_fields=["id"])
    if user_data:
        if contact_data and (
            (
                "first_name" in contact_data
                and contact_data["first_name"] != user_data["first_name"]
            )
            or (
                "last_name" in contact_data
                and contact_data["last_name"] != user_data["last_name"]
            )
        ):
            sfdc.update(user_data, contact_data)
    else:
        contact_data["token"] = generate_token()
        contact_data["email"] = data["email"]
        contact_data["record_type"] = settings.DONATE_CONTACT_RECORD_TYPE

        # returns a dict with the new ID but no other user data, but that's enough here
        user_data = sfdc.add(contact_data)
        if not user_data.get("id"):
            # retry here to make sure we associate the donation data with the proper account
            raise RetryTask("User not yet available")

    # add opportunity
    donation = {
        "RecordTypeId": settings.DONATE_OPP_RECORD_TYPE,
        "Name": "Foundation Donation",
        "Donation_Contact__c": user_data["id"],
        "StageName": "Closed Won",
        "Amount": float(data["donation_amount"]),
        "Currency__c": data["currency"].upper(),
        "Payment_Source__c": data["service"],
        "PMT_Transaction_ID__c": data["transaction_id"],
        "Payment_Type__c": "Recurring" if data["recurring"] else "One-Time",
    }
    # https://github.com/mozmeao/basket/issues/364
    if "campaign_id" in data:
        donation["CampaignId"] = data["campaign_id"]

    # this is a unix timestamp in ms since epoc
    timestamp = data.get("created")
    if timestamp:
        donation["CloseDate"] = iso_format_unix_timestamp(timestamp)

    for dest_name, source_name in DONATION_NEW_FIELDS.items():
        if source_name in data:
            donation[dest_name] = data[source_name]

    for dest_name, source_name in DONATION_OPTIONAL_FIELDS.items():
        if data.get(source_name):
            # truncate at 2000 chars as that's the max for
            # a SFDC text field. We may do more granular
            # truncation per field in future.
            donation[dest_name] = data[source_name][:2000]

    try:
        sfdc.opportunity.create(donation)
    except sfapi.SalesforceMalformedRequest as e:
        if e.content and e.content[0].get("errorCode") == "DUPLICATE_VALUE":
            # already in the system, ignore
            pass
        else:
            raise


@et_task
def process_newsletter_subscribe(data):
    data = data["form"]
    data["lang"] = get_best_supported_lang(data["lang"])
    upsert_user(SUBSCRIBE, data)


PETITION_CONTACT_FIELDS = [
    "first_name",
    "last_name",
    "country",
    "postal_code",
    "source_url",
]


@et_task
def process_petition_signature(data):
    """
    Add petition signature to SFDC
    """
    data = data["form"]
    get_lock(data["email"])
    # tells the backend to leave the "subscriber" flag alone
    contact_data = {"_set_subscriber": False}
    contact_data.update({k: data[k] for k in PETITION_CONTACT_FIELDS if data.get(k)})

    user_data = get_user_data(email=data["email"], extra_fields=["id"])
    if user_data:
        sfdc.update(user_data, contact_data)
    else:
        contact_data["token"] = generate_token()
        contact_data["email"] = data["email"]
        contact_data["record_type"] = settings.DONATE_CONTACT_RECORD_TYPE
        sfdc.add(contact_data)
        # fetch again to get ID
        user_data = get_user_data(email=data.get("email"), extra_fields=["id"])
        if not user_data:
            # retry here to make sure we associate the donation data with the proper account
            raise RetryTask("User not yet available")

    if data.get("email_subscription", False):
        upsert_user.delay(
            SUBSCRIBE,
            {
                "token": user_data["token"],
                "lang": data.get("lang", "en-US"),
                "newsletters": "mozilla-foundation",
                "source_url": data["source_url"],
            },
        )

    campaign_id = data["campaign_id"]
    # Fix a specific issue with a specific campaign where the ID was entered without
    # the leading 7
    if len(campaign_id) == 17 and not campaign_id.startswith("7"):
        campaign_id = f"7{campaign_id}"

    campaign_member = {
        "CampaignId": campaign_id,
        "ContactId": user_data["id"],
        "Full_URL__c": data["source_url"],
        "Status": "Signed",
    }
    comments = data.get("comments")
    if comments:
        campaign_member["Petition_Comments__c"] = comments[:500]

    metadata = data.get("metadata")
    if metadata:
        campaign_member["Petition_Flex__c"] = json.dumps(metadata)[:500]

    try:
        sfdc.campaign_member.create(campaign_member)
    except sfapi.SalesforceMalformedRequest as e:
        if e.content and e.content[0].get("errorCode") == "DUPLICATE_VALUE":
            # already in the system, ignore
            pass
        else:
            raise


def upsert_amo_user_data(data, user_sync=False):
    """
    Update AMO user data in the SFDC contact, or create a contact.
    Return the Contact data (the contact ID at a minimum).

    :param data: dict of amo user data
    :param user_sync: bool True if this is a User Sync request
    :return: dict of SFDC contact data
    """
    data = data.copy()
    fxa_id = data.pop("fxa_id", None)
    amo_id = data.pop("id", None)
    user = None

    # records can come in with no "id" or "fxa_id" field
    if amo_id:
        user = get_user_data(amo_id=amo_id, extra_fields=["id", "amo_id", "fxa_id"])
        if not user and fxa_id:
            # Try to find user with fxa_id
            user = get_user_data(fxa_id=fxa_id, extra_fields=["id", "amo_id", "fxa_id"])

    if not user:
        # Cannot find user with FxA ID or AMO ID, ignore the update
        return None

    if user_sync and not user["amo_id"]:
        # do not update user as AMO User unless it comes from an AddonSync
        return None

    amo_deleted = data.pop("deleted", False)
    amo_data = {f"amo_{k}": v for k, v in data.items() if v}
    amo_data["amo_id"] = amo_id
    amo_data["amo_deleted"] = amo_deleted
    if not user_sync:
        # only ensure this is true if this is from an addon sync
        amo_data["amo_user"] = True

    if amo_deleted or fxa_id is None:
        amo_data["amo_id"] = None

    sfdc.update(user, amo_data)
    return user


def amo_compress_categories(categories):
    cats_list = []
    for product, cats in categories.items():
        cats_list.extend([f"{product}-{cat}" for cat in cats])

    return ",".join(cats_list)


def amo_check_user_for_deletion(user_id):
    """If a user has no addons their AMO info should be removed"""
    addons = sfdc.sf.query(
        sfapi.format_soql(
            "SELECT Id FROM DevAddOn__c WHERE AMO_Contact_ID__c = {contact_id} LIMIT 1",
            contact_id=user_id,
        ),
    )
    if not addons["records"]:
        sfdc.update({"id": user_id}, {"amo_id": None, "amo_user": False})


@et_task
def amo_sync_addon(data):
    data = deepcopy(data)
    if data["status"] == "deleted":
        try:
            addon_record = sfdc.addon.get_by_custom_id("AMO_AddOn_Id__c", data["id"])
        except sfapi.SalesforceResourceNotFound:
            return
        # if deleted, go ahead and delete the author associations and addon
        addon_users = sfdc.sf.query(
            sfapi.format_soql(
                "SELECT Id, AMO_Contact_ID__c FROM DevAddOn__c WHERE AMO_AddOn_ID__c = {addon_id}",
                addon_id=addon_record["Id"],
            ),
        )
        for record in addon_users["records"]:
            sfdc.dev_addon.delete(record["Id"])
            amo_check_user_for_deletion(record["AMO_Contact_ID__c"])

        sfdc.addon.delete(addon_record["Id"])
        return

    users = [upsert_amo_user_data(author) for author in data["authors"]]
    # filter out the users that couldn't be found
    users = [user for user in users if user]
    addon_data = {
        "AMO_Category__c": amo_compress_categories(data["categories"]),
        "AMO_Default_Language__c": data["default_locale"],
        "AMO_GUID__c": data["guid"],
        "AMO_Rating__c": data["ratings"]["average"],
        "AMO_Slug__c": data["slug"],
        "AMO_Status__c": data["status"],
        "AMO_Type__c": data["type"],
        "AMO_Update__c": data["last_updated"],
        "Average_Daily_Users__c": data["average_daily_users"],
        "Dev_Disabled__c": "Yes" if data["is_disabled"] else "No",
        "AMO_Recommended__c": data["is_recommended"],
    }
    # check for possible None or empty values
    if data["name"]:
        addon_data["Name"] = data["name"]

    # versions can be removed, so they should be removed if they are null
    if data["current_version"]:
        addon_data["AMO_Current_Version__c"] = data["current_version"]["version"]
    else:
        addon_data["AMO_Current_Version__c"] = ""

    if data["latest_unlisted_version"]:
        addon_data["AMO_Current_Version_Unlisted__c"] = data["latest_unlisted_version"][
            "version"
        ]
    else:
        addon_data["AMO_Current_Version_Unlisted__c"] = ""

    sfdc.addon.upsert(f'AMO_AddOn_Id__c/{data["id"]}', addon_data)
    addon_record = sfdc.addon.get_by_custom_id("AMO_AddOn_Id__c", data["id"])

    # delete users no longer associated with the addon
    existing_users = sfdc.sf.query(
        sfapi.format_soql(
            "SELECT Id, AMO_Contact_ID__c FROM DevAddOn__c WHERE AMO_AddOn_ID__c = {addon_id}",
            addon_id=addon_record["Id"],
        ),
    )
    user_ids_to_records = {
        i["AMO_Contact_ID__c"]: i["Id"] for i in existing_users["records"]
    }
    existing_user_ids = set(user_ids_to_records.keys())
    new_user_ids = {user["id"] for user in users}
    if new_user_ids == existing_user_ids:
        # no need to continue as no users have been added or removed
        return

    to_delete = existing_user_ids - new_user_ids
    for delete_user_id in to_delete:
        sfdc.dev_addon.delete(user_ids_to_records[delete_user_id])
        amo_check_user_for_deletion(delete_user_id)

    to_add = new_user_ids - existing_user_ids
    if not to_add:
        # no new users to add
        return

    for user in users:
        if user["id"] not in to_add:
            # record exists
            continue

        try:
            sfdc.dev_addon.upsert(
                f'ConcatenateAMOID__c/{user["amo_id"]}-{data["id"]}',
                {
                    "AMO_AddOn_ID__c": addon_record["Id"],
                    "AMO_Contact_ID__c": user["id"],
                },
            )
        except sfapi.SalesforceMalformedRequest as e:
            if e.content[0]["errorCode"] == "DUPLICATE_VALUE":
                # dupe error, so we don't need to do this again
                pass
            else:
                raise e


@et_task
def amo_sync_user(data):
    # copy input so it's not modified for retry
    upsert_amo_user_data(data.copy(), user_sync=True)


@celery_app.task()
def snitch(start_time=None):
    if start_time is None:
        snitch.delay(time())
        return

    snitch_id = settings.SNITCH_ID
    totalms = int((time() - start_time) * 1000)
    statsd.timing("news.tasks.snitch.timing", totalms)
    requests.post("https://nosnch.in/{}".format(snitch_id), data={"m": totalms})


def get_fxa_user_data(fxa_id, email):
    """Return a user data dict, just like `get_user_data` below, but ensure we have a good FxA contact

    First look for a user by FxA ID. If we get a user, and the email matches what was passed in, return it.
    If the email doesn't match, set the first user's FxA_ID to "DUPE:<fxa_id>" so that we don't run into dupe
    issues, and set "fxa_deleted" to True. Then look up a user with the email address and return that or None.
    """
    user_data = None
    # try getting user data with the fxa_id first
    user_data_fxa = get_user_data(fxa_id=fxa_id, extra_fields=["id"])
    if user_data_fxa:
        user_data = user_data_fxa
        # If email doesn't match, update FxA primary email field with the new email.
        if user_data_fxa["email"] != email:
            sfdc.update(user_data_fxa, {"fxa_primary_email": email})

    # if we still don't have user data try again with email this time
    if not user_data:
        user_data = get_user_data(email=email, extra_fields=["id"])

    return user_data

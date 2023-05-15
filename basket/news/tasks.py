import logging
import re
from datetime import date, datetime, timedelta
from email.utils import formatdate
from functools import wraps
from time import mktime, time
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache
from django.utils.timezone import now

import requests
import sentry_sdk
import user_agents
from celery.signals import task_failure, task_retry, task_success
from celery.utils.time import get_exponential_backoff_interval
from dateutil.parser import isoparse
from django_statsd.clients import statsd
from silverpop.api import SilverpopResponseException

from basket.base.utils import email_is_testing
from basket.news.backends.acoustic import acoustic, acoustic_tx
from basket.news.backends.common import NewsletterException
from basket.news.backends.ctms import (
    CTMSNotFoundByAltIDError,
    CTMSUniqueIDConflictError,
    ctms,
)
from basket.news.celery import app as celery_app
from basket.news.models import (
    AcousticTxEmailMessage,
    CommonVoiceUpdate,
    FailedTask,
    Interest,
    Newsletter,
    QueuedTask,
)
from basket.news.newsletters import get_transactional_message_ids, newsletter_languages
from basket.news.utils import (
    SUBSCRIBE,
    UNSUBSCRIBE,
    generate_token,
    get_accept_languages,
    get_best_language,
    get_user_data,
    iso_format_unix_timestamp,
    parse_newsletters,
    parse_newsletters_csv,
)

log = logging.getLogger(__name__)

# don't propagate and don't retry if these are the error messages
IGNORE_ERROR_MSGS = [
    "INVALID_EMAIL_ADDRESS",
    "InvalidEmailAddress",
    "An invalid phone number was provided",
    "No valid subscribers were provided",
    "There are no valid subscribers",
    "email address is suppressed",
    "invalid email address",
]
# don't propagate and don't retry if these regex match the error messages
IGNORE_ERROR_MSGS_RE = [re.compile(r"campaignId \d+ not found")]
# don't propagate after max retries if these are the error messages
IGNORE_ERROR_MSGS_POST_RETRY = []
# tasks exempt from maintenance mode queuing
MAINTENANCE_EXEMPT = []


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


def ignore_error(exc, to_ignore=None, to_ignore_re=None):
    to_ignore = to_ignore or IGNORE_ERROR_MSGS
    to_ignore_re = to_ignore_re or IGNORE_ERROR_MSGS_RE
    msg = str(exc)
    for ignore_msg in to_ignore:
        if ignore_msg in msg:
            return True

    for ignore_re in to_ignore_re:
        if ignore_re.search(msg):
            return True

    return False


def ignore_error_post_retry(exc):
    return ignore_error(exc, IGNORE_ERROR_MSGS_POST_RETRY)


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
                # str() gives more info than repr() on
                # celery.datastructures.ExceptionInfo
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
                    name=self.name,
                    args=args,
                    kwargs=kwargs,
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
            SilverpopResponseException,
        ) as e:
            # These could all be connection issues, so try again later.
            # IOError covers URLError, SSLError, and requests.HTTPError.
            if ignore_error(e):
                with sentry_sdk.push_scope() as scope:
                    scope.set_tag("action", "ignored")
                    sentry_sdk.capture_exception()
                return

            try:
                if not (isinstance(e, RetryTask) or ignore_error_post_retry(e)):
                    with sentry_sdk.push_scope() as scope:
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

    # Update CTMS
    user_data = get_user_data(fxa_id=fxa_id, extra_fields=["id"])
    if user_data:
        ctms.update(user_data, {"fxa_primary_email": email})
    else:
        # FxA record not found, try email
        user_data = get_user_data(email=email, extra_fields=["id"])
        if user_data:
            ctms.update(user_data, {"fxa_id": fxa_id, "fxa_primary_email": email})
        else:
            # No matching record for Email or FxA ID. Create one.
            data = {
                "email": email,
                "token": generate_token(),
                "fxa_id": fxa_id,
                "fxa_primary_email": email,
            }
            ctms_data = data.copy()
            contact = ctms.add(ctms_data)
            if contact:
                data["email_id"] = contact["email"]["email_id"]
            statsd.incr("news.tasks.fxa_email_changed.user_not_found")

    cache.set(cache_key, ts, 7200)  # 2 hr


def fxa_direct_update_contact(fxa_id, data):
    """Set some small data for a contact with an FxA ID

    Ignore if contact with FxA ID can't be found
    """
    try:
        ctms.update_by_alt_id("fxa_id", fxa_id, data)
    except CTMSNotFoundByAltIDError:
        # No associated record found, skip this update.
        pass


@et_task
def fxa_delete(data):
    fxa_direct_update_contact(data["uid"], {"fxa_deleted": True})


@et_task
def fxa_verified(data):
    """Add new FxA users"""
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
            "ts": data["ts"],
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

    login_data = {
        "FXA_ID": data["fxa_id"],
        "SERVICE": data.get("service", "unknown").strip() or "unknown",
        "LOGIN_DATE": date.fromtimestamp(data["ts"]).isoformat(),
        "FIRST_DEVICE": "y" if data.get("first_device") else "n",
        "OS_NAME": user_agent.os.family,
        "OS_VERSION": user_agent.os.version_string,
        "BROWSER": "{0} {1}".format(
            user_agent.browser.family,
            user_agent.browser.version_string,
        ),
        "DEVICE_NAME": user_agent.device.family,
        "DEVICE_TYPE": device_type,
    }
    fxa_activity_acoustic.delay(login_data)


@et_task
def fxa_activity_acoustic(data):
    acoustic.insert_update_relational_table(
        table_id=settings.ACOUSTIC_FXA_TABLE_ID,
        rows=[data],
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
    try:
        ctms.update_by_alt_id("token", token, data)
    except CTMSNotFoundByAltIDError:
        raise


@et_task
def upsert_user(api_call_type, data):
    """
    Update or insert (upsert) a contact record

    @param int api_call_type: What kind of API call it was. Could be
        SUBSCRIBE, UNSUBSCRIBE, or SET.
    @param dict data: POST data from the form submission
    @return:
    """
    upsert_contact(
        api_call_type,
        data,
        get_user_data(
            token=data.get("token"),
            email=data.get("email"),
            extra_fields=["id"],
        ),
    )


def upsert_contact(api_call_type, data, user_data):
    """
    Update or insert (upsert) a contact record

    @param int api_call_type: What kind of API call it was. Could be
        SUBSCRIBE, UNSUBSCRIBE, or SET.
    @param dict data: POST data from the form submission
    @param dict user_data: existing contact data
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
            send_acoustic_tx_messages(
                data["email"],
                data.get("lang", "en-US"),
                list(transactionals),
            )
            if not newsletters:
                # no regular newsletters
                return None, None

    # Set the newsletter flags in the record by comparing to their
    # current subscriptions.
    update_data["newsletters"] = parse_newsletters(
        api_call_type,
        newsletters,
        cur_newsletters,
    )
    send_confirm = False

    if api_call_type != UNSUBSCRIBE:
        # Check for newsletter-specific user updates
        to_subscribe_slugs = [nl for nl, sub in update_data["newsletters"].items() if sub]
        check_optin = not (forced_optin or (user_data and user_data.get("optin")))
        check_mofo = not (user_data and user_data.get("mofo_relevant"))
        if to_subscribe_slugs and (check_optin or check_mofo):
            to_subscribe = Newsletter.objects.filter(slug__in=to_subscribe_slugs)

            # Are they subscribing to any newsletters that require confirmation?
            # If none require confirmation, user goes straight to confirmed (optin)
            # Otherwise, prepare to send a fx or moz confirmation
            if check_optin:
                exempt_from_confirmation = any(
                    [not o.requires_double_optin for o in to_subscribe],
                )
                if exempt_from_confirmation:
                    update_data["optin"] = True
                else:
                    send_fx_confirm = all([o.firefox_confirm for o in to_subscribe])
                    send_confirm = "fx" if send_fx_confirm else "moz"

            # Update a user to MoFo-relevant if they subscribed to a MoFo newsletters
            if check_mofo:
                if any([ns.is_mofo for ns in to_subscribe]):
                    update_data["mofo_relevant"] = True

    if user_data is None:
        # no user found. create new one.
        token = update_data["token"] = generate_token()
        if settings.MAINTENANCE_MODE:
            sfdc_add_update.delay(update_data)
        else:
            ctms.add(update_data)

        if send_confirm and settings.SEND_CONFIRM_MESSAGES:
            send_confirm_message.delay(
                data["email"],
                token,
                data.get("lang", "en-US"),
                send_confirm,
            )

        return token, True

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
        ctms.update(user_data, update_data)

    if send_confirm and settings.SEND_CONFIRM_MESSAGES:
        send_confirm_message.delay(
            data["email"],
            token,
            update_data.get("lang", user_data.get("lang", "en-US")),
            send_confirm,
        )

    return token, False


@et_task
def sfdc_add_update(update_data, user_data=None):
    """
    Add or update contact data when maintainance mode is completed.

    The first version was temporary, with:
    TODO remove after maintenance is over and queue is processed

    The next version allowed SFDC / CTMS dual-write mode.

    This version only writes to CTMS, so it is now misnamed, but task
    renames require coordination.
    """
    if user_data:
        ctms.update(user_data, update_data)
        return

    try:
        ctms.add(update_data)
    except CTMSUniqueIDConflictError:
        # Try as an update
        user_data = get_user_data(email=update_data["email"])
        if not user_data:
            raise
        update_data.pop("token", None)
        update_data.pop("email_id", None)
        ctms.update(user_data, update_data)


@et_task
def send_acoustic_tx_message(email, vendor_id, fields=None):
    acoustic_tx.send_mail(email, vendor_id, fields)


def send_acoustic_tx_messages(email, lang, message_ids):
    sent = 0
    lang = lang.strip()
    lang = lang or "en-US"
    for mid in message_ids:
        vid = AcousticTxEmailMessage.objects.get_vendor_id(mid, lang)
        if vid:
            send_acoustic_tx_message.delay(email, vid)
            sent += 1

    return sent


@et_task
def send_confirm_message(email, token, lang, message_type):
    lang = lang.strip()
    lang = lang or "en-US"
    message_id = f"newsletter-confirm-{message_type}"
    vid = AcousticTxEmailMessage.objects.get_vendor_id(message_id, lang)
    if vid:
        acoustic_tx.send_mail(email, vid, {"basket_token": token}, save_to_db=True)


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
        statsd.incr("news.tasks.confirm_user.confirm_user_not_found")
        return

    if user_data["optin"]:
        # already confirmed
        return

    if not ("email" in user_data and user_data["email"]):
        raise BasketError("token has no email in ET")

    ctms.update(user_data, {"optin": True})


@et_task
def update_custom_unsub(token, reason):
    """Record a user's custom unsubscribe reason."""
    try:
        ctms.update_by_alt_id("token", token, {"reason": reason})
    except CTMSNotFoundByAltIDError:
        # No record found for that token, nothing to do.
        pass


@et_task
def send_recovery_message_acoustic(email, token, lang, fmt):
    message_name = "account-recovery"
    if fmt != "H":
        message_name += "-text"

    vid = AcousticTxEmailMessage.objects.get_vendor_id(message_name, lang)
    if vid:
        acoustic_tx.send_mail(email, vid, {"basket_token": token})


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
        ctms.update(user_data, new_data)
    else:
        new_data.update({"email": email, "token": generate_token()})
        ctms.add(new_data)


@celery_app.task()
def process_common_voice_batch():
    if not settings.COMMON_VOICE_BATCH_PROCESSING:
        return

    updates = CommonVoiceUpdate.objects.filter(ack=False)[: settings.COMMON_VOICE_BATCH_CHUNK_SIZE]
    per_user = {}
    for update in updates:
        # last_active_date is when the update was sent basically, so we can use
        # it for ordering
        data = update.data
        last_active = isoparse(data["last_active_date"])
        if data["email"] in per_user and per_user[data["email"]]["last_active"] > last_active:
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
    """
    Return a user data dict, just like `get_user_data` below, but ensure we have
    a good FxA contact

    First look for a user by FxA ID. If we get a user, and the email matches
    what was passed in, return it. If the email doesn't match, set the first
    user's FxA_ID to "DUPE:<fxa_id>" so that we don't run into dupe issues, and
    set "fxa_deleted" to True. Then look up a user with the email address and
    return that or None.
    """
    user_data = None
    # try getting user data with the fxa_id first
    user_data_fxa = get_user_data(fxa_id=fxa_id, extra_fields=["id"])
    if user_data_fxa:
        user_data = user_data_fxa
        # If email doesn't match, update FxA primary email field with the new email.
        if user_data_fxa["email"] != email:
            ctms.update(user_data_fxa, {"fxa_primary_email": email})

    # if we still don't have user data try again with email this time
    if not user_data:
        user_data = get_user_data(email=email, extra_fields=["id"])

    return user_data

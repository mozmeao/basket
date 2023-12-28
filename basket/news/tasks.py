import logging
from datetime import date
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache

import user_agents

from basket import metrics
from basket.base.decorators import rq_task
from basket.base.exceptions import BasketError
from basket.base.utils import email_is_testing
from basket.news.backends.acoustic import acoustic, acoustic_tx
from basket.news.backends.ctms import (
    CTMSNotFoundByAltIDError,
    CTMSUniqueIDConflictError,
    ctms,
)
from basket.news.models import (
    AcousticTxEmailMessage,
    Interest,
    Newsletter,
)
from basket.news.newsletters import get_transactional_message_ids, newsletter_languages, newsletter_obj
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


def fxa_source_url(metrics):
    source_url = settings.FXA_REGISTER_SOURCE_URL
    query = {k: v for k, v in metrics.items() if k.startswith("utm_")}
    if query:
        source_url = "?".join((source_url, urlencode(query)))

    return source_url


@rq_task
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
            metrics.incr("news.tasks.fxa_email_changed.user_not_found")

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


@rq_task
def fxa_delete(data):
    fxa_direct_update_contact(data["uid"], {"fxa_deleted": True})


@rq_task
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


@rq_task
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


@rq_task
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
        "BROWSER": f"{user_agent.browser.family} {user_agent.browser.version_string}",
        "DEVICE_NAME": user_agent.device.family,
        "DEVICE_TYPE": device_type,
    }
    fxa_activity_acoustic.delay(login_data)


@rq_task
def fxa_activity_acoustic(data):
    acoustic.insert_update_relational_table(
        table_id=settings.ACOUSTIC_FXA_TABLE_ID,
        rows=[data],
    )


@rq_task
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


@rq_task
def update_user_meta(token, data):
    """Update a user's metadata, not newsletters"""
    try:
        ctms.update_by_alt_id("token", token, data)
    except CTMSNotFoundByAltIDError:
        raise


@rq_task
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
                exempt_from_confirmation = any(not o.requires_double_optin for o in to_subscribe)
                if exempt_from_confirmation:
                    update_data["optin"] = True
                else:
                    send_fx_confirm = all(o.firefox_confirm for o in to_subscribe)
                    send_confirm = "fx" if send_fx_confirm else "moz"

            # Update a user to MoFo-relevant if they subscribed to a MoFo newsletters
            if check_mofo:
                if any(ns.is_mofo for ns in to_subscribe):
                    update_data["mofo_relevant"] = True

    if user_data is None:
        # no user found. create new one.
        token = update_data["token"] = generate_token()
        if settings.MAINTENANCE_MODE:
            ctms_add_or_update.delay(update_data)
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
        ctms_add_or_update.delay(update_data, user_data)
    else:
        ctms.update(user_data, update_data)

    # In the rare case the user hasn't confirmed their email and is subscribing to the same newsletter, send the confirmation again.
    # We catch this by checking if the user `optin` is `False` and if the `update_data["newsletters"]` is empty.
    if user_data and user_data.get("optin", False) is False and not update_data["newsletters"]:
        newsletter_objs = filter(None, [newsletter_obj(n) for n in newsletters])
        if newsletter_objs:
            needs_confirmation = any(n.requires_double_optin for n in newsletter_objs)
            if needs_confirmation:
                send_fx_confirm = all(n.firefox_confirm for n in newsletter_objs)
                send_confirm = "fx" if send_fx_confirm else "moz"

    if send_confirm and settings.SEND_CONFIRM_MESSAGES:
        send_confirm_message.delay(
            data["email"],
            token,
            update_data.get("lang", user_data.get("lang", "en-US")),
            send_confirm,
        )

    return token, False


@rq_task
def ctms_add_or_update(update_data, user_data=None):
    """
    Add or update contact data when maintainance mode is completed.
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


@rq_task
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


@rq_task
def send_confirm_message(email, token, lang, message_type):
    lang = lang.strip()
    lang = lang or "en-US"
    message_id = f"newsletter-confirm-{message_type}"
    vid = AcousticTxEmailMessage.objects.get_vendor_id(message_id, lang)
    if vid:
        acoustic_tx.send_mail(email, vid, {"basket_token": token}, save_to_db=True)


@rq_task
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
        metrics.incr("news.tasks.confirm_user.confirm_user_not_found")
        return

    if user_data["optin"]:
        # already confirmed
        return

    if not ("email" in user_data and user_data["email"]):
        raise BasketError("token has no email in ET")

    ctms.update(user_data, {"optin": True})


@rq_task
def update_custom_unsub(token, reason):
    """Record a user's custom unsubscribe reason."""
    try:
        ctms.update_by_alt_id("token", token, {"reason": reason})
    except CTMSNotFoundByAltIDError:
        # No record found for that token, nothing to do.
        pass


@rq_task
def send_recovery_message_acoustic(email, token, lang, fmt):
    message_name = "account-recovery"
    if fmt != "H":
        message_name += "-text"

    vid = AcousticTxEmailMessage.objects.get_vendor_id(message_name, lang)
    if vid:
        acoustic_tx.send_mail(email, vid, {"basket_token": token})


@rq_task
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

import logging
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache

from basket import metrics
from basket.base.decorators import rq_task
from basket.base.exceptions import BasketError
from basket.base.utils import email_is_testing
from basket.news.backends.braze import BrazeUserNotFoundByFxaIdError, braze, braze_tx
from basket.news.backends.ctms import (
    CTMSNotFoundByAltIDError,
    CTMSUniqueIDConflictError,
    ctms,
)
from basket.news.models import (
    BrazeTxEmailMessage,
    Newsletter,
)
from basket.news.newsletters import newsletter_languages, newsletter_obj
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
def fxa_email_changed(
    data,
    use_braze_backend=False,
    pre_generated_token=None,
    pre_generated_email_id=None,
    **kwargs,
):
    ts = data["ts"]
    fxa_id = data["uid"]
    email = data["email"]
    cache_key = f"fxa_email_changed:{fxa_id}"
    prev_ts = float(cache.get(cache_key, 0))
    if prev_ts and prev_ts > ts:
        # message older than our last update for this UID
        return

    # Update backend
    user_data = get_user_data(fxa_id=fxa_id, extra_fields=["id", "email_id"], use_braze_backend=use_braze_backend)
    if user_data:
        if use_braze_backend:
            braze.update(user_data, {"fxa_primary_email": email})
        else:
            ctms.update(user_data, {"fxa_primary_email": email})
    else:
        # FxA record not found, try email
        user_data = get_user_data(email=email, extra_fields=["id", "email_id"], use_braze_backend=use_braze_backend)
        if user_data:
            if use_braze_backend:
                braze.update(user_data, {"fxa_id": fxa_id, "fxa_primary_email": email})
            else:
                ctms.update(user_data, {"fxa_id": fxa_id, "fxa_primary_email": email})
        else:
            # No matching record for Email or FxA ID. Create one.
            data = {
                "email": email,
                "token": pre_generated_token or generate_token(),
                "fxa_id": fxa_id,
                "fxa_primary_email": email,
            }
            if pre_generated_email_id:
                data["email_id"] = pre_generated_email_id

            backend_data = data.copy()
            contact = None
            if use_braze_backend:
                contact = braze.add(backend_data)
            else:
                contact = ctms.add(backend_data)
            if contact:
                data["email_id"] = contact["email"]["email_id"]
            metrics.incr("news.tasks.fxa_email_changed.user_not_found")

    cache.set(cache_key, ts, 7200)  # 2 hr


def fxa_direct_update_contact(fxa_id, data, use_braze_backend=False):
    """Set some small data for a contact with an FxA ID

    Ignore if contact with FxA ID can't be found
    """
    try:
        if use_braze_backend:
            braze.update_by_fxa_id(fxa_id, data)
        else:
            ctms.update_by_alt_id("fxa_id", fxa_id, data)
    except (CTMSNotFoundByAltIDError, BrazeUserNotFoundByFxaIdError):
        # No associated record found, skip this update.
        pass


@rq_task
def fxa_delete(data, use_braze_backend=False, **kwargs):
    fxa_direct_update_contact(data["uid"], {"fxa_deleted": True}, use_braze_backend)


@rq_task
def fxa_verified(
    data,
    use_braze_backend=False,
    should_send_tx_messages=True,
    pre_generated_token=None,
    pre_generated_email_id=None,
):
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
    metrics_context = data.get("metricsContext", {})
    new_data = {
        "email": email,
        "source_url": fxa_source_url(metrics_context),
        "country": data.get("countryCode", ""),
        "fxa_lang": data.get("locale"),
        "fxa_service": data.get("service", ""),
        "fxa_id": fxa_id,
        "optin": True,
    }
    if create_date:
        new_data["fxa_create_date"] = iso_format_unix_timestamp(create_date)

    newsletters = newsletters or []
    newsletters.append(settings.FXA_REGISTER_NEWSLETTER)
    new_data["newsletters"] = newsletters

    user_data = get_fxa_user_data(fxa_id, email, use_braze_backend)
    # don't overwrite the user's language if already set
    if not (user_data and user_data.get("lang")):
        new_data["lang"] = lang

    upsert_contact(
        SUBSCRIBE,
        new_data,
        user_data,
        use_braze_backend=use_braze_backend,
        should_send_tx_messages=should_send_tx_messages,
        pre_generated_token=pre_generated_token,
        pre_generated_email_id=pre_generated_email_id,
    )


@rq_task
def fxa_newsletters_update(
    data,
    use_braze_backend=False,
    should_send_tx_messages=True,
    pre_generated_token=None,
    pre_generated_email_id=None,
):
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
    }
    upsert_contact(
        SUBSCRIBE,
        new_data,
        get_fxa_user_data(fxa_id, email),
        use_braze_backend=use_braze_backend,
        should_send_tx_messages=should_send_tx_messages,
        pre_generated_token=pre_generated_token,
        pre_generated_email_id=pre_generated_email_id,
    )


@rq_task
def fxa_login(
    data,
    use_braze_backend=False,
    should_send_tx_messages=True,
    pre_generated_token=None,
    pre_generated_email_id=None,
):
    email = data["email"]
    # if we're not using the sandbox ignore testing domains
    if email_is_testing(email):
        return

    metrics_context = data.get("metricsContext", {})
    newsletter = settings.FXA_LOGIN_CAMPAIGNS.get(metrics_context.get("utm_campaign"))
    if newsletter:
        upsert_user.delay(
            SUBSCRIBE,
            {
                "email": email,
                "newsletters": newsletter,
                "source_url": fxa_source_url(metrics_context),
                "country": data.get("countryCode", ""),
            },
            use_braze_backend=use_braze_backend,
            should_send_tx_messages=should_send_tx_messages,
            pre_generated_token=pre_generated_token,
            pre_generated_email_id=pre_generated_email_id,
        )


@rq_task
def update_user_meta(token, data, use_braze_backend=False):
    """Update a user's metadata, not newsletters"""
    if use_braze_backend:
        braze.update_by_token(token, data)
    else:
        try:
            ctms.update_by_alt_id("token", token, data)
        except CTMSNotFoundByAltIDError:
            raise


@rq_task
def upsert_user(
    api_call_type,
    data,
    use_braze_backend=False,
    should_send_tx_messages=True,
    pre_generated_token=None,
    pre_generated_email_id=None,
):
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
            extra_fields=["id", "email_id"],
            use_braze_backend=use_braze_backend,
        ),
        use_braze_backend=use_braze_backend,
        should_send_tx_messages=should_send_tx_messages,
        pre_generated_token=pre_generated_token,
        pre_generated_email_id=pre_generated_email_id,
    )


def upsert_contact(
    api_call_type,
    data,
    user_data,
    use_braze_backend=False,
    should_send_tx_messages=True,
    pre_generated_token=None,
    pre_generated_email_id=None,
):
    """
    Update or insert (upsert) a contact record

    @param int api_call_type: What kind of API call it was. Could be
        SUBSCRIBE, UNSUBSCRIBE, or SET.
    @param dict data: POST data from the form submission
    @param dict user_data: existing contact data
    @return: token, created
    """
    update_data = data.copy()
    update_data.pop("format", None)  # Format defaults to "H".
    forced_optin = data.pop("optin", False)

    newsletters = parse_newsletters_csv(data.get("newsletters"))
    cur_newsletters = user_data and user_data.get("newsletters")

    if user_data and data.get("token") and user_data.get("token") != data["token"]:
        # We were passed a token but it doesn't match the user.
        return None, None

    if api_call_type == SUBSCRIBE:
        newsletters_set = set(newsletters)

        # Check for Braze transactional messages in the set of newsletters, and remove after processing.
        braze_msg_ids = set(BrazeTxEmailMessage.objects.get_tx_message_ids())
        braze_txs = newsletters_set & braze_msg_ids
        if braze_txs:
            braze_msgs = [t for t in braze_txs if t in braze_msg_ids]
            if should_send_tx_messages:
                send_tx_messages(
                    data["email"],
                    data.get("lang", "en-US"),
                    braze_msgs,
                )
            newsletters_set -= set(braze_msgs)

        newsletters = list(newsletters_set)
        if not newsletters:
            # Only transactional messages found, nothing else to do.
            return None, None
    elif use_braze_backend and update_data.get("optout"):
        # Unsubscribe from all current Braze newsletters if user is opting out
        newsletters = cur_newsletters if api_call_type == UNSUBSCRIBE else []

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
        if api_call_type != SUBSCRIBE:
            # Doesn't make sense to create a new user for UNSUBSCRIBE or SET
            return None, False

        # no user found. create new one.
        token = update_data["token"] = pre_generated_token or generate_token()

        if pre_generated_email_id:
            update_data["email_id"] = pre_generated_email_id

        if settings.MAINTENANCE_MODE:
            if use_braze_backend:
                braze_add_or_update.delay(update_data)
            else:
                ctms_add_or_update.delay(update_data)
        else:
            if use_braze_backend:
                new_user = braze.add(update_data)
            else:
                new_user = ctms.add(update_data)

        if send_confirm and settings.SEND_CONFIRM_MESSAGES and should_send_tx_messages:
            send_confirm_message.delay(
                data["email"],
                token,
                data.get("lang", "en-US"),
                send_confirm,
                new_user and new_user.get("email", {}).get("email_id") or None,
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
        token = update_data["token"] = pre_generated_token or generate_token()

    if settings.MAINTENANCE_MODE:
        if use_braze_backend:
            braze_add_or_update.delay(update_data, user_data)
        else:
            ctms_add_or_update.delay(update_data, user_data)
    else:
        if use_braze_backend:
            braze.update(user_data, update_data)
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

    if send_confirm and settings.SEND_CONFIRM_MESSAGES and should_send_tx_messages:
        send_confirm_message.delay(
            data["email"],
            token,
            update_data.get("lang", user_data.get("lang", "en-US")),
            send_confirm,
            user_data.get("email_id"),
        )

    return token, False


@rq_task
def braze_add_or_update(update_data, user_data=None):
    if user_data is None:
        braze.add(update_data)
    else:
        braze.update(user_data, update_data)


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
        user_data = get_user_data(email=update_data["email"], extra_fields=["email_id"])
        if not user_data:
            raise
        update_data.pop("token", None)
        update_data.pop("email_id", None)
        ctms.update(user_data, update_data)


@rq_task
def send_tx_message(email, message_id, language, user_data=None):
    metrics.incr("news.tasks.send_tx_message", tags=[f"message_id:{message_id}", f"language:{language}"])
    braze_tx.interface.track_user(email, event=f"send-{message_id}-{language}", user_data=user_data)


def send_tx_messages(email, lang, message_ids):
    sent = 0
    lang = lang.strip() or "en-US"
    for mid in message_ids:
        mid = settings.BRAZE_MESSAGE_ID_MAP.get(mid, mid)
        txm = BrazeTxEmailMessage.objects.get_message(mid, lang)
        if txm:
            send_tx_message.delay(email, txm.message_id, txm.language)
            sent += 1

    return sent


@rq_task
def send_confirm_message(email, token, lang, message_type, email_id):
    lang = lang.strip()
    lang = lang or "en-US"
    message_id = f"newsletter-confirm-{message_type}"
    txm = BrazeTxEmailMessage.objects.get_message(message_id, lang)
    if txm:
        send_tx_message(email, txm.message_id, txm.language, user_data={"basket_token": token, "email_id": email_id})


@rq_task
def confirm_user(token, use_braze_backend=False, extra_metrics_tags=None):
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
    if extra_metrics_tags is None:
        extra_metrics_tags = []

    user_data = get_user_data(
        token=token,
        extra_fields=["email_id"],
        use_braze_backend=use_braze_backend,
    )

    if user_data is None:
        metrics.incr("news.tasks.confirm_user.confirm_user_not_found", tags=extra_metrics_tags)
        return

    if user_data["optin"]:
        # already confirmed
        return

    if not ("email" in user_data and user_data["email"]):
        raise BasketError(f"token has no email in {'Braze' if use_braze_backend else 'CTMS'}")

    if use_braze_backend:
        braze.update(user_data, {"optin": True, "optout": False})
    else:
        ctms.update(user_data, {"optin": True})


@rq_task
def update_custom_unsub(token, reason, use_braze_backend=False):
    """Record a user's custom unsubscribe reason."""
    if use_braze_backend:
        braze.update_by_token(token, {"unsub_reason": reason})
    else:
        try:
            ctms.update_by_alt_id("token", token, {"reason": reason})
        except CTMSNotFoundByAltIDError:
            # No record found for that token, nothing to do.
            pass


@rq_task
def send_recovery_message(email, token, lang, email_id):
    message_id = "account-recovery"
    txm = BrazeTxEmailMessage.objects.get_message(message_id, lang)
    if txm:
        user_data = {"basket_token": token, "email_id": email_id}
        send_tx_message(email, txm.message_id, txm.language, user_data=user_data)


@rq_task
def record_common_voice_update(data):
    # do not change the sent data in place. A retry will use the changed data.
    dcopy = data.copy()
    email = dcopy.pop("email")
    user_data = get_user_data(email=email, extra_fields=["id", "email_id"])
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


def get_fxa_user_data(fxa_id, email, use_braze_backend=False):
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
    user_data_fxa = get_user_data(fxa_id=fxa_id, extra_fields=["id", "email_id"], use_braze_backend=use_braze_backend)
    if user_data_fxa:
        user_data = user_data_fxa
        # If email doesn't match, update FxA primary email field with the new email.
        if user_data_fxa["email"] != email:
            if use_braze_backend:
                braze.update(user_data_fxa, {"fxa_primary_email": email})
            else:
                ctms.update(user_data_fxa, {"fxa_primary_email": email})

    # if we still don't have user data try again with email this time
    if not user_data:
        user_data = get_user_data(email=email, extra_fields=["id", "email_id"], use_braze_backend=use_braze_backend)

    return user_data

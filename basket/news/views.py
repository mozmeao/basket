import os
import re
from urllib.parse import urlencode

from django.conf import settings
from django.core.exceptions import NON_FIELD_ERRORS
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.cache import cache_page, never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_safe

import fxa.constants
import sentry_sdk
from ratelimit.core import is_ratelimited
from ratelimit.exceptions import Ratelimited

from basket import errors, metrics
from basket.news import tasks
from basket.news.forms import (
    CommonVoiceForm,
    UpdateUserMeta,
)
from basket.news.models import BrazeTxEmailMessage, Newsletter
from basket.news.newsletters import (
    newsletter_and_group_slugs,
    newsletter_languages,
    newsletter_private_slugs,
    newsletter_slugs,
)
from basket.news.utils import (
    MSG_EMAIL_OR_TOKEN_REQUIRED,
    MSG_USER_NOT_FOUND,
    SET,
    SUBSCRIBE,
    UNSUBSCRIBE,
    HttpResponseJSON,
    NewsletterException,
    email_is_blocked,
    get_accept_languages,
    get_best_language,
    get_best_request_lang,
    get_best_supported_lang,
    get_fxa_clients,
    get_user,
    get_user_data,
    has_valid_api_key,
    is_authorized,
    language_code_is_valid,
    newsletter_exception_response,
    parse_newsletters_csv,
    process_email,
)

TOKEN_RE = re.compile(r"^[0-9a-f-]{36}$", flags=re.IGNORECASE)
IP_RATE_LIMIT_EXTERNAL = getattr(settings, "IP_RATE_LIMIT_EXTERNAL", "40/m")
IP_RATE_LIMIT_INTERNAL = getattr(settings, "IP_RATE_LIMIT_INTERNAL", "400/m")
# four submissions for a specific message per phone number per 5 minutes
PHONE_NUMBER_RATE_LIMIT = getattr(settings, "PHONE_NUMBER_RATE_LIMIT", "4/5m")
# four submissions for a set of newsletters per email address per 5 minutes
EMAIL_SUBSCRIBE_RATE_LIMIT = getattr(settings, "EMAIL_SUBSCRIBE_RATE_LIMIT", "4/5m")


def is_token(word):
    return bool(TOKEN_RE.match(word))


def ip_rate_limit_key(group, request):
    return request.headers.get("X-Cluster-Client-Ip", request.META.get("REMOTE_ADDR"))


def ip_rate_limit_rate(group, request):
    client_ip = ip_rate_limit_key(group, request)
    if client_ip and client_ip.startswith("10."):
        # internal request, high limit.
        return IP_RATE_LIMIT_INTERNAL

    return IP_RATE_LIMIT_EXTERNAL


def source_ip_rate_limit_key(group, request):
    return request.headers.get("X-Source-Ip", None)


def source_ip_rate_limit_rate(group, request):
    source_ip = source_ip_rate_limit_key(group, request)
    if source_ip is None:
        # header not provided, no limit.
        return None

    return IP_RATE_LIMIT_EXTERNAL


def ratelimited(request, e):
    # strip out false-y and tokens in the url.
    dotted_path = ".".join(filter(lambda x: x and not is_token(x), request.path.split("/")))
    metrics.incr("news.views.ratelimited", tags=[f"path:{dotted_path}"])
    return HttpResponseJSON(
        {
            "status": "error",
            "desc": "rate limit reached",
            "code": errors.BASKET_USAGE_ERROR,
        },
        429,
    )


def generate_fxa_state():
    return os.urandom(16).hex()


def get_fxa_authorization_url(state, redirect_uri, email):
    fxa_server = fxa.constants.ENVIRONMENT_URLS.get(settings.FXA_OAUTH_SERVER_ENV)["oauth"]
    params = {
        "client_id": settings.FXA_CLIENT_ID,
        "state": state,
        "redirect_uri": redirect_uri,
        "scope": "profile",
    }
    if email:
        params["email"] = email

    return f"{fxa_server}/authorization?{urlencode(params)}"


@require_safe
def fxa_start(request):
    if not settings.FXA_CLIENT_ID:
        redirect_to = "https://www.mozilla.org/firefox/accounts/"
    else:
        fxa_state = request.session["fxa_state"] = generate_fxa_state()
        redirect_uri = request.build_absolute_uri("/fxa/callback/")
        email = request.GET.get("email")
        redirect_to = get_fxa_authorization_url(fxa_state, redirect_uri, email)

    return HttpResponseRedirect(redirect_to)


@require_safe
def fxa_callback(request):
    # remove state from session to prevent multiple attempts
    error_url = f"https://{settings.FXA_EMAIL_PREFS_DOMAIN}/newsletter/recovery/?fxa_error=1"
    sess_state = request.session.pop("fxa_state", None)
    if sess_state is None:
        metrics.incr("news.views.fxa_callback", tags=["status:error", "error:no_sess_state"])
        return HttpResponseRedirect(error_url)

    code = request.GET.get("code")
    state = request.GET.get("state")
    if not (code and state):
        metrics.incr("news.views.fxa_callback", tags=["status:error", "error:no_code_or_state"])
        return HttpResponseRedirect(error_url)

    if sess_state != state:
        metrics.incr("news.views.fxa_callback", tags=["status:error", "error:no_state_match"])
        return HttpResponseRedirect(error_url)

    fxa_oauth, fxa_profile = get_fxa_clients()
    try:
        access_token = fxa_oauth.trade_code(code, ttl=settings.FXA_OAUTH_TOKEN_TTL)["access_token"]
        user_profile = fxa_profile.get_profile(access_token)
    except Exception:
        metrics.incr("news.views.fxa_callback", tags=["status:error", "error:fxa_comm"])
        sentry_sdk.capture_exception()
        return HttpResponseRedirect(error_url)

    email = user_profile.get("email")
    uid = user_profile.get("uid")
    try:
        user_data = get_user_data(email=email, fxa_id=uid)
    except Exception:
        metrics.incr("news.views.fxa_callback", tags=["status:error", "error:user_data"])
        sentry_sdk.capture_exception()
        return HttpResponseRedirect(error_url)

    if user_data:
        token = user_data["token"]
    else:
        new_user_data = {
            "email": email,
            "optin": True,
            "newsletters": [settings.FXA_REGISTER_NEWSLETTER],
            "source_url": f"{settings.FXA_REGISTER_SOURCE_URL}?utm_source=basket-fxa-oauth",
        }
        locale = user_profile.get("locale")
        if locale:
            new_user_data["fxa_lang"] = locale
            lang = get_best_language(get_accept_languages(locale))
            if lang not in newsletter_languages():
                lang = "other"

            new_user_data["lang"] = lang

        try:
            token = tasks.upsert_contact(SUBSCRIBE, new_user_data, None)[0]
        except Exception:
            metrics.incr("news.views.fxa_callback", tags=["status:error", "error:upsert_contact"])
            sentry_sdk.capture_exception()
            return HttpResponseRedirect(error_url)

    metrics.incr("news.views.fxa_callback", tags=["status:success"])
    redirect_to = f"https://{settings.FXA_EMAIL_PREFS_DOMAIN}/newsletter/existing/{token}/?fxa=1"
    return HttpResponseRedirect(redirect_to)


@require_POST
@csrf_exempt
def confirm(request, token):
    token = str(token)
    if is_ratelimited(
        request,
        group="basket.news.views.confirm",
        key=lambda x, y: token,
        rate=EMAIL_SUBSCRIBE_RATE_LIMIT,
        increment=True,
    ):
        raise Ratelimited()
    tasks.confirm_user.delay(token)
    return HttpResponseJSON({"status": "ok"})


def respond_ok(request, data, template_name="news/thankyou.html"):
    """
    Return either a JSON or HTML success response

    @param request: the request
    @param data: the incoming request data
    @param template_name: the template name in case of HTML response
    @return: HttpResponse object
    """
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return HttpResponseJSON({"status": "ok"})
    else:
        return render(request, template_name, data)


def respond_error(request, form, message, code, template_name="news/formerror.html"):
    """
    Return either a JSON or HTML error response

    @param request: the request
    @param form: the bound form object
    @param message: the error message
    @param code: the HTTP status code
    @param template_name: the template name in case of HTML response
    @return: HttpResponse object
    """
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return HttpResponseJSON(
            {
                "status": "error",
                "errors": [message],
                "errors_by_field": {NON_FIELD_ERRORS: [message]},
            },
            code,
        )
    else:
        form.add_error(None, message)
        return render(request, template_name, {"form": form}, status=code)


def format_form_errors(errors):
    """Convert a dict of form errors into a list"""
    error_list = []
    for fname, ferrors in errors.items():
        for err in ferrors:
            error_list.append(f"{fname}: {err}")

    return error_list


@require_POST
@csrf_exempt
def common_voice_goals(request):
    if not has_valid_api_key(request):
        return HttpResponseJSON(
            {
                "status": "error",
                "desc": "requires a valid API-key",
                "code": errors.BASKET_AUTH_ERROR,
            },
            401,
        )

    form = CommonVoiceForm(request.POST)
    if form.is_valid():
        # don't send empty values and use ISO formatted date strings
        data = {k: v for k, v in form.cleaned_data.items() if not (v == "" or v is None)}
        tasks.record_common_voice_update.delay(data)

        return HttpResponseJSON({"status": "ok"})
    else:
        # form is invalid
        return HttpResponseJSON(
            {
                "status": "error",
                "errors": format_form_errors(form.errors),
                "errors_by_field": form.errors,
            },
            400,
        )


@require_POST
@csrf_exempt
def subscribe(request):
    data = request.POST.dict()
    newsletters = data.get("newsletters", None)
    if not newsletters:
        return HttpResponseJSON(
            {
                "status": "error",
                "desc": "newsletters is missing",
                "code": errors.BASKET_USAGE_ERROR,
            },
            400,
        )

    email = data.pop("email", None)
    token = data.pop("token", None)

    if not (email or token):
        return HttpResponseJSON(
            {
                "status": "error",
                "desc": "email or token is required",
                "code": errors.BASKET_USAGE_ERROR,
            },
            401,
        )

    # If we don't have an email, we must have a token after the above check.
    if not email:
        # Validate we have a UUID token.
        if not is_token(token):
            return invalid_token_response()
        # Get the user's email from the token.
        try:
            user_data = get_user_data(token=token)
            if user_data:
                email = user_data.get("email")
        except NewsletterException as e:
            return newsletter_exception_response(e)

    email = process_email(email)
    if not email:
        return invalid_token_response() if token else invalid_email_response()
    data["email"] = email

    if email_is_blocked(email):
        metrics.incr("news.views.subscribe", tags=["info:email_blocked"])
        # don't let on there's a problem
        return HttpResponseJSON({"status": "ok"})

    optin = data.pop("optin", "N").upper() == "Y"
    sync = data.pop("sync", "N").upper() == "Y"

    authorized = False
    if optin or sync:
        if is_authorized(request, email):
            authorized = True

    if optin and not authorized:
        # for backward compat we just ignore the optin if
        # no valid API key is sent.
        optin = False

    if sync:
        if not authorized:
            return HttpResponseJSON(
                {
                    "status": "error",
                    "desc": "Using subscribe with sync=Y, you need to pass a valid `api-key` or FxA OAuth Authorization.",
                    "code": errors.BASKET_AUTH_ERROR,
                },
                401,
            )

    # NOTE this is not a typo; Referrer is misspelled in the HTTP spec
    # https://www.w3.org/Protocols/rfc2616/rfc2616-sec14.html#sec14.36
    if not data.get("source_url") and request.headers.get("Referer"):
        # try to get it from referrer
        metrics.incr("news.views.subscribe", tags=["info:use_referrer"])
        data["source_url"] = request.headers["referer"]

    return update_user_task(request, SUBSCRIBE, data=data, optin=optin, sync=sync)


def invalid_email_response():
    resp_data = {
        "status": "error",
        "code": errors.BASKET_INVALID_EMAIL,
        "desc": "Invalid email address",
    }
    metrics.incr("news.views.invalid_email_response")
    return HttpResponseJSON(resp_data, 400)


def invalid_token_response():
    resp_data = {
        "status": "error",
        "code": errors.BASKET_INVALID_TOKEN,
        "desc": "Invalid basket token",
    }
    metrics.incr("news.views.invalid_token_response")
    return HttpResponseJSON(resp_data, 400)


@require_POST
@csrf_exempt
def unsubscribe(request, token):
    token = str(token)
    data = request.POST.dict()
    data["token"] = token

    if data.get("optout", "N") == "Y":
        data["optout"] = True
        data["newsletters"] = ",".join(newsletter_slugs())

    return update_user_task(request, UNSUBSCRIBE, data)


@require_POST
@csrf_exempt
def user_meta(request, token):
    """Only update user metadata, not newsletters"""
    token = str(token)
    form = UpdateUserMeta(request.POST)
    if form.is_valid():
        # don't send empty values
        data = {k: v for k, v in form.cleaned_data.items() if v}
        tasks.update_user_meta.delay(token, data)
        return HttpResponseJSON({"status": "ok"})

    return HttpResponseJSON(
        {
            "status": "error",
            "desc": "data is invalid",
            "code": errors.BASKET_USAGE_ERROR,
        },
        400,
    )


@csrf_exempt
@never_cache
def user(request, token):
    token = str(token)
    if request.method == "POST":
        data = request.POST.dict()
        data["token"] = token
        if "email" in data:
            email = process_email(data["email"])
            if not email:
                return invalid_email_response()

            data["email"] = email
        return update_user_task(request, SET, data)

    get_fxa = "fxa" in request.GET
    masked = not has_valid_api_key(request)
    return get_user(token, get_fxa=get_fxa, masked=masked)


@require_POST
@csrf_exempt
def send_recovery_message(request):
    """
    Send a recovery message to an email address.

    required form parameter: email

    If email not provided or not syntactically correct, returns 400.
    If email not known, returns 404.
    Otherwise, queues a task to send the message and returns 200.
    """
    email = process_email(request.POST.get("email"))
    if not email:
        return invalid_email_response()

    if email_is_blocked(email):
        # don't let on there's a problem
        return HttpResponseJSON({"status": "ok"})

    try:
        user_data = get_user_data(email=email)
    except NewsletterException as e:
        return newsletter_exception_response(e)

    if not user_data:
        return HttpResponseJSON(
            {
                "status": "error",
                "desc": "Email address not known",
                "code": errors.BASKET_UNKNOWN_EMAIL,
            },
            404,
        )  # Note: Bedrock looks for this 404

    lang = user_data.get("lang", "en") or "en"
    email_id = user_data.get("email_id")
    tasks.send_recovery_message.delay(email, user_data["token"], lang, email_id)
    return HttpResponseJSON({"status": "ok"})


# Custom update methods


@csrf_exempt
def custom_unsub_reason(request):
    """Update the reason field for the user, which logs why the user
    unsubscribed from all newsletters."""

    if "token" not in request.POST or "reason" not in request.POST:
        return HttpResponseJSON(
            {
                "status": "error",
                "desc": "custom_unsub_reason requires the `token` and `reason` POST parameters",
                "code": errors.BASKET_USAGE_ERROR,
            },
            400,
        )

    tasks.update_custom_unsub.delay(request.POST["token"], request.POST["reason"])
    return HttpResponseJSON({"status": "ok"})


# Get data about current newsletters
@require_safe
@cache_page(300)
def newsletters(request):
    # Get the newsletters as a dictionary of dictionaries that are
    # easily jsonified
    result = {}
    for newsletter in Newsletter.objects.all().values():
        newsletter["languages"] = newsletter["languages"].split(",")
        result[newsletter["slug"]] = newsletter
        del newsletter["id"]  # caller doesn't need to know our pkey
        del newsletter["slug"]  # or our slug

    return HttpResponseJSON({"status": "ok", "newsletters": result})


@never_cache
def lookup_user(request):
    """Lookup a user in CTMS given email or token (not both).

    To look up by email, a valid API key is required.

    If email and token are both provided, an error is returned rather
    than trying to define all the possible behaviors.

    SSL is always required when using this call. If no SSL, it'll fail
    with 401 and an appropriate message in the response body.

    Response content is always JSON.

    If user is not found, returns a 404 status and json is::

        {
            'status': 'error',
            'desc': 'No such user'
        }

    (If you need to distinguish user not found from an error calling
    the API, check the response content.)

    If a required, valid API key is not provided, status is 401 Unauthorized.
    The API key can be provided either as a GET query parameter ``api-key``
    or a request header ``X-api-key``. If it's provided as a query parameter,
    any request header is ignored.

    For other errors, similarly response status is 4xx and the json 'desc'
    says what's wrong.

    Otherwise, status is 200 and json is the return value from
    `get_user_data`. See that method for details.

    Note that because this method always calls CTMS one or more times, it can be
    slower than some other Basket APIs, and will fail if CTMS is down.
    """
    if settings.MAINTENANCE_MODE and not settings.MAINTENANCE_READ_ONLY:
        # can't return user data during maintenance
        return HttpResponseJSON(
            {
                "status": "error",
                "desc": "user data is not available in maintenance mode",
                "code": errors.BASKET_NETWORK_FAILURE,
            },
            400,
        )

    token = request.GET.get("token", None)
    email = request.GET.get("email", None)
    get_fxa = "fxa" in request.GET

    if (not email and not token) or (email and token):
        return HttpResponseJSON(
            {
                "status": "error",
                "desc": MSG_EMAIL_OR_TOKEN_REQUIRED,
                "code": errors.BASKET_USAGE_ERROR,
            },
            400,
        )

    authorized = is_authorized(request, email)
    if email and not authorized:
        return HttpResponseJSON(
            {
                "status": "error",
                "desc": "Using lookup_user with `email`, you need to pass a valid `api-key` or FxA OAuth Autorization header.",
                "code": errors.BASKET_AUTH_ERROR,
            },
            401,
        )

    if email:
        email = process_email(email)
        if not email:
            return invalid_email_response()

    try:
        user_data = get_user_data(token=token, email=email, get_fxa=get_fxa, masked=not authorized)
    except NewsletterException as e:
        return newsletter_exception_response(e)

    status_code = 200
    if not user_data:
        code = errors.BASKET_UNKNOWN_TOKEN if token else errors.BASKET_UNKNOWN_EMAIL
        user_data = {
            "status": "error",
            "desc": MSG_USER_NOT_FOUND,
            "code": code,
        }
        status_code = 404

    return HttpResponseJSON(user_data, status_code)


@require_safe
@cache_page(300)
def list_newsletters(request):
    """
    Public web page listing currently active newsletters.
    """
    active_newsletters = Newsletter.objects.filter(active=True, private=False)
    return render(request, "news/newsletters.html", {"newsletters": active_newsletters})


def update_user_task(request, api_call_type, data=None, optin=False, sync=False):
    """Call the update_user task async with the right parameters.

    If sync==True, be sure to include the token in the response.
    Otherwise, basket can just do everything in the background.
    """
    data = data or request.POST.dict()

    newsletters = parse_newsletters_csv(data.get("newsletters"))
    if newsletters:
        if api_call_type == SUBSCRIBE:
            all_transactionals = BrazeTxEmailMessage.objects.get_tx_message_ids()
            all_newsletters = newsletter_and_group_slugs() + all_transactionals
        else:
            all_newsletters = newsletter_slugs()

        private_newsletters = newsletter_private_slugs()

        for nl in newsletters:
            if nl not in all_newsletters:
                return HttpResponseJSON(
                    {
                        "status": "error",
                        "desc": "invalid newsletter",
                        "code": errors.BASKET_INVALID_NEWSLETTER,
                    },
                    400,
                )

            if api_call_type == SUBSCRIBE and nl in private_newsletters:
                if not is_authorized(request, data.get("email")):
                    return HttpResponseJSON(
                        {
                            "status": "error",
                            "desc": "private newsletter subscription requires a valid API key or OAuth",
                            "code": errors.BASKET_AUTH_ERROR,
                        },
                        401,
                    )

    if "lang" in data:
        if not language_code_is_valid(data["lang"]):
            data["lang"] = "en"
    elif "accept_lang" in data:
        lang = get_best_language(get_accept_languages(data["accept_lang"]))
        if lang:
            data["lang"] = lang
            del data["accept_lang"]
    # if lang not provided get the best one from the accept-language header
    else:
        lang = get_best_request_lang(request)
        if lang:
            data["lang"] = lang

    # now ensure that if we do have a lang that it's a supported one
    if "lang" in data:
        data["lang"] = get_best_supported_lang(data["lang"])

    email = data.get("email")
    token = data.get("token")
    if not (email or token):
        return HttpResponseJSON(
            {
                "status": "error",
                "desc": MSG_EMAIL_OR_TOKEN_REQUIRED,
                "code": errors.BASKET_USAGE_ERROR,
            },
            400,
        )

    if optin:
        data["optin"] = True

    if api_call_type == SUBSCRIBE and email and data.get("newsletters"):
        # only rate limit here so we don't rate limit errors.
        if is_ratelimited(
            request,
            group="basket.news.views.update_user_task.subscribe",
            key=lambda x, y: f"{data['newsletters']}-{email}",
            rate=EMAIL_SUBSCRIBE_RATE_LIMIT,
            increment=True,
        ):
            raise Ratelimited()

    if api_call_type == SET and token and data.get("newsletters"):
        # only rate limit here so we don't rate limit errors.
        if is_ratelimited(
            request,
            group="basket.news.views.update_user_task.set",
            key=lambda x, y: f"{data['newsletters']}-{token}",
            rate=EMAIL_SUBSCRIBE_RATE_LIMIT,
            increment=True,
        ):
            raise Ratelimited()

    if sync:
        metrics.incr("news.views.subscribe.sync")
        if settings.MAINTENANCE_MODE and not settings.MAINTENANCE_READ_ONLY:
            # save what we can
            tasks.upsert_user.delay(api_call_type, data)
            # have to error since we can't return a token
            return HttpResponseJSON(
                {
                    "status": "error",
                    "desc": "sync is not available in maintenance mode",
                    "code": errors.BASKET_NETWORK_FAILURE,
                },
                400,
            )

        try:
            user_data = get_user_data(email=email, token=token)
        except NewsletterException as e:
            return newsletter_exception_response(e)

        if not user_data:
            if not email:
                # must have email to create a user
                return HttpResponseJSON(
                    {
                        "status": "error",
                        "desc": MSG_EMAIL_OR_TOKEN_REQUIRED,
                        "code": errors.BASKET_USAGE_ERROR,
                    },
                    400,
                )

        token, created = tasks.upsert_contact(api_call_type, data, user_data)
        return HttpResponseJSON({"status": "ok", "token": token, "created": created})
    else:
        tasks.upsert_user.delay(api_call_type, data)
        return HttpResponseJSON({"status": "ok"})

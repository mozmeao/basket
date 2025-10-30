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
from django_ratelimit.core import is_ratelimited
from django_ratelimit.exceptions import Ratelimited

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
    MSG_EMAIL_AUTH_REQUIRED,
    MSG_EMAIL_OR_TOKEN_REQUIRED,
    MSG_MAINTENANCE_MODE,
    MSG_USER_NOT_FOUND,
    SET,
    SUBSCRIBE,
    UNSUBSCRIBE,
    HttpResponseJSON,
    NewsletterException,
    email_is_blocked,
    generate_token,
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


def is_token(word):
    return bool(TOKEN_RE.match(word))


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

    def handler(
        email,
        uid,
        use_braze_backend=False,
        should_send_tx_messages=True,
        extra_metrics_tags=None,
        pre_generated_token=None,
    ):
        if extra_metrics_tags is None:
            extra_metrics_tags = []

        try:
            user_data = get_user_data(
                email=email,
                fxa_id=uid,
                use_braze_backend=use_braze_backend,
            )
        except Exception:
            metrics.incr("news.views.fxa_callback", tags=["status:error", "error:user_data", *extra_metrics_tags])
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
                token = tasks.upsert_contact(
                    SUBSCRIBE,
                    new_user_data,
                    None,
                    use_braze_backend=use_braze_backend,
                    should_send_tx_messages=should_send_tx_messages,
                    pre_generated_token=pre_generated_token,
                )[0]
            except Exception:
                metrics.incr("news.views.fxa_callback", tags=["status:error", "error:upsert_contact", *extra_metrics_tags])
                sentry_sdk.capture_exception()
                return HttpResponseRedirect(error_url)

        metrics.incr("news.views.fxa_callback", tags=["status:success", *extra_metrics_tags])
        redirect_to = f"https://{settings.FXA_EMAIL_PREFS_DOMAIN}/newsletter/existing/{token}/?fxa=1"
        return HttpResponseRedirect(redirect_to)

    if settings.BRAZE_PARALLEL_WRITE_ENABLE:
        pre_generated_token = generate_token()
        try:
            handler(
                email,
                uid,
                use_braze_backend=True,
                should_send_tx_messages=False,
                extra_metrics_tags=["backend:braze"],
                pre_generated_token=pre_generated_token,
            )
        except Exception:
            sentry_sdk.capture_exception()

        return handler(
            email,
            uid,
            use_braze_backend=False,
            should_send_tx_messages=True,
            pre_generated_token=pre_generated_token,
        )
    elif settings.BRAZE_ONLY_WRITE_ENABLE:
        return handler(
            email,
            uid,
            use_braze_backend=True,
            should_send_tx_messages=True,
            extra_metrics_tags=["backend:braze"],
        )
    else:
        return handler(
            email,
            uid,
            use_braze_backend=False,
            should_send_tx_messages=True,
        )


@require_POST
@csrf_exempt
def confirm(request, token):
    token = str(token)
    if is_ratelimited(
        request,
        group="basket.news.views.confirm",
        key=lambda x, y: token,
        rate=settings.EMAIL_SUBSCRIBE_RATE_LIMIT,
        increment=True,
    ):
        raise Ratelimited()

    if settings.BRAZE_PARALLEL_WRITE_ENABLE:
        tasks.confirm_user.delay(
            token,
            use_braze_backend=True,
            extra_metrics_tags=["backend:braze"],
        )
        tasks.confirm_user.delay(
            token,
            use_braze_backend=False,
        )
    elif settings.BRAZE_ONLY_WRITE_ENABLE:
        tasks.confirm_user.delay(
            token,
            use_braze_backend=True,
            extra_metrics_tags=["backend:braze"],
        )
    else:
        tasks.confirm_user.delay(
            token,
            use_braze_backend=False,
        )

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
    def handler(
        request,
        use_braze_backend=False,
        should_send_tx_messages=True,
        rate_limit_increment=True,
        extra_metrics_tags=None,
        pre_generated_token=None,
        pre_generated_email_id=None,
    ):
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

        if extra_metrics_tags is None:
            extra_metrics_tags = []

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
                user_data = get_user_data(token=token, use_braze_backend=use_braze_backend)
                if user_data:
                    email = user_data.get("email")
            except NewsletterException as e:
                return newsletter_exception_response(e)

        email = process_email(email)
        if not email:
            return invalid_token_response() if token else invalid_email_response()
        data["email"] = email

        if email_is_blocked(email):
            metrics.incr("news.views.subscribe", tags=["info:email_blocked", *extra_metrics_tags])
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
            metrics.incr("news.views.subscribe", tags=["info:use_referrer", *extra_metrics_tags])
            data["source_url"] = request.headers["referer"]

        return update_user_task(
            request,
            SUBSCRIBE,
            data=data,
            optin=optin,
            sync=sync,
            use_braze_backend=use_braze_backend,
            should_send_tx_messages=should_send_tx_messages,
            rate_limit_increment=rate_limit_increment,
            extra_metrics_tags=extra_metrics_tags,
            pre_generated_token=pre_generated_token,
            pre_generated_email_id=pre_generated_email_id,
        )

    # We are doing parallel writes and want the token/email_id
    # to be same in both CTMS and Braze so we eagerly generate them now.
    pre_generated_token = generate_token()
    pre_generated_email_id = generate_token()

    if settings.BRAZE_PARALLEL_WRITE_ENABLE:
        try:
            handler(
                request,
                use_braze_backend=True,
                should_send_tx_messages=False,
                rate_limit_increment=False,
                extra_metrics_tags=["backend:braze"],
                pre_generated_token=pre_generated_token,
                pre_generated_email_id=pre_generated_email_id,
            )
        except Exception:
            sentry_sdk.capture_exception()

        return handler(
            request,
            use_braze_backend=False,
            should_send_tx_messages=True,
            rate_limit_increment=True,
            pre_generated_token=pre_generated_token,
            pre_generated_email_id=pre_generated_email_id,
        )
    elif settings.BRAZE_ONLY_WRITE_ENABLE:
        return handler(
            request,
            use_braze_backend=True,
            should_send_tx_messages=True,
            rate_limit_increment=True,
            extra_metrics_tags=["backend:braze"],
            # After the external_id migration we can stop passing in email_id here.
            pre_generated_email_id=pre_generated_email_id,
        )
    else:
        return handler(
            request,
            use_braze_backend=False,
            should_send_tx_messages=True,
            rate_limit_increment=True,
        )


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

    if settings.BRAZE_PARALLEL_WRITE_ENABLE:
        try:
            update_user_task(
                request,
                UNSUBSCRIBE,
                data,
                use_braze_backend=True,
                should_send_tx_messages=False,
                rate_limit_increment=False,
                extra_metrics_tags=["backend:braze"],
            )
        except Exception:
            sentry_sdk.capture_exception()

        return update_user_task(
            request,
            UNSUBSCRIBE,
            data,
            use_braze_backend=False,
            should_send_tx_messages=True,
            rate_limit_increment=True,
        )
    elif settings.BRAZE_ONLY_WRITE_ENABLE:
        return update_user_task(
            request,
            UNSUBSCRIBE,
            data,
            use_braze_backend=True,
            should_send_tx_messages=True,
            rate_limit_increment=True,
            extra_metrics_tags=["backend:braze"],
        )
    else:
        return update_user_task(
            request,
            UNSUBSCRIBE,
            data,
            use_braze_backend=False,
            should_send_tx_messages=True,
            rate_limit_increment=True,
        )


@require_POST
@csrf_exempt
def user_meta(request, token):
    """Only update user metadata, not newsletters"""
    token = str(token)
    form = UpdateUserMeta(request.POST)
    if form.is_valid():
        # don't send empty values
        data = {k: v for k, v in form.cleaned_data.items() if v}
        if settings.BRAZE_PARALLEL_WRITE_ENABLE:
            tasks.update_user_meta.delay(token, data, use_braze_backend=True)
            tasks.update_user_meta.delay(token, data, use_braze_backend=False)
        elif settings.BRAZE_ONLY_WRITE_ENABLE:
            tasks.update_user_meta.delay(token, data, use_braze_backend=True)
        else:
            tasks.update_user_meta.delay(token, data, use_braze_backend=False)
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
        if settings.BRAZE_PARALLEL_WRITE_ENABLE:
            pre_generated_token = generate_token()
            update_user_task(
                request,
                SET,
                data,
                use_braze_backend=True,
                should_send_tx_messages=False,
                rate_limit_increment=False,
                extra_metrics_tags=["backend:braze"],
                pre_generated_token=pre_generated_token,
            )
            return update_user_task(
                request,
                SET,
                data,
                use_braze_backend=False,
                should_send_tx_messages=True,
                rate_limit_increment=True,
                pre_generated_token=pre_generated_token,
            )
        elif settings.BRAZE_ONLY_WRITE_ENABLE:
            return update_user_task(
                request,
                SET,
                data,
                use_braze_backend=True,
                should_send_tx_messages=True,
                rate_limit_increment=True,
                extra_metrics_tags=["backend:braze"],
            )
        else:
            return update_user_task(
                request,
                SET,
                data,
                use_braze_backend=False,
                should_send_tx_messages=True,
                rate_limit_increment=True,
            )

    masked = not has_valid_api_key(request)

    if settings.BRAZE_READ_WITH_FALLBACK_ENABLE:
        try:
            response = get_user(token, masked=masked, use_braze_backend=True)
            # If token migration isn't complete we might only find the user
            # in CTMS when looking up by token.
            if response.status_code == 404:
                return get_user(token, masked=masked, use_braze_backend=False)
            return response
        except Exception:
            sentry_sdk.capture_exception()
            return get_user(token, masked=masked, use_braze_backend=False)
    elif settings.BRAZE_ONLY_READ_ENABLE:
        return get_user(token, masked=masked, use_braze_backend=True)
    else:
        return get_user(token, masked=masked, use_braze_backend=False)


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
        if settings.BRAZE_READ_WITH_FALLBACK_ENABLE:
            try:
                user_data = get_user_data(
                    email=email,
                    extra_fields=["email_id"],
                    use_braze_backend=True,
                )
            except Exception:
                sentry_sdk.capture_exception()
                user_data = get_user_data(
                    email=email,
                    extra_fields=["email_id"],
                    use_braze_backend=False,
                )
        elif settings.BRAZE_ONLY_READ_ENABLE:
            user_data = get_user_data(
                email=email,
                extra_fields=["email_id"],
                use_braze_backend=True,
            )
        else:
            user_data = get_user_data(
                email=email,
                extra_fields=["email_id"],
                use_braze_backend=False,
            )
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


# TODO confirm if this endpoint is still needed.
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
                "desc": MSG_MAINTENANCE_MODE,
                "code": errors.BASKET_MAINTENANCE_ERROR,
            },
            400,
        )

    token = request.GET.get("token", None)
    email = request.GET.get("email", None)

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
                "desc": MSG_EMAIL_AUTH_REQUIRED,
                "code": errors.BASKET_AUTH_ERROR,
            },
            401,
        )

    if email:
        email = process_email(email)
        if not email:
            return invalid_email_response()

    try:
        if settings.BRAZE_READ_WITH_FALLBACK_ENABLE:
            try:
                user_data = get_user_data(
                    token=token,
                    email=email,
                    masked=not authorized,
                    use_braze_backend=True,
                )
                # If token migration isn't complete we might only find the user
                # in CTMS when looking up by token.
                if not user_data:
                    user_data = get_user_data(
                        token=token,
                        email=email,
                        masked=not authorized,
                        use_braze_backend=False,
                    )
            except Exception:
                sentry_sdk.capture_exception()
                user_data = get_user_data(
                    token=token,
                    email=email,
                    masked=not authorized,
                    use_braze_backend=False,
                )
        elif settings.BRAZE_ONLY_READ_ENABLE:
            user_data = get_user_data(
                token=token,
                email=email,
                masked=not authorized,
                use_braze_backend=True,
            )
        else:
            user_data = get_user_data(
                token=token,
                email=email,
                masked=not authorized,
                use_braze_backend=False,
            )
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


def update_user_task(
    request,
    api_call_type,
    data=None,
    optin=False,
    sync=False,
    use_braze_backend=False,
    should_send_tx_messages=True,
    rate_limit_increment=True,
    extra_metrics_tags=None,
    pre_generated_token=None,
    pre_generated_email_id=None,
):
    """Call the update_user task async with the right parameters.

    If sync==True, be sure to include the token in the response.
    Otherwise, basket can just do everything in the background.
    """
    if extra_metrics_tags is None:
        extra_metrics_tags = []

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
            rate=settings.EMAIL_SUBSCRIBE_RATE_LIMIT,
            increment=rate_limit_increment,
        ):
            raise Ratelimited()

    if api_call_type == SET and token and data.get("newsletters"):
        # only rate limit here so we don't rate limit errors.
        if is_ratelimited(
            request,
            group="basket.news.views.update_user_task.set",
            key=lambda x, y: f"{data['newsletters']}-{token}",
            rate=settings.EMAIL_SUBSCRIBE_RATE_LIMIT,
            increment=rate_limit_increment,
        ):
            raise Ratelimited()

    if sync:
        metrics.incr("news.views.subscribe.sync", tags=extra_metrics_tags)
        if settings.MAINTENANCE_MODE and not settings.MAINTENANCE_READ_ONLY:
            # save what we can
            tasks.upsert_user.delay(
                api_call_type,
                data,
                use_braze_backend=use_braze_backend,
                should_send_tx_messages=should_send_tx_messages,
                pre_generated_token=pre_generated_token,
                pre_generated_email_id=pre_generated_email_id,
            )
            # have to error since we can't return a token
            return HttpResponseJSON(
                {
                    "status": "error",
                    "desc": MSG_MAINTENANCE_MODE,
                    "code": errors.BASKET_MAINTENANCE_ERROR,
                },
                400,
            )

        try:
            user_data = get_user_data(
                email=email,
                token=token,
                extra_fields=["email_id"],
                use_braze_backend=use_braze_backend,
            )
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

        token, created = tasks.upsert_contact(
            api_call_type,
            data,
            user_data,
            use_braze_backend=use_braze_backend,
            should_send_tx_messages=should_send_tx_messages,
            pre_generated_token=pre_generated_token,
            pre_generated_email_id=pre_generated_email_id,
        )
        return HttpResponseJSON({"status": "ok", "token": token, "created": created})
    else:
        tasks.upsert_user.delay(
            api_call_type,
            data,
            use_braze_backend=use_braze_backend,
            should_send_tx_messages=should_send_tx_messages,
            pre_generated_token=pre_generated_token,
            pre_generated_email_id=pre_generated_email_id,
        )
        return HttpResponseJSON({"status": "ok"})

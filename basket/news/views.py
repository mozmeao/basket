import json
import os
import re
from time import time
from urllib.parse import urlencode

from django.conf import settings
from django.core.exceptions import NON_FIELD_ERRORS
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.cache import cache_page, never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_safe

import fxa.constants
from basket import errors
from django_statsd.clients import statsd
from ratelimit.exceptions import Ratelimited
from ratelimit.utils import is_ratelimited
from raven.contrib.django.raven_compat.models import client as sentry_client
from synctool.routing import Route

from basket.news.forms import CommonVoiceForm, SubscribeForm, UpdateUserMeta, SOURCE_URL_RE
from basket.news.models import Newsletter, Interest, LocaleStewards, NewsletterGroup, LocalizedSMSMessage, \
    TransactionalEmailMessage
from basket.news.newsletters import get_sms_vendor_id, newsletter_slugs, newsletter_and_group_slugs, \
    newsletter_private_slugs, get_transactional_message_ids
from basket.news.tasks import (
    add_sms_user,
    confirm_user,
    record_common_voice_goals,
    record_fxa_concerts_rsvp,
    send_recovery_message_task,
    update_custom_unsub,
    update_get_involved,
    update_user_meta,
    upsert_contact,
    upsert_user,
    process_subhub_event_credit_card_expiring,
    process_subhub_event_customer_created,
    process_subhub_event_customer_updated,
    process_subhub_event_payment_failed,
    process_subhub_event_subscription_updated,
    process_subhub_event_subscription_charge,
)
from basket.news.utils import (
    SET,
    SUBSCRIBE,
    UNSUBSCRIBE,
    MSG_EMAIL_OR_TOKEN_REQUIRED,
    MSG_USER_NOT_FOUND,
    email_is_blocked,
    get_accept_languages,
    get_best_language,
    get_best_supported_lang,
    get_fxa_clients,
    get_user_data,
    get_user,
    has_valid_api_key,
    HttpResponseJSON,
    is_authorized,
    language_code_is_valid,
    NewsletterException,
    parse_phone_number,
    process_email,
    newsletter_exception_response,
    parse_newsletters_csv, get_best_request_lang)


TOKEN_RE = re.compile(r'^[0-9a-f-]{36}$', flags=re.IGNORECASE)
IP_RATE_LIMIT_EXTERNAL = getattr(settings, 'IP_RATE_LIMIT_EXTERNAL', '40/m')
IP_RATE_LIMIT_INTERNAL = getattr(settings, 'IP_RATE_LIMIT_INTERNAL', '400/m')
# four submissions for a specific message per phone number per 5 minutes
PHONE_NUMBER_RATE_LIMIT = getattr(settings, 'PHONE_NUMBER_RATE_LIMIT', '4/5m')
# four submissions for a set of newsletters per email address per 5 minutes
EMAIL_SUBSCRIBE_RATE_LIMIT = getattr(settings, 'EMAIL_SUBSCRIBE_RATE_LIMIT', '4/5m')
sync_route = Route(api_token=settings.SYNC_KEY)


SUBHUB_EVENT_TYPES = {
    'customer.created': process_subhub_event_customer_created,
    'customer.source.expiring': process_subhub_event_credit_card_expiring,
    'customer.subscription.updated': process_subhub_event_subscription_updated,  # creations, updates, & cancellations
    'customer.updated': process_subhub_event_customer_updated,
    'invoice.finalized': process_subhub_event_subscription_charge,  # used for both new and recurring charges
    'invoice.payment_failed': process_subhub_event_payment_failed,
    'payment_intent.succeeded': process_subhub_event_subscription_charge,  # used for both new and recurring charges
}


def is_token(word):
    return bool(TOKEN_RE.match(word))


@sync_route.queryset('sync')
def news_sync():
    return [
        Newsletter.objects.all(),
        NewsletterGroup.objects.all(),
        Interest.objects.all(),
        LocaleStewards.objects.all(),
        LocalizedSMSMessage.objects.all(),
        TransactionalEmailMessage.objects.all(),
    ]


def ip_rate_limit_key(group, request):
    return request.META.get('HTTP_X_CLUSTER_CLIENT_IP',
                            request.META.get('REMOTE_ADDR'))


def ip_rate_limit_rate(group, request):
    client_ip = ip_rate_limit_key(group, request)
    if client_ip and client_ip.startswith('10.'):
        # internal request, high limit.
        return IP_RATE_LIMIT_INTERNAL

    return IP_RATE_LIMIT_EXTERNAL


def source_ip_rate_limit_key(group, request):
    return request.META.get('HTTP_X_SOURCE_IP', None)


def source_ip_rate_limit_rate(group, request):
    source_ip = source_ip_rate_limit_key(group, request)
    if source_ip is None:
        # header not provided, no limit.
        return None

    return IP_RATE_LIMIT_EXTERNAL


def ratelimited(request, e):
    parts = [x.strip() for x in request.path.split('/') if x.strip()]
    # strip out tokens in the urls
    parts = [x for x in parts if not is_token(x)]
    statsd.incr('.'.join(parts + ['ratelimited']))
    return HttpResponseJSON({
        'status': 'error',
        'desc': 'rate limit reached',
        'code': errors.BASKET_USAGE_ERROR,
    }, 429)


def generate_fxa_state():
    return os.urandom(16).hex()


def get_fxa_authorization_url(state, redirect_uri, email):
    fxa_server = fxa.constants.ENVIRONMENT_URLS.get(settings.FXA_OAUTH_SERVER_ENV)['oauth']
    params = {
        'client_id': settings.FXA_CLIENT_ID,
        'state': state,
        'redirect_uri': redirect_uri,
        'scope': 'profile',
    }
    if email:
        params['email'] = email

    return '{}/authorization?{}'.format(fxa_server, urlencode(params))


@require_safe
def fxa_start(request):
    if not settings.FXA_CLIENT_ID:
        redirect_to = 'https://www.mozilla.org/firefox/accounts/'
    else:
        fxa_state = request.session['fxa_state'] = generate_fxa_state()
        redirect_uri = request.build_absolute_uri('/fxa/callback/')
        email = request.GET.get('email')
        redirect_to = get_fxa_authorization_url(fxa_state, redirect_uri, email)

    return HttpResponseRedirect(redirect_to)


@require_safe
def fxa_callback(request):
    # remove state from session to prevent multiple attempts
    error_url = 'https://{}/newsletter/fxa-error/'.format(settings.FXA_EMAIL_PREFS_DOMAIN)
    sess_state = request.session.pop('fxa_state', None)
    if sess_state is None:
        statsd.incr('news.views.fxa_callback.error.no_state')
        return HttpResponseRedirect(error_url)

    code = request.GET.get('code')
    state = request.GET.get('state')
    if not (code and state):
        statsd.incr('news.views.fxa_callback.error.no_code_state')
        return HttpResponseRedirect(error_url)

    if sess_state != state:
        statsd.incr('news.views.fxa_callback.error.no_state_match')
        return HttpResponseRedirect(error_url)

    fxa_oauth, fxa_profile = get_fxa_clients()
    try:
        access_token = fxa_oauth.trade_code(code)['access_token']
        user_profile = fxa_profile.get_profile(access_token)
    except Exception:
        statsd.incr('news.views.fxa_callback.error.fxa_comm')
        sentry_client.captureException()
        return HttpResponseRedirect(error_url)

    email = user_profile['email']
    user_data = get_user_data(email=email)
    if user_data:
        token = user_data['token']
    else:
        new_user_data = {
            'email': email,
            'optin': True,
            'format': 'H',
            'newsletters': [settings.FXA_REGISTER_NEWSLETTER],
            'source_url': settings.FXA_REGISTER_SOURCE_URL + '?utm_source=basket-fxa-oauth',
        }
        lang = user_profile.get('locale')
        if lang:
            lang = get_best_language(get_accept_languages(lang))
            new_user_data['lang'] = lang

        token = upsert_contact(SUBSCRIBE, new_user_data, None)[0]

    redirect_to = 'https://{}/newsletter/existing/{}/?fxa=1'.format(settings.FXA_EMAIL_PREFS_DOMAIN, token)
    return HttpResponseRedirect(redirect_to)


@require_POST
@csrf_exempt
def confirm(request, token):
    token = str(token)
    if is_ratelimited(request, group='basket.news.views.confirm',
                      key=lambda x, y: token,
                      rate=EMAIL_SUBSCRIBE_RATE_LIMIT, increment=True):
        raise Ratelimited()
    confirm_user.delay(token, start_time=time())
    return HttpResponseJSON({'status': 'ok'})


@require_POST
@csrf_exempt
def fxa_concerts_rsvp(request):
    if not has_valid_api_key(request):
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'requires a valid API-key',
            'code': errors.BASKET_AUTH_ERROR,
        }, 401)

    fields = ('email', 'is_firefox', 'campaign_id')
    data = request.POST.dict()
    if not all(f in data for f in fields):
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'missing required field',
            'code': errors.BASKET_USAGE_ERROR,
        }, 401)

    is_firefox = 'Y' if data['is_firefox'][0].upper() == 'Y' else 'N'
    record_fxa_concerts_rsvp.delay(
        email=data['email'],
        is_firefox=is_firefox,
        campaign_id=data['campaign_id'],
    )
    return HttpResponseJSON({'status': 'ok'})


@require_POST
@csrf_exempt
def get_involved(request):
    data = request.POST.dict()
    if 'email' not in data:
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'email is required',
            'code': errors.BASKET_USAGE_ERROR,
        }, 401)
    if email_is_blocked(data['email']):
        # don't let on there's a problem
        return HttpResponseJSON({'status': 'ok'})
    if 'interest_id' not in data:
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'interest_id is required',
            'code': errors.BASKET_USAGE_ERROR,
        }, 401)

    try:
        Interest.objects.get(interest_id=data['interest_id'])
    except Interest.DoesNotExist:
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'invalid interest_id',
            'code': errors.BASKET_USAGE_ERROR,
        }, 401)

    if 'lang' not in data:
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'lang is required',
            'code': errors.BASKET_USAGE_ERROR,
        }, 401)
    if not language_code_is_valid(data['lang']):
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'invalid language',
            'code': errors.BASKET_INVALID_LANGUAGE,
        }, 400)
    if 'name' not in data:
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'name is required',
            'code': errors.BASKET_USAGE_ERROR,
        }, 401)
    if 'country' not in data:
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'country is required',
            'code': errors.BASKET_USAGE_ERROR,
        }, 401)

    email = process_email(data.get('email'))
    if not email:
        return invalid_email_response()

    update_get_involved.delay(
        data['interest_id'],
        data['lang'],
        data['name'],
        email,
        data['country'],
        data.get('format', 'H'),
        data.get('subscribe', False),
        data.get('message', None),
        data.get('source_url', None),
    )
    return HttpResponseJSON({'status': 'ok'})


def respond_ok(request, data, template_name='news/thankyou.html'):
    """
    Return either a JSON or HTML success response

    @param request: the request
    @param data: the incoming request data
    @param template_name: the template name in case of HTML response
    @return: HttpResponse object
    """
    if request.is_ajax():
        return HttpResponseJSON({'status': 'ok'})
    else:
        return render(request, template_name, data)


def respond_error(request, form, message, code, template_name='news/formerror.html'):
    """
    Return either a JSON or HTML error response

    @param request: the request
    @param form: the bound form object
    @param message: the error message
    @param code: the HTTP status code
    @param template_name: the template name in case of HTML response
    @return: HttpResponse object
    """
    if request.is_ajax():
        return HttpResponseJSON({
            'status': 'error',
            'errors': [message],
            'errors_by_field': {NON_FIELD_ERRORS: [message]}
        }, code)
    else:
        form.add_error(None, message)
        return render(request, template_name, {'form': form}, status=code)


def format_form_errors(errors):
    """Convert a dict of form errors into a list"""
    error_list = []
    for fname, ferrors in errors.items():
        for err in ferrors:
            error_list.append('{}: {}'.format(fname, err))

    return error_list


@require_POST
@csrf_exempt
def common_voice_goals(request):
    if not has_valid_api_key(request):
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'requires a valid API-key',
            'code': errors.BASKET_AUTH_ERROR,
        }, 401)

    form = CommonVoiceForm(request.POST)
    if form.is_valid():
        # don't send empty values and use ISO formatted date strings
        data = {k: v for k, v in form.cleaned_data.items() if not (v == '' or v is None)}
        record_common_voice_goals.delay(data)
        return HttpResponseJSON({'status': 'ok'})
    else:
        # form is invalid
        return HttpResponseJSON({
            'status': 'error',
            'errors': format_form_errors(form.errors),
            'errors_by_field': form.errors,
        }, 400)


@require_POST
@csrf_exempt
def subscribe_json(request):
    request.META['HTTP_X_REQUESTED_WITH'] = 'XMLHttpRequest'
    return subscribe_main(request)


@require_POST
@csrf_exempt
def subscribe_main(request):
    """Subscription view for use with client side JS"""
    form = SubscribeForm(request.POST)
    if form.is_valid():
        data = form.cleaned_data

        if email_is_blocked(data['email']):
            statsd.incr('news.views.subscribe_main.email_blocked')
            # don't let on there's a problem
            return respond_ok(request, data)

        data['format'] = data.pop('fmt') or 'H'

        if data['lang']:
            if not language_code_is_valid(data['lang']):
                data['lang'] = 'en'
        # if lang not provided get the best one from the accept-language header
        else:
            lang = get_best_request_lang(request)
            if lang:
                data['lang'] = lang
            else:
                del data['lang']

        # now ensure that if we do have a lang that it's a supported one
        if 'lang' in data:
            data['lang'] = get_best_supported_lang(data['lang'])

        # if source_url not provided we should store the referrer header
        # NOTE this is not a typo; Referrer is misspelled in the HTTP spec
        # https://www.w3.org/Protocols/rfc2616/rfc2616-sec14.html#sec14.36
        if not data['source_url'] and request.META.get('HTTP_REFERER'):
            referrer = request.META['HTTP_REFERER']
            if SOURCE_URL_RE.match(referrer):
                statsd.incr('news.views.subscribe_main.use_referrer')
                data['source_url'] = referrer

        if is_ratelimited(request, group='basket.news.views.subscribe_main',
                          key=lambda x, y: '%s-%s' % (':'.join(data['newsletters']), data['email']),
                          rate=EMAIL_SUBSCRIBE_RATE_LIMIT, increment=True):
            statsd.incr('subscribe.ratelimited')
            return respond_error(request, form, 'Rate limit reached', 429)

        try:
            upsert_user.delay(SUBSCRIBE, data, start_time=time())
        except Exception:
            return respond_error(request, form, 'Unknown error', 500)

        return respond_ok(request, data)

    else:
        # form is invalid
        if request.is_ajax():
            return HttpResponseJSON({
                'status': 'error',
                'errors': format_form_errors(form.errors),
                'errors_by_field': form.errors,
            }, 400)
        else:
            return render(request, 'news/formerror.html', {'form': form}, status=400)


@require_POST
@csrf_exempt
def subscribe(request):
    data = request.POST.dict()
    newsletters = data.get('newsletters', None)
    if not newsletters:
        # request.body causes tests to raise exceptions
        # while request.read() works.
        raw_request = request.read().decode()
        if 'newsletters=' in raw_request:
            # malformed request from FxOS
            # Can't use QueryDict since the string is not url-encoded.
            # It will convert '+' to ' ' for example.
            data = dict(pair.split('=') for pair in raw_request.split('&') if '=' in pair)
            statsd.incr('news.views.subscribe.fxos-workaround')
        else:
            return HttpResponseJSON({
                'status': 'error',
                'desc': 'newsletters is missing',
                'code': errors.BASKET_USAGE_ERROR,
            }, 400)

    if 'email' not in data:
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'email is required',
            'code': errors.BASKET_USAGE_ERROR,
        }, 401)

    email = process_email(data['email'])
    if not email:
        return invalid_email_response()

    data['email'] = email

    if email_is_blocked(data['email']):
        statsd.incr('news.views.subscribe.email_blocked')
        # don't let on there's a problem
        return HttpResponseJSON({'status': 'ok'})

    optin = data.pop('optin', 'N').upper() == 'Y'
    sync = data.pop('sync', 'N').upper() == 'Y'

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
            return HttpResponseJSON({
                'status': 'error',
                'desc': 'Using subscribe with sync=Y, you need to pass a '
                        'valid `api-key` or FxA OAuth Authorization.',
                'code': errors.BASKET_AUTH_ERROR,
            }, 401)

    # NOTE this is not a typo; Referrer is misspelled in the HTTP spec
    # https://www.w3.org/Protocols/rfc2616/rfc2616-sec14.html#sec14.36
    if not data.get('source_url') and request.META.get('HTTP_REFERER'):
        # try to get it from referrer
        statsd.incr('news.views.subscribe.use_referrer')
        data['source_url'] = request.META['HTTP_REFERER']

    return update_user_task(request, SUBSCRIBE, data=data, optin=optin, sync=sync)


def invalid_email_response():
    resp_data = {
        'status': 'error',
        'code': errors.BASKET_INVALID_EMAIL,
        'desc': 'Invalid email address',
    }
    statsd.incr('news.views.invalid_email_response')
    return HttpResponseJSON(resp_data, 400)


@require_POST
@csrf_exempt
def subscribe_sms(request):
    mobile = request.POST.get('mobile_number')
    if not mobile:
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'mobile_number is missing',
            'code': errors.BASKET_USAGE_ERROR,
        }, 400)

    country = request.POST.get('country', 'us')
    language = request.POST.get('lang', 'en-US')
    msg_name = request.POST.get('msg_name', 'SMS_Android')
    vendor_id = get_sms_vendor_id(msg_name, country, language)
    if not vendor_id:
        if language != 'en-US':
            # if not available in the requested language, try the default
            language = 'en-US'
            vendor_id = get_sms_vendor_id(msg_name, country, language)

    if not vendor_id:
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'Invalid msg_name + country + language',
            'code': errors.BASKET_USAGE_ERROR,
        }, 400)

    mobile = parse_phone_number(mobile, country)
    if not mobile:
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'mobile_number is invalid',
            'code': errors.BASKET_USAGE_ERROR,
        }, 400)

    # only rate limit numbers here so we don't rate limit errors.
    if is_ratelimited(request, group='basket.news.views.subscribe_sms',
                      key=lambda x, y: '%s-%s' % (msg_name, mobile),
                      rate=PHONE_NUMBER_RATE_LIMIT, increment=True):
        raise Ratelimited()

    optin = request.POST.get('optin', 'N') == 'Y'

    add_sms_user.delay(msg_name, mobile, optin, vendor_id=vendor_id)
    return HttpResponseJSON({'status': 'ok'})


@require_POST
@csrf_exempt
def unsubscribe(request, token):
    token = str(token)
    data = request.POST.dict()
    data['token'] = token

    if data.get('optout', 'N') == 'Y':
        data['optout'] = True
        data['newsletters'] = ','.join(newsletter_slugs())

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
        # don't change subscriber status
        data['_set_subscriber'] = False
        update_user_meta.delay(token, data)
        return HttpResponseJSON({'status': 'ok'})

    return HttpResponseJSON({
        'status': 'error',
        'desc': 'data is invalid',
        'code': errors.BASKET_USAGE_ERROR,
    }, 400)


@csrf_exempt
@never_cache
def user(request, token):
    token = str(token)
    if request.method == 'POST':
        data = request.POST.dict()
        data['token'] = token
        if 'email' in data:
            email = process_email(data['email'])
            if not email:
                return invalid_email_response()

            data['email'] = email
        return update_user_task(request, SET, data)

    get_fxa = 'fxa' in request.GET
    return get_user(token, get_fxa=get_fxa)


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
    email = process_email(request.POST.get('email'))
    if not email:
        return invalid_email_response()

    if email_is_blocked(email):
        # don't let on there's a problem
        return HttpResponseJSON({'status': 'ok'})

    try:
        user_data = get_user_data(email=email)
    except NewsletterException as e:
        return newsletter_exception_response(e)

    if not user_data:
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'Email address not known',
            'code': errors.BASKET_UNKNOWN_EMAIL,
        }, 404)  # Note: Bedrock looks for this 404

    send_recovery_message_task.delay(email)
    return HttpResponseJSON({'status': 'ok'})


@never_cache
def debug_user(request):
    return HttpResponseJSON({
        'status': 'error',
        'desc': 'method removed. use lookup-user and an API key.',
        'code': errors.BASKET_USAGE_ERROR,
    }, 404)


# Custom update methods

@csrf_exempt
def custom_unsub_reason(request):
    """Update the reason field for the user, which logs why the user
    unsubscribed from all newsletters."""

    if 'token' not in request.POST or 'reason' not in request.POST:
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'custom_unsub_reason requires the `token` '
                    'and `reason` POST parameters',
            'code': errors.BASKET_USAGE_ERROR,
        }, 400)

    update_custom_unsub.delay(request.POST['token'], request.POST['reason'])
    return HttpResponseJSON({'status': 'ok'})


# Get data about current newsletters
@require_safe
@cache_page(300)
def newsletters(request):
    # Get the newsletters as a dictionary of dictionaries that are
    # easily jsonified
    result = {}
    for newsletter in Newsletter.objects.all().values():
        newsletter['languages'] = newsletter['languages'].split(",")
        result[newsletter['slug']] = newsletter
        del newsletter['id']  # caller doesn't need to know our pkey
        del newsletter['slug']  # or our slug

    return HttpResponseJSON({
        'status': 'ok',
        'newsletters': result,
    })


@never_cache
def lookup_user(request):
    """Lookup a user in Exact Target given email or token (not both).

    To look up by email, a valid API key are required.

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

    For other errors, similarly
    response status is 4xx and the json 'desc' says what's wrong.

    Otherwise, status is 200 and json is the return value from
    `get_user_data`. See that method for details.

    Note that because this method always calls Exact Target one or
    more times, it can be slower than some other Basket APIs, and will
    fail if ET is down.
    """
    if settings.MAINTENANCE_MODE and not settings.MAINTENANCE_READ_ONLY:
        # can't return user data during maintenance
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'user data is not available in maintenance mode',
            'code': errors.BASKET_NETWORK_FAILURE,
        }, 400)

    token = request.GET.get('token', None)
    email = request.GET.get('email', None)
    get_fxa = 'fxa' in request.GET

    if (not email and not token) or (email and token):
        return HttpResponseJSON({
            'status': 'error',
            'desc': MSG_EMAIL_OR_TOKEN_REQUIRED,
            'code': errors.BASKET_USAGE_ERROR,
        }, 400)

    if email and not is_authorized(request, email):
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'Using lookup_user with `email`, you need to pass a '
                    'valid `api-key` or FxA OAuth Autorization header.',
            'code': errors.BASKET_AUTH_ERROR,
        }, 401)

    if email:
        email = process_email(email)
        if not email:
            return invalid_email_response()

    try:
        user_data = get_user_data(token=token, email=email, get_fxa=get_fxa)
    except NewsletterException as e:
        return newsletter_exception_response(e)

    status_code = 200
    if not user_data:
        code = errors.BASKET_UNKNOWN_TOKEN if token else errors.BASKET_UNKNOWN_EMAIL
        user_data = {
            'status': 'error',
            'desc': MSG_USER_NOT_FOUND,
            'code': code,
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
    return render(request, 'news/newsletters.html',
                  {'newsletters': active_newsletters})


def update_user_task(request, api_call_type, data=None, optin=False, sync=False):
    """Call the update_user task async with the right parameters.

    If sync==True, be sure to include the token in the response.
    Otherwise, basket can just do everything in the background.
    """
    data = data or request.POST.dict()

    newsletters = parse_newsletters_csv(data.get('newsletters'))
    if newsletters:
        if api_call_type == SUBSCRIBE:
            all_newsletters = newsletter_and_group_slugs() + get_transactional_message_ids()
        else:
            all_newsletters = newsletter_slugs()

        private_newsletters = newsletter_private_slugs()

        for nl in newsletters:
            if nl not in all_newsletters:
                return HttpResponseJSON({
                    'status': 'error',
                    'desc': 'invalid newsletter',
                    'code': errors.BASKET_INVALID_NEWSLETTER,
                }, 400)

            if api_call_type != UNSUBSCRIBE and nl in private_newsletters:
                if not is_authorized(request, data.get('email')):
                    return HttpResponseJSON({
                        'status': 'error',
                        'desc': 'private newsletter subscription requires a valid API key or OAuth',
                        'code': errors.BASKET_AUTH_ERROR,
                    }, 401)

    if 'lang' in data:
        if not language_code_is_valid(data['lang']):
            data['lang'] = 'en'
    elif 'accept_lang' in data:
        lang = get_best_language(get_accept_languages(data['accept_lang']))
        if lang:
            data['lang'] = lang
            del data['accept_lang']
    # if lang not provided get the best one from the accept-language header
    else:
        lang = get_best_request_lang(request)
        if lang:
            data['lang'] = lang

    # now ensure that if we do have a lang that it's a supported one
    if 'lang' in data:
        data['lang'] = get_best_supported_lang(data['lang'])

    email = data.get('email')
    token = data.get('token')
    if not (email or token):
        return HttpResponseJSON({
            'status': 'error',
            'desc': MSG_EMAIL_OR_TOKEN_REQUIRED,
            'code': errors.BASKET_USAGE_ERROR,
        }, 400)

    if optin:
        data['optin'] = True

    if api_call_type == SUBSCRIBE and email and data.get('newsletters'):
        # only rate limit here so we don't rate limit errors.
        if is_ratelimited(request, group='basket.news.views.update_user_task.subscribe',
                          key=lambda x, y: '%s-%s' % (data['newsletters'], email),
                          rate=EMAIL_SUBSCRIBE_RATE_LIMIT, increment=True):
            raise Ratelimited()

    if api_call_type == SET and token and data.get('newsletters'):
        # only rate limit here so we don't rate limit errors.
        if is_ratelimited(request, group='basket.news.views.update_user_task.set',
                          key=lambda x, y: '%s-%s' % (data['newsletters'], token),
                          rate=EMAIL_SUBSCRIBE_RATE_LIMIT, increment=True):
            raise Ratelimited()

    if sync:
        statsd.incr('news.views.subscribe.sync')
        if settings.MAINTENANCE_MODE and not settings.MAINTENANCE_READ_ONLY:
            # save what we can
            upsert_user.delay(api_call_type, data, start_time=time())
            # have to error since we can't return a token
            return HttpResponseJSON({
                'status': 'error',
                'desc': 'sync is not available in maintenance mode',
                'code': errors.BASKET_NETWORK_FAILURE,
            }, 400)

        try:
            user_data = get_user_data(email=email, token=token)
        except NewsletterException as e:
            return newsletter_exception_response(e)

        if not user_data:
            if not email:
                # must have email to create a user
                return HttpResponseJSON({
                    'status': 'error',
                    'desc': MSG_EMAIL_OR_TOKEN_REQUIRED,
                    'code': errors.BASKET_USAGE_ERROR,
                }, 400)

        token, created = upsert_contact(api_call_type, data, user_data)
        return HttpResponseJSON({
            'status': 'ok',
            'token': token,
            'created': created,
        })
    else:
        upsert_user.delay(api_call_type, data, start_time=time())
        return HttpResponseJSON({
            'status': 'ok',
        })


@require_POST
@csrf_exempt
def subhub_post(request):
    if not has_valid_api_key(request):
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'requires a valid API-key',
            'code': errors.BASKET_AUTH_ERROR,
        }, 401)

    try:
        data = json.loads(request.body)
    except ValueError:
        statsd.incr('subhub_post.message.json_error')
        sentry_client.captureException(data={'extra': {'request.body': request.body}})

        return HttpResponseJSON({
            'status': 'error',
            'desc': 'JSON error',
            'code': errors.BASKET_USAGE_ERROR,
        }, 400)
    else:
        etype = data['event_type']
        processor = SUBHUB_EVENT_TYPES.get(etype)

        if processor:
            processor.delay(data)

            # TODO: remove!
            sentry_client.capture('raven.events.Message', request=request)

            return HttpResponseJSON({'status': 'ok'})
        else:
            return HttpResponseJSON({
                'desc': 'unknown event type',
                'status': 'error',
                'code': errors.BASKET_USAGE_ERROR
            }, 400)

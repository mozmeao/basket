import json
import re
from time import time

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.utils.encoding import force_unicode
from django.views.decorators.cache import cache_page, never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_safe

# Get error codes from basket-client so users see the same definitions
from basket import errors
from django_statsd.clients import statsd
from ratelimit.exceptions import Ratelimited
from ratelimit.utils import is_ratelimited
from synctool.routing import Route

from news.models import Newsletter, Interest, LocaleStewards, NewsletterGroup, SMSMessage, \
    TransactionalEmailMessage
from news.newsletters import get_sms_messages, newsletter_slugs, newsletter_and_group_slugs, \
    newsletter_private_slugs, get_transactional_message_ids
from news.tasks import (
    add_fxa_activity,
    add_sms_user,
    confirm_user,
    send_recovery_message_task,
    update_custom_unsub,
    update_fxa_info,
    update_get_involved,
    update_student_ambassadors,
    upsert_contact,
    upsert_user,
)
from news.utils import (
    SET,
    SUBSCRIBE,
    UNSUBSCRIBE,
    MSG_EMAIL_OR_TOKEN_REQUIRED,
    MSG_USER_NOT_FOUND,
    EmailValidationError,
    email_is_blocked,
    get_accept_languages,
    get_best_language,
    get_user_data,
    get_user,
    has_valid_api_key,
    HttpResponseJSON,
    language_code_is_valid,
    NewsletterException,
    validate_email,
    newsletter_exception_response,
    parse_newsletters_csv)


IP_RATE_LIMIT_EXTERNAL = getattr(settings, 'IP_RATE_LIMIT_EXTERNAL', '40/m')
IP_RATE_LIMIT_INTERNAL = getattr(settings, 'IP_RATE_LIMIT_INTERNAL', '400/m')
PHONE_NUMBER_RATE_LIMIT = getattr(settings, 'PHONE_NUMBER_RATE_LIMIT', '1/h')
sync_route = Route(api_token=settings.SYNC_KEY)


@sync_route.queryset('sync')
def news_sync():
    return [
        Newsletter.objects.all(),
        NewsletterGroup.objects.all(),
        Interest.objects.all(),
        LocaleStewards.objects.all(),
        SMSMessage.objects.all(),
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
    statsd.incr('.'.join(request.path.split('/') + ['ratelimited']))
    return HttpResponseJSON({
        'status': 'error',
        'desc': 'rate limit reached',
        'code': errors.BASKET_USAGE_ERROR,
    }, 429)


@require_POST
@csrf_exempt
def confirm(request, token):
    confirm_user.delay(token, start_time=time())
    return HttpResponseJSON({'status': 'ok'})


@require_POST
@csrf_exempt
def fxa_activity(request):
    if not request.is_secure():
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'fxa-activity requires SSL',
            'code': errors.BASKET_SSL_REQUIRED,
        }, 401)
    if not has_valid_api_key(request):
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'fxa-activity requires a valid API-key',
            'code': errors.BASKET_AUTH_ERROR,
        }, 401)

    data = json.loads(request.body)
    if 'fxa_id' not in data:
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'fxa-activity requires a Firefox Account ID',
            'code': errors.BASKET_USAGE_ERROR,
        }, 401)

    add_fxa_activity.delay(data)
    return HttpResponseJSON({'status': 'ok'})


@require_POST
@csrf_exempt
def fxa_register(request):
    if not request.is_secure():
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'fxa-register requires SSL',
            'code': errors.BASKET_SSL_REQUIRED,
        }, 401)
    if not has_valid_api_key(request):
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'fxa-register requires a valid API-key',
            'code': errors.BASKET_AUTH_ERROR,
        }, 401)

    data = request.POST.dict()
    if 'email' not in data:
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'fxa-register requires an email address',
            'code': errors.BASKET_USAGE_ERROR,
        }, 401)
    if 'fxa_id' not in data:
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'fxa-register requires a Firefox Account ID',
            'code': errors.BASKET_USAGE_ERROR,
        }, 401)
    if 'accept_lang' not in data:
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'fxa-register requires accept_lang',
            'code': errors.BASKET_USAGE_ERROR,
        }, 401)

    lang = get_best_language(get_accept_languages(data['accept_lang']))
    if lang is None:
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'invalid language',
            'code': errors.BASKET_INVALID_LANGUAGE,
        }, 400)

    update_fxa_info.delay(data['email'], lang, data['fxa_id'])
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

    try:
        validate_email(data.get('email'))
    except EmailValidationError as e:
        return invalid_email_response(e)

    update_get_involved.delay(
        data['interest_id'],
        data['lang'],
        data['name'],
        data['email'],
        data['country'],
        data.get('format', 'H'),
        data.get('subscribe', False),
        data.get('message', None),
        data.get('source_url', None),
    )
    return HttpResponseJSON({'status': 'ok'})


@require_POST
@csrf_exempt
def subscribe(request):
    data = request.POST.dict()
    newsletters = data.get('newsletters', None)
    if not newsletters:
        # request.body causes tests to raise exceptions
        # while request.read() works.
        raw_request = request.read()
        if 'newsletters=' in raw_request:
            # malformed request from FxOS
            # Can't use QueryDict since the string is not url-encoded.
            # It will convert '+' to ' ' for example.
            data = dict(pair.split('=') for pair in raw_request.split('&'))
            email = data.get('email')
            if email:
                data['email'] = force_unicode(email)
            statsd.incr('subscribe-fxos-workaround')
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

    if email_is_blocked(data['email']):
        # don't let on there's a problem
        return HttpResponseJSON({'status': 'ok'})

    optin = data.pop('optin', 'N').upper() == 'Y'
    sync = data.pop('sync', 'N').upper() == 'Y'

    if optin and (not request.is_secure() or not has_valid_api_key(request)):
        # for backward compat we just ignore the optin if
        # no valid API key is sent.
        optin = False

    if sync:
        if not request.is_secure():
            return HttpResponseJSON({
                'status': 'error',
                'desc': 'subscribe with sync=Y requires SSL',
                'code': errors.BASKET_SSL_REQUIRED,
            }, 401)
        if not has_valid_api_key(request):
            return HttpResponseJSON({
                'status': 'error',
                'desc': 'Using subscribe with sync=Y, you need to pass a '
                        'valid `api-key` GET or POST parameter or X-api-key header',
                'code': errors.BASKET_AUTH_ERROR,
            }, 401)

    try:
        validate_email(data.get('email'))
    except EmailValidationError as e:
        return invalid_email_response(e)

    return update_user_task(request, SUBSCRIBE, data=data, optin=optin, sync=sync)


def invalid_email_response(e):
    resp_data = {
        'status': 'error',
        'code': errors.BASKET_INVALID_EMAIL,
        'desc': e.messages[0],
    }
    if e.suggestion:
        resp_data['suggestion'] = e.suggestion
    return HttpResponseJSON(resp_data, 400)


@require_POST
@csrf_exempt
def subscribe_sms(request):
    if 'mobile_number' not in request.POST:
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'mobile_number is missing',
            'code': errors.BASKET_USAGE_ERROR,
        }, 400)

    messages = get_sms_messages()
    msg_name = request.POST.get('msg_name', 'SMS_Android')
    if msg_name not in messages:
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'Invalid msg_name',
            'code': errors.BASKET_USAGE_ERROR,
        }, 400)

    mobile = request.POST['mobile_number']
    mobile = re.sub(r'\D+', '', mobile)
    if len(mobile) == 10:
        mobile = '1' + mobile
    elif len(mobile) != 11 or mobile[0] != '1':
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'mobile_number must be a US number',
            'code': errors.BASKET_USAGE_ERROR,
        }, 400)

    # only rate limit numbers here so we don't rate limit errors.
    if is_ratelimited(request, group='news.views.subscribe_sms',
                      key=lambda x, y: '%s-%s' % (msg_name, mobile),
                      rate=PHONE_NUMBER_RATE_LIMIT, increment=True):
        raise Ratelimited()

    optin = request.POST.get('optin', 'N') == 'Y'

    add_sms_user.delay(msg_name, mobile, optin)
    return HttpResponseJSON({'status': 'ok'})


@require_POST
@csrf_exempt
def unsubscribe(request, token):
    data = request.POST.dict()
    data['token'] = token

    if data.get('optout', 'N') == 'Y':
        data['optout'] = True
        data['newsletters'] = ','.join(newsletter_slugs())

    return update_user_task(request, UNSUBSCRIBE, data)


@csrf_exempt
@never_cache
def user(request, token):
    if request.method == 'POST':
        data = request.POST.dict()
        data['token'] = token
        return update_user_task(request, SET, data)

    return get_user(token)


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
    try:
        validate_email(request.POST.get('email'))
    except EmailValidationError as e:
        return invalid_email_response(e)

    email = request.POST.get('email')
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
    if 'email' not in request.GET or 'supertoken' not in request.GET:
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'Using debug_user, you need to pass the '
                    '`email` and `supertoken` GET parameters',
            'code': errors.BASKET_USAGE_ERROR,
        }, 400)

    if request.GET['supertoken'] != settings.SUPERTOKEN:
        return HttpResponseJSON({'status': 'error',
                                 'desc': 'Bad supertoken',
                                 'code': errors.BASKET_AUTH_ERROR},
                                401)

    email = request.GET['email']
    try:
        user_data = get_user_data(email=email)
    except NewsletterException as e:
        return newsletter_exception_response(e)

    return HttpResponseJSON(user_data, 200)


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


@require_POST
@csrf_exempt
def custom_update_student_ambassadors(request, token):
    update_student_ambassadors.delay(request.POST.dict(), token)
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


@require_safe
@cache_page(10)
def healthz(request):
    """for use with healthchecks. wrapped with `cache_page` to test redis cache."""
    # here to make sure DB is working
    assert Newsletter.objects.exists(), 'no newsletters exist'
    return HttpResponse('OK')


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

    if not request.is_secure():
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'lookup_user always requires SSL',
            'code': errors.BASKET_SSL_REQUIRED,
        }, 401)

    token = request.GET.get('token', None)
    email = request.GET.get('email', None)

    if (not email and not token) or (email and token):
        return HttpResponseJSON({
            'status': 'error',
            'desc': MSG_EMAIL_OR_TOKEN_REQUIRED,
            'code': errors.BASKET_USAGE_ERROR,
        }, 400)

    if email and not has_valid_api_key(request):
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'Using lookup_user with `email`, you need to pass a '
                    'valid `api-key` GET parameter or X-api-key header',
            'code': errors.BASKET_AUTH_ERROR,
        }, 401)

    try:
        user_data = get_user_data(token=token, email=email)
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
                if not request.is_secure():
                    return HttpResponseJSON({
                        'status': 'error',
                        'desc': 'private newsletter subscription requires SSL',
                        'code': errors.BASKET_SSL_REQUIRED,
                    }, 401)

                if not has_valid_api_key(request):
                    return HttpResponseJSON({
                        'status': 'error',
                        'desc': 'private newsletter subscription requires a valid API key',
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
        else:
            data['lang'] = 'en'

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

    if sync:
        if settings.MAINTENANCE_MODE:
            return HttpResponseJSON({
                'status': 'error',
                'desc': 'sync is not available in maintenance mode',
                'code': errors.BASKET_UNKNOWN_ERROR,
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

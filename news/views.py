from functools import wraps
import json
import re
from django.utils.translation.trans_real import parse_accept_lang_header

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import cache_control, never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

# Get error codes from basket-client so users see the same definitions
from basket import errors
from django_statsd.clients import statsd

from .backends.common import NewsletterNoResultsException
from .backends.exacttarget import (ExactTargetDataExt, NewsletterException,
                                   UnauthorizedException)
from .email import get_valid_email
from .models import APIUser, Newsletter, Subscriber, Interest
from .tasks import (
    MSG_EMAIL_OR_TOKEN_REQUIRED, MSG_TOKEN_REQUIRED, MSG_USER_NOT_FOUND,
    SET, SUBSCRIBE, UNSUBSCRIBE,
    add_sms_user,
    confirm_user,
    send_recovery_message_task,
    update_custom_unsub,
    update_fxa_info,
    update_get_involved,
    update_phonebook,
    update_student_ambassadors,
    update_user,
)
from .newsletters import newsletter_fields, newsletter_slugs, slug_to_vendor_id, \
    newsletter_languages


## Utility functions


class HttpResponseJSON(HttpResponse):
    def __init__(self, data, status=None):
        super(HttpResponseJSON, self).__init__(content=json.dumps(data),
                                               content_type='application/json',
                                               status=status)


class EmailValidationError(ValidationError):
    def __init__(self, message, suggestion=None):
        super(EmailValidationError, self).__init__(message)
        self.suggestion = suggestion


def has_valid_api_key(request):
    # The API key could be the query parameter 'api-key' or the
    # request header 'X-api-key'.

    api_key = request.REQUEST.get('api-key', None) or\
        request.META.get('HTTP_X_API_KEY', None)
    return APIUser.is_valid(api_key)


def lookup_subscriber(token=None, email=None):
    """
    Find or create Subscriber object for given token and/or email.

    If we don't already have a Basket Subscriber record, we check
    in ET to see if we know about this user there.  If they exist in
    ET, we create a new Basket Subscriber record with the information
    from ET. If they don't exist in ET, and we were given an email,
    we create a new Subscriber record with the given email and make
    up a new token for them.

    # FIXME: when we create a new token for a new email, maybe we
    should put that in ET right away. Though we couldn't put that in
    any of our three existing tables, so we either need a
    fourth one for users who are neither confirmed nor pending, or
    to come up with another solution.

    If we are only given a token, and cannot find any user with that
    token in Basket or ET, then the returned subscriber is None.

    Returns (Subscriber, user_data, created).

    The user_data is only provided if we had to ask ET about this
    email/token (and found it there); otherwise, it's None.
    """
    if not (token or email):
        raise Exception(MSG_EMAIL_OR_TOKEN_REQUIRED)
    kwargs = {}
    if token:
        kwargs['token'] = token
    if email:
        kwargs['email'] = email
    user_data = None
    try:
        subscriber = Subscriber.objects.get(**kwargs)
    except Subscriber.DoesNotExist:
        # Note: If both token and email were passed in, it would be possible
        # that subscribers exist that match one or the other but not both.
        # But currently no callers pass both, so luckily we don't have to
        # figure out what we would do in that case.
        created = True
        # Check with ET to see if our DB is just out of sync
        user_data = get_user_data(sync_data=True, **kwargs)
        if user_data and user_data['status'] == 'ok':
            # Found them in ET and updated subscriber db locally
            subscriber = Subscriber.objects.get(**kwargs)
        else:
            # Not in ET. If we have an email, create a new basket
            # record for them
            if email:
                # It's barely possible the subscriber has been created
                # since we checked, so play it safe and get_or_create.
                # (Yes, this has been seen.)
                subscriber, created = Subscriber.objects.\
                    get_or_create(email=email)
            else:
                # No email?  Just token? Token not known in basket or ET?
                # That's an error.
                subscriber = None
    else:
        created = False
    return subscriber, user_data, created


def logged_in(f):
    """Decorator to check if the user has permission to view these
    pages"""

    @wraps(f)
    def wrapper(request, token, *args, **kwargs):
        subscriber, subscriber_data, created = lookup_subscriber(token=token)

        if not subscriber:
            return HttpResponseJSON({
                'status': 'error',
                'desc': MSG_TOKEN_REQUIRED,
                'code': errors.BASKET_USAGE_ERROR,
            }, 403)

        request.subscriber_data = subscriber_data
        request.subscriber = subscriber
        return f(request, token, *args, **kwargs)
    return wrapper


LANG_RE = re.compile(r'^[a-z]{2,3}(?:-[a-z]{2})?$', re.IGNORECASE)


def language_code_is_valid(code):
    """Return True if ``code`` looks like a language code.

    So it must be either 2 (or 3) alpha characters, or 2 pairs of 2
    characters separated by a dash. It will also
    accept the empty string.

    Raises TypeError if anything but a string is passed in.
    """
    if not isinstance(code, basestring):
        raise TypeError("Language code must be a string")

    if code == '':
        return True
    else:
        return bool(LANG_RE.match(code))


def update_user_task(request, type, data=None, optin=True, sync=False):
    """Call the update_user task async with the right parameters.

    If sync==True, be sure to do the update synchronously and include the token
    in the response.  Otherwise, basket has the option to do it all later
    in the background.
    """
    # NOTE: currently this code always generates the token and returns it
    # in the response. If optimizing that into a background task, be sure
    # to observe whether sync==True and still return a token in that case.

    sub = getattr(request, 'subscriber', None)
    data = data or request.POST.dict()

    newsletters = data.get('newsletters', None)
    if newsletters:
        all_newsletters = newsletter_slugs()
        for nl in [x.strip() for x in newsletters.split(',')]:
            if nl not in all_newsletters:
                return HttpResponseJSON({
                    'status': 'error',
                    'desc': 'invalid newsletter',
                    'code': errors.BASKET_INVALID_NEWSLETTER,
                }, 400)

    if 'lang' in data and not language_code_is_valid(data['lang']):
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'invalid language',
            'code': errors.BASKET_INVALID_LANGUAGE,
        }, 400)

    email = data.get('email')
    if not (email or sub):
        return HttpResponseJSON({
            'status': 'error',
            'desc': MSG_EMAIL_OR_TOKEN_REQUIRED,
            'code': errors.BASKET_USAGE_ERROR,
        }, 400)

    created = False
    if not sub:
        # We need a token for this user. If we don't have a Subscriber
        # object for them already, we'll need to find or make one,
        # checking ET first if need be.
        sub, user_data, created = lookup_subscriber(email=email)

    update_user.delay(data, sub.email, sub.token, created, type, optin)
    return HttpResponseJSON({
        'status': 'ok',
        'token': sub.token,
        'created': created,
    })


def look_for_user(database, email, token, fields):
    """Try to get the user's data from the specified ET database.
    If found and the database is not the 'Confirmed' database,
    return it (a dictionary, see get_user_data).
    If found and it's the 'Confirmed' database, just return True.
    If not found, return None.
    Any other exception just propagates and needs to be handled
    by the caller.
    """
    ext = ExactTargetDataExt(settings.EXACTTARGET_USER,
                             settings.EXACTTARGET_PASS)
    try:
        user = ext.get_record(database,
                              email or token,
                              fields,
                              'EMAIL_ADDRESS_' if email else 'TOKEN')
    except NewsletterNoResultsException:
        return None
    if database == settings.EXACTTARGET_CONFIRMATION:
        return True
    newsletters = []
    for slug in newsletter_slugs():
        vendor_id = slug_to_vendor_id(slug)
        flag = "%s_FLG" % vendor_id
        if user.get(flag, 'N') == 'Y':
            newsletters.append(slug)
    user_data = {
        'status': 'ok',
        'email': user['EMAIL_ADDRESS_'],
        'format': user['EMAIL_FORMAT_'] or 'H',
        'country': user['COUNTRY_'] or '',
        'lang': user['LANGUAGE_ISO2'] or '',  # Never None
        'token': user['TOKEN'],
        'created-date': user['CREATED_DATE_'],
        'newsletters': newsletters,
    }
    return user_data


def get_user_data(token=None, email=None, sync_data=False):
    """Return a dictionary of the user's data from Exact Target.
    Look them up by their email if given, otherwise by the token.

    If sync_data is set, create or update our local basket record
    if needed so we have a record of this email and the token that
    goes with it.

    Look first for the user in the master subscribers database, then in the
    optin database.

    If they're not in the master subscribers database but are in the
    optin database, then check the confirmation database too.  If we
    find them in either the master subscribers or confirmation database,
    add 'confirmed': True to their data; otherwise, 'confirmed': False.
    Also, ['pending'] is True if they are in the double-opt-in database
    and not in the confirmed or master databases.

    If the user was not found, return None instead of a dictionary.

    If there was an error, result['status'] == 'error'
    and result['desc'] has more info;
    otherwise, result['status'] == 'ok'

    Review of results:

    None = user completely unknown, no errors talking to ET.

    otherwise, return value is::

    {
        'status':  'ok',      # no errors talking to ET
        'status':  'error',   # errors talking to ET, see next field
        'desc':  'error message'   # details if status is error
        'email': 'email@address',
        'format': 'T'|'H',
        'country': country code,
        'lang': language code,
        'token': UUID,
        'created-date': date created,
        'newsletters': list of slugs of newsletters subscribed to,
        'confirmed': True if user has confirmed subscription (or was excepted),
        'pending': True if we're waiting for user to confirm subscription
        'master': True if we found them in the master subscribers table
    }


    """
    newsletters = newsletter_fields()

    fields = [
        'EMAIL_ADDRESS_',
        'EMAIL_FORMAT_',
        'COUNTRY_',
        'LANGUAGE_ISO2',
        'TOKEN',
        'CREATED_DATE_',
    ]

    for nl in newsletters:
        fields.append('%s_FLG' % nl)

    confirmed = True
    pending = False
    master = True
    try:
        # Look first in the master subscribers database for the user
        user_data = look_for_user(settings.EXACTTARGET_DATA,
                                  email, token, fields)
        # If we get back a user, then they have already confirmed.

        # If not, look for them in the database of unconfirmed users.
        if user_data is None:
            master = False
            confirmed = False
            user_data = look_for_user(settings.EXACTTARGET_OPTIN_STAGE,
                                      email, token, fields)
            if user_data is None:
                # No such user, as far as we can tell - if they're in
                # neither the master subscribers nor optin database,
                # we don't know them.
                return None

            # We found them in the optin database. But actually, they
            # might have confirmed but the batch job hasn't
            # yet run to move their data to the master subscribers
            # database; catch that case here by looking for them in the
            # Confirmed database.  Do it simply; the confirmed database
            # doesn't have most of the user's data, just their token.
            if look_for_user(settings.EXACTTARGET_CONFIRMATION,
                             email, token, ['Token']):
                # Ah-ha, they're in the Confirmed DB so they did confirm
                confirmed = True

        user_data['confirmed'] = confirmed
        user_data['pending'] = pending
        user_data['master'] = master
    except NewsletterException as e:
        return {
            'status': 'error',
            'status_code': 400,
            'desc': str(e),
            'code': errors.BASKET_NETWORK_FAILURE,
        }
    except UnauthorizedException as e:
        return {
            'status': 'error',
            'status_code': 500,
            'desc': 'Email service provider auth failure',
            'code': errors.BASKET_EMAIL_PROVIDER_AUTH_FAILURE,
        }

    # We did find a user
    if sync_data:
        # if user not in our db create it, if token mismatch fix it.
        Subscriber.objects.get_and_sync(user_data['email'], user_data['token'])

    return user_data


def get_user(token=None, email=None, sync_data=False):
    user_data = get_user_data(token, email, sync_data)
    status_code = user_data.pop('status_code', 200) if user_data else 400
    return HttpResponseJSON(user_data, status_code)


def get_accept_languages(header_value):
    """
    Parse the user's Accept-Language HTTP header and return a list of languages
    """
    # adapted from bedrock: http://j.mp/1o3pWo5
    languages = []
    pattern = re.compile(r'^([A-Za-z]{2,3})(?:-([A-Za-z]{2})(?:-[A-Za-z0-9]+)?)?$')

    try:
        parsed = parse_accept_lang_header(header_value)
    except ValueError:  # see https://code.djangoproject.com/ticket/21078
        return languages

    for lang, priority in parsed:
        m = pattern.match(lang)

        if not m:
            continue

        lang = m.group(1).lower()

        # Check if the shorter code is supported. This covers obsolete long
        # codes like fr-FR (should match fr) or ja-JP (should match ja)
        if m.group(2) and lang not in newsletter_languages():
            lang += '-' + m.group(2).upper()

        if lang not in languages:
            languages.append(lang)

    return languages


def get_best_language(languages):
    """
    Return the best language for use with our newsletters. If none match, return first in list.

    @param languages: list of language codes.
    @return: a single language code
    """
    if not languages:
        return None

    supported_langs = newsletter_languages()
    for lang in languages:
        if lang in supported_langs:
            return lang

    return languages[0]


## Views


@require_POST
@logged_in
@csrf_exempt
def confirm(request, token):
    confirm_user.delay(request.subscriber.token,
                       request.subscriber_data)
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
    args = [data['email'], lang, data['fxa_id']]
    if 'source_url' in data:
        args.append(data['source_url'])
    update_fxa_info.delay(*args)
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
        validate_email(data)
    except EmailValidationError as e:
        return invalid_email_response(e)

    update_get_involved.delay(
        data['interest_id'],
        data['lang'],
        data['name'],
        data['email'],
        data['country'],
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
            statsd.incr('subscribe-fxos-workaround')
        else:
            return HttpResponseJSON({
                'status': 'error',
                'desc': 'newsletters is missing',
                'code': errors.BASKET_USAGE_ERROR,
            }, 400)

    optin = data.get('optin', 'N').upper() == 'Y'
    sync = data.get('sync', 'N').upper() == 'Y'

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
        validate_email(data)
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


def validate_email(data):
    """Validates that the email key in the passed dict is valid.

    Alternately checks that the 'validated' arg was passed in.
    Returns None on success and raises a ValidationError if
    invalid. The exception will have a 'suggestion' parameter
    that will contain the suggested email address or None.

    @param data: dict. usually the POST data
    @return: None if email address in the 'email' key is valid
    @raise: EmailValidationError if 'email' key is invalid
    """
    # we send suggestions back to users of valid email addresses.
    # A client could choose to use that suggestion or indicate that
    # the address is indeed valid. Said client should pass:
    #     validated=1
    if data.get('validated', False):
        return None

    email = data.get('email', None)
    valid_email, is_suggestion = get_valid_email(email)
    if not valid_email or is_suggestion:
        raise EmailValidationError('Invalid email address', valid_email)


@require_POST
@csrf_exempt
def subscribe_sms(request):
    if 'mobile_number' not in request.POST:
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'mobile_number is missing',
            'code': errors.BASKET_USAGE_ERROR,
        }, 400)

    msg_name = request.POST.get('msg_name', 'SMS_Android')
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

    optin = request.POST.get('optin', 'N') == 'Y'

    add_sms_user.delay(msg_name, mobile, optin)
    return HttpResponseJSON({'status': 'ok'})


@require_POST
@logged_in
@csrf_exempt
def unsubscribe(request, token):
    data = request.POST.dict()

    if data.get('optout', 'N') == 'Y':
        data['newsletters'] = ','.join(newsletter_slugs())

    return update_user_task(request, UNSUBSCRIBE, data)


@logged_in
@csrf_exempt
@never_cache
def user(request, token):
    if request.method == 'POST':
        return update_user_task(request, SET)

    if request.subscriber_data:
        return HttpResponseJSON(request.subscriber_data)

    return get_user(request.subscriber.token)


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
        validate_email(request.POST)
    except EmailValidationError as e:
        return invalid_email_response(e)

    email = request.POST.get('email')
    user_data = get_user_data(email=email, sync_data=True)
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
    if not 'email' in request.GET or not 'supertoken' in request.GET:
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
    user_data = get_user_data(email=email)
    status_code = user_data.pop('status_code', 200)
    try:
        user = Subscriber.objects.get(email=email)
        user_data['in_basket'] = True
        user_data['basket_token'] = user.token
    except Subscriber.DoesNotExist:
        user_data['in_basket'] = False
        user_data['basket_token'] = ''

    return HttpResponseJSON(user_data, status_code)


# Custom update methods

@csrf_exempt
def custom_unsub_reason(request):
    """Update the reason field for the user, which logs why the user
    unsubscribed from all newsletters."""

    if not 'token' in request.POST or not 'reason' in request.POST:
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'custom_unsub_reason requires the `token` '
                    'and `reason` POST parameters',
            'code': errors.BASKET_USAGE_ERROR,
        }, 400)

    update_custom_unsub.delay(request.POST['token'], request.POST['reason'])
    return HttpResponseJSON({'status': 'ok'})


@require_POST
@logged_in
@csrf_exempt
def custom_update_student_ambassadors(request, token):
    sub = request.subscriber
    update_student_ambassadors.delay(request.POST.dict(), sub.email,
                                     sub.token)
    return HttpResponseJSON({'status': 'ok'})


@require_POST
@logged_in
@csrf_exempt
def custom_update_phonebook(request, token):
    sub = request.subscriber
    update_phonebook.delay(request.POST.dict(), sub.email, sub.token)
    return HttpResponseJSON({'status': 'ok'})


# Get data about current newsletters
@require_GET
@cache_control(max_age=300)
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

    status_code = 200
    user_data = get_user_data(token=token, email=email)
    if not user_data:
        code = errors.BASKET_UNKNOWN_TOKEN if token else errors.BASKET_UNKNOWN_EMAIL
        user_data = {
            'status': 'error',
            'desc': MSG_USER_NOT_FOUND,
            'code': code,
        }
        status_code = 404
    elif user_data['status'] == 'error':
        status_code = 400

    return HttpResponseJSON(user_data, status_code)


def list_newsletters(request):
    """
    Public web page listing currently active newsletters.
    """

    active_newsletters = Newsletter.objects.filter(active=True)
    return render(request, "news/newsletters.html",
                  {'newsletters': active_newsletters})

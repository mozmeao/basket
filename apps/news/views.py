from functools import wraps
import json
import re

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.cache import cache_control, never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from backends.exacttarget import (ExactTargetDataExt, NewsletterException,
                                  UnauthorizedException)
from models import Newsletter, Subscriber
from news.backends.common import NewsletterNoResultsException
from tasks import (
    SET, SUBSCRIBE, UNSUBSCRIBE,
    add_sms_user,
    confirm_user,
    update_custom_unsub,
    update_phonebook,
    update_student_ambassadors,
    update_user,
)
from .newsletters import (newsletter_fields, newsletter_languages,
                          newsletter_names)


## Utility functions


class HttpResponseJSON(HttpResponse):
    def __init__(self, data, status=None):
        super(HttpResponseJSON, self).__init__(content=json.dumps(data),
                                               content_type='application/json',
                                               status=status)


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
        raise Exception("lookup_subscriber needs token or email")
    kwargs = {}
    if token:
        kwargs['token'] = token
    if email:
        kwargs['email'] = email
    user_data = None
    try:
        subscriber = Subscriber.objects.get(**kwargs)
    except Subscriber.DoesNotExist:
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
                subscriber = Subscriber.objects.create(email=email)
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
                'desc': 'Must have valid token for this request',
            }, 403)

        request.subscriber_data = subscriber_data
        request.subscriber = subscriber
        return f(request, token, *args, **kwargs)
    return wrapper


def language_code_is_valid(code):
    """Return True if ``code`` is the empty string, or one of the language
    codes associated with a newsletter.  Since language codes come in both
    2-letter and 5-letter varieties ("en" and "en-US"), we consider codes
    to also match if the 5-letter code starts with the 2-letter code.

    Not case sensitive.

    Raises TypeError if anything but a string is passed in.
    """
    if not isinstance(code, basestring):
        raise TypeError("Language code must be a string")

    # Accept empty string, or newsletter languages. Lowercase all the things.
    langs = [''] + [lang.lower() for lang in newsletter_languages()]
    code = code.lower()

    if code in langs:
        return True
    elif len(code) in [2, 5]:
        # If the length is valid, consider 2-letter matches
        code2 = code[:2]
        if any(code2 == lang[:2] for lang in langs):
            return True
    return False


def update_user_task(request, type, data=None, optin=True):
    """Call the update_user task async with the right parameters"""

    sub = getattr(request, 'subscriber', None)
    data = data or request.POST.copy()

    newsletters = data.get('newsletters', None)
    if newsletters:
        all_newsletters = newsletter_names()
        for nl in [x.strip() for x in newsletters.split(',')]:
            if nl not in all_newsletters:
                return HttpResponseJSON({
                    'status': 'error',
                    'desc': 'invalid newsletter',
                }, 400)

    if 'lang' in data and not language_code_is_valid(data['lang']):
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'invalid language',
        }, 400)

    email = data.get('email')
    if not (email or sub):
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'An email address or token is required.',
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
    user_data = {
        'status': 'ok',
        'email': user['EMAIL_ADDRESS_'],
        'format': user['EMAIL_FORMAT_'],
        'country': user['COUNTRY_'],
        'lang': user['LANGUAGE_ISO2'],
        'token': user['TOKEN'],
        'created-date': user['CREATED_DATE_'],
        'newsletters': [nl for nl in newsletter_names()
                        if user.get('%s_FLG' % nl, False) == 'Y'],
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

    otherwise, return value is:
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
                             email, token, []):
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
        }
    except UnauthorizedException as e:
        return {
            'status': 'error',
            'status_code': 500,
            'desc': 'Email service provider auth failure',
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
def subscribe(request):
    newsletters = request.POST.get('newsletters', None)
    if not newsletters:
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'newsletters is missing',
        }, 400)

    optin = request.POST.get('optin', 'Y') == 'Y'
    return update_user_task(request, SUBSCRIBE, optin=optin)


@require_POST
@csrf_exempt
def subscribe_sms(request):
    if 'mobile_number' not in request.POST:
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'mobile_number is missing',
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
        }, 400)

    optin = request.POST.get('optin', 'N') == 'Y'

    add_sms_user.delay(msg_name, mobile, optin)
    return HttpResponseJSON({'status': 'ok'})


@require_POST
@logged_in
@csrf_exempt
def unsubscribe(request, token):
    data = request.POST.copy()

    if data.get('optout', 'N') == 'Y':
        data['newsletters'] = ','.join(newsletter_names())

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


@never_cache
def debug_user(request):
    if not 'email' in request.GET or not 'supertoken' in request.GET:
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'Using debug_user, you need to pass the '
                    '`email` and `supertoken` GET parameters',
        }, 400)

    if request.GET['supertoken'] != settings.SUPERTOKEN:
        return HttpResponseJSON({'status': 'error', 'desc': 'Bad supertoken'},
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
        }, 400)

    update_custom_unsub.delay(request.POST['token'], request.POST['reason'])
    return HttpResponseJSON({'status': 'ok'})


@require_POST
@logged_in
@csrf_exempt
def custom_update_student_ambassadors(request, token):
    sub = request.subscriber
    update_student_ambassadors.delay(dict(request.POST.items()), sub.email,
                                     sub.token)
    return HttpResponseJSON({'status': 'ok'})


@require_POST
@logged_in
@csrf_exempt
def custom_update_phonebook(request, token):
    sub = request.subscriber
    update_phonebook.delay(dict(request.POST.items()), sub.email, sub.token)
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

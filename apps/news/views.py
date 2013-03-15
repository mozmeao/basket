from functools import wraps
import json
import re

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from backends.exacttarget import (ExactTargetDataExt, NewsletterException,
                                  UnauthorizedException)
from models import Newsletter, Subscriber
from tasks import (
    add_sms_user,
    confirm_user,
    update_custom_unsub,
    update_phonebook,
    update_student_reps,
    update_user,
    SET, SUBSCRIBE, UNSUBSCRIBE,
)
from .newsletters import newsletter_fields, newsletter_name, newsletter_names


## Utility functions


class HttpResponseJSON(HttpResponse):
    def __init__(self, data, status=None):
        super(HttpResponseJSON, self).__init__(content=json.dumps(data),
                                               content_type='application/json',
                                               status=status)


def logged_in(f):
    """Decorator to check if the user has permission to view these
    pages"""

    @wraps(f)
    def wrapper(request, token, *args, **kwargs):
        subscriber = None
        subscriber_data = None
        try:
            subscriber = Subscriber.objects.get(token=token)
        except Subscriber.DoesNotExist:
            # Check with ET to see if our DB is just out of sync
            subscriber_data = get_user_data(token=token, sync_data=True)
            if subscriber_data['status'] == 'ok':
                try:
                    subscriber = Subscriber.objects.get(token=token)
                except Subscriber.DoesNotExist:
                    pass

        if not subscriber:
            return HttpResponseJSON({
                'status': 'error',
                'desc': 'Must have valid token for this request',
            }, 403)

        request.subscriber_data = subscriber_data
        request.subscriber = subscriber
        return f(request, token, *args, **kwargs)
    return wrapper


def update_user_task(request, type, data=None, optin=True):
    """Call the update_user task async with the right parameters"""

    sub = getattr(request, 'subscriber', None)
    data = data or request.POST.copy()
    email = data.get('email')
    created = False
    if not sub:
        if email:
            sub, created = Subscriber.objects.get_or_create(email=email)
        else:
            return HttpResponseJSON({
                'status': 'error',
                'desc': 'An email address or token is required.',
            }, 400)

    update_user.delay(data, sub.email, sub.token, created, type, optin)
    return HttpResponseJSON({
        'status': 'ok',
        'token': sub.token,
        'created': created,
    })


def get_user_data(token=None, email=None, sync_data=False):
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

    try:
        ext = ExactTargetDataExt(settings.EXACTTARGET_USER,
                                 settings.EXACTTARGET_PASS)
        user = ext.get_record(settings.EXACTTARGET_DATA,
                              email or token,
                              fields,
                              'EMAIL_ADDRESS_' if email else 'TOKEN')
    except NewsletterException, e:
        return {
            'status': 'error',
            'status_code': 400,
            'desc': e.message,
        }
    except UnauthorizedException, e:
        return {
            'status': 'error',
            'status_code': 500,
            'desc': 'Email service provider auth failure',
        }

    user_data = {
        'status': 'ok',
        'email': user['EMAIL_ADDRESS_'],
        'format': user['EMAIL_FORMAT_'],
        'country': user['COUNTRY_'],
        'lang': user['LANGUAGE_ISO2'],
        'token': user['TOKEN'],
        'created-date': user['CREATED_DATE_'],
        'newsletters': [newsletter_name(nl) for nl in newsletters
                        if user.get('%s_FLG' % nl, False) == 'Y'],
    }

    if sync_data:
        # if user not in our db create it, if token mismatch fix it.
        Subscriber.objects.get_and_sync(user_data['email'], user_data['token'])

    return user_data


def get_user(token=None, email=None, sync_data=False):
    user_data = get_user_data(token, email, sync_data)
    status_code = user_data.pop('status_code', 200)
    return HttpResponseJSON(user_data, status_code)


## Views


@require_POST
@logged_in
@csrf_exempt
def confirm(request, token):
    confirm_user.delay(request.subscriber.token)
    return HttpResponseJSON({'status': 'ok'})


@require_POST
@csrf_exempt
def subscribe(request):
    if 'newsletters' not in request.POST:
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
def user(request, token):
    if request.method == 'POST':
        return update_user_task(request, SET)

    if request.subscriber_data:
        return HttpResponseJSON(request.subscriber_data)

    return get_user(request.subscriber.token)


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


@csrf_exempt
def custom_student_reps(request):
    data = dict(request.POST.items())
    update_student_reps.delay(data)
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

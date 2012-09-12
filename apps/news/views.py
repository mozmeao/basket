from functools import wraps
import json

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.conf import settings
import re

from tasks import (add_sms_user, update_user, confirm_user,
                   update_student_reps, SUBSCRIBE, UNSUBSCRIBE)
from newsletters import *
from models import Subscriber
from backends.exacttarget import (ExactTargetDataExt, NewsletterException,
                                  UnauthorizedException)


## Utility functions

def logged_in(f):
    """Decorator to check if the user has permission to view these
    pages"""

    @wraps(f)
    def wrapper(request, token, *args, **kwargs):
        subscriber = Subscriber.objects.filter(token=token)
        if not subscriber.exists():
            return json_response({
                'status': 'error',
                'desc': 'Must have valid token for this request',
            }, status=403)

        request.subscriber = subscriber[0]
        return f(request, token, *args, **kwargs)
    return wrapper


def json_response(data, status=200):
    res = HttpResponse(json.dumps(data),
                       mimetype='application/json')
    res.status_code = status
    return res


def update_user_task(request, type, data=None, optin=True):
    """Call the update_user task async with the right parameters"""

    user = getattr(request, 'subscriber', None)

    # When celery is turned on, use delay to call update_user and
    # don't catch any exceptions. For now, return an error if
    # something goes wrong.
    try:
        update_user(data or request.POST.copy(),
                    user and user.email,
                    type,
                    optin)
        return json_response({'status': 'ok'})
    except (NewsletterException, UnauthorizedException), e:
        return json_response({'status': 'error',
                              'desc': e.message},
                             status=500)


def get_user(token=None, email=None):
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
        return json_response({'status': 'error',
                              'desc': e.message},
                             status=500)
    except UnauthorizedException, e:
        return json_response({'status': 'error',
                              'desc': 'Email service provider auth failure'},
                             status=500)

    user_data = {
        'email': user['EMAIL_ADDRESS_'],
        'format': user['EMAIL_FORMAT_'],
        'country': user['COUNTRY_'],
        'lang': user['LANGUAGE_ISO2'],
        'token': user['TOKEN'],
        'created-date': user['CREATED_DATE_'],
        'newsletters': [newsletter_name(nl) for nl in newsletters
                        if user.get('%s_FLG' % nl, False) == 'Y'],
    }

    return json_response(user_data)

## Views


@require_POST
@logged_in
@csrf_exempt
def confirm(request, token):
    # Until celery is turned on, return a message immediately
    try:
        confirm_user(request.subscriber.token)
        return json_response({'status': 'ok'})
    except (NewsletterException, UnauthorizedException), e:
        return json_response({'status': 'error',
                              'desc': e.message},
                             status=500)


@require_POST
@csrf_exempt
def subscribe(request):
    if 'newsletters' not in request.POST:
        return json_response({'status': 'error',
                              'desc': 'newsletters is missing'},
                             status=500)

    optin = request.POST.get('optin', 'Y') == 'Y'
    return update_user_task(request, SUBSCRIBE, optin=optin)


@require_POST
@csrf_exempt
def subscribe_sms(request):
    if 'mobile_number' not in request.POST:
        return json_response({'status': 'error',
                              'desc': 'mobile_number is missing'},
                             status=400)

    msg_name = request.POST.get('msg_name', 'SMS_Android')
    mobile = request.POST['mobile_number']
    mobile = re.sub(r'\D+', '', mobile)
    if len(mobile) == 10:
        mobile = '1' + mobile
    elif len(mobile) != 11 or mobile[0] != '1':
        return json_response({'status': 'error',
                              'desc': 'mobile_number must be a US number'},
                             status=400)

    optin = request.POST.get('optin', 'N') == 'Y'

    # When celery is turned on, use delay to call update_user and
    # don't catch any exceptions. For now, return an error if
    # something goes wrong.
    try:
        add_sms_user(msg_name, mobile, optin)
        return json_response({'status': 'ok'})
    except (NewsletterException, UnauthorizedException), e:
        return json_response({'status': 'error',
                              'desc': e.message},
                             status=500)


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

    return get_user(request.subscriber.token)


def debug_user(request):
    if not 'email' in request.GET or not 'supertoken' in request.GET:
        return json_response({
            'status': 'error',
            'desc': 'Using debug_user, you need to pass the '
                    '`email` and `supertoken` GET parameters',
        }, status=500)

    if request.GET['supertoken'] != settings.SUPERTOKEN:
        return json_response({'status': 'error',
                              'desc': 'Bad supertoken'},
                             status=401)

    return get_user(email=request.GET['email'])


# Custom update methods

@csrf_exempt
def custom_unsub_reason(request):
    """Update the reason field for the user, which logs why the user
    unsubscribed from all newsletters."""

    if not 'token' in request.POST or not 'reason' in request.POST:
        return json_response({
            'status': 'error',
            'desc': 'custom_unsub_reason requires the `token` '
                    'and `reason` POST parameters',
        }, status=401)

    token = request.POST['token']
    reason = request.POST['reason']

    ext = ExactTargetDataExt(settings.EXACTTARGET_USER,
                             settings.EXACTTARGET_PASS)
    ext.add_record(settings.EXACTTARGET_DATA,
                   ['TOKEN', 'UNSUBSCRIBE_REASON'],
                   [token, reason])

    return json_response({'status': 'ok'})


@csrf_exempt
def custom_student_reps(request):
    data = dict(request.POST.items())
    try:
        update_student_reps(data)
        return json_response({'status': 'ok'})
    except (NewsletterException, UnauthorizedException), e:
        return json_response({'status': 'error',
                              'desc': e.message},
                             status=500)

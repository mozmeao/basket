from functools import wraps
import urlparse
import json

from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt 
from django.conf import settings

from tasks import update_user, SUBSCRIBE, UNSUBSCRIBE, SET
from newsletters import *
from models import Subscriber
from responsys import Responsys, NewsletterException, UnauthorizedException

## Utility functions

def logged_in(f):
    """Decorator to check if the user has permission to view these
    pages"""

    @wraps(f)
    def wrapper(request, token, *args, **kwargs):
        subscriber = Subscriber.objects.filter(token=token)
        if not subscriber.exists():
            return json_response({'desc': 'Must have valid token for this request'},
                                 status=403)
        
        request.subscriber = subscriber[0]
        return f(request, token, *args, **kwargs)
    return wrapper


def json_response(data, status=200):
    res = HttpResponse(json.dumps(data),
                       mimetype='application/json')
    res.status_code = status
    return res


def update_user_task(request, type, data=None):
    """Call the update_user task async with the right parameters"""

    user = getattr(request, 'subscriber', None)
    update_user.apply_async((data or request.POST.copy(),
                             user and user.email,
                             type))

## Views

@csrf_exempt
def subscribe(request):
    if request.method != 'POST':
        return HttpResponseBadRequest("Only POST supported")

    if 'newsletters' not in request.POST:
        return json_response({'desc': 'newsletters is missing'},
                             status=500)

    # If the user isn't opting in yet, we tell the system to
    # unsubscribe them instead of subscribe them, which sets a flag
    # for those newsletters that still requires confirmation by other
    # means (confirmation email, etc)
    optin = request.POST.get('optin', 'Y') == 'Y'
    update_user_task(request,
                     SUBSCRIBE if optin else UNSUBSCRIBE)
    return json_response({})


@logged_in
@csrf_exempt
def unsubscribe(request, token):
    if request.method != 'POST':
        return HttpResponseBadRequest("Only POST supported")

    data = request.POST.copy()

    if data.get('optout', 'N') == 'Y':
        data['optin'] = 'N'
        data['newsletters'] = ','.join(newsletter_names())

    update_user_task(request, UNSUBSCRIBE, data)
    return json_response({})


@logged_in
@csrf_exempt
def user(request, token):
    if request.method == 'POST':
        update_user_task(request, SET)
        return json_response({})

    newsletters = newsletter_fields()

    fields = [
        'EMAIL_ADDRESS_',
        'EMAIL_FORMAT_',
        'COUNTRY_',
        'LANGUAGE_ISO2'
    ]

    for nl in newsletters:
        fields.append('%s_FLG' % nl)

    try:
        rs = Responsys()
        rs.login(settings.RESPONSYS_USER, settings.RESPONSYS_PASS)
        user = rs.retrieve_list_members(request.subscriber.email,
                                        settings.RESPONSYS_FOLDER,
                                        settings.RESPONSYS_LIST,
                                        fields)
    except NewsletterException, e:
        return json_response({'desc': e.message},
                             status=500)
    except UnauthorizedException, e:
        return json_response({'desc': 'Responsys auth failure'},
                             status=500)

    user_data = {
        'email': request.subscriber.email,
        'format': user['EMAIL_FORMAT_'],
        'country': user['COUNTRY_'],
        'lang': user['LANGUAGE_ISO2'],
        'newsletters': [newsletter_name(nl) for nl in newsletters
                        if user.get('%s_FLG' % nl, False) == 'Y']
    }

    rs.logout()

    return json_response(user_data)


@logged_in
@csrf_exempt
def delete_user(request, token):
    try:
        rs = Responsys()
        rs.login(settings.RESPONSYS_USER, settings.RESPONSYS_PASS)
        rs.delete_list_members(request.subscriber.email,
                               settings.RESPONSYS_FOLDER,
                               settings.RESPONSYS_LIST)
        rs.logout()
    except NewsletterException, e:
        return json_response({'desc': e.message},
                             status=500)
    except UnauthorizedException, e:
        return json_response({'desc': 'Responsys auth failure'},
                             status=500)

    request.subscriber.delete()
    return json_response({})

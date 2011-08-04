from functools import wraps
from datetime import date
import urlparse
import json

from django.http import (HttpResponse, HttpResponseRedirect,
                         HttpResponseBadRequest, HttpResponseForbidden)
from django.views.decorators.csrf import csrf_exempt 
from django.conf import settings

from models import Subscriber
from responsys import Responsys, NewsletterException, UnauthorizedException

NEWSLETTERS = {
    'mozilla-and-you': 'MOZILLA_AND_YOU',
}

NEWSLETTER_NAMES = NEWSLETTERS.keys()
NEWSLETTER_FIELDS = NEWSLETTERS.values()

# Utility functions

def newsletter_field(name):
    return NEWSLETTERS.get(name, False)


def newsletter_name(field):
    i = NEWSLETTER_FIELDS.index(field)
    return NEWSLETTER_NAMES[i]


def logged_in(f):
    """ Decorator to check if the user has permission to view these
    pages """

    @wraps(f)
    def wrapper(request, token, *args, **kwargs):
        subscriber = Subscriber.objects.filter(token=token)
        if not subscriber.exists():
            return HttpResponseForbidden('Must have valid token for this '
                                         'request')
        
        request.subscriber = subscriber[0]
        return f(request, token, *args, **kwargs)
    return wrapper


def json_response(data):
    res = HttpResponse(json.dumps(data),
                       mimetype='application/json')

    # Allow all cross-domain requests, this service will restrict
    # access on the server level
    res['Access-Control-Allow-Origin'] = '*'
    return res


class Update(object):
    SUBSCRIBE=1
    UNSUBSCRIBE=2
    SET=3


@csrf_exempt
def subscribe(request):
    return update_user(request, Update.SUBSCRIBE)


@logged_in
@csrf_exempt
def unsubscribe(request, token):
    return update_user(request, Update.UNSUBSCRIBE)


@logged_in
@csrf_exempt
def user(request, token):
    if request.method == 'POST':
        return update_user(request, Update.SET)

    newsletters = NEWSLETTERS.values()

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
        rs.login('MOZILLA_API', '')
        user = rs.retrieve_list_members(request.subscriber.email,
                                        settings.RESPONSYS_FOLDER,
                                        settings.RESPONSYS_LIST,
                                        fields)
    except NewsletterException, e:
        return json_response({'status': 'error',
                              'desc': e.message})
    except UnauthorizedException, e:
        return json_response({'status': 'error',
                              'desc': 'Responsys auth failure'})
            
    user_data = {
        'email': request.subscriber.email,
        'format': user['EMAIL_FORMAT_'],
        'country': user['COUNTRY_'],
        'lang': user['LANGUAGE_ISO2'],
        'newsletters': [newsletter_name(nl) for nl in newsletters
                        if user.get('%s_FLG' % nl, False) == 'Y']
    }

    rs.logout()

    user_data['status'] = 'ok'
    return json_response(user_data)

def parse_newsletters(record, type, newsletters):
    """ Parse the newsletter data from a comma-delimited string and
    set the appropriate fields in the record """

    newsletters = [x.strip() for x in newsletters.split(',')]

    if type == Update.SUBSCRIBE or type == Update.SET:
        # Subscribe the user to these newsletters
        for nl in newsletters:
            name = newsletter_field(nl)
            if name:
                record['%s_FLG' % name] = 'Y'
                record['%s_DATE' % name] = date.today().strftime('%Y-%m-%d')

    else:
        # Unsubscribe the user to these newsletters
        unsubs = newsletters

        if type == Update.SET:
            # Unsubscribe to the inversion of these newsletters
            subs = Set(newsletters)
            all = Set(NEWSLETTER_NAMES)
            unsubs = all.difference(subs)

        for nl in unsubs:
            name = newsletter_field(nl)
            if name:
                record['%s_FLG' % name] = 'N'


def update_user(request, type):
    """ General method for updating user's preferences and subscribed
    newsletters. Assumes data to be in POST """

    if request.method != 'POST':
        return HttpResponseBadRequest("Only POST supported")

    has_auth = hasattr(request, 'subscriber')
    
    # validate parameters
    if not has_auth and 'email' not in request.POST:
        return json_response({'status': 'error',
                              'desc': 'email is required when not using tokens'})

    if 'newsletters' not in request.POST:
        return json_response({'status': 'error',
                              'desc': 'newsletters is missing'})

    # parse the parameters
    data = request.POST
    record = {'EMAIL_ADDRESS_': (request.subscriber.email if has_auth
                                 else data['email'])}

    extra_fields = {
        'format': 'EMAIL_FORMAT_',
        'country': 'COUNTRY_',
        'lang': 'LANGUAGE_ISO2'
    }

    for field in extra_fields.keys():
        if field in data:
            record[extra_fields[field]] = data[field]

    # setup the newsletter fields
    parse_newsletters(record, type, data['newsletters'])

    print record

    # save the user's fields
    try:
        rs = Responsys()
        rs.login('MOZILLA_API', '')
        rs.merge_list_members(settings.RESPONSYS_FOLDER,
                              settings.RESPONSYS_LIST,
                              record.keys(),
                              record.values())
        rs.logout()
    except NewsletterException, e:
        return json_response({'status': 'error',
                              'desc': e.message})
    except UnauthorizedException, e:
        return json_response({'status': 'error',
                              'desc': 'Responsys auth failure'})
        

    return json_response({'status': 'ok'})


from datetime import date
import urlparse

from django.http import (HttpResponse, HttpResponseRedirect,
                         HttpResponseBadRequest, HttpResponseForbidden)
from django.views.decorators.csrf import csrf_exempt 
from django.conf import settings

from responsys import Responsys


@csrf_exempt
def subscribe(request):
    if request.method == 'POST':
        data = request.POST

        # validate parameters
        for name in ['email']:
            if name not in data:
                return HttpResponseBadRequest('%s is missing' % name)

        record = {'EMAIL_ADDRESS_': data['email'],
                  'EMAIL_FORMAT_': data.get('format', 'H'),
                  'COUNTRY_': data.get('country', 'en'),
                  'MOZILLA_AND_YOU_FLG': 'Y',
                  'MOZILLA_AND_YOU_DATE': date.today().strftime('%Y-%m-%d')}

        # do the subscription
        rs = Responsys()
        rs.login(settings.RESPONSYS_USER, settings.RESPONSYS_PASS)
        rs.merge_list_members(settings.RESPONSYS_FOLDER,
                              settings.RESPONSYS_LIST,
                              record.keys(),
                              record.values())
        rs.logout()

        # redirect back to the page, if any
        next = data.get('next', request.META.get('HTTP_REFERER', None))
        if next:
            parts = urlparse.urlsplit(next)
            query = '%s%s%s' % (parts.query, 
                                '&' if parts.query else '', 
                                'subscribed')
            next = urlparse.urlunsplit((parts.scheme,
                                        parts.netloc,
                                        parts.path,
                                        query,
                                        parts.fragment))
            return HttpResponseRedirect(next)
        return HttpResponse('Success! You have been subscribed.')

    return HttpResponseBadRequest('GET is not supported')


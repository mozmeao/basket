import logging

from django.http import HttpResponse

import oauth2 as oauth

from piston.models import Consumer as ConsumerModel


class BasketAuthentication(object):
    """
    This supplements Piston's auth system by providing 2-legged OAuth
    using the oauth2 library.  Piston's OAuth only supports a 3-legged scheme
    [link to 2/3 legged definition]
    """
    def __init__(self, realm="Basket"):
        self.realm = realm
        self.server = oauth.Server()
        self.server.add_signature_method(oauth.SignatureMethod_HMAC_SHA1())

    def is_authenticated(self, request):
        try:
            params = dict(request.POST.items())
            if 'Authorization' not in request.META and \
                'HTTP_AUTHORIZATION' in request.META:
                request.META['Authorization'] = request.META['HTTP_AUTHORIZATION']

            oauth_req = oauth.Request.from_request(
                request.method,
                request.build_absolute_uri(),
                headers=request.META,
                parameters=params,
                query_string=request.environ.get('QUERY_STRING', ''))

            if oauth_req is None:
                raise oauth.Error

            key = oauth_req.get_parameter('oauth_consumer_key')
            r = ConsumerModel.objects.get(key=key)
            consumer = oauth.Consumer(key=r.key, secret=r.secret)

            self.server.verify_request(oauth_req, consumer, None)
            return True
        except ConsumerModel.DoesNotExist, e:
            logging.error(e)
            return False
        except oauth.Error, e:
            logging.error(e)
            logging.error(request)
            return False
        except:
            logging.error('fallback error')
            logging.error(request)

    def challenge(self):
        response = HttpResponse(status=401)
        for k, v in self.server.build_authenticate_header().iteritems():
            response[k] = v
        return response

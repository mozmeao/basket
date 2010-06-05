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
            params = request.POST or {}

            oauth_req = oauth.Request.from_request(
                request.method,
                request.build_absolute_uri(),
                headers=request.META,
                parameters=params,
                query_string=request.environ.get('QUERY_STRING', ''))

            r = self.get_consumer_record(oauth_req.get_parameter('oauth_consumer_key'))
            consumer = oauth.Consumer(key=r.key, secret=r.secret)

            self.server.verify_request(oauth_req, consumer, None)
            return True
        except ConsumerModel.DoesNotExist, e:
            # TODO: add logging
            return False
        except oauth.Error, e:
            return False

    def get_consumer_record(self, key):
        return ConsumerModel.objects.get(key=key)

    def challenge(self):
        response = HttpResponse(status=401)
        for k, v in self.server.build_authenticate_header().iteritems():
            response[k] = v
        return response

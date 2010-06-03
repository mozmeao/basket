import time
from nose.tools import eq_
import unittest
import oauth2 as oauth
from piston.models import Consumer as ConsumerModel
from . import BasketAuthentication
from utils import RequestFactory


class AuthTest(unittest.TestCase):
    # why doesn't find+install this fixture?
    fixtures = ['consumer.json']

    def setUp(self):
        ConsumerModel.objects.create(name='test', key='test', secret='test')

        self.rf = RequestFactory()
        # RequestFactory defaults SERVER_NAME to testserver
        # it's important that this URL matches that, so the signature matches
        self.url = "http://testserver/api"

        self.auth_provider = BasketAuthentication()
        self.method = "POST"
        self.consumer = oauth.Consumer(key='test', secret='test')
        self.signature_method = oauth.SignatureMethod_HMAC_SHA1()
        # we're only using 2-legged auth, no need for tokens
        self.token = None

        self.params = {
            'oauth_consumer_key': self.consumer.key,
            'oauth_version': '1.0',
            'oauth_nonce': oauth.generate_nonce(),
            'oauth_timestamp': int(time.time()),
        }

    def tearDown(self):
        ConsumerModel.objects.all().delete()

    def build_request(self):
        oauth_req = oauth.Request(method=self.method, url=self.url, parameters=self.params)
        oauth_req.sign_request(self.signature_method, self.consumer, self.token)
        header = oauth_req.to_header()
        return self.rf.post(self.url, {}, **header)

    def test_get_consumer_record(self):
        self.auth_provider.get_consumer_record('test')

    def test_valid_auth(self):
        r = self.build_request()
        eq_(self.auth_provider.is_authenticated(r), True)

    def test_invalid_auth(self):
        self.consumer = oauth.Consumer('test', 'fail')
        r = self.build_request()
        eq_(self.auth_provider.is_authenticated(r), False)

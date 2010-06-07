import time

from django.core.exceptions import ValidationError
from django import test

from nose.tools import eq_
import oauth2 as oauth
from piston.models import Consumer as ConsumerModel
from django.test.client import Client
from test_utils import RequestFactory

from .models import Subscription

class SubscriptionTest(test.TestCase):
    def setUp(self):
        ConsumerModel.objects.create(name='test', key='test', secret='test')

        self.rf = RequestFactory()
        # RequestFactory defaults SERVER_NAME to testserver
        # it's important that this URL matches that, so the signature matches
        self.url = "http://testserver/api"

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
        self.c = Client()

    def tearDown(self):
        ConsumerModel.objects.all().delete()

    def subscribe(self, **kwargs):
        kwargs.update(self.params)
        oauth_req = oauth.Request(method='POST', url='http://testserver/subscriptions/subscribe', paramters=kwargs)
        oauth.req.sign_request(self.signature_method, self.consumer, self.token)
        header = oauth_req.to_header()
        return self.c.post('http://testserver/subscriptions/subscribe', {}, **header)

    def test_validation(self):
        a = Subscription()
        # fail on blank email
        self.assertRaises(ValidationError, a.full_clean)
        a.email = 'foo';
        # fail on bad email format
        self.assertRaises(ValidationError, a.full_clean)
        a.email = 'foo@foo.com';
        # fail on blank campaign
        self.assertRaises(ValidationError, a.full_clean)
        a.campaign = 'foo'
        # fail on bad locale
        a.locale = 'foo'
        self.assertRaises(ValidationError, a.full_clean)
        # source can be blank
        a.source = ''
        # locale can be blank
        a.locale = ''
        # success
        a.full_clean()
        # blank locale falls back to en-US
        eq_(a.locale, 'en-US')
        a.save()

    #def test_create(self):
    #    resp = self.subscribe(email='')
    #    eq_(resp.status_code, 400)
    #    resp = self.subscribe(campaign='')
    #    eq_(resp.status_code, 400)
    #    count = Subscription.objects.count
    #    eq_(count(), 0)
    #    resp = self.subscribe()
    #    eq_(resp.status_code, 200, resp.content)
    #    eq_(count(), 1)
        # new record is active

    # locale must be in list of valid locales

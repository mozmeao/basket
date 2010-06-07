import time

from django.core.exceptions import ValidationError
from django import test

from nose.tools import eq_

from .models import Subscription
from test_client import TestClient


class SubscriptionTest(test.TestCase):
    def setUp(self):
        self.c = TestClient()
        self.count = Subscription.objects.count

    def tearDown(self):
        self.c.tearDown()

    def valid_subscription(self):
        # email and campaign are required
        return Subscription(email='foo@foo.com', campaign='test')

    def test_validation(self):
        # test valid subscription
        a = self.valid_subscription()
        a.save()

        # fail on blank email
        a.email = ''
        self.assertRaises(ValidationError, a.full_clean)
        # fail on bad email format
        a.email = 'foo'
        self.assertRaises(ValidationError, a.full_clean)

        # fail on blank campaign
        b = self.valid_subscription()
        b.campaign = ''
        self.assertRaises(ValidationError, b.full_clean)
  
        # fail on bad locale
        c = self.valid_subscription()
        c.locale = 'foo'
        self.assertRaises(ValidationError, c.full_clean)

    def test_locale_fallback(self):
        """A blank locale will fall back to en-US"""

        a = self.valid_subscription()
        a.locale = ''
        a.full_clean()
        eq_(a.locale, 'en-US')

    def test_active_default(self):
        """A new record is active be default"""

        a = self.valid_subscription()
        a.save()
        eq_(a.active, True)

    def test_status_codes(self):
        # validation errors return 400
        resp = self.c.subscribe(email='')
        eq_(resp.status_code, 400, resp.content)
        eq_(self.count(), 0)
        
        # success returns 200
        resp = self.c.subscribe(email='foo@bar.com', campaign='foo')
        eq_(resp.status_code, 200, resp.content)
        eq_(self.count(), 1)
        eq_(Subscription.objects.filter(email='foo@bar.com').count(), 1)

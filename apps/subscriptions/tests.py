import time

from django.core.exceptions import ValidationError
from django import test

from nose.tools import eq_
import oauth2 as oauth

from .models import Subscription

class SubscriptionTest(test.TestCase):

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
        # source can be None
        a.source = None
        # success
        a.full_clean()
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


    # test email required
    # email format validation
    # list / campaign ID required
    # locale fallback to en-US
    # test auth
    # test welcome
    # test unsubscribe

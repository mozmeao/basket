from django.core.exceptions import ValidationError
from django import test

from nose.tools import eq_
from piston.utils import rc

from .management.commands.unsubscribe import Command as UnsubscribeCommand
from .models import Subscription, Subscriber
from test_client import TestClient


class SubscriptionTest(test.TestCase):
    def setUp(self):
        self.c = TestClient()
        self.count = Subscription.objects.count

    def tearDown(self):
        self.c.tearDown()

    def valid_subscriber(self):
        return Subscriber(email='foo@foo.com')

    def valid_subscription(self):
        subscriber = self.valid_subscriber()
        subscriber.save()
        s = Subscription(campaign='test')
        s.subscriber = subscriber
        return s

    def test_subscriber_validation(self):
        # test valid subscriber
        a = self.valid_subscriber()
        a.save()

        # fail on blank email
        a.email = ''
        self.assertRaises(ValidationError, a.full_clean)

        # fail on bad email format
        a.email = 'foo'
        self.assertRaises(ValidationError, a.full_clean)

    def test_subscription_validation(self):
        # test valid subscription
        a = self.valid_subscription()
        a.save()

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

    def test_valid_locale(self):
        """A valid locale, other than en-US, works"""

        a = self.valid_subscription()
        a.locale = 'es-ES'
        a.full_clean()
        a.save()
        eq_(Subscription.objects.filter(locale='es-ES').count(), 1)

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
        eq_(resp.status_code, 201, resp.content)
        eq_(self.count(), 1)
        eq_(Subscription.objects.filter(subscriber__email='foo@bar.com').count(), 1)

        # duplicate returns 409
        resp = self.c.subscribe(email='foo@bar.com', campaign='foo')
        eq_(resp.status_code, 409, resp.content)
        eq_(self.count(), 1)
        eq_(Subscription.objects.filter(subscriber__email='foo@bar.com').count(), 1)

    def test_read(self):
        resp = self.c.read()
        eq_(resp.status_code, 501)


def unsubscribe_conditional(subscription):
    return subscription.subscriber.email == 'foo@foo.com'
    
class UnsubscribeManagementTest(test.TestCase):
    fixtures = ['subscriptions']

    def setUp(self):
        self.command = UnsubscribeCommand()
        self.run = self.command.handle_label
        
    def test_unsubscribe_all(self):
        self.run('foo')
        eq_(Subscription.objects.filter(active=True).count(), 0)
        
    def test_conditional_unsubscribe(self):
        self.run('foo', conditional='subscriptions.tests.unsubscribe_conditional')
        eq_(Subscription.objects.filter(active=True).count(), 1)
        rec = Subscription.objects.get(subscriber__email='foo@foo.com')
        eq_(rec.active, False)

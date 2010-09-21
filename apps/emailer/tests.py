from django import test

import mock
from nose.tools import eq_

from . import  charsets, Email, Emailer
from .models import Recipient
import mysmtp
from test_client import TestClient


class TestEmail(Email):
    id = 'test'

test_email = TestEmail()
test_emailer = Emailer('test', test_email)


@mock.patch('mysmtp.EmailBackend.open')
@mock.patch('mysmtp.EmailBackend._send')
def test_smtp_backend_no_connection(send_mock, open_mock):
    backend = mysmtp.EmailBackend()
    msgs = ['failed', 'failed', 'failed']
    rv = backend.send_messages(msgs)
    eq_(rv, ([], msgs))


@mock.patch('mysmtp.EmailBackend.open')
@mock.patch('mysmtp.EmailBackend._send')
def test_send_failure(send_mock, open_mock):
    sent = [True, False, True]
    send_mock.side_effect = lambda *a, **k: sent.pop()

    backend = mysmtp.EmailBackend()
    backend.connection = mock.Mock()

    expected = ['sent', 'sent'], ['failed']
    rv = backend.send_messages(['sent', 'failed', 'sent'])
    eq_(send_mock.call_count, 3)
    eq_(rv, expected)

class EmailTest(test.TestCase):
    fixtures = ['subscriptions']

    def setUp(self):
        self.email = test_email
        self.emailer = test_emailer

    def test_get_email(self):
        email = Email.get('emailer.tests.TestEmail')
        eq_(email.id, 'test')
        
    def test_get_subscriptions(self):
        subs = self.emailer.get_subscriptions()
        eq_(subs.count(), 2)

    @mock.patch('emailer.mail.get_connection')
    def test_recipients_saved(self, conn_mock):
        sent = [True, False]

        backend = mysmtp.EmailBackend()
        backend.connection = mock.Mock()
        backend._send = lambda *a, **k: sent.pop()

        conn_mock.return_value = backend
        eq_(Recipient.objects.all().count(), 0)
        self.emailer.send_email()
        eq_(Recipient.objects.all().count(), 1)

        subs = self.emailer.get_subscriptions()
        # zero subscriptions found because failures are marked as unsubscribed
        eq_(subs.count(), 0)

    def test_email_charset(self):
        self.email.lang = 'it'
        expected = charsets['it']
  
        msg = self.email.message('test').message()

        for x in msg.get_payload():
            eq_(x.get_charset(), expected)

    @mock.patch('emailer.mail.get_connection')
    def test_bad_email_unsubscribed(self, conn_mock):
        sent = [False, False]

        backend = mysmtp.EmailBackend()
        backend.connection = mock.Mock()
        backend._send = lambda *a, **k: sent.pop()

        conn_mock.return_value = backend
        self.emailer.send_email()

        subs = self.emailer.get_subscriptions()
        eq_(subs.count(), 0)

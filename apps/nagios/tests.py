from django import test
from django.test.client import Client
from nose.tools import eq_


class NagiosTest(test.TestCase):
    def setUp(self):
        self.c = Client()

    def test_nagios(self):
        resp = self.c.get('/nagios/')
        eq_(resp.status_code, 200)
        eq_(resp.content, 'SUCCESS')

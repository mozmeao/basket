import time

from django import test

import oauth2 as oauth
from nose.tools import eq_

from . import BasketAuthentication
from test_client import TestClient


class AuthTest(test.TestCase):

    def setUp(self):
        self.auth_provider = BasketAuthentication()
        self.c = TestClient()

    def test_valid_auth(self):
        r = self.c.subscribe_request(email='foo@bar.com')
        eq_(self.auth_provider.is_authenticated(r), True)

    def test_invalid_auth(self):
        self.c.consumer = oauth.Consumer('fail', 'fail')
        r = self.c.subscribe_request()
        eq_(self.auth_provider.is_authenticated(r), False)

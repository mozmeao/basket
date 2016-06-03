from django.core.cache import cache
from django.test import TestCase

from mock import patch, call, Mock

from news.backends.common import NewsletterException
from news.backends import sfmc


@patch('news.backends.sfmc.time', Mock(return_value=600))
@patch.object(sfmc.ETRefreshClient, 'build_soap_client', Mock())
@patch.object(sfmc.ETRefreshClient, 'load_wsdl', Mock())
@patch.object(sfmc.ETRefreshClient, 'request_token')
@patch.object(sfmc.ETRefreshClient, 'refresh_auth_tokens_from_cache')
@patch.object(sfmc.ETRefreshClient, 'cache_auth_tokens')
@patch.object(sfmc.ETRefreshClient, 'token_is_expired')
class TestRefreshToken(TestCase):
    def test_refresh_token(self, exp_mock, cache_mock, refresh_mock, request_mock):
        request_mock.return_value = {
            'accessToken': 'good-token',
            'expiresIn': 9000,
            'legacyToken': 'internal-token',
            'refreshToken': 'refresh-key',
        }
        client = sfmc.ETRefreshClient(params={'clientid': 'id', 'clientsecret': 'sssshhhh'})
        self.assertTrue(refresh_mock.called)
        self.assertFalse(exp_mock.called)
        self.assertTrue(cache_mock.called)
        self.assertEqual(client.authToken, 'good-token')
        self.assertEqual(client.authTokenExpiration, 9600)  # because of time mock
        self.assertEqual(client.internalAuthToken, 'internal-token')
        self.assertEqual(client.refreshKey, 'refresh-key')


@patch.object(sfmc.ETRefreshClient, 'load_wsdl', Mock())
@patch.object(sfmc.ETRefreshClient, 'build_soap_client', Mock())
@patch.object(sfmc.ETRefreshClient, 'refresh_token', Mock())
@patch('news.backends.sfmc.cache')
class TestCacheTokens(TestCase):
    def test_cache_auth_tokens(self, cache_mock):
        client = sfmc.ETRefreshClient()
        client.authToken = 'good-token'
        client._old_authToken = 'old-token'
        client.authTokenExpiration = 9600
        client.authTokenExpiresIn = 100
        client.internalAuthToken = 'internal-token'
        client.refreshKey = 'refresh-key'
        client.cache_auth_tokens()
        cache_mock.set.assert_called_once_with(client.token_cache_key, {
            'authToken': 'good-token',
            'authTokenExpiration': 9600,
            'internalAuthToken': 'internal-token',
            'refreshKey': 'refresh-key',
        }, 700)

    def test_cache_auth_tokens_skip(self, cache_mock):
        """Should skip setting cache when token is good"""
        client = sfmc.ETRefreshClient()
        client.authToken = 'good-token'
        client._old_authToken = client.authToken
        self.assertFalse(cache_mock.set.called)

    def test_refresh_auth_tokens_from_cache(self, cache_mock):
        client = sfmc.ETRefreshClient()
        client.authToken = None
        cache_mock.get.return_value = {
            'authToken': 'good-token',
            'authTokenExpiration': 9600,
            'internalAuthToken': 'internal-token',
            'refreshKey': 'refresh-key',
        }
        client.refresh_auth_tokens_from_cache()
        self.assertEqual(client.authToken, 'good-token')
        self.assertEqual(client.authTokenExpiration, 9600)
        self.assertEqual(client.internalAuthToken, 'internal-token')
        self.assertEqual(client.refreshKey, 'refresh-key')


@patch.object(sfmc.ETRefreshClient, 'load_wsdl', Mock())
@patch.object(sfmc.ETRefreshClient, 'refresh_token', Mock())
@patch('news.backends.sfmc.time')
@patch('news.backends.sfmc.randint')
class TestTokenIsExpired(TestCase):
    def test_token_is_expired(self, randint_mock, time_mock):
        client = sfmc.ETRefreshClient()
        client.authTokenExpiration = None
        self.assertTrue(client.token_is_expired())

        client.authTokenExpiration = 1000
        time_mock.return_value = 900
        randint_mock.return_value = 100
        self.assertTrue(client.token_is_expired())

        time_mock.return_value = 100
        self.assertFalse(client.token_is_expired())


@patch.object(sfmc.ETRefreshClient, 'load_wsdl', Mock())
@patch.object(sfmc.ETRefreshClient, 'refresh_token', Mock())
@patch('news.backends.sfmc.requests')
class TestRequestToken(TestCase):
    def setUp(self):
        cache.clear()

    def test_request_token_success(self, req_mock):
        client = sfmc.ETRefreshClient()
        req_mock.post.return_value.json.return_value = {'accessToken': 'good-token'}
        payload = {'refreshToken': 'token'}
        client.request_token(payload)
        # called once when first call is successful
        req_mock.post.assert_called_once_with(client.auth_url, json=payload)

    def test_request_token_first_fail(self, req_mock):
        """
        If first call fails it should try again without refreshToken
        """
        client = sfmc.ETRefreshClient()
        req_mock.post.return_value.json.side_effect = [{}, {'accessToken': 'good-token'}]
        payload = {'refreshToken': 'token'}
        client.request_token(payload)
        # payload should be modified
        self.assertEqual(req_mock.post.call_count, 2)
        req_mock.post.assert_has_calls([
            call(client.auth_url, json={'refreshToken': 'token'}),
            call().json(),
            call(client.auth_url, json={}),
            call().json(),
        ])

    def test_request_token_both_fail(self, req_mock):
        """If both calls fail it should raise an exception"""
        client = sfmc.ETRefreshClient()
        req_mock.post.return_value.json.return_value = {}
        payload = {'refreshToken': 'token'}
        with self.assertRaises(NewsletterException):
            client.request_token(payload)

        self.assertEqual(req_mock.post.call_count, 2)

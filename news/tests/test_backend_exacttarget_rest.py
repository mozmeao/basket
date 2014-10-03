from django.conf import settings
from django.test import TestCase
from django.test.utils import override_settings

from mock import Mock, patch

from news.backends.exacttarget_rest import ETRestError, ExactTargetRest


@override_settings(ET_CLIENT_ID='client_id', ET_CLIENT_SECRET='client_secret')
class ExactTargetRestTests(TestCase):
    def setUp(self):
        patcher = patch('news.backends.exacttarget_rest.requests.request')
        self.request = patcher.start()
        self.addCleanup(patcher.stop)

    def test_init_no_client_id(self):
        """If no client ID is found, raise a ValueError."""
        del settings.ET_CLIENT_ID
        with self.assertRaises(ValueError):
            ExactTargetRest()

    def test_init_no_client_secret(self):
        """If no client secret is found, raise a ValueError."""
        del settings.ET_CLIENT_SECRET
        with self.assertRaises(ValueError):
            ExactTargetRest()

    def test_init_default_to_settings(self):
        """
        If no values are passed in for client secret or client id, use
        the settings as default values.
        """
        backend = ExactTargetRest()
        self.assertEqual(backend.client_id, 'client_id')
        self.assertEqual(backend.client_secret, 'client_secret')

    def test_use_given_values(self):
        """
        If values are given for client_id and client_secret, use those
        instead of the settings.
        """
        backend = ExactTargetRest('foo', 'bar')
        self.assertEqual(backend.client_id, 'foo')
        self.assertEqual(backend.client_secret, 'bar')

    def test_auth_token_expired(self):
        backend = ExactTargetRest()
        with patch('news.backends.exacttarget_rest.time.time') as mock_time:
            # Not expired
            mock_time.return_value = 100
            backend._access_token_expires = 200
            backend._access_token_expire_buffer = 50
            self.assertFalse(backend.auth_token_expired())

            # Not expired but within buffer
            mock_time.return_value = 100
            backend._access_token_expires = 120
            backend._access_token_expire_buffer = 50
            self.assertTrue(backend.auth_token_expired())

            # Expired
            mock_time.return_value = 100
            backend._access_token_expires = 80
            backend._access_token_expire_buffer = 50
            self.assertTrue(backend.auth_token_expired())

    def test_auth_token_has_token(self):
        """If we already have a valid auth token, return it."""
        backend = ExactTargetRest()
        backend._access_token = 'mytoken'
        backend.auth_token_expired = Mock(return_value=False)
        self.assertEqual(backend.auth_token, 'mytoken')

    def test_auth_token_known_error(self):
        """
        If there's an error code in the response, raise an
        ETRestError.
        """
        backend = ExactTargetRest()
        backend._request = Mock()
        backend._request.return_value.json.return_value = {
            'errorcode': '17',
            'message': 'SNAKES',
        }
        with self.assertRaises(ETRestError) as ETRE:
            backend.auth_token

        self.assertEqual(str(ETRE.exception), '17: SNAKES')

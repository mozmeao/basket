from unittest.mock import patch, Mock, ANY
import json

from django.test import TestCase
from django.test.utils import override_settings

from requests import Response
from requests.exceptions import HTTPError

from basket.news.backends.ctms import ctms_session, CTMSSession


class CTMSSessionTests(TestCase):

    EXAMPLE_TOKEN = {
        "access_token": "a.long.base64.string",
        "token_type": "bearer",
        "expires_in": 3600,
        "expires_at": 1617144323.2891595,
    }

    @patch("basket.news.backends.ctms.cache", spec_set=("get", "set"))
    @patch("basket.news.backends.ctms.OAuth2Session")
    def test_get_with_new_auth(self, mock_oauth2_session, mock_cache):
        """An OAuth2 token is fetched if needed."""
        mock_session = Mock(
            spec_set=(
                "authorized",
                "fetch_token",
                "request",
                "register_compliance_hook",
            )
        )
        mock_session.authorized = False
        mock_session.fetch_token.return_value = self.EXAMPLE_TOKEN
        mock_response = Mock(spec_set=("status_code",))
        mock_response.status_code = 200
        mock_session.request.return_value = mock_response
        mock_oauth2_session.return_value = mock_session
        mock_cache.get.return_value = None

        session = CTMSSession("https://ctms.example.com", "id", "secret")
        resp = session.get("/ctms", params={"primary_email": "test@example.com"})
        assert resp == mock_response

        mock_oauth2_session.assert_called_once_with(client=ANY, token=None)
        mock_session.register_compliance_hook.assert_called_once()
        mock_cache.get.assert_called_once_with("ctms_token")
        mock_session.fetch_token.assert_called_once_with(
            client_id="id",
            client_secret="secret",
            token_url="https://ctms.example.com/token",
        )
        mock_cache.set.assert_called_once_with(
            "ctms_token", self.EXAMPLE_TOKEN, timeout=3420
        )
        mock_session.request.assert_called_once_with(
            "GET",
            "https://ctms.example.com/ctms",
            params={"primary_email": "test@example.com"},
        )

    @patch("basket.news.backends.ctms.cache", spec_set=("get",))
    @patch("basket.news.backends.ctms.OAuth2Session")
    def test_get_with_existing_auth(self, mock_oauth2_session, mock_cache):
        """An existing OAuth2 token is reused without calling fetch_token."""
        mock_session = Mock(
            spec_set=("authorized", "request", "register_compliance_hook")
        )
        mock_session.authorized = True
        mock_response = Mock(spec_set=("status_code",))
        mock_response.status_code = 200
        mock_session.request.return_value = mock_response
        mock_oauth2_session.return_value = mock_session
        mock_cache.get.return_value = self.EXAMPLE_TOKEN

        session = CTMSSession("https://ctms.example.com", "id", "secret")
        resp = session.get("/ctms", params={"primary_email": "test@example.com"})
        assert resp == mock_response

        mock_oauth2_session.assert_called_once_with(
            client=ANY, token=self.EXAMPLE_TOKEN
        )
        mock_session.register_compliance_hook.assert_called_once()
        mock_cache.get.assert_called_once_with("ctms_token")
        mock_session.request.assert_called_once_with(
            "GET",
            "https://ctms.example.com/ctms",
            params={"primary_email": "test@example.com"},
        )

    @patch("basket.news.backends.ctms.cache", spec_set=("get", "set"))
    @patch("basket.news.backends.ctms.OAuth2Session")
    def test_get_with_re_auth(self, mock_oauth2_session, mock_cache):
        """A new OAuth2 token is fetched on an auth error."""
        mock_session = Mock(
            spec_set=(
                "authorized",
                "fetch_token",
                "request",
                "register_compliance_hook",
            )
        )
        mock_session.authorized = True
        new_token = {
            "access_token": "a.different.base64.string",
            "token_type": "bearer",
            "expires_in": 7200,
            "expires_at": 161715000.999,
        }
        mock_session.fetch_token.return_value = new_token
        mock_response_1 = Mock(spec_set=("status_code",))
        mock_response_1.status_code = 401
        mock_response_2 = Mock(spec_set=("status_code",))
        mock_response_2.status_code = 200
        mock_session.request.side_effect = [mock_response_1, mock_response_2]
        mock_oauth2_session.return_value = mock_session
        mock_cache.get.return_value = self.EXAMPLE_TOKEN

        session = CTMSSession("https://ctms.example.com", "id", "secret")
        resp = session.get("/ctms", params={"primary_email": "test@example.com"})
        assert resp == mock_response_2

        mock_oauth2_session.assert_called_once_with(
            client=ANY, token=self.EXAMPLE_TOKEN
        )
        mock_session.register_compliance_hook.assert_called_once()
        mock_cache.get.assert_called_once_with("ctms_token")
        mock_session.fetch_token.assert_called_once_with(
            client_id="id",
            client_secret="secret",
            token_url="https://ctms.example.com/token",
        )
        mock_cache.set.assert_called_once_with("ctms_token", new_token, timeout=6840)
        mock_session.request.assert_called_with(
            "GET",
            "https://ctms.example.com/ctms",
            params={"primary_email": "test@example.com"},
        )
        assert mock_session.request.call_count == 2

    @patch("basket.news.backends.ctms.cache", spec_set=("get",))
    @patch("basket.news.backends.ctms.OAuth2Session")
    def test_get_with_failed_auth(self, mock_oauth2_session, mock_cache):
        """A new OAuth2 token is fetched on an auth error."""
        mock_session = Mock(
            spec_set=("authorized", "fetch_token", "register_compliance_hook")
        )
        mock_session.authorized = False
        err_resp = Response()
        err_resp.status_code = 400
        err_resp._content = json.dumps({"detail": "Incorrect username or password"})
        err = HTTPError(response=err_resp)
        mock_session.fetch_token.side_effect = err
        mock_oauth2_session.return_value = mock_session
        mock_cache.get.return_value = None

        session = CTMSSession("https://ctms.example.com", "id", "secret")
        with self.assertRaises(HTTPError) as context:
            session.get("/ctms", params={"primary_email": "test@example.com"})
        assert context.exception == err

        mock_oauth2_session.assert_called_once_with(client=ANY, token=None)
        mock_session.register_compliance_hook.assert_called_once()
        mock_cache.get.assert_called_once_with("ctms_token")
        mock_session.fetch_token.assert_called_once_with(
            client_id="id",
            client_secret="secret",
            token_url="https://ctms.example.com/token",
        )

    def test_init_bad_parameter(self):
        """CTMSSession() fails if parameters are bad."""

        params = {
            "api_url": "http://ctms.example.com",
            "client_id": "id",
            "client_secret": "secret",
        }
        CTMSSession(**params)  # Doesn't raise

        bad_param_values = {
            "api_url": ("/ctms", "ctms.example.com", "https://"),
            "client_id": ("",),
            "client_secret": ("",),
            "token_cache_key": ("",),
        }
        for key, values in bad_param_values.items():
            for value in values:
                bad_params = params.copy()
                bad_params[key] = value
                with self.assertRaises(ValueError):
                    CTMSSession(**bad_params)

    def test_init_long_api_url(self):
        """CTMSSession() uses protocol and netloc of api_url."""

        session = CTMSSession(
            "https://ctms.example.com/docs?refresh=1", "client_id", "client_secret"
        )
        assert session.api_url == "https://ctms.example.com"

    @override_settings(
        CTMS_ENABLED=True,
        CTMS_URL="https://ctms.example.com",
        CTMS_CLIENT_ID="client_id",
        CTMS_CLIENT_SECRET="client_secret",
    )
    def test_ctms_session_enabled(self):
        """ctms_session() returns a CTMSSession from Django settings"""
        session = ctms_session()
        assert session.api_url == "https://ctms.example.com"

    @override_settings(CTMS_ENABLED=False)
    def test_ctms_session_disabled(self):
        """ctms_session() returns None when CTMS_ENABLED=False"""
        session = ctms_session()
        assert session is None

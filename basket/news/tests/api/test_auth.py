from unittest.mock import Mock, patch

from django.test import RequestFactory

import fxa.errors
import pytest

from basket.news.auth import (
    AUTHORIZED,
    UNAUTHORIZED,
    FxaBearerToken,
    HeaderApiKey,
    QueryApiKey,
    Unauthorized,
)
from basket.news.models import APIUser


@pytest.mark.django_db
class TestQueryApiKey:
    def setup_method(self):
        self.request = RequestFactory()
        APIUser.objects.create(api_key="abides")

    def test_valid_key(self):
        request = self.request.get("/?api-key=abides")
        key = QueryApiKey()._get_key(request)
        assert key == "abides"
        assert QueryApiKey().authenticate(request, key) == AUTHORIZED

    def test_invalid_key(self):
        request = self.request.get("/?api-key=invalid")
        key = QueryApiKey()._get_key(request)
        assert key == "invalid"
        assert QueryApiKey().authenticate(request, key) is None

    def test_wrong_query_param(self):
        request = self.request.get("/?x-api-key=abides")
        key = QueryApiKey()._get_key(request)
        assert key is None
        assert QueryApiKey().authenticate(request, key) is None


@pytest.mark.django_db
class TestHeaderApiKey:
    def setup_method(self):
        self.request = RequestFactory()
        APIUser.objects.create(api_key="abides")

    def test_valid_key(self):
        request = self.request.get("/", HTTP_X_API_KEY="abides")
        key = HeaderApiKey()._get_key(request)
        assert key == "abides"
        assert HeaderApiKey().authenticate(request, key) == AUTHORIZED

    def test_invalid_key(self):
        request = self.request.get("/", HTTP_X_API_KEY="invalid")
        key = HeaderApiKey()._get_key(request)
        assert key == "invalid"
        assert HeaderApiKey().authenticate(request, key) is None

    def test_wrong_header(self):
        request = self.request.get("/", HTTP_API_KEY="wrong_header")
        key = HeaderApiKey()._get_key(request)
        assert key is None
        assert HeaderApiKey().authenticate(request, key) is None


class TestFxaBearerToken:
    def setup_method(self):
        self.request = RequestFactory()

    def test_no_email(self):
        request = self.request.get("/")
        assert FxaBearerToken().authenticate(request, "token") is None

    def test_valid_token_matching_email_GET(self):
        with patch("basket.news.auth.get_fxa_clients") as mock_get_clients:
            oauth_mock = Mock()
            profile_mock = Mock()
            profile_mock.get_email.return_value = "test@example.com"
            mock_get_clients.return_value = (oauth_mock, profile_mock)

            request = self.request.get("/?email=test@example.com")
            assert FxaBearerToken().authenticate(request, "valid_token") == AUTHORIZED

            oauth_mock.verify_token.assert_called_once_with("valid_token", scope=["basket", "profile:email"])
            profile_mock.get_email.assert_called_once_with("valid_token")

    def test_valid_token_matching_email_POST(self):
        with patch("basket.news.auth.get_fxa_clients") as mock_get_clients:
            oauth_mock = Mock()
            profile_mock = Mock()
            profile_mock.get_email.return_value = "test@example.com"
            mock_get_clients.return_value = (oauth_mock, profile_mock)

            request = self.request.post("/", data={"email": "test@example.com"})
            assert FxaBearerToken().authenticate(request, "valid_token") == AUTHORIZED

            oauth_mock.verify_token.assert_called_once_with("valid_token", scope=["basket", "profile:email"])
            profile_mock.get_email.assert_called_once_with("valid_token")

    def test_valid_token_non_matching_email(self):
        with patch("basket.news.auth.get_fxa_clients") as mock_get_clients:
            oauth_mock = Mock()
            profile_mock = Mock()
            profile_mock.get_email.return_value = "other@example.com"
            mock_get_clients.return_value = (oauth_mock, profile_mock)

            request = self.request.get("/?email=test@example.com")
            assert FxaBearerToken().authenticate(request, "valid_token") is None

    def test_invalid_token(self):
        with patch("basket.news.auth.get_fxa_clients") as mock_get_clients:
            oauth_mock = Mock()
            oauth_mock.verify_token.side_effect = fxa.errors.Error("Invalid token")
            profile_mock = Mock()
            mock_get_clients.return_value = (oauth_mock, profile_mock)

            request = self.request.get("/?email=test@example.com")
            assert FxaBearerToken().authenticate(request, "invalid_token") is None


class TestUnauthorized:
    def setup_method(self):
        self.request = RequestFactory()

    def test_always_returns_unauthorized(self):
        request = self.request.get("/")
        assert Unauthorized()(request) == UNAUTHORIZED

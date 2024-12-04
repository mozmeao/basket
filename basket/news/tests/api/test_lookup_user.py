import uuid
from unittest.mock import Mock, patch

from django.urls import reverse

import pytest

from basket import errors
from basket.news import models
from basket.news.schemas import ErrorSchema, UserSchema
from basket.news.tests.api import _TestAPIBase
from basket.news.utils import (
    MSG_EMAIL_AUTH_REQUIRED,
    MSG_EMAIL_OR_TOKEN_REQUIRED,
    MSG_INVALID_EMAIL,
    MSG_USER_NOT_FOUND,
)


@pytest.mark.django_db
class TestLookupUserAPI(_TestAPIBase):
    def setup_method(self, method):
        self.url = reverse("api.v1:users.lookup")
        self.email = "test@example.com"
        self.token = str(uuid.uuid4())
        self.fxa_id = str(uuid.uuid4())
        self.email_id = str(uuid.uuid4())
        self.user_data = {
            "country": "US",
            "created_date": "2022-03-14T21:47:32.011954+00:00",
            "email": self.email,
            "first_name": "Test",
            "format": "H",
            "fxa_primary_email": None,
            "lang": "en",
            "last_modified_date": "2023-12-05T19:36:56.655122+00:00",
            "last_name": "User",
            "mofo_relevant": False,
            "newsletters": ["newsletter1", "newsletter2"],
            "optin": False,
            "optout": False,
            "status": "ok",
            "token": self.token,
            # Extra fields that are not part of the schema.
            "amo_display_name": "Add-ons Author",
            "amo_homepage": "firefox/user/98765",
            "amo_id": "98765",
            "email_id": self.email_id,
            "fxa_id": self.fxa_id,
        }
        self.api_user = models.APIUser.objects.create(name="test")
        self.api_key = self.api_user.api_key
        self.fxa_jwt = "eyJhbGciOiAiSFMyNTYiLCAidHlwIjogIkpXVCJ9.eyJuYW1lIjogIlRoZSBEdWRlIn0.abides"

    def _user_data(self, **kwargs):
        data = self.user_data.copy()
        data.update(kwargs)
        return data

    def valid_request(self, client):
        return client.get(self.url, {"token": self.token})

    def test_lookup_user_by_email_authorized_qs(self, client):
        # Test lookup by email with an authorized API key in the query string.
        with patch("basket.news.utils.ctms", spec_set=["get"]) as mock_ctms:
            mock_ctms.get.return_value = self._user_data()
            resp = client.get(self.url, {"email": self.email, "api-key": self.api_key})
            assert resp.status_code == 200
            mock_ctms.get.assert_called_once_with(
                email="test@example.com",
                fxa_id=None,
                token=None,
            )
            data = resp.json()
            self.validate_schema(data, UserSchema)
            # Spot check some data.
            assert data["email"] == "test@example.com"
            assert data["token"] == self.token

    def test_lookup_user_by_email_authorized_header(self, client):
        # Test lookup by email with an authorized API key in the headers.
        with patch("basket.news.utils.ctms", spec_set=["get"]) as mock_ctms:
            mock_ctms.get.return_value = self._user_data()
            resp = client.get(self.url, {"email": self.email}, headers={"X-Api-Key": self.api_key})
            assert resp.status_code == 200
            mock_ctms.get.assert_called_once_with(
                email="test@example.com",
                fxa_id=None,
                token=None,
            )
            data = resp.json()
            self.validate_schema(data, UserSchema)
            # Spot check some data.
            assert data["email"] == "test@example.com"
            assert data["token"] == self.token

    def test_lookup_user_by_token(self, client):
        # Test lookup by token without an API key.
        with patch("basket.news.utils.ctms", spec_set=["get"]) as mock_ctms:
            mock_ctms.get.return_value = self._user_data()
            resp = client.get(self.url, {"token": self.token})
            assert resp.status_code == 200
            mock_ctms.get.assert_called_once_with(
                email=None,
                fxa_id=None,
                token=self.token,
            )
            data = resp.json()
            self.validate_schema(data, UserSchema)
            # Spot check some data.
            assert data["email"] == "t**t@e*****e.com"
            assert data["token"] == self.token

    def test_lookup_user_by_token_authorized(self, client):
        # Test lookup by token with an authorized API key in the query string.
        with patch("basket.news.utils.ctms", spec_set=["get"]) as mock_ctms:
            mock_ctms.get.return_value = self._user_data()
            resp = client.get(self.url, {"token": self.token, "api-key": self.api_key})
            assert resp.status_code == 200
            mock_ctms.get.assert_called_once_with(
                email=None,
                fxa_id=None,
                token=self.token,
            )
            data = resp.json()
            self.validate_schema(data, UserSchema)
            # Spot check some data.
            assert data["email"] == "test@example.com"
            assert data["token"] == self.token

    def test_lookup_user_with_has_fxa(self, client):
        # Test lookup with fxa param adds has_fxa to the response.
        with patch("basket.news.utils.ctms", spec_set=["get"]) as mock_ctms:
            mock_ctms.get.return_value = self._user_data()
            resp = client.get(self.url, {"token": self.token})
            assert resp.status_code == 200
            data = resp.json()
            self.validate_schema(data, UserSchema)
            assert data["has_fxa"] is True

    def test_lookup_user_with_has_fxa_false(self, client):
        # Test lookup with fxa param adds has_fxa to the response.
        with patch("basket.news.utils.ctms", spec_set=["get"]) as mock_ctms:
            mock_ctms.get.return_value = self._user_data(fxa_id=None)
            resp = client.get(self.url, {"token": self.token})
            assert resp.status_code == 200
            data = resp.json()
            self.validate_schema(data, UserSchema)
            assert data["has_fxa"] is False

    def test_lookup_email_with_fxa_bearer_token(self, client):
        with patch("basket.news.utils.ctms", spec_set=["get"]) as mock_ctms:
            mock_ctms.get.return_value = self._user_data()
            with patch("basket.news.auth.get_fxa_clients") as mock_get_clients:
                oauth_mock = Mock()
                profile_mock = Mock()
                profile_mock.get_email.return_value = self.email
                mock_get_clients.return_value = (oauth_mock, profile_mock)

                resp = client.get(
                    self.url,
                    {"email": self.email},
                    headers={"Authorization": f"bearer {self.fxa_jwt}"},
                )
                assert resp.status_code == 200
                data = resp.json()
                self.validate_schema(data, UserSchema)
                assert data["email"] == self.email
                assert data["token"] == self.token

                oauth_mock.verify_token.assert_called_once_with(self.fxa_jwt, scope=["basket", "profile:email"])
                profile_mock.get_email.assert_called_once_with(self.fxa_jwt)

    # 4xx errors

    def test_lookup_user_no_params(self, client):
        # Test lookup with no params returns a 400 error.
        with patch("basket.news.utils.ctms", spec_set=["get"]) as mock_ctms:
            resp = client.get(self.url)
            assert resp.status_code == 400
            data = resp.json()
            self.validate_schema(data, ErrorSchema)
            assert data["status"] == "error"
            assert data["code"] == errors.BASKET_USAGE_ERROR
            assert data["desc"] == MSG_EMAIL_OR_TOKEN_REQUIRED
            mock_ctms.get.assert_not_called()

    def test_lookup_both_email_and_token(self, client):
        # Test lookup by both email and token returns a 400 error.
        with patch("basket.news.utils.ctms", spec_set=["get"]) as mock_ctms:
            resp = client.get(self.url, {"email": self.email, "token": self.token})
            assert resp.status_code == 400
            data = resp.json()
            self.validate_schema(data, ErrorSchema)
            assert data["status"] == "error"
            assert data["code"] == errors.BASKET_USAGE_ERROR
            assert data["desc"] == MSG_EMAIL_OR_TOKEN_REQUIRED
            mock_ctms.get.assert_not_called()

    def test_lookup_user_email_not_found(self, client):
        # Test no user found returns 404.
        with patch("basket.news.utils.ctms", spec_set=["get"]) as mock_ctms:
            mock_ctms.get.return_value = None
            resp = client.get(self.url, {"email": self.email, "api-key": self.api_key})
            assert resp.status_code == 404
            data = resp.json()
            self.validate_schema(data, ErrorSchema)
            assert data["status"] == "error"
            assert data["code"] == errors.BASKET_UNKNOWN_EMAIL
            assert data["desc"] == MSG_USER_NOT_FOUND

    def test_lookup_user_invalid_email(self, client):
        # Test invalid email.
        with patch("basket.news.utils.ctms", spec_set=["get"]) as mock_ctms:
            mock_ctms.get.return_value = None
            resp = client.get(self.url, {"email": "invalid", "api-key": self.api_key})
            assert resp.status_code == 400
            data = resp.json()
            self.validate_schema(data, ErrorSchema)
            assert data["status"] == "error"
            assert data["code"] == errors.BASKET_INVALID_EMAIL
            assert data["desc"] == MSG_INVALID_EMAIL

    def test_lookup_user_token_not_found(self, client):
        # Test no user with token found returns 404.
        with patch("basket.news.utils.ctms", spec_set=["get"]) as mock_ctms:
            mock_ctms.get.return_value = None
            resp = client.get(self.url, {"token": self.token})
            assert resp.status_code == 404
            data = resp.json()
            self.validate_schema(data, ErrorSchema)
            assert data["status"] == "error"
            assert data["code"] == errors.BASKET_UNKNOWN_TOKEN
            assert data["desc"] == MSG_USER_NOT_FOUND

    def test_lookup_user_by_email_unauthorized(self, client):
        # Test lookup by email without an API key returns a 401 error.
        with patch("basket.news.utils.ctms", spec_set=["get"]) as mock_ctms:
            mock_ctms.get.return_value = None
            resp = client.get(self.url, {"email": self.email})
            assert resp.status_code == 401
            data = resp.json()
            self.validate_schema(data, ErrorSchema)
            assert data["status"] == "error"
            assert data["code"] == errors.BASKET_AUTH_ERROR
            assert data["desc"] == MSG_EMAIL_AUTH_REQUIRED
            mock_ctms.get.assert_not_called()

    def test_lookup_user_by_email_api_key_disabled(self, client):
        # Test lookup by email with a disabled API key returns a 401 error.
        with patch("basket.news.utils.ctms", spec_set=["get"]) as mock_ctms:
            mock_ctms.get.return_value = None
            self.api_user.enabled = False
            self.api_user.save()
            resp = client.get(self.url, {"email": self.email, "api-key": self.api_key})
            assert resp.status_code == 401
            data = resp.json()
            self.validate_schema(data, ErrorSchema)
            assert data["status"] == "error"
            assert data["code"] == errors.BASKET_AUTH_ERROR
            assert data["desc"] == MSG_EMAIL_AUTH_REQUIRED
            mock_ctms.get.assert_not_called()

    def test_lookup_user_by_email_api_key_bad(self, client):
        # Test lookup by email with a bad API key returns a 401 error.
        with patch("basket.news.utils.ctms", spec_set=["get"]) as mock_ctms:
            mock_ctms.get.return_value = None
            resp = client.get(self.url, {"email": self.email, "api-key": "0xBAD"})
            assert resp.status_code == 401
            data = resp.json()
            self.validate_schema(data, ErrorSchema)
            assert data["status"] == "error"
            assert data["code"] == errors.BASKET_AUTH_ERROR
            assert data["desc"] == MSG_EMAIL_AUTH_REQUIRED
            mock_ctms.get.assert_not_called()

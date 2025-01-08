import uuid
from unittest.mock import patch

from django.urls import reverse

import pytest

from basket import errors
from basket.news.schemas import ErrorSchema, OkSchema
from basket.news.tests.api import _TestAPIwCTMSBase
from basket.news.utils import (
    MSG_USER_NOT_FOUND,
    email_block_list_cache,
)


@pytest.mark.django_db
class TestUsersRecoverAPI(_TestAPIwCTMSBase):
    def setup_method(self, method):
        super().setup_method(method)
        self.url = reverse("api.v1:users.recover")
        self.email = "test@example.com"
        self.token = str(uuid.uuid4())
        self.email_id = str(uuid.uuid4())
        self.user_data = {
            "email": self.email,
            "lang": "en",
            "token": self.token,
            "email_id": self.email_id,
        }
        email_block_list_cache.set("email_block_list", ["blocked.com"])

    def teardown_method(self, method):
        email_block_list_cache.clear()

    def valid_request(self):
        return self.client.post(self.url, {"email": self.email}, content_type="application/json")

    def _user_data(self, **kwargs):
        data = self.user_data.copy()
        data.update(kwargs)
        return data

    def test_blocked_email(self):
        with patch("basket.news.tasks.send_recovery_message.delay", autospec=True) as mock_send:
            resp = self.client.post(self.url, {"email": "bad@blocked.com"}, content_type="application/json")
            assert resp.status_code == 200
            data = resp.json()
            self.validate_schema(data, OkSchema)
            assert mock_send.called is False

    def test_good_email(self):
        with patch("basket.news.utils.ctms", spec_set=["get"]) as mock_ctms:
            with patch("basket.news.tasks.send_recovery_message.delay", autospec=True) as mock_send:
                mock_ctms.get.return_value = self._user_data()
                resp = self.client.post(self.url, {"email": self.email}, content_type="application/json")
                assert resp.status_code == 200, resp.content
                data = resp.json()
                self.validate_schema(data, OkSchema)
                mock_send.assert_called_with(self.email, self.token, "en", self.email_id)

    # 4xx errors

    def test_bad_email(self):
        resp = self.client.post(self.url, {"email": "not_an_email"}, content_type="application/json")
        assert resp.status_code == 422
        data = resp.json()
        self.validate_schema(data, ErrorSchema)
        assert data["status"] == "error"
        assert data["code"] == errors.BASKET_USAGE_ERROR
        assert "value is not a valid email address" in data["desc"]

    def test_no_user_data(self):
        with patch("basket.news.utils.ctms", spec_set=["get"]) as mock_ctms:
            mock_ctms.get.return_value = None
            resp = self.client.post(self.url, {"email": self.email}, content_type="application/json")
            assert resp.status_code == 404
            data = resp.json()
            self.validate_schema(data, ErrorSchema)
            assert data["status"] == "error"
            assert data["code"] == errors.BASKET_UNKNOWN_EMAIL
            assert data["desc"] == MSG_USER_NOT_FOUND

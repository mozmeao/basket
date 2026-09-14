import uuid
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

import pytest

from basket import errors
from basket.news.schemas import ErrorSchema, OkSchema
from basket.news.tests.api import _TestAPIBase


@pytest.mark.django_db
class TestUsersConfirmAPI(_TestAPIBase):
    def setup_method(self, method):
        super().setup_method(method)
        self.token = str(uuid.uuid4())
        self.url = reverse("api.v1:users.confirm", kwargs={"token": self.token})
        self.email = "test@example.com"
        self.email_id = str(uuid.uuid4())
        self.user_data = {
            "email": self.email,
            "token": self.token,
            "email_id": self.email_id,
            "optin": False,
        }

    def _user_data(self, **kwargs):
        data = self.user_data.copy()
        data.update(kwargs)
        return data

    def valid_request(self):
        return self.client.post(self.url)

    def test_good_email(self):
        # Test that the `optin` is set to True.
        with patch("basket.news.tasks.ctms", spec_set=["update"]) as mock_ctms:
            with patch("basket.news.tasks.get_user_data", autospec=True) as get_user_data:
                get_user_data.return_value = self._user_data()
                resp = self.client.post(self.url)
                assert resp.status_code == 200, resp.content
                data = resp.json()
                self.validate_schema(data, OkSchema)
                mock_ctms.update.assert_called_with(self.user_data, {"optin": True})

    def test_good_email_already_confirmed(self):
        # Test that `ctms.update` is not called if already confirmed.
        with patch("basket.news.tasks.ctms", spec_set=["update"]) as mock_ctms:
            with patch("basket.news.tasks.get_user_data", autospec=True) as get_user_data:
                get_user_data.return_value = self._user_data(optin=True)
                resp = self.client.post(self.url)
                assert resp.status_code == 200, resp.content
                data = resp.json()
                self.validate_schema(data, OkSchema)
                mock_ctms.update.assert_not_called()

    def test_no_user_data(self):
        # Test that `ctms.update` is not called if no user.
        with patch("basket.news.tasks.ctms", spec_set=["update"]) as mock_ctms:
            with patch("basket.news.tasks.get_user_data", autospec=True) as get_user_data:
                get_user_data.return_value = None
                resp = self.client.post(self.url)
                assert resp.status_code == 200, resp.content
                data = resp.json()
                self.validate_schema(data, OkSchema)
                mock_ctms.update.assert_not_called()

    def test_user_has_no_email(self):
        # Test that `ctms.update` is not called if user has no email.
        with patch("basket.news.tasks.ctms", spec_set=["update"]) as mock_ctms:
            with patch("basket.news.tasks.get_user_data", autospec=True) as get_user_data:
                get_user_data.return_value = self._user_data(email=None)
                resp = self.client.post(self.url)
                assert resp.status_code == 200, resp.content
                data = resp.json()
                self.validate_schema(data, OkSchema)
                mock_ctms.update.assert_not_called()

    # 4xx errors

    def test_throttle(self, metricsmock):
        """
        Test that the request is throttled after {count} requests.

        Where {count} is the first number in the rate limit.
        """
        count = settings.EMAIL_SUBSCRIBE_RATE_LIMIT.split("/")[0]
        cache.clear()

        with patch("basket.news.tasks.ctms", spec_set=["update"]) as mock_ctms:
            with patch("basket.news.tasks.get_user_data", autospec=True) as get_user_data:
                get_user_data.return_value = self._user_data()
                for _ in range(int(count)):
                    resp = self.client.post(self.url)
                    assert resp.status_code == 200, resp.content
                data = resp.json()
                self.validate_schema(data, OkSchema)
                mock_ctms.update.assert_called_with(self.user_data, {"optin": True})
                mock_ctms.reset_mock()
                assert cache.has_key(f"throttle_token_{self.token}")

                # Second request should be throttled.
                resp = self.client.post(self.url)
                assert resp.status_code == 429, resp.content
                data = resp.json()
                self.validate_schema(data, ErrorSchema)
                assert data["status"] == "error"
                assert data["code"] == errors.BASKET_USAGE_ERROR
                assert "Rate limit exceeded" in data["desc"]
                mock_ctms.update.assert_not_called()
                metricsmock.assert_incr_once("api.throttled", tags=["path:api.v1.users.confirm"])

        cache.clear()

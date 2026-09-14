import uuid
from unittest.mock import patch

from django.core.cache import cache
from django.urls import reverse

import pytest

from basket import errors
from basket.news.schemas import ErrorSchema, OkSchema
from basket.news.tests.api import _TestAPIBase

WEBHOOK_SECRET = "webhook-secret"


@pytest.mark.django_db
class TestUsersAssignAPI(_TestAPIBase):
    def setup_method(self, method):
        super().setup_method(method)
        self.url = reverse("api.v1:users.assign")
        self.test_maintenance_mode = False  # endpoint does not gate on maintenance mode
        self.auth = {"Authorization": f"Bearer {WEBHOOK_SECRET}"}

    @pytest.fixture(autouse=True)
    def _set_secret(self, settings):
        settings.ASSIGN_WEBHOOK_SECRET = WEBHOOK_SECRET

    def valid_request(self):
        return self.client.post(
            self.url,
            {"basket_token": str(uuid.uuid4())},
            content_type="application/json",
            headers=self.auth,
        )

    def test_valid_request_enqueues_braze_task(self, settings):
        settings.BRAZE_ONLY_WRITE_ENABLE = True
        token = str(uuid.uuid4())
        with patch("basket.news.tasks.braze_assign_external_id.delay", autospec=True) as mock_task:
            resp = self.client.post(
                self.url,
                {"basket_token": token},
                content_type="application/json",
                headers=self.auth,
            )
            assert resp.status_code == 200, resp.content
            self.validate_schema(resp.json(), OkSchema)
            mock_task.assert_called_once_with({"email": None, "basket_token": token, "fxa_id": None})

    def test_noop_when_braze_not_write_backend(self, settings):
        # Backend-gated: with no Braze write flag set, nothing is dispatched but the call succeeds.
        settings.BRAZE_PARALLEL_WRITE_ENABLE = False
        settings.BRAZE_ONLY_WRITE_ENABLE = False
        with patch("basket.news.tasks.braze_assign_external_id.delay", autospec=True) as mock_task:
            resp = self.valid_request()
            assert resp.status_code == 200, resp.content
            self.validate_schema(resp.json(), OkSchema)
            mock_task.assert_not_called()

    def test_missing_auth_is_401(self):
        with patch("basket.news.tasks.braze_assign_external_id.delay", autospec=True) as mock_task:
            resp = self.client.post(
                self.url,
                {"basket_token": str(uuid.uuid4())},
                content_type="application/json",
            )
            assert resp.status_code == 401
            mock_task.assert_not_called()

    def test_bad_key_is_401(self):
        with patch("basket.news.tasks.braze_assign_external_id.delay", autospec=True) as mock_task:
            resp = self.client.post(
                self.url,
                {"basket_token": str(uuid.uuid4())},
                content_type="application/json",
                headers={"Authorization": "Bearer nope"},
            )
            assert resp.status_code == 401
            mock_task.assert_not_called()

    def test_no_identifier_is_400(self):
        with patch("basket.news.tasks.braze_assign_external_id.delay", autospec=True) as mock_task:
            resp = self.client.post(self.url, {}, content_type="application/json", headers=self.auth)
            assert resp.status_code == 400
            data = resp.json()
            self.validate_schema(data, ErrorSchema)
            assert data["code"] == errors.BASKET_USAGE_ERROR
            mock_task.assert_not_called()

    def test_blank_email_with_token_is_accepted(self, settings):
        # Braze Liquid may send an empty email alongside a real identifier; the blank email
        # is coerced to None (not rejected by EmailStr) and the token is used.
        settings.BRAZE_ONLY_WRITE_ENABLE = True
        token = str(uuid.uuid4())
        with patch("basket.news.tasks.braze_assign_external_id.delay", autospec=True) as mock_task:
            resp = self.client.post(
                self.url,
                {"email": "", "basket_token": token},
                content_type="application/json",
                headers=self.auth,
            )
            assert resp.status_code == 200, resp.content
            mock_task.assert_called_once_with({"email": None, "basket_token": token, "fxa_id": None})

    def test_invalid_email_is_rejected(self):
        # A non-empty malformed email fails EmailStr validation at the boundary (422).
        with patch("basket.news.tasks.braze_assign_external_id.delay", autospec=True) as mock_task:
            resp = self.client.post(
                self.url,
                {"email": "not-an-email"},
                content_type="application/json",
                headers=self.auth,
            )
            assert resp.status_code == 422
            mock_task.assert_not_called()

    def test_overlong_identifier_is_rejected(self):
        with patch("basket.news.tasks.braze_assign_external_id.delay", autospec=True) as mock_task:
            resp = self.client.post(
                self.url,
                {"basket_token": "a" * 129},
                content_type="application/json",
                headers=self.auth,
            )
            assert resp.status_code == 422
            mock_task.assert_not_called()

    def test_throttled_per_identifier(self):
        # The default rate is "4/5m", so repeated calls for the SAME identifier are throttled.
        cache.clear()
        token = str(uuid.uuid4())
        with patch("basket.news.tasks.braze_assign_external_id.delay", autospec=True):
            codes = [
                self.client.post(
                    self.url,
                    {"basket_token": token},
                    content_type="application/json",
                    headers=self.auth,
                ).status_code
                for _ in range(6)
            ]
        assert 429 in codes
        cache.clear()

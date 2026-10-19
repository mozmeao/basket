import json
import time
import uuid
from unittest.mock import patch

from django.core.cache import cache
from django.urls import reverse

import pytest

from basket import errors
from basket.contact.tests.conftest import sign_intake_body
from basket.news.models import APIUser
from basket.news.schemas import ErrorSchema, OkSchema
from basket.news.tests.api import _TestAPIBase


@pytest.mark.django_db
class TestUsersAssignAPI(_TestAPIBase):
    def setup_method(self, method):
        super().setup_method(method)
        self.url = reverse("api.v1:users.assign")
        self.test_maintenance_mode = False  # endpoint does not gate on maintenance mode
        self.api_user = APIUser.objects.create(name="braze")

    def post(self, payload, timestamp=None, signed=True, api_key=None):
        body = json.dumps(payload).encode()
        headers = {"X-Api-Key": api_key or self.api_user.api_key}
        if signed:
            ts, sig = sign_intake_body(self.api_user, body, timestamp=timestamp)
            headers["X-Basket-Signature"] = f"t={ts},v1={sig}"
        return self.client.post(self.url, body, content_type="application/json", headers=headers)

    def valid_request(self):
        return self.post({"basket_token": str(uuid.uuid4())})

    def test_valid_request_enqueues_braze_task(self):
        token = str(uuid.uuid4())
        with patch("basket.news.tasks.braze_assign_external_id.delay", autospec=True) as mock_task:
            resp = self.post({"basket_token": token})
            assert resp.status_code == 200, resp.content
            self.validate_schema(resp.json(), OkSchema)
            mock_task.assert_called_once_with({"email": None, "basket_token": token, "fxa_id": None})

    def test_missing_signature_is_401(self):
        with patch("basket.news.tasks.braze_assign_external_id.delay", autospec=True) as mock_task:
            resp = self.post({"basket_token": str(uuid.uuid4())}, signed=False)
            assert resp.status_code == 401
            mock_task.assert_not_called()

    def test_missing_api_key_is_401(self):
        with patch("basket.news.tasks.braze_assign_external_id.delay", autospec=True) as mock_task:
            body = json.dumps({"basket_token": str(uuid.uuid4())}).encode()
            ts, sig = sign_intake_body(self.api_user, body)
            resp = self.client.post(
                self.url,
                body,
                content_type="application/json",
                headers={"X-Basket-Signature": f"t={ts},v1={sig}"},
            )
            assert resp.status_code == 401
            mock_task.assert_not_called()

    def test_bad_api_key_is_401(self):
        with patch("basket.news.tasks.braze_assign_external_id.delay", autospec=True) as mock_task:
            resp = self.post({"basket_token": str(uuid.uuid4())}, api_key="nope")
            assert resp.status_code == 401
            mock_task.assert_not_called()

    def test_bad_signature_is_401(self):
        with patch("basket.news.tasks.braze_assign_external_id.delay", autospec=True) as mock_task:
            resp = self.client.post(
                self.url,
                {"basket_token": str(uuid.uuid4())},
                content_type="application/json",
                headers={"X-Api-Key": self.api_user.api_key, "X-Basket-Signature": f"t={int(time.time())},v1={'0' * 64}"},
            )
            assert resp.status_code == 401
            mock_task.assert_not_called()

    def test_tampered_body_is_401(self):
        with patch("basket.news.tasks.braze_assign_external_id.delay", autospec=True) as mock_task:
            ts, sig = sign_intake_body(self.api_user, json.dumps({"basket_token": "a"}).encode())
            resp = self.client.post(
                self.url,
                {"basket_token": "b"},
                content_type="application/json",
                headers={"X-Api-Key": self.api_user.api_key, "X-Basket-Signature": f"t={ts},v1={sig}"},
            )
            assert resp.status_code == 401
            mock_task.assert_not_called()

    def test_stale_timestamp_is_401(self, settings):
        with patch("basket.news.tasks.braze_assign_external_id.delay", autospec=True) as mock_task:
            stale = int(time.time()) - settings.INTAKE_SIGNATURE_TOLERANCE_SECONDS - 1
            resp = self.post({"basket_token": str(uuid.uuid4())}, timestamp=stale)
            assert resp.status_code == 401
            mock_task.assert_not_called()

    def test_replayed_request_is_401(self):
        payload = {"basket_token": str(uuid.uuid4())}
        ts = int(time.time())
        with patch("basket.news.tasks.braze_assign_external_id.delay", autospec=True) as mock_task:
            assert self.post(payload, timestamp=ts).status_code == 200
            assert self.post(payload, timestamp=ts).status_code == 401
            mock_task.assert_called_once()

    def test_no_identifier_is_400(self):
        with patch("basket.news.tasks.braze_assign_external_id.delay", autospec=True) as mock_task:
            resp = self.post({})
            assert resp.status_code == 400
            data = resp.json()
            self.validate_schema(data, ErrorSchema)
            assert data["code"] == errors.BASKET_USAGE_ERROR
            mock_task.assert_not_called()

    def test_blank_email_with_token_is_accepted(self):
        # Braze Liquid may send an empty email alongside a real identifier; the blank email
        # is coerced to None (not rejected by EmailStr) and the token is used.
        token = str(uuid.uuid4())
        with patch("basket.news.tasks.braze_assign_external_id.delay", autospec=True) as mock_task:
            resp = self.post({"email": "", "basket_token": token})
            assert resp.status_code == 200, resp.content
            mock_task.assert_called_once_with({"email": None, "basket_token": token, "fxa_id": None})

    def test_invalid_email_is_rejected(self):
        # A non-empty malformed email fails EmailStr validation at the boundary (422).
        with patch("basket.news.tasks.braze_assign_external_id.delay", autospec=True) as mock_task:
            resp = self.post({"email": "not-an-email"})
            assert resp.status_code == 422
            mock_task.assert_not_called()

    def test_overlong_identifier_is_rejected(self):
        with patch("basket.news.tasks.braze_assign_external_id.delay", autospec=True) as mock_task:
            resp = self.post({"basket_token": "a" * 129})
            assert resp.status_code == 422
            mock_task.assert_not_called()

    def test_throttled_per_identifier(self):
        # The default rate is "4/5m", so repeated calls for the SAME identifier are throttled.
        cache.clear()
        token = str(uuid.uuid4())
        with patch("basket.news.tasks.braze_assign_external_id.delay", autospec=True):
            now = int(time.time())
            codes = [self.post({"basket_token": token}, timestamp=now - i).status_code for i in range(6)]
        assert 429 in codes
        cache.clear()

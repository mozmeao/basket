import json
import time

from django.urls import reverse

import pytest

from basket import errors
from basket.contact.models import FormDestination, FormRoute, FormSubmission
from basket.contact.tests.conftest import sign_intake_body as _sign
from basket.news.models import APIUser
from basket.news.tests.api import _TestAPIBase


@pytest.mark.django_db
class TestIntakeAPI(_TestAPIBase):
    def setup_method(self, method):
        super().setup_method(method)
        self.method = "POST"
        self.test_maintenance_mode = False
        self.url = reverse("api.v1:intake.submit")
        self.api_user = APIUser.objects.create(name="springfield", enabled=True, allowed_form_ids=["enterprise-contact"])
        self.route = FormRoute.objects.create(form_id="enterprise-contact", name="Enterprise Contact", active=True, created_by="dev@example.com")
        FormDestination.objects.create(route=self.route, dest_type="gsheet", label="Sheet", config={}, field_map={"email": "A"}, active=True)

    def _post(self, body_dict, api_key=None, sign_ts=None, sign_body=None):
        body = json.dumps(body_dict).encode()
        key = api_key if api_key is not None else self.api_user.api_key
        ts, sig = _sign(self.api_user, sign_body if sign_body is not None else body, timestamp=sign_ts)
        return self.client.post(
            self.url,
            data=body,
            content_type="application/json",
            headers={"X-Api-Key": key, "X-Basket-Signature": f"t={ts},v1={sig}"},
        )

    def valid_request(self):
        return self._post({"form_id": "enterprise-contact", "data": {"email": "a@b.com"}})

    def test_valid_submission_queues_and_enqueues_task(self, mocker):
        mock_delay = mocker.patch("basket.contact.intake_api.deliver_to_gsheet.delay")
        resp = self.valid_request()
        assert resp.status_code == 200
        assert resp.json() == {"status": "queued"}
        mock_delay.assert_called_once()

    def test_bad_api_key_returns_generic_401(self):
        resp = self._post({"form_id": "enterprise-contact", "data": {}}, api_key="nope")
        assert resp.status_code == 401
        assert resp.json() == {"status": "error", "detail": "unauthorized", "code": errors.BASKET_AUTH_ERROR}

    def test_bad_signature_returns_generic_401(self):
        resp = self._post({"form_id": "enterprise-contact", "data": {}}, sign_body=b"different-body")
        assert resp.status_code == 401
        assert resp.json() == {"status": "error", "detail": "unauthorized", "code": errors.BASKET_AUTH_ERROR}

    def test_stale_signature_returns_generic_401(self, settings):
        stale_ts = int(time.time()) - settings.INTAKE_SIGNATURE_TOLERANCE_SECONDS - 1
        resp = self._post({"form_id": "enterprise-contact", "data": {}}, sign_ts=stale_ts)
        assert resp.status_code == 401

    def test_form_id_outside_allowed_list_returns_403(self):
        resp = self._post({"form_id": "not-allowed", "data": {}})
        assert resp.status_code == 403
        assert resp.json()["detail"] == "form_id not permitted for this api user"

    def test_unknown_form_id_returns_404(self):
        self.api_user.allowed_form_ids = []
        self.api_user.save()
        resp = self._post({"form_id": "does-not-exist", "data": {}})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "unknown or inactive form_id"

    def test_inactive_route_returns_404(self):
        self.route.active = False
        self.route.save()
        resp = self.valid_request()
        assert resp.status_code == 404

    def test_inactive_destinations_are_not_enqueued(self, mocker):
        mock_delay = mocker.patch("basket.contact.intake_api.deliver_to_gsheet.delay")
        FormDestination.objects.filter(route=self.route).update(active=False)
        resp = self.valid_request()
        assert resp.status_code == 200
        mock_delay.assert_not_called()

    def test_submission_is_recorded_with_raw_payload(self, mocker):
        mocker.patch("basket.contact.intake_api.deliver_to_gsheet.delay")
        self.valid_request()
        submission = FormSubmission.objects.get(route=self.route)
        assert submission.status == "queued"
        assert submission.payload["data"]["email"] == "a@b.com"

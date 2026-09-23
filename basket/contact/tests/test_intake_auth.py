import time

from django.test import RequestFactory

import pytest

from basket.contact.intake_auth import IntakeAuth, IntakeUnauthorized
from basket.contact.tests.conftest import sign_intake_body as _sign
from basket.news.models import APIUser

BODY = b'{"form_id": "enterprise-contact", "data": {"email": "a@b.com"}}'


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def api_user(db):
    return APIUser.objects.create(name="test-partner", enabled=True)


def _request(rf, body, ts, sig):
    return rf.post(
        "/api/v1/intake/",
        data=body,
        content_type="application/json",
        HTTP_X_BASKET_SIGNATURE=f"t={ts},v1={sig}",
    )


@pytest.mark.django_db
class TestIntakeAuth:
    def test_valid_key_and_signature_authenticates(self, rf, api_user):
        ts, sig = _sign(api_user, BODY)
        request = _request(rf, BODY, ts, sig)
        assert IntakeAuth().authenticate(request, api_user.api_key) == api_user

    def test_unknown_api_key_rejected(self, rf, api_user):
        ts, sig = _sign(api_user, BODY)
        request = _request(rf, BODY, ts, sig)
        with pytest.raises(IntakeUnauthorized):
            IntakeAuth().authenticate(request, "not-a-real-key")

    def test_disabled_api_key_rejected(self, rf, api_user):
        api_user.enabled = False
        api_user.save()
        ts, sig = _sign(api_user, BODY)
        request = _request(rf, BODY, ts, sig)
        with pytest.raises(IntakeUnauthorized):
            IntakeAuth().authenticate(request, api_user.api_key)

    def test_bad_signature_rejected(self, rf, api_user):
        ts, _ = _sign(api_user, BODY)
        request = _request(rf, BODY, ts, "0" * 64)
        with pytest.raises(IntakeUnauthorized):
            IntakeAuth().authenticate(request, api_user.api_key)

    def test_stale_timestamp_rejected(self, rf, api_user, settings):
        stale_ts = int(time.time()) - settings.INTAKE_SIGNATURE_TOLERANCE_SECONDS - 1
        ts, sig = _sign(api_user, BODY, timestamp=stale_ts)
        request = _request(rf, BODY, ts, sig)
        with pytest.raises(IntakeUnauthorized):
            IntakeAuth().authenticate(request, api_user.api_key)

    def test_missing_signature_header_rejected(self, rf, api_user):
        request = rf.post("/api/v1/intake/", data=BODY, content_type="application/json")
        with pytest.raises(IntakeUnauthorized):
            IntakeAuth().authenticate(request, api_user.api_key)

    def test_tampered_body_rejected(self, rf, api_user):
        # Signature computed over one body, sent with a different one.
        ts, sig = _sign(api_user, BODY)
        request = _request(rf, b'{"form_id": "other", "data": {}}', ts, sig)
        with pytest.raises(IntakeUnauthorized):
            IntakeAuth().authenticate(request, api_user.api_key)

    def test_empty_hmac_secret_rejected(self, rf, api_user):
        # Not reachable via the admin anymore (blank=True was removed), but fail closed
        # for any row that still has one rather than signing with a guessable empty key.
        api_user.hmac_secret = ""
        api_user.save()
        ts, sig = _sign(api_user, BODY)
        request = _request(rf, BODY, ts, sig)
        with pytest.raises(IntakeUnauthorized):
            IntakeAuth().authenticate(request, api_user.api_key)

    def test_replayed_signature_rejected(self, rf, api_user):
        ts, sig = _sign(api_user, BODY)
        first = _request(rf, BODY, ts, sig)
        assert IntakeAuth().authenticate(first, api_user.api_key) == api_user

        second = _request(rf, BODY, ts, sig)
        with pytest.raises(IntakeUnauthorized):
            IntakeAuth().authenticate(second, api_user.api_key)

    def test_successful_auth_updates_last_accessed(self, rf, api_user):
        assert api_user.last_accessed is None
        ts, sig = _sign(api_user, BODY)
        request = _request(rf, BODY, ts, sig)
        IntakeAuth().authenticate(request, api_user.api_key)
        api_user.refresh_from_db()
        assert api_user.last_accessed is not None

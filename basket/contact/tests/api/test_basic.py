from unittest.mock import patch

from django.urls import reverse

import pytest

from basket.news.tests.api import _TestAPIBase


@pytest.mark.django_db
class TestContactBasicAPI(_TestAPIBase):
    @pytest.fixture(autouse=True)
    def disable_ratelimit(self, settings):
        settings.RATELIMIT_ENABLE = False

    @pytest.fixture(autouse=True)
    def mock_task(self):
        with patch("basket.contact.tasks.submit_contact.delay") as mock_delay:
            self._mock_delay = mock_delay
            yield mock_delay

    def setup_method(self, method):
        super().setup_method(method)
        self.method = "POST"
        self.test_maintenance_mode = False
        self.url = reverse("api.v1:contact.basic")

    def valid_payload(self):
        return {
            "first_name": "Jane",
            "last_name": "Doe",
            "company": "Acme Corp",
            "job_title": "Engineer",
            "business_email": "jane@acme.com",
            "country": "Canada",
            "accepted_terms": "on",
            "opt_in": "on",
            "lead_source": "basic-default-lead-submission",
            "cta": "contact-us",
        }

    def valid_request(self):
        return self.client.post(self.url, data=self.valid_payload(), content_type="application/json")

    def post(self, **overrides):
        extra = {k: overrides.pop(k) for k in list(overrides) if k.isupper()}
        payload = self.valid_payload()
        payload.update(overrides)
        return self.client.post(self.url, data=payload, content_type="application/json", **extra)

    def test_valid_submission_returns_200(self):
        resp = self.valid_request()
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_task_enqueued_with_contact_data(self):
        self.valid_request()
        self._mock_delay.assert_called_once_with(self.valid_payload())

    def test_honeypot_silently_drops_submission(self):
        resp = self.post(office_fax="anything")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        self._mock_delay.assert_not_called()

    def test_extra_fields_are_ignored(self):
        resp = self.post(message="hi", error="error")
        assert resp.status_code == 200
        self._mock_delay.assert_called_once_with(self.valid_payload())

    @pytest.mark.parametrize(
        "overrides",
        [
            {"first_name": ""},
            {"last_name": ""},
            {"company": ""},
            {"job_title": ""},
            {"country": ""},
            {"accepted_terms": ""},
            {"first_name": "Jane2"},
            {"last_name": "Doe!"},
            {"first_name": "https://example.com"},
            {"company": "acme.com"},
            {"business_email": "not-an-email"},
            {"business_email": "jane@mailinator.com"},
            {"first_name": "a" * 101},
            {"last_name": "a" * 101},
            {"company": "a" * 201},
            {"job_title": "a" * 151},
            {"country": "a" * 256},
        ],
    )
    def test_rejects_invalid_payload(self, overrides):
        assert self.post(**overrides).status_code == 422

    @pytest.mark.parametrize("field", ["first_name", "last_name", "company", "job_title", "business_email", "country", "accepted_terms"])
    def test_rejects_missing_required_field(self, field):
        payload = self.valid_payload()
        del payload[field]
        resp = self.client.post(self.url, data=payload, content_type="application/json")
        assert resp.status_code == 422

    def test_opt_in_is_optional(self):
        payload = self.valid_payload()
        del payload["opt_in"]
        resp = self.client.post(self.url, data=payload, content_type="application/json")
        assert resp.status_code == 200
        self._mock_delay.assert_called_once_with(payload | {"opt_in": "False"})

    def test_optional_fields_default_to_empty(self):
        optional = ["lead_source", "cta"]
        payload = self.valid_payload()
        for field in optional:
            del payload[field]
        resp = self.client.post(self.url, data=payload, content_type="application/json")
        assert resp.status_code == 200
        self._mock_delay.assert_called_once_with(payload | dict.fromkeys(optional, ""))

    def test_allows_unicode_and_accepted_symbols_in_names(self):
        resp = self.post(first_name="Ëve-Ånne", last_name="O'Conner Smith")
        assert resp.status_code == 200

    def test_rate_limited_by_ip_returns_429(self, settings):
        settings.RATELIMIT_ENABLE = True
        settings.CONTACT_ENTERPRISE_RATE_LIMIT = "1/h"
        assert self.post(business_email="one@acme.com").status_code == 200
        assert self.post(business_email="two@acme.com").status_code == 429

    def test_rate_limited_by_email_returns_429(self, settings):
        settings.RATELIMIT_ENABLE = True
        settings.CONTACT_ENTERPRISE_RATE_LIMIT = "1/h"
        assert self.post(REMOTE_ADDR="10.0.0.1").status_code == 200
        assert self.post(REMOTE_ADDR="10.0.0.2").status_code == 429

    def test_enterprise_rate_limit_is_separate(self, settings):
        # Exhausting the basic limit must not block the enterprise form (different group).
        settings.RATELIMIT_ENABLE = True
        settings.CONTACT_ENTERPRISE_RATE_LIMIT = "1/h"
        assert self.post().status_code == 200
        assert self.post().status_code == 429

        enterprise = self.valid_payload() | {
            "firefox_use_stage": "piloting",
            "deployment_size": "1",
            "support_needs": "deployment_config",
            "timeline": "immediately",
        }
        resp = self.client.post(reverse("api.v1:contact.enterprise"), data=enterprise, content_type="application/json")
        assert resp.status_code == 200

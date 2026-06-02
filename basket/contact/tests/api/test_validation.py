from unittest.mock import MagicMock, patch

from django.urls import reverse

import pytest

from basket.news.tests.api import _TestAPIBase


@pytest.mark.django_db
class TestContactEnterpriseAPI(_TestAPIBase):
    @pytest.fixture(autouse=True)
    def disable_ratelimit(self, settings):
        settings.RATELIMIT_ENABLE = False

    @pytest.fixture(autouse=True)
    def mock_sink(self):
        self._mock_sink = MagicMock()
        with patch("basket.contact.api.get_contact_sink", return_value=self._mock_sink):
            yield self._mock_sink

    def setup_method(self, method):
        super().setup_method(method)
        self.method = "POST"
        self.test_maintenance_mode = False
        self.url = reverse("api.v1:contact.enterprise")

    def valid_payload(self):
        return {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane@acme.com",
            "company": "Acme Corp",
            "job_title": "Engineer",
            "message": "I'd like to learn more about your enterprise plan.",
            "website": ""
        }

    def valid_request(self):
        return self.client.post(
            self.url,
            data=self.valid_payload(),
            content_type="application/json",
        )

    # --- 200 happy path ---

    def test_valid_submission_returns_200(self):
        resp = self.valid_request()
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_success_if_website_exists(self):
        payload = self.valid_payload()
        payload["website"] = "www.firefox.com"
        resp = self.client.post(self.url, data=payload, content_type="application/json")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    # --- URL injection ---

    def test_rejects_url_in_first_name(self):
        payload = self.valid_payload()
        payload["first_name"] = "http://evil.com"
        resp = self.client.post(self.url, data=payload, content_type="application/json")
        assert resp.status_code == 422

    def test_rejects_url_in_last_name(self):
        payload = self.valid_payload()
        payload["last_name"] = "www.spam.com"
        resp = self.client.post(self.url, data=payload, content_type="application/json")
        assert resp.status_code == 422

    def test_rejects_url_in_company(self):
        payload = self.valid_payload()
        payload["company"] = "https://evil.com"
        resp = self.client.post(self.url, data=payload, content_type="application/json")
        assert resp.status_code == 422

    def test_rejects_bare_tld_in_first_name(self):
        payload = self.valid_payload()
        payload["first_name"] = "spam.net"
        resp = self.client.post(self.url, data=payload, content_type="application/json")
        assert resp.status_code == 422

    # --- Length caps ---

    def test_rejects_first_name_over_100_chars(self):
        payload = self.valid_payload()
        payload["first_name"] = "a" * 101
        resp = self.client.post(self.url, data=payload, content_type="application/json")
        assert resp.status_code == 422

    def test_rejects_last_name_over_100_chars(self):
        payload = self.valid_payload()
        payload["last_name"] = "a" * 101
        resp = self.client.post(self.url, data=payload, content_type="application/json")
        assert resp.status_code == 422

    def test_rejects_company_over_200_chars(self):
        payload = self.valid_payload()
        payload["company"] = "a" * 201
        resp = self.client.post(self.url, data=payload, content_type="application/json")
        assert resp.status_code == 422

    def test_rejects_job_title_over_150_chars(self):
        payload = self.valid_payload()
        payload["job_title"] = "a" * 151
        resp = self.client.post(self.url, data=payload, content_type="application/json")
        assert resp.status_code == 422

    def test_rejects_message_over_2000_chars(self):
        payload = self.valid_payload()
        payload["message"] = "a" * 2001
        resp = self.client.post(self.url, data=payload, content_type="application/json")
        assert resp.status_code == 422

    # --- Missing fields ---

    def test_rejects_missing_first_name(self):
        payload = self.valid_payload()
        del payload["first_name"]
        resp = self.client.post(self.url, data=payload, content_type="application/json")
        assert resp.status_code == 422

    def test_rejects_missing_last_name(self):
        payload = self.valid_payload()
        del payload["last_name"]
        resp = self.client.post(self.url, data=payload, content_type="application/json")
        assert resp.status_code == 422

    def test_rejects_empty_body(self):
        resp = self.client.post(self.url, data={}, content_type="application/json")
        assert resp.status_code == 422

    # --- Invalid fields ---

    def test_if_message_contains_multiple_urls(self):
        payload = self.valid_payload()
        payload["message"] = "www.firefox.com www.firefox.org www.firefox.net"
        resp = self.client.post(self.url, data=payload, content_type="application/json")
        assert resp.status_code == 422
        assert resp.json()["status"] == "error"

    def test_rejects_first_name_with_numbers(self):
        payload = self.valid_payload()
        payload["first_name"] = "Jan3"
        resp = self.client.post(self.url, data=payload, content_type="application/json")
        assert resp.status_code == 422
        assert resp.json()["status"] == "error"

    def test_rejects_last_name_with_numbers(self):
        payload = self.valid_payload()
        payload["last_name"] = "Jan3"
        resp = self.client.post(self.url, data=payload, content_type="application/json")
        assert resp.status_code == 422
        assert resp.json()["status"] == "error"

    def test_rejects_first_name_with_symbols(self):
        payload = self.valid_payload()
        payload["first_name"] = "J@ne"
        resp = self.client.post(self.url, data=payload, content_type="application/json")
        assert resp.status_code == 422
        assert resp.json()["status"] == "error"

    def test_rejects_last_name_with_symbols(self):
        payload = self.valid_payload()
        payload["last_name"] = "J@ne"
        resp = self.client.post(self.url, data=payload, content_type="application/json")
        assert resp.status_code == 422
        assert resp.json()["status"] == "error"

    def test_rejects_spam_domains(self):
        payload = self.valid_payload()
        payload["email"] = "jane@10minutemail.com"
        resp = self.client.post(self.url, data=payload, content_type="application/json")
        assert resp.status_code == 422
        assert resp.json()["status"] == "error"

    # --- Allowed fields ---

    def test_allows_first_name_unicode(self):
        payload = self.valid_payload()
        payload["first_name"] = "François"
        resp = self.client.post(self.url, data=payload, content_type="application/json")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_allows_last_name_unicode(self):
        payload = self.valid_payload()
        payload["last_name"] = "López"
        resp = self.client.post(self.url, data=payload, content_type="application/json")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_allows_first_name_accepted_symbols(self):
        payload = self.valid_payload()
        payload["first_name"] = "Jan'-e"
        resp = self.client.post(self.url, data=payload, content_type="application/json")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_allows_last_name_accepted_symbols(self):
        payload = self.valid_payload()
        payload["last_name"] = "Jan'-e"
        resp = self.client.post(self.url, data=payload, content_type="application/json")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    # --- Rate limiting ---

    def test_rate_limited_by_ip_returns_429(self):
        with patch("basket.contact.api.is_ratelimited", side_effect=[True]):
            resp = self.valid_request()
        assert resp.status_code == 429
        assert resp.json()["status"] == "error"

    def test_rate_limited_by_email_returns_429(self):
        with patch("basket.contact.api.is_ratelimited", side_effect=[False, True]):
            resp = self.valid_request()
        assert resp.status_code == 429
        assert resp.json()["status"] == "error"

    def test_not_rate_limited_returns_200(self):
        with patch("basket.contact.api.is_ratelimited", return_value=False):
            resp = self.valid_request()
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    # --- Backend failure ---

    def test_sink_submit_called_with_contact_data(self):
        self.valid_request()
        self._mock_sink.submit.assert_called_once()
        submitted = self._mock_sink.submit.call_args[0][0]
        assert submitted["email"] == "jane@acme.com"
        assert "website" not in submitted

    def test_backend_failure_returns_500(self):
        self._mock_sink.submit.side_effect = Exception("sheets unavailable")
        self.client.raise_request_exception = False
        resp = self.valid_request()
        assert resp.status_code == 500


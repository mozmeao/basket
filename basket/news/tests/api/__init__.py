import json
from unittest.mock import patch

from django.test import Client
from django.urls import resolve

from requests import Response
from requests.exceptions import HTTPError

from basket import errors
from basket.news.backends.braze import BrazeNotConfigured
from basket.news.schemas import ErrorSchema
from basket.news.utils import MSG_MAINTENANCE_MODE


class _TestAPIBase:
    def setup_method(self, method):
        self.client = Client(headers={"Content-Type": "application/json"})
        self.method = "POST"  # Subclasses should override this if necessary.
        self.test_maintenance_mode = True  # Subclasses should override this if necessary.

    def validate_schema(self, data, schema):
        # This will raise an exception if the data doesn't validate against the schema.
        return schema.model_validate(data)

    def test_csrf_exempt(self):
        # Test the API is exempt from CSRF.
        # By default ninja makes all APIs exempt from CSRF. This can be overridden globally or per view.
        resolver = resolve(self.url)
        assert getattr(resolver.func, "csrf_exempt", None) is True

    def test_preflight(self):
        resp = self.client.options(
            self.url,
            content_type="application/json",
            headers={"origin": "https://example.com", "access-control-request-method": self.method},
        )
        assert resp.status_code == 200
        assert resp["Access-Control-Allow-Origin"] == "*"
        assert self.method in resp["Access-Control-Allow-Methods"]
        assert "content-type" in resp["Access-Control-Allow-Headers"]

    def test_maintenance_mode(self, settings):
        if self.test_maintenance_mode:
            settings.MAINTENANCE_MODE = True
            settings.MAINTENANCE_READ_ONLY = False
            # If the underlying view tries to get user data from CTMS.
            with patch("basket.news.utils.braze", spec_set=["get"]) as braze_mock:
                resp = self.valid_request()
                assert resp.status_code == 400
                data = resp.json()
                self.validate_schema(data, ErrorSchema)
                assert data["status"] == "error"
                assert data["code"] == errors.BASKET_MAINTENANCE_ERROR
                assert data["desc"] == MSG_MAINTENANCE_MODE
                braze_mock.get.assert_not_called()


class _TestAPIwBrazeBase(_TestAPIBase):
    def braze_error(self, status_code, detail, reason):
        """Return a Braze error response"""
        response = Response()
        response.status_code = status_code
        response._content = json.dumps({"detail": detail})
        if reason:
            response.reason = reason
        error = HTTPError()
        error.response = response
        return error

    # Note: Subclasses should defined a `self.valid_request` method for these the following tests.

    def test_braze_network_failure(self):
        # Test CTMS network failure returns a 400 error.
        with patch("basket.news.utils.braze", spec_set=["get"]) as braze_mock:
            braze_mock.get.side_effect = self.braze_error(500, "Network failure", "Server Error")
            resp = self.valid_request()
            assert resp.status_code == 400
            data = resp.json()
            self.validate_schema(data, ErrorSchema)
            assert data["status"] == "error"
            assert data["code"] == errors.BASKET_NETWORK_FAILURE
            assert data["desc"] == ""

    # 500 errors

    def test_braze_not_configured(self):
        # Test CTMS not configured returns a 500 error.
        with patch("basket.news.utils.braze", spec_set=["get"]) as braze_mock:
            braze_mock.get.side_effect = BrazeNotConfigured()
            resp = self.valid_request()
            assert resp.status_code == 500
            data = resp.json()
            self.validate_schema(data, ErrorSchema)
            assert data["status"] == "error"
            assert data["code"] == errors.BASKET_EMAIL_PROVIDER_AUTH_FAILURE
            assert data["desc"] == "Email service provider auth failure"

    def test_ctms_unauthorized(self):
        # Test CTMS unauthorized returns a 500 error.
        with patch("basket.news.utils.braze", spec_set=["get"]) as braze_mock:
            braze_mock.get.side_effect = self.braze_error(401, "Unauthorized", "Not authenticated")
            resp = self.valid_request()
            assert resp.status_code == 500
            data = resp.json()
            self.validate_schema(data, ErrorSchema)
            assert data["status"] == "error"
            assert data["code"] == errors.BASKET_EMAIL_PROVIDER_AUTH_FAILURE
            assert data["desc"] == "Email service provider auth failure"

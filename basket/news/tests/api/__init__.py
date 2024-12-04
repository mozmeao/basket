import json
from unittest.mock import patch

from django.urls import resolve

from requests import Response
from requests.exceptions import HTTPError

from basket import errors
from basket.news.backends.ctms import CTMSMultipleContactsError, CTMSNotConfigured
from basket.news.schemas import ErrorSchema
from basket.news.utils import MSG_MAINTENANCE_MODE


class _TestAPIBase:
    def validate_schema(self, data, schema):
        # This will raise an exception if the data doesn't validate against the schema.
        return schema.model_validate(data)

    def ctms_error(self, status_code, detail, reason):
        """Return a CTMS error response"""
        response = Response()
        response.status_code = status_code
        response._content = json.dumps({"detail": detail})
        if reason:
            response.reason = reason
        error = HTTPError()
        error.response = response
        return error

    def test_csrf_exempt(self):
        # Test the API is exempt from CSRF.
        # By default ninja makes all APIs exempt from CSRF. This can be overridden globally or per view.
        resolver = resolve(self.url)
        assert getattr(resolver.func, "csrf_exempt", None) is True

    # Note: Subclasses should defined a `self.valid_request` method for these the following tests.

    def test_ctms_network_failure(self, client):
        # Test CTMS network failure returns a 400 error.
        with patch("basket.news.utils.ctms", spec_set=["get"]) as mock_ctms:
            mock_ctms.get.side_effect = self.ctms_error(500, "Network failure", "Server Error")
            resp = self.valid_request(client)
            assert resp.status_code == 400
            data = resp.json()
            self.validate_schema(data, ErrorSchema)
            assert data["status"] == "error"
            assert data["code"] == errors.BASKET_NETWORK_FAILURE
            assert data["desc"] == ""

    def test_ctms_multiple_contacts(self, client):
        # Test CTMS multiple contacts returns a 400 error.
        with patch("basket.news.utils.ctms", spec_set=["get"]) as mock_ctms:
            mock_ctms.get.side_effect = CTMSMultipleContactsError(
                "token",
                self.token,
                [
                    {"email": {"email_id": "id_1", "basket_token": self.token}},
                    {"email": {"email_id": "id_2", "basket_token": self.token}},
                ],
            )
            resp = self.valid_request(client)
            assert resp.status_code == 400
            data = resp.json()
            self.validate_schema(data, ErrorSchema)
            assert data["status"] == "error"
            assert data["code"] == errors.BASKET_NETWORK_FAILURE
            assert data["desc"] == f"2 contacts returned for token='{self.token}' with email_ids ['id_1', 'id_2']"

    def test_maintenance_mode(self, client, settings):
        settings.MAINTENANCE_MODE = True
        settings.MAINTENANCE_READ_ONLY = False
        with patch("basket.news.utils.ctms", spec_set=["get"]) as mock_ctms:
            resp = self.valid_request(client)
            assert resp.status_code == 400
            data = resp.json()
            self.validate_schema(data, ErrorSchema)
            assert data["status"] == "error"
            assert data["code"] == errors.BASKET_MAINTENANCE_ERROR
            assert data["desc"] == MSG_MAINTENANCE_MODE
            mock_ctms.get.assert_not_called()

    # 500 errors

    def test_ctms_not_configured(self, client):
        # Test CTMS not configured returns a 500 error.
        with patch("basket.news.utils.ctms", spec_set=["get"]) as mock_ctms:
            mock_ctms.get.side_effect = CTMSNotConfigured()
            resp = self.valid_request(client)
            assert resp.status_code == 500
            data = resp.json()
            self.validate_schema(data, ErrorSchema)
            assert data["status"] == "error"
            assert data["code"] == errors.BASKET_EMAIL_PROVIDER_AUTH_FAILURE
            assert data["desc"] == "Email service provider auth failure"

    def test_ctms_unauthorized(self, client):
        # Test CTMS unauthorized returns a 500 error.
        with patch("basket.news.utils.ctms", spec_set=["get"]) as mock_ctms:
            mock_ctms.get.side_effect = self.ctms_error(401, "Unauthorized", "Not authenticated")
            resp = self.valid_request(client)
            assert resp.status_code == 500
            data = resp.json()
            self.validate_schema(data, ErrorSchema)
            assert data["status"] == "error"
            assert data["code"] == errors.BASKET_EMAIL_PROVIDER_AUTH_FAILURE
            assert data["desc"] == "Email service provider auth failure"

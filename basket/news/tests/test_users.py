import json
import uuid
from unittest.mock import patch

from django.http import HttpResponse
from django.test import TestCase
from django.urls import reverse

from requests import Response
from requests.exceptions import HTTPError

from basket import errors
from basket.news.backends.ctms import CTMSMultipleContactsError, CTMSNotConfigured
from basket.news.models import APIUser
from basket.news.utils import SET


class UserTest(TestCase):
    def setUp(self):
        self.auth = APIUser.objects.create(name="test")
        self.token = str(uuid.uuid4())
        self.url = reverse("user", kwargs={"token": self.token})

    @patch("basket.news.views.update_user_task")
    def test_user_set(self, update_user_task):
        """If request is POST, it should attempt to update the user's info."""
        update_user_task.return_value = HttpResponse()
        resp = self.client.post(self.url, data={"country": "CA"})
        update_user_task.assert_called_with_subset(
            resp.wsgi_request,
            SET,
            {"country": "CA", "token": self.token},
        )

    @patch("basket.news.utils.ctms", spec_set=["get"])
    def test_user(self, ctms_mock):
        ctms_mock.get.return_value = {
            "email": "hisdudeness@example.com",
        }
        resp = self.client.get(self.url)
        assert resp.status_code == 200
        assert resp.json() == {
            "email": "h*********s@e*****e.com",
            "status": "ok",
            "has_fxa": False,
        }

    @patch("basket.news.utils.ctms", spec_set=["get"])
    def test_user_with_api_key(self, ctms_mock):
        ctms_mock.get.return_value = {
            "email": "hisdudeness@example.com",
        }
        resp = self.client.get(self.url, data={"api-key": self.auth.api_key})
        assert resp.status_code == 200
        assert resp.json() == {
            "email": "hisdudeness@example.com",
            "status": "ok",
            "has_fxa": False,
        }

    @patch("basket.news.utils.ctms", spec_set=["get"])
    def test_user_with_fxa(self, ctms_mock):
        ctms_mock.get.return_value = {
            "email": "hisdudeness@example.com",
            "fxa_id": "the-dude-abides",
        }
        resp = self.client.get(self.url)
        assert resp.status_code == 200
        assert resp.json() == {
            "email": "h*********s@e*****e.com",
            "has_fxa": True,
            "status": "ok",
        }


class TestLookupUser(TestCase):
    """test for API lookup-user"""

    # Keep in mind that this API requires SSL. We make it look like an
    # SSL request by adding {'wsgi.url_scheme': 'https'} to the arguments
    # of the client.get

    def setUp(self):
        self.auth = APIUser.objects.create(name="test")
        self.user_data = {"status": "ok"}
        self.url = reverse("lookup_user")

    def get(self, params=None, **extra):
        params = params or {}
        return self.client.get(self.url, data=params, **extra)

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

    def test_no_parms(self):
        """Passing no parms is a 400 error"""
        rsp = self.get()
        self.assertEqual(400, rsp.status_code, rsp.content)

    def test_both_parms(self):
        """Passing both parms is a 400 error"""
        params = {
            "token": "dummy",
            "email": "dummy@example.com",
        }
        rsp = self.get(params=params)
        self.assertEqual(400, rsp.status_code, rsp.content)

    @patch("basket.news.utils.ctms", spec_set=["get"])
    def test_with_token(self, ctms_mock):
        """Passing a token gets back that user's data"""
        ctms_mock.get.return_value = {
            "token": "dummy",
            "email": "hisdudeness@example.com",
        }
        rsp = self.get(params={"token": "dummy"})
        assert rsp.status_code == 200
        assert rsp.json() == {
            "email": "h*********s@e*****e.com",
            "status": "ok",
            "token": "dummy",
            "has_fxa": False,
        }
        ctms_mock.get.assert_called_once_with(
            email=None,
            fxa_id=None,
            token="dummy",
        )

    @patch("basket.news.utils.ctms", spec_set=["get"])
    def test_with_token_authorized(self, ctms_mock):
        """Passing a token gets back that user's data"""
        ctms_mock.get.return_value = {
            "token": "dummy",
            "email": "hisdudeness@example.com",
        }
        rsp = self.get(params={"token": "dummy", "api-key": self.auth.api_key})
        assert rsp.status_code == 200
        assert rsp.json() == {
            "email": "hisdudeness@example.com",
            "status": "ok",
            "token": "dummy",
            "has_fxa": False,
        }
        ctms_mock.get.assert_called_once_with(
            email=None,
            fxa_id=None,
            token="dummy",
        )

    @patch("basket.news.utils.ctms", spec_set=["get"])
    def test_get_fxa_status(self, ctms_mock):
        """Should return FxA status"""
        ctms_mock.get.return_value = {
            "email": "hisdudeness@example.com",
            "fxa_id": "the-dude-abides",
        }
        rsp = self.get(params={"token": "dummy"})
        assert rsp.status_code == 200
        assert rsp.json() == {
            "email": "h*********s@e*****e.com",
            "has_fxa": True,
            "status": "ok",
        }

    @patch("basket.news.utils.ctms", spec_set=["get"])
    def test_get_fxa_status_false(self, ctms_mock):
        """Should return FxA status"""
        ctms_mock.get.return_value = {"email": "hisdudeness@example.com"}
        rsp = self.get(params={"token": "dummy"})
        assert rsp.status_code == 200
        assert rsp.json() == {
            "email": "h*********s@e*****e.com",
            "has_fxa": False,
            "status": "ok",
        }

    @patch("basket.news.utils.ctms", spec_set=["get"])
    def test_get_fxa_status_with_api_key(self, ctms_mock):
        """Passing email and valid api key param gets user's data"""
        ctms_mock.get.return_value = {
            "email": "hisdudeness@example.com",
            "fxa_id": "the-dude-abides",
        }
        params = {
            "email": "hisdudeness@example.com",
            "api-key": self.auth.api_key,
        }
        rsp = self.get(params)
        self.assertEqual(200, rsp.status_code, rsp.content)
        self.assertEqual(
            rsp.json(),
            {
                "email": "hisdudeness@example.com",
                "has_fxa": True,
                "status": "ok",
            },
        )

    @patch("basket.news.utils.ctms", spec_set=["get"])
    def test_ctms_user_not_found(self, ctms_mock):
        """If CTMS return no records, return is None"""
        ctms_mock.get.return_value = None
        rsp = self.get(params={"token": "dummy"})
        assert rsp.status_code == 404

    @patch("basket.news.utils.ctms", spec_set=["get"])
    def test_ctms_user_not_authenticated(self, ctms_mock):
        """If CTMS is not authenticated, an exception is raised"""
        ctms_mock.get.side_effect = self.ctms_error(
            401,
            "Unauthorized",
            "Not authenticated",
        )
        rsp = self.get(params={"token": "dummy"})
        assert rsp.status_code == 500
        assert rsp.json() == {
            "code": errors.BASKET_EMAIL_PROVIDER_AUTH_FAILURE,
            "desc": "Email service provider auth failure",
            "status": "error",
        }

    @patch("basket.news.utils.ctms", spec_set=["get"])
    def test_ctms_user_not_configured(self, ctms_mock):
        """If CTMS was not configured, an exception is raised"""
        ctms_mock.get.side_effect = CTMSNotConfigured()
        rsp = self.get(params={"token": "dummy"})
        assert rsp.status_code == 500
        assert rsp.json() == {
            "code": errors.BASKET_EMAIL_PROVIDER_AUTH_FAILURE,
            "desc": "Email service provider auth failure",
            "status": "error",
        }

    @patch("basket.news.utils.ctms", spec_set=["get"])
    def test_ctms_user_runtime_error(self, ctms_mock):
        """If CTMS finds multiple contacts, an error is returned"""
        ctms_mock.get.side_effect = CTMSMultipleContactsError(
            "token",
            "dummy",
            [
                {"email": {"email_id": "id_1", "basket_token": "dummy"}},
                {"email": {"email_id": "id_2", "basket_token": "dummy"}},
            ],
        )
        rsp = self.get(params={"token": "dummy"})
        assert rsp.status_code == 400
        assert rsp.json() == {
            "status": "error",
            "code": errors.BASKET_NETWORK_FAILURE,
            "desc": "2 contacts returned for token='dummy' with email_ids ['id_1', 'id_2']",
        }

    @patch("basket.news.utils.ctms", spec_set=["get"])
    def test_ctms_user_server_error(self, ctms_mock):
        """If CTMS has a network failure, an error is returned"""
        ctms_mock.get.side_effect = self.ctms_error(
            500,
            "CTMS is rebooting...",
            "Server Error",
        )
        rsp = self.get(params={"token": "dummy"})
        assert rsp.status_code == 400
        assert rsp.json() == {
            "status": "error",
            "code": errors.BASKET_NETWORK_FAILURE,
            "desc": "",
        }

    def test_with_email_no_api_key(self):
        """Passing email without api key is a 401"""
        params = {
            "email": "mail@example.com",
        }
        rsp = self.get(params)
        self.assertEqual(401, rsp.status_code, rsp.content)

    def test_with_email_disabled_auth(self):
        """Passing email with a disabled api key is a 401"""
        self.auth.enabled = False
        self.auth.save()
        params = {
            "email": "mail@example.com",
            "api-key": self.auth.api_key,
        }
        rsp = self.get(params)
        self.assertEqual(401, rsp.status_code, rsp.content)

    def test_with_email_bad_auth(self):
        """Passing email with bad api key is a 401"""
        params = {
            "email": "mail@example.com",
            "api-key": "BAD KEY",
        }
        rsp = self.get(params)
        self.assertEqual(401, rsp.status_code, rsp.content)

    @patch("basket.news.views.get_user_data")
    def test_with_email_and_auth_parm(self, get_user_data):
        """Passing email and valid api key parm gets user's data"""
        params = {
            "email": "mail@example.com",
            "api-key": self.auth.api_key,
        }
        get_user_data.return_value = self.user_data
        rsp = self.get(params)
        self.assertEqual(200, rsp.status_code, rsp.content)
        self.assertEqual(self.user_data, json.loads(rsp.content))

    @patch("basket.news.views.get_user_data")
    def test_with_email_and_auth_header(self, get_user_data):
        """Passing email and valid api key header gets user's data"""
        params = {
            "email": "mail@example.com",
        }
        get_user_data.return_value = self.user_data
        rsp = self.get(params, HTTP_X_API_KEY=self.auth.api_key)
        self.assertEqual(200, rsp.status_code, rsp.content)
        self.assertEqual(self.user_data, json.loads(rsp.content))

    @patch("basket.news.views.get_user_data")
    def test_no_user(self, get_user_data):
        """If no such user, returns 404"""
        get_user_data.return_value = None
        params = {
            "email": "mail@example.com",
            "api-key": self.auth.api_key,
        }
        rsp = self.get(params)
        self.assertEqual(404, rsp.status_code, rsp.content)

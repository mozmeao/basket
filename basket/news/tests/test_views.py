# -*- coding: utf8 -*-

import json

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from django.test import override_settings
from django.test.client import RequestFactory, Client
from django.urls import reverse

from basket import errors
from email_validator import EmailSyntaxError
from mock import Mock, patch, ANY

from basket.news import models, views, utils
from basket.news.newsletters import newsletter_languages, newsletter_fields
from basket.news.tasks import SUBSCRIBE
from basket.news.utils import email_block_list_cache


none_mock = Mock(return_value=None)


@patch.object(views, "update_user_meta")
class UpdateUserMetaTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def test_invalid_data(self, uum_mock):
        req = self.rf.post("/", {"country": "dude"})
        resp = views.user_meta(req, "the-dudes-token-man")
        assert resp.status_code == 400
        uum_mock.delay.assert_not_called()

    def test_valid_uppercase_country(self, uum_mock):
        req = self.rf.post("/", {"country": "GB"})
        resp = views.user_meta(req, "the-dudes-token-man")
        assert resp.status_code == 200
        uum_mock.delay.assert_called_with(
            "the-dudes-token-man", {"country": "gb", "_set_subscriber": False},
        )

    def test_only_send_given_values(self, uum_mock):
        req = self.rf.post("/", {"first_name": "The", "last_name": "Dude"})
        resp = views.user_meta(req, "the-dudes-token-man")
        assert resp.status_code == 200
        uum_mock.delay.assert_called_with(
            "the-dudes-token-man",
            {"first_name": "The", "last_name": "Dude", "_set_subscriber": False},
        )


class TestIsToken(TestCase):
    def test_invalid_tokens(self):
        self.assertFalse(views.is_token("the dude"))
        self.assertFalse(views.is_token("abcdef-1234"))
        self.assertFalse(views.is_token("abcdef-abcdef-abcdef-deadbeef_123456"))

    def test_valid_tokens(self):
        self.assertTrue(views.is_token("abcdef-abcdef-abcdef-deadbeef-123456"))
        self.assertTrue(views.is_token(utils.generate_token()))


class GetInvolvedTests(TestCase):
    def setUp(self):
        self.interest = models.Interest.objects.create(
            title="Bowling", interest_id="bowling",
        )
        self.rf = RequestFactory()
        self.base_data = {
            "email": "dude@example.com",
            "lang": "en",
            "country": "us",
            "name": "The Dude",
            "interest_id": "bowling",
            "format": "T",
        }

        patcher = patch("basket.news.views.process_email")
        self.addCleanup(patcher.stop)
        self.process_email = patcher.start()

        patcher = patch("basket.news.views.update_get_involved")
        self.addCleanup(patcher.stop)
        self.update_get_involved = patcher.start()

    def tearDown(self):
        email_block_list_cache.clear()

    def _request(self, data):
        req = self.rf.post("/", data)
        resp = views.get_involved(req)
        return json.loads(resp.content)

    def test_successful_submission(self):
        self.process_email.return_value = self.base_data["email"]
        resp = self._request(self.base_data)
        self.process_email.assert_called_with(self.base_data["email"])
        self.assertEqual(resp["status"], "ok", resp)
        self.update_get_involved.delay.assert_called_with(
            "bowling",
            "en",
            "The Dude",
            "dude@example.com",
            "us",
            "T",
            False,
            None,
            None,
        )

    @patch("basket.news.utils.get_email_block_list")
    def test_blocked_email(self, get_email_block_mock):
        get_email_block_mock.return_value = ["example.com"]
        resp = self._request(self.base_data)
        self.assertEqual(resp["status"], "ok", resp)
        self.assertFalse(self.update_get_involved.delay.called)

    def test_requires_valid_interest(self):
        """Should only submit successfully with a valid interest_id."""
        self.base_data["interest_id"] = "takin-it-easy"
        resp = self._request(self.base_data)
        self.assertEqual(resp["status"], "error", resp)
        self.assertEqual(resp["desc"], "invalid interest_id", resp)
        self.assertFalse(self.update_get_involved.called)

        del self.base_data["interest_id"]
        resp = self._request(self.base_data)
        self.assertEqual(resp["status"], "error", resp)
        self.assertEqual(resp["desc"], "interest_id is required", resp)
        self.assertFalse(self.update_get_involved.called)

    def test_requires_valid_email(self):
        """Should only submit successfully with a valid email."""
        self.process_email.return_value = None
        resp = self._request(self.base_data)
        self.assertEqual(resp["status"], "error", resp)
        self.assertEqual(resp["code"], errors.BASKET_INVALID_EMAIL, resp)
        self.process_email.assert_called_with(self.base_data["email"])
        self.assertFalse(self.update_get_involved.called)

        del self.base_data["email"]
        resp = self._request(self.base_data)
        self.assertEqual(resp["status"], "error", resp)
        self.assertEqual(resp["desc"], "email is required", resp)
        self.assertFalse(self.update_get_involved.called)

    def test_requires_valid_lang(self):
        """Should only submit successfully with a valid lang."""
        self.base_data["lang"] = "this is not a lang"
        resp = self._request(self.base_data)
        self.assertEqual(resp["status"], "error", resp)
        self.assertEqual(resp["desc"], "invalid language", resp)
        self.assertFalse(self.update_get_involved.called)

        del self.base_data["lang"]
        resp = self._request(self.base_data)
        self.assertEqual(resp["status"], "error", resp)
        self.assertEqual(resp["desc"], "lang is required", resp)
        self.assertFalse(self.update_get_involved.called)

    def test_requires_name(self):
        """Should only submit successfully with a name provided."""
        del self.base_data["name"]
        resp = self._request(self.base_data)
        self.assertEqual(resp["status"], "error", resp)
        self.assertEqual(resp["desc"], "name is required", resp)
        self.assertFalse(self.update_get_involved.called)

    def test_requires_country(self):
        """Should only submit successfully with a country provided."""
        del self.base_data["country"]
        resp = self._request(self.base_data)
        self.assertEqual(resp["status"], "error", resp)
        self.assertEqual(resp["desc"], "country is required", resp)
        self.assertFalse(self.update_get_involved.called)

    def test_optional_parameters(self):
        """Should pass through optional parameters."""
        self.base_data.update(
            {
                "subscribe": "ok",
                "message": "I like bowling",
                "source_url": "https://arewebowlingyet.com/",
            },
        )
        self.process_email.return_value = self.base_data["email"]

        resp = self._request(self.base_data)
        self.assertEqual(resp["status"], "ok", resp)
        self.update_get_involved.delay.assert_called_with(
            "bowling",
            "en",
            "The Dude",
            "dude@example.com",
            "us",
            "T",
            "ok",
            "I like bowling",
            "https://arewebowlingyet.com/",
        )


@patch("basket.news.views.update_user_task")
class FxOSMalformedPOSTTest(TestCase):
    """Bug 962225"""

    def setUp(self):
        self.rf = RequestFactory()

    def test_deals_with_broken_post_data(self, update_user_mock):
        """Should be able to parse data from the raw request body.

        FxOS sends POST requests with the wrong mime-type, so request.POST is never
        filled out. We should parse the raw request body to get the data until this
        is fixed in FxOS in bug 949170.
        """
        req = self.rf.generic(
            "POST",
            "/news/subscribe/",
            data="email=dude+abides@example.com&newsletters=firefox-os",
            content_type="text/plain; charset=UTF-8",
        )
        self.assertFalse(bool(req.POST))
        views.subscribe(req)
        update_user_mock.assert_called_with(
            req,
            views.SUBSCRIBE,
            data={"email": "dude+abides@example.com", "newsletters": "firefox-os"},
            optin=False,
            sync=False,
        )


class SubscribeEmailValidationTest(TestCase):
    email = "dude@example.com"
    data = {
        "email": email,
        "newsletters": "os",
    }
    view = "subscribe"

    def setUp(self):
        self.rf = RequestFactory()

    @patch("basket.news.views.process_email")
    def test_invalid_email(self, mock_validate):
        """Should return proper error for invalid email."""
        mock_validate.return_value = None
        view = getattr(views, self.view)
        resp = view(self.rf.post("/", self.data))
        resp_data = json.loads(resp.content)
        mock_validate.assert_called_with(self.email)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp_data["status"], "error")
        self.assertEqual(resp_data["code"], errors.BASKET_INVALID_EMAIL)

    @patch("basket.news.views.update_user_task")
    def test_non_ascii_email_fxos_malformed_post(self, update_user_mock):
        """Should be able to parse data from the raw request body including non-ascii chars."""
        req = self.rf.generic(
            "POST",
            "/news/subscribe/",
            data="email=dude@黒川.日本&newsletters=firefox-os",
            content_type="text/plain; charset=UTF-8",
        )
        views.subscribe(req)
        update_user_mock.assert_called_with(
            req,
            views.SUBSCRIBE,
            data={"email": "dude@xn--5rtw95l.xn--wgv71a", "newsletters": "firefox-os"},
            optin=False,
            sync=False,
        )

    @patch("basket.news.views.update_user_task")
    def test_non_ascii_email(self, update_user_mock):
        """Should be able to accept valid email including non-ascii chars."""
        req = self.rf.post(
            "/news/subscribe/",
            data={"email": "dude@黒川.日本", "newsletters": "firefox-os"},
        )
        views.subscribe(req)
        update_user_mock.assert_called_with(
            req,
            views.SUBSCRIBE,
            data={"email": "dude@xn--5rtw95l.xn--wgv71a", "newsletters": "firefox-os"},
            optin=False,
            sync=False,
        )

    @patch("basket.news.views.update_user_task")
    def test_empty_email_invalid(self, update_user_mock):
        """Should report an error for missing or empty value."""
        req = self.rf.post(
            "/news/subscribe/", data={"email": "", "newsletters": "firefox-os"},
        )
        resp = views.subscribe(req)
        resp_data = json.loads(resp.content)
        self.assertEqual(resp_data["status"], "error")
        self.assertEqual(resp_data["code"], errors.BASKET_INVALID_EMAIL)
        self.assertFalse(update_user_mock.called)

        # no email at all
        req = self.rf.post("/news/subscribe/", data={"newsletters": "firefox-os"})
        resp = views.subscribe(req)
        resp_data = json.loads(resp.content)
        self.assertEqual(resp_data["status"], "error")
        self.assertEqual(resp_data["code"], errors.BASKET_USAGE_ERROR)
        self.assertFalse(update_user_mock.called)


class RecoveryMessageEmailValidationTest(SubscribeEmailValidationTest):
    view = "send_recovery_message"


class ViewsPatcherMixin(object):
    def _patch_views(self, name):
        patcher = patch("basket.news.views." + name)
        setattr(self, name, patcher.start())
        self.addCleanup(patcher.stop)


@override_settings(DEBUG=True)
class SubscribeMainTests(ViewsPatcherMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        self._patch_views("upsert_user")
        self._patch_views("process_email")
        self._patch_views("email_is_blocked")
        models.Newsletter.objects.create(
            slug="slug",
            title="title",
            active=False,
            languages="en-US,fr",
            vendor_id="VENDOR1",
        )
        models.Newsletter.objects.create(slug="slug2", vendor_id="VENDOR2")
        models.Newsletter.objects.create(slug="slug3", vendor_id="VENDOR3")
        models.Newsletter.objects.create(
            slug="slug-private", vendor_id="VENDOR4", private=True,
        )

    def tearDown(self):
        cache.clear()
        email_block_list_cache.clear()

    def _request(self, *args, **kwargs):
        kwargs.setdefault("HTTP_X_REQUESTED_WITH", "XMLHttpRequest")
        return views.subscribe_main(self.factory.post("/", *args, **kwargs))

    def test_subscribe_success(self):
        self.process_email.return_value = "dude@example.com"
        self.email_is_blocked.return_value = False
        response = self._request(
            {"newsletters": "slug", "email": "dude@example.com", "privacy": "true"},
        )
        assert response.status_code == 200
        self.upsert_user.delay.assert_called_with(
            SUBSCRIBE,
            {
                "newsletters": ["slug"],
                "email": "dude@example.com",
                "privacy": True,
                "format": "H",
                "first_name": "",
                "last_name": "",
                "country": "",
                "source_url": "",
            },
            start_time=ANY,
        )

    def test_subscribe_success_non_ajax(self):
        self.process_email.return_value = "dude@example.com"
        self.email_is_blocked.return_value = False
        response = self._request(
            {"newsletters": "slug", "email": "dude@example.com", "privacy": "true"},
            HTTP_X_REQUESTED_WITH="",
        )
        assert response.status_code == 200
        self.upsert_user.delay.assert_called_with(
            SUBSCRIBE,
            {
                "newsletters": ["slug"],
                "email": "dude@example.com",
                "privacy": True,
                "format": "H",
                "first_name": "",
                "last_name": "",
                "country": "",
                "source_url": "",
            },
            start_time=ANY,
        )
        assert b"Thank you for subscribing" in response.content

    def test_privacy_required(self):
        self.process_email.return_value = "dude@example.com"
        self.email_is_blocked.return_value = False
        response = self._request({"newsletters": "slug", "email": "dude@example.com"})
        assert response.status_code == 400
        assert json.loads(response.content) == {
            "status": "error",
            "errors": ["privacy: This field is required."],
            "errors_by_field": {"privacy": ["This field is required."]},
        }

    def test_subscribe_error(self):
        self.process_email.return_value = "dude@example.com"
        self.email_is_blocked.return_value = False
        response = self._request({"email": "dude@example.com", "privacy": "true"})
        assert response.status_code == 400
        assert json.loads(response.content) == {
            "status": "error",
            "errors": ["newsletters: This field is required."],
            "errors_by_field": {"newsletters": ["This field is required."]},
        }

        response = self._request(
            {"newsletters": "walter", "email": "dude@example.com", "privacy": "true"},
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            "status": "error",
            "errors": [
                "newsletters: Select a valid choice. walter is not "
                "one of the available choices.",
            ],
            "errors_by_field": {
                "newsletters": [
                    "Select a valid choice. walter is not one of "
                    "the available choices.",
                ],
            },
        }

    def test_subscribe_error_non_ajax(self):
        self.process_email.return_value = "dude@example.com"
        self.email_is_blocked.return_value = False
        response = self._request(
            {"email": "dude@example.com", "privacy": "true"}, HTTP_X_REQUESTED_WITH="",
        )
        assert response.status_code == 400
        assert b"This field is required" in response.content

    def test_lang_via_accept_language(self):
        self.process_email.return_value = "dude@example.com"
        self.email_is_blocked.return_value = False
        response = self._request(
            {"newsletters": "slug", "email": "dude@example.com", "privacy": "true"},
            HTTP_ACCEPT_LANGUAGE="de,fr,en-US",
        )
        assert response.status_code == 200
        self.upsert_user.delay.assert_called_with(
            SUBSCRIBE,
            {
                "newsletters": ["slug"],
                "email": "dude@example.com",
                "privacy": True,
                "format": "H",
                "lang": "fr",  # because fr is in the newsletter
                "first_name": "",
                "last_name": "",
                "country": "",
                "source_url": "",
            },
            start_time=ANY,
        )

    def test_lang_instead_of_accept_language(self):
        # specifying a lang still overrides
        self.process_email.return_value = "dude@example.com"
        self.email_is_blocked.return_value = False
        response = self._request(
            {
                "newsletters": "slug",
                "email": "dude@example.com",
                "privacy": "true",
                "lang": "fr",
            },
            HTTP_ACCEPT_LANGUAGE="de,fr,en-US",
        )
        assert response.status_code == 200
        self.upsert_user.delay.assert_called_with(
            SUBSCRIBE,
            {
                "newsletters": ["slug"],
                "email": "dude@example.com",
                "privacy": True,
                "format": "H",
                "lang": "fr",
                "first_name": "",
                "last_name": "",
                "country": "",
                "source_url": "",
            },
            start_time=ANY,
        )

    def test_lang_default_if_unsupported(self):
        # specifying a lang still overrides
        self.process_email.return_value = "dude@example.com"
        self.email_is_blocked.return_value = False
        response = self._request(
            {
                "newsletters": "slug",
                "email": "dude@example.com",
                "privacy": "true",
                "lang": "es",
            },
        )
        assert response.status_code == 200
        self.upsert_user.delay.assert_called_with(
            SUBSCRIBE,
            {
                "newsletters": ["slug"],
                "email": "dude@example.com",
                "privacy": True,
                "format": "H",
                "lang": "en",
                "first_name": "",
                "last_name": "",
                "country": "",
                "source_url": "",
            },
            start_time=ANY,
        )

    def test_source_url_from_referrer(self):
        self.process_email.return_value = "dude@example.com"
        self.email_is_blocked.return_value = False
        response = self._request(
            {"newsletters": "slug", "email": "dude@example.com", "privacy": "true"},
            HTTP_REFERER="https://example.com/bowling",
        )
        assert response.status_code == 200
        self.upsert_user.delay.assert_called_with(
            SUBSCRIBE,
            {
                "newsletters": ["slug"],
                "email": "dude@example.com",
                "privacy": True,
                "format": "H",
                "first_name": "",
                "last_name": "",
                "country": "",
                "source_url": "https://example.com/bowling",
            },
            start_time=ANY,
        )

    def test_source_url_from_invalid_referrer(self):
        self.process_email.return_value = "dude@example.com"
        self.email_is_blocked.return_value = False
        response = self._request(
            {"newsletters": "slug", "email": "dude@example.com", "privacy": "true"},
            HTTP_REFERER='javascript:alert("dude!")',
        )
        assert response.status_code == 200
        self.upsert_user.delay.assert_called_with(
            SUBSCRIBE,
            {
                "newsletters": ["slug"],
                "email": "dude@example.com",
                "privacy": True,
                "format": "H",
                "first_name": "",
                "last_name": "",
                "country": "",
                "source_url": "",
            },
            start_time=ANY,
        )

    def test_source_url_overrides_referrer(self):
        self.process_email.return_value = "dude@example.com"
        self.email_is_blocked.return_value = False
        response = self._request(
            {
                "newsletters": "slug",
                "email": "dude@example.com",
                "privacy": "true",
                "source_url": "https://example.com/abiding",
            },
            HTTP_REFERER="https://example.com/bowling",
        )
        assert response.status_code == 200
        self.upsert_user.delay.assert_called_with(
            SUBSCRIBE,
            {
                "newsletters": ["slug"],
                "email": "dude@example.com",
                "privacy": True,
                "format": "H",
                "first_name": "",
                "last_name": "",
                "country": "",
                "source_url": "https://example.com/abiding",
            },
            start_time=ANY,
        )

    def test_multiple_newsletters(self):
        self.process_email.return_value = "dude@example.com"
        self.email_is_blocked.return_value = False
        response = self._request(
            {
                "newsletters": ["slug", "slug2, slug3"],
                "email": "dude@example.com",
                "privacy": "true",
                "first_name": "The",
                "last_name": "Dude",
            },
        )
        assert response.status_code == 200
        self.upsert_user.delay.assert_called_with(
            SUBSCRIBE,
            {
                "newsletters": ["slug", "slug2", "slug3"],
                "email": "dude@example.com",
                "privacy": True,
                "format": "H",
                "first_name": "The",
                "last_name": "Dude",
                "country": "",
                "source_url": "",
            },
            start_time=ANY,
        )

    def test_blocked_email(self):
        self.process_email.return_value = "dude@example.com"
        self.email_is_blocked.return_value = True
        response = self._request(
            {"newsletters": "slug", "email": "dude@example.com", "privacy": "true"},
        )
        assert response.status_code == 200
        self.upsert_user.delay.assert_not_called()


class SubscribeTests(ViewsPatcherMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        self._patch_views("update_user_task")
        self._patch_views("process_email")
        self._patch_views("is_authorized")

    def tearDown(self):
        cache.clear()
        email_block_list_cache.clear()

    def assert_response_error(self, response, status_code, basket_code):
        self.assertEqual(response.status_code, status_code)
        response_data = json.loads(response.content)
        self.assertEqual(response_data["code"], basket_code)

    def test_newsletters_missing(self):
        """If the newsletters param is missing, return a 400."""
        request = self.factory.post("/")
        response = views.subscribe(request)
        self.assert_response_error(response, 400, errors.BASKET_USAGE_ERROR)

    def test_optin_valid_api_key_required(self):
        """
        If optin is 'Y' but the API key isn't valid, disable optin.
        """
        request_data = {
            "newsletters": "asdf",
            "optin": "Y",
            "email": "dude@example.com",
        }
        update_data = request_data.copy()
        del update_data["optin"]
        self.process_email.return_value = update_data["email"]
        request = self.factory.post("/", request_data)
        self.is_authorized.return_value = False

        response = views.subscribe(request)
        self.assertEqual(response, self.update_user_task.return_value)
        self.update_user_task.assert_called_with(
            request, SUBSCRIBE, data=update_data, optin=False, sync=False,
        )

    def test_sync_invalid_api_key(self):
        """
        If sync is set to 'Y' and the request has an invalid API key,
        return a 401.
        """
        request = self.factory.post(
            "/", {"newsletters": "asdf", "sync": "Y", "email": "dude@example.com"},
        )
        self.is_authorized.return_value = False

        response = views.subscribe(request)
        self.assert_response_error(response, 401, errors.BASKET_AUTH_ERROR)
        self.is_authorized.assert_called_with(request, self.process_email.return_value)

    def test_email_validation_error(self):
        """
        If process_email returns None, return an
        invalid email response.
        """
        request_data = {"newsletters": "asdf", "email": "dude@example.com"}
        request = self.factory.post("/", request_data)
        self.process_email.return_value = None

        with patch(
            "basket.news.views.invalid_email_response",
        ) as invalid_email_response:
            response = views.subscribe(request)
            self.assertEqual(response, invalid_email_response.return_value)
            self.process_email.assert_called_with(request_data["email"])
            invalid_email_response.assert_called()

    @patch("basket.news.utils.get_email_block_list")
    def test_blocked_email(self, get_block_list_mock):
        """Test basic success case with no optin or sync."""
        get_block_list_mock.return_value = ["example.com"]
        request_data = {
            "newsletters": "news,lets",
            "optin": "N",
            "sync": "N",
            "email": "dude@example.com",
        }
        request = self.factory.post("/", request_data)

        response = views.subscribe(request)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.update_user_task.called)

    @patch("basket.news.views.update_user_task")
    def test_email_fxos_malformed_post_bad_data(self, update_user_mock):
        """Should be able to parse data from the raw request body even with bad data."""
        # example from real error with PII details changed
        self.process_email.return_value = "dude@example.com"
        req = self.factory.generic(
            "POST",
            "/news/subscribe/",
            data=b"newsletters=mozilla-foundation&"
            b"source_url=https%3A%2F%2Fadvocacy.mozilla.org%2Fencrypt"
            b"&lang=en&email=dude@example.com"
            b"&country=DE&first_name=Dude&Walter",
            content_type="text/plain; charset=UTF-8",
        )
        views.subscribe(req)
        update_user_mock.assert_called_with(
            req,
            views.SUBSCRIBE,
            data={
                "email": "dude@example.com",
                "newsletters": "mozilla-foundation",
                "source_url": "https%3A%2F%2Fadvocacy.mozilla.org%2Fencrypt",
                "lang": "en",
                "country": "DE",
                "first_name": "Dude",
            },
            optin=False,
            sync=False,
        )

    @patch("basket.news.views.update_user_task")
    def test_email_fxos_malformed_post(self, update_user_mock):
        """Should be able to parse data from the raw request body."""
        self.process_email.return_value = "dude@example.com"
        req = self.factory.generic(
            "POST",
            "/news/subscribe/",
            data="email=dude@example.com&newsletters=firefox-os",
            content_type="text/plain; charset=UTF-8",
        )
        views.subscribe(req)
        update_user_mock.assert_called_with(
            req,
            views.SUBSCRIBE,
            data={"email": "dude@example.com", "newsletters": "firefox-os"},
            optin=False,
            sync=False,
        )

    def test_no_source_url_referrer(self):
        """Test referrer used when no source_url."""
        request_data = {
            "newsletters": "news,lets",
            "optin": "N",
            "sync": "N",
            "email": "dude@example.com",
            "first_name": "The",
            "last_name": "Dude",
        }
        update_data = request_data.copy()
        del update_data["optin"]
        del update_data["sync"]
        update_data["source_url"] = "https://example.com/newsletter"
        self.process_email.return_value = update_data["email"]
        request = self.factory.post(
            "/", request_data, HTTP_REFERER=update_data["source_url"],
        )

        response = views.subscribe(request)

        self.assertEqual(response, self.update_user_task.return_value)
        self.process_email.assert_called_with(request_data["email"])
        self.update_user_task.assert_called_with(
            request, SUBSCRIBE, data=update_data, optin=False, sync=False,
        )

    def test_source_url_overrides_referrer(self):
        """Test source_url used when referrer also provided."""
        request_data = {
            "newsletters": "news,lets",
            "optin": "N",
            "sync": "N",
            "email": "dude@example.com",
            "first_name": "The",
            "last_name": "Dude",
            "source_url": "https://example.com/thedude",
        }
        update_data = request_data.copy()
        del update_data["optin"]
        del update_data["sync"]
        self.process_email.return_value = update_data["email"]
        request = self.factory.post(
            "/", request_data, HTTP_REFERER="https://example.com/donnie",
        )

        response = views.subscribe(request)

        self.assertEqual(response, self.update_user_task.return_value)
        self.process_email.assert_called_with(request_data["email"])
        self.update_user_task.assert_called_with(
            request, SUBSCRIBE, data=update_data, optin=False, sync=False,
        )

    def test_success(self):
        """Test basic success case with no optin or sync."""
        request_data = {
            "newsletters": "news,lets",
            "optin": "N",
            "sync": "N",
            "email": "dude@example.com",
            "first_name": "The",
            "last_name": "Dude",
        }
        update_data = request_data.copy()
        del update_data["optin"]
        del update_data["sync"]
        self.process_email.return_value = update_data["email"]
        request = self.factory.post("/", request_data)

        response = views.subscribe(request)

        self.assertEqual(response, self.update_user_task.return_value)
        self.process_email.assert_called_with(request_data["email"])
        self.update_user_task.assert_called_with(
            request, SUBSCRIBE, data=update_data, optin=False, sync=False,
        )

    def test_success_sync_optin(self):
        """Test success case with optin and sync."""
        request_data = {
            "newsletters": "news,lets",
            "optin": "Y",
            "sync": "Y",
            "email": "dude@example.com",
        }
        update_data = request_data.copy()
        del update_data["optin"]
        del update_data["sync"]
        request = self.factory.post("/", request_data)
        self.is_authorized.return_value = True
        self.process_email.return_value = update_data["email"]

        response = views.subscribe(request)

        self.is_authorized.assert_called_with(request, self.process_email.return_value)
        self.assertEqual(response, self.update_user_task.return_value)
        self.process_email.assert_called_with("dude@example.com")
        self.update_user_task.assert_called_with(
            request, SUBSCRIBE, data=update_data, optin=True, sync=True,
        )

    def test_success_sync_optin_lowercase(self):
        """Test success case with optin and sync, using lowercase y."""
        request_data = {
            "newsletters": "news,lets",
            "optin": "y",
            "sync": "y",
            "email": "dude@example.com",
        }
        update_data = request_data.copy()
        del update_data["optin"]
        del update_data["sync"]
        request = self.factory.post("/", request_data)
        self.process_email.return_value = update_data["email"]
        self.is_authorized.return_value = True
        response = views.subscribe(request)
        self.is_authorized.assert_called_with(request, self.process_email.return_value)

        self.assertEqual(response, self.update_user_task.return_value)
        self.process_email.assert_called_with("dude@example.com")
        self.update_user_task.assert_called_with(
            request, SUBSCRIBE, data=update_data, optin=True, sync=True,
        )


class TestRateLimitingFunctions(ViewsPatcherMixin, TestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def test_ip_rate_limit_key(self):
        req = self.rf.get(
            "/", HTTP_X_CLUSTER_CLIENT_IP="1.1.1.1", REMOTE_ADDR="2.2.2.2",
        )
        self.assertEqual(views.ip_rate_limit_key(None, req), "1.1.1.1")

    def test_ip_rate_limit_key_fallback(self):
        req = self.rf.get("/", REMOTE_ADDR="2.2.2.2")
        self.assertEqual(views.ip_rate_limit_key(None, req), "2.2.2.2")

    def test_source_ip_rate_limit_key_no_header(self):
        req = self.rf.get("/")
        self.assertIsNone(views.source_ip_rate_limit_key(None, req))

    def test_source_ip_rate_limit_key(self):
        req = self.rf.get("/", HTTP_X_SOURCE_IP="2.2.2.2")
        self.assertEqual(views.source_ip_rate_limit_key(None, req), "2.2.2.2")

    def test_ip_rate_limit_rate(self):
        req = self.rf.get("/", HTTP_X_CLUSTER_CLIENT_IP="1.1.1.1")
        self.assertEqual(views.ip_rate_limit_rate(None, req), "40/m")

    def test_ip_rate_limit_rate_internal(self):
        req = self.rf.get("/", HTTP_X_CLUSTER_CLIENT_IP="10.1.1.1")
        self.assertEqual(views.ip_rate_limit_rate(None, req), "400/m")

    def test_source_ip_rate_limit_rate_no_header(self):
        req = self.rf.get("/")
        self.assertIsNone(views.source_ip_rate_limit_rate(None, req))

    def test_source_ip_rate_limit_rate(self):
        req = self.rf.get("/", HTTP_X_SOURCE_IP="2.2.2.2")
        self.assertEqual(views.source_ip_rate_limit_rate(None, req), "40/m")


class TestNewslettersAPI(TestCase):
    def setUp(self):
        self.url = reverse("newsletters_api")
        self.rf = RequestFactory()

    def test_newsletters_view(self):
        # We can fetch the newsletter data
        nl1 = models.Newsletter.objects.create(
            slug="slug",
            title="title",
            active=False,
            languages="en-US,fr",
            vendor_id="VENDOR1",
        )

        models.Newsletter.objects.create(slug="slug2", vendor_id="VENDOR2", indent=True)
        models.Newsletter.objects.create(
            slug="slug3", vendor_id="VENDOR3", private=True,
        )

        req = self.rf.get(self.url)
        resp = views.newsletters(req)
        data = json.loads(resp.content)
        newsletters = data["newsletters"]
        self.assertEqual(3, len(newsletters))
        # Find the 'slug' newsletter in the response
        obj = newsletters["slug"]

        self.assertTrue(newsletters["slug3"]["private"])
        self.assertTrue(newsletters["slug2"]["indent"])
        self.assertFalse(newsletters["slug3"]["indent"])
        self.assertEqual(nl1.title, obj["title"])
        self.assertEqual(nl1.active, obj["active"])
        for lang in ["en-US", "fr"]:
            self.assertIn(lang, obj["languages"])

    def test_strip_languages(self):
        # If someone edits Newsletter and puts whitespace in the languages
        # field, we strip it on save
        nl1 = models.Newsletter.objects.create(
            slug="slug",
            title="title",
            active=False,
            languages="en-US, fr, de ",
            vendor_id="VENDOR1",
        )
        nl1 = models.Newsletter.objects.get(id=nl1.id)
        self.assertEqual("en-US,fr,de", nl1.languages)

    def test_newsletter_languages(self):
        # newsletter_languages() returns the set of languages
        # of the newsletters
        # (Note that newsletter_languages() is not part of the external
        # API, but is used internally)
        models.Newsletter.objects.create(
            slug="slug",
            title="title",
            active=False,
            languages="en-US",
            vendor_id="VENDOR1",
        )
        models.Newsletter.objects.create(
            slug="slug2",
            title="title",
            active=False,
            languages="fr, de ",
            vendor_id="VENDOR2",
        )
        models.Newsletter.objects.create(
            slug="slug3",
            title="title",
            active=False,
            languages="en-US, fr",
            vendor_id="VENDOR3",
        )
        expect = set(["en-US", "fr", "de"])
        self.assertEqual(expect, newsletter_languages())

    def test_newsletters_cached(self):
        models.Newsletter.objects.create(
            slug="slug",
            title="title",
            vendor_id="VEND1",
            active=False,
            languages="en-US, fr, de ",
        )
        # This should get the data cached
        newsletter_fields()
        # Now request it again and it shouldn't have to generate the
        # data from scratch.
        with patch("basket.news.newsletters._get_newsletters_data") as get:
            newsletter_fields()
        self.assertFalse(get.called)

    def test_cache_clearing(self):
        # Our caching of newsletter data doesn't result in wrong answers
        # when newsletters change
        models.Newsletter.objects.create(
            slug="slug",
            title="title",
            vendor_id="VEND1",
            active=False,
            languages="en-US, fr, de ",
        )
        vendor_ids = newsletter_fields()
        self.assertEqual(["VEND1"], vendor_ids)
        # Now add another newsletter
        models.Newsletter.objects.create(
            slug="slug2",
            title="title2",
            vendor_id="VEND2",
            active=False,
            languages="en-US, fr, de ",
        )
        vendor_ids2 = set(newsletter_fields())
        self.assertEqual(set(["VEND1", "VEND2"]), vendor_ids2)

    def test_cache_clear_on_delete(self):
        # Our caching of newsletter data doesn't result in wrong answers
        # when newsletters are deleted
        nl1 = models.Newsletter.objects.create(
            slug="slug",
            title="title",
            vendor_id="VEND1",
            active=False,
            languages="en-US, fr, de ",
        )
        vendor_ids = newsletter_fields()
        self.assertEqual(["VEND1"], vendor_ids)
        # Now delete it
        nl1.delete()
        vendor_ids = newsletter_fields()
        self.assertEqual([], vendor_ids)


class RecoveryViewTest(TestCase):
    # See the task tests for more
    def setUp(self):
        self.url = reverse("send_recovery_message")

    def tearDown(self):
        email_block_list_cache.clear()

    def test_no_email(self):
        """email not provided - return 400"""
        resp = self.client.post(self.url, {})
        self.assertEqual(400, resp.status_code)

    def test_bad_email(self):
        """Invalid email should return 400"""
        resp = self.client.post(self.url, {"email": "not_an_email"})
        self.assertEqual(400, resp.status_code)

    @patch("basket.news.views.process_email", Mock(return_value="dude@example.com"))
    @patch("basket.news.views.get_user_data", autospec=True)
    def test_unknown_email(self, mock_get_user_data):
        """Unknown email should return 404"""
        email = "dude@example.com"
        mock_get_user_data.return_value = None
        resp = self.client.post(self.url, {"email": email})
        self.assertEqual(404, resp.status_code)

    @patch("basket.news.utils.get_email_block_list")
    @patch("basket.news.views.send_recovery_message_acoustic.delay", autospec=True)
    def test_blocked_email(
        self, mock_send_recovery_message_task, mock_get_email_block_list,
    ):
        """email provided - pass to the task, return 200"""
        email = "dude@example.com"
        mock_get_email_block_list.return_value = ["example.com"]
        # It should pass the email to the task
        resp = self.client.post(self.url, {"email": email})
        self.assertEqual(200, resp.status_code)
        self.assertFalse(mock_send_recovery_message_task.called)

    @patch("basket.news.views.process_email", Mock(return_value="dude@example.com"))
    @patch("basket.news.views.get_user_data", autospec=True)
    @patch("basket.news.views.send_recovery_message_acoustic.delay", autospec=True)
    def test_known_email(self, mock_send_recovery_message_task, mock_get_user_data):
        """email provided - pass to the task, return 200"""
        email = "dude@example.com"
        mock_get_user_data.return_value = {"token": "el-dudarino"}
        # It should pass the email to the task
        resp = self.client.post(self.url, {"email": email})
        self.assertEqual(200, resp.status_code)
        mock_send_recovery_message_task.assert_called_with(
            email, "el-dudarino", "en", "H",
        )


class TestValidateEmail(TestCase):
    email = "dude@example.com"

    def test_valid_email(self):
        """Should return without raising an exception for a valid email."""
        self.assertEqual(utils.process_email(self.email), self.email)

    @patch.object(utils, "validate_email")
    def test_invalid_email(self, ve_mock):
        """Should return None for an invalid email."""
        ve_mock.side_effect = EmailSyntaxError
        self.assertIsNone(utils.process_email(self.email))


class CommonVoiceGoalsTests(ViewsPatcherMixin, TestCase):
    def setUp(self):
        self.rf = RequestFactory()

        self._patch_views("has_valid_api_key")
        self._patch_views("record_common_voice_update")

    def test_valid_submission(self):
        self.has_valid_api_key.return_value = True
        req = self.rf.post(
            "/",
            {
                "email": "dude@example.com",
                "days_interval": "1",
                "created_at": "2019-04-07T12:42:34Z",
                "goal_reached_at": "",
            },
        )
        resp = views.common_voice_goals(req)
        self.record_common_voice_update.delay.assert_called_with(
            {
                "email": "dude@example.com",
                "days_interval": 1,
                "created_at": "2019-04-07T12:42:34Z",
            },
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = json.loads(resp.content)
        self.assertEqual("ok", data["status"])

    def test_valid_submission_with_boolean(self):
        self.has_valid_api_key.return_value = True
        req = self.rf.post(
            "/",
            {
                "email": "dude@example.com",
                "days_interval": "1",
                "created_at": "2019-04-07T12:42:34Z",
                "last_active_date": "2019-04-17T12:42:34Z",
                "two_day_streak": "True",
            },
        )
        resp = views.common_voice_goals(req)
        self.record_common_voice_update.delay.assert_called_with(
            {
                "email": "dude@example.com",
                "days_interval": 1,
                "created_at": "2019-04-07T12:42:34Z",
                "last_active_date": "2019-04-17T12:42:34Z",
                "two_day_streak": True,
            },
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = json.loads(resp.content)
        self.assertEqual("ok", data["status"])

    def test_invalid_date(self):
        self.has_valid_api_key.return_value = True
        req = self.rf.post(
            "/",
            {
                "email": "dude@example.com",
                "days_interval": "1",
                # invalid format
                "created_at": "2019-04-07 12:42:34",
            },
        )
        resp = views.common_voice_goals(req)
        self.record_common_voice_update.delay.assert_not_called()
        self.assertEqual(resp.status_code, 400, resp.content)
        data = json.loads(resp.content)
        self.assertEqual("error", data["status"])


@override_settings(FXA_EMAIL_PREFS_DOMAIN="www.mozilla.org")
class FxAPrefCenterOauthCallbackTests(ViewsPatcherMixin, TestCase):
    def setUp(self):
        self.client = Client()
        self._patch_views("get_user_data")
        self._patch_views("get_fxa_clients")
        self._patch_views("statsd")
        self._patch_views("sentry_sdk")
        self._patch_views("upsert_contact")

    def test_no_session_state(self):
        """Should return a redirect to error page"""
        resp = self.client.get("/fxa/callback/")
        assert resp.status_code == 302
        assert resp["location"] == "https://www.mozilla.org/newsletter/fxa-error/"
        self.statsd.incr.assert_called_with("news.views.fxa_callback.error.no_state")

    def test_no_returned_state(self):
        """Should return a redirect to error page"""
        session = self.client.session
        session["fxa_state"] = "thedude"
        session.save()
        resp = self.client.get("/fxa/callback/", {"code": "thecode"})
        assert resp.status_code == 302
        assert resp["location"] == "https://www.mozilla.org/newsletter/fxa-error/"
        self.statsd.incr.assert_called_with(
            "news.views.fxa_callback.error.no_code_state",
        )

    def test_no_returned_code(self):
        """Should return a redirect to error page"""
        session = self.client.session
        session["fxa_state"] = "thedude"
        session.save()
        resp = self.client.get("/fxa/callback/", {"state": "thedude"})
        assert resp.status_code == 302
        assert resp["location"] == "https://www.mozilla.org/newsletter/fxa-error/"
        self.statsd.incr.assert_called_with(
            "news.views.fxa_callback.error.no_code_state",
        )

    def test_session_and_request_state_no_match(self):
        """Should return a redirect to error page"""
        session = self.client.session
        session["fxa_state"] = "thedude"
        session.save()
        # no state
        resp = self.client.get("/fxa/callback/", {"code": "thecode", "state": "walter"})
        assert resp.status_code == 302
        assert resp["location"] == "https://www.mozilla.org/newsletter/fxa-error/"
        self.statsd.incr.assert_called_with(
            "news.views.fxa_callback.error.no_state_match",
        )

    def test_fxa_communication_issue(self):
        """Should return a redirect to error page"""
        fxa_oauth_mock = Mock()
        self.get_fxa_clients.return_value = fxa_oauth_mock, Mock()
        fxa_oauth_mock.trade_code.side_effect = RuntimeError
        session = self.client.session
        session["fxa_state"] = "thedude"
        session.save()
        # no state
        resp = self.client.get(
            "/fxa/callback/", {"code": "thecode", "state": "thedude"},
        )
        assert resp.status_code == 302
        assert resp["location"] == "https://www.mozilla.org/newsletter/fxa-error/"
        self.statsd.incr.assert_called_with("news.views.fxa_callback.error.fxa_comm")
        self.sentry_sdk.capture_exception.assert_called()

    def test_existing_user(self):
        """Should return a redirect to email pref center"""
        fxa_oauth_mock, fxa_profile_mock = Mock(), Mock()
        fxa_oauth_mock.trade_code.return_value = {"access_token": "access-token"}
        fxa_profile_mock.get_profile.return_value = {"email": "dude@example.com"}
        self.get_fxa_clients.return_value = fxa_oauth_mock, fxa_profile_mock
        self.get_user_data.return_value = {"token": "the-token"}
        session = self.client.session
        session["fxa_state"] = "thedude"
        session.save()
        # no state
        resp = self.client.get(
            "/fxa/callback/", {"code": "thecode", "state": "thedude"},
        )
        assert resp.status_code == 302
        fxa_oauth_mock.trade_code.assert_called_with(
            "thecode", ttl=settings.FXA_OAUTH_TOKEN_TTL,
        )
        fxa_profile_mock.get_profile.assert_called_with("access-token")
        self.statsd.incr.assert_not_called()
        assert (
            resp["location"]
            == "https://www.mozilla.org/newsletter/existing/the-token/?fxa=1"
        )
        self.get_user_data.assert_called_with(email="dude@example.com")

    def test_new_user_with_locale(self):
        """Should return a redirect to email pref center"""
        fxa_oauth_mock, fxa_profile_mock = Mock(), Mock()
        fxa_oauth_mock.trade_code.return_value = {"access_token": "access-token"}
        fxa_profile_mock.get_profile.return_value = {
            "email": "dude@example.com",
            "locale": "en,en-US",
        }
        self.get_fxa_clients.return_value = fxa_oauth_mock, fxa_profile_mock
        self.get_user_data.return_value = None
        self.upsert_contact.return_value = "the-new-token", True
        session = self.client.session
        session["fxa_state"] = "thedude"
        session.save()
        # no state
        resp = self.client.get(
            "/fxa/callback/", {"code": "thecode", "state": "thedude"},
        )
        assert resp.status_code == 302
        fxa_oauth_mock.trade_code.assert_called_with(
            "thecode", ttl=settings.FXA_OAUTH_TOKEN_TTL,
        )
        fxa_profile_mock.get_profile.assert_called_with("access-token")
        self.statsd.incr.assert_not_called()
        assert (
            resp["location"]
            == "https://www.mozilla.org/newsletter/existing/the-new-token/?fxa=1"
        )
        self.get_user_data.assert_called_with(email="dude@example.com")
        self.upsert_contact.assert_called_with(
            SUBSCRIBE,
            {
                "email": "dude@example.com",
                "optin": True,
                "format": "H",
                "newsletters": [settings.FXA_REGISTER_NEWSLETTER],
                "source_url": settings.FXA_REGISTER_SOURCE_URL
                + "?utm_source=basket-fxa-oauth",
                "lang": "other",
                "fxa_lang": "en,en-US",
            },
            None,
        )

    def test_new_user_without_locale(self):
        """Should return a redirect to email pref center"""
        fxa_oauth_mock, fxa_profile_mock = Mock(), Mock()
        fxa_oauth_mock.trade_code.return_value = {"access_token": "access-token"}
        fxa_profile_mock.get_profile.return_value = {
            "email": "dude@example.com",
        }
        self.get_fxa_clients.return_value = fxa_oauth_mock, fxa_profile_mock
        self.get_user_data.return_value = None
        self.upsert_contact.return_value = "the-new-token", True
        session = self.client.session
        session["fxa_state"] = "thedude"
        session.save()
        # no state
        resp = self.client.get(
            "/fxa/callback/", {"code": "thecode", "state": "thedude"},
        )
        assert resp.status_code == 302
        fxa_oauth_mock.trade_code.assert_called_with(
            "thecode", ttl=settings.FXA_OAUTH_TOKEN_TTL,
        )
        fxa_profile_mock.get_profile.assert_called_with("access-token")
        self.statsd.incr.assert_not_called()
        assert (
            resp["location"]
            == "https://www.mozilla.org/newsletter/existing/the-new-token/?fxa=1"
        )
        self.get_user_data.assert_called_with(email="dude@example.com")
        self.upsert_contact.assert_called_with(
            SUBSCRIBE,
            {
                "email": "dude@example.com",
                "optin": True,
                "format": "H",
                "newsletters": [settings.FXA_REGISTER_NEWSLETTER],
                "source_url": settings.FXA_REGISTER_SOURCE_URL
                + "?utm_source=basket-fxa-oauth",
            },
            None,
        )


@override_settings(FXA_CLIENT_ID="dude")
class FxAPrefCenterOauthStartTests(ViewsPatcherMixin, TestCase):
    def setUp(self):
        self.client = Client()
        self._patch_views("get_fxa_authorization_url")
        self._patch_views("generate_fxa_state")

    def test_get_redirect_url(self):
        self.get_fxa_authorization_url.return_value = (
            good_redirect
        ) = "https://example.com/oauth"
        self.generate_fxa_state.return_value = "the-dude-abides"
        resp = self.client.get("/fxa/")
        self.get_fxa_authorization_url.assert_called_with(
            "the-dude-abides", "http://testserver/fxa/callback/", None,
        )
        assert resp.status_code == 302
        assert resp["location"] == good_redirect

    def test_get_redirect_url_with_email(self):
        self.get_fxa_authorization_url.return_value = (
            good_redirect
        ) = "https://example.com/oauth"
        self.generate_fxa_state.return_value = "the-dude-abides"
        resp = self.client.get("/fxa/?email=dude%40example.com")
        self.get_fxa_authorization_url.assert_called_with(
            "the-dude-abides", "http://testserver/fxa/callback/", "dude@example.com",
        )
        assert resp.status_code == 302
        assert resp["location"] == good_redirect


class AMOSyncTests(ViewsPatcherMixin, TestCase):
    def setUp(self):
        self.client = Client()
        self._patch_views("amo_sync_addon")
        self._patch_views("amo_sync_user")
        self._patch_views("has_valid_api_key")
        # the above patch doesn't replace in the dict
        views.AMO_SYNC_TYPES.update(
            userprofile=self.amo_sync_user, addon=self.amo_sync_addon,
        )

    def test_require_valid_api_key(self):
        self.has_valid_api_key.return_value = False
        resp = self.client.post(
            "/amo-sync/userprofile/",
            data=json.dumps({"name": "The Dude"}),
            content_type="application/json",
        )
        assert resp.status_code == 401
        self.amo_sync_user.delay.assert_not_called()
        self.amo_sync_addon.delay.assert_not_called()

    def test_call_user_task(self):
        self.has_valid_api_key.return_value = True
        data = {"name": "The Dude"}
        resp = self.client.post(
            "/amo-sync/userprofile/",
            data=json.dumps(data),
            content_type="application/json",
        )
        assert resp.status_code == 200
        self.amo_sync_user.delay.assert_called_with(data)
        self.amo_sync_addon.delay.assert_not_called()

    def test_call_addon_task(self):
        self.has_valid_api_key.return_value = True
        data = {"name": "The Dude"}
        resp = self.client.post(
            "/amo-sync/addon/",
            data=json.dumps({"name": "The Dude"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        self.amo_sync_user.delay.assert_not_called()
        self.amo_sync_addon.delay.assert_called_with(data)

    def test_invalid_amo_url(self):
        resp = self.client.post(
            "/amo-sync/dude/",
            data=json.dumps({"name": "The Dude"}),
            content_type="application/json",
        )
        assert resp.status_code == 404

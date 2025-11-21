import json
import uuid
from unittest.mock import Mock, patch

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.test.client import Client, RequestFactory
from django.urls import reverse

from django_ratelimit.exceptions import Ratelimited
from email_validator import EmailSyntaxError

from basket import errors
from basket.news import models, tasks, utils, views
from basket.news.newsletters import newsletter_fields, newsletter_languages
from basket.news.tasks import SUBSCRIBE
from basket.news.tests import TasksPatcherMixin, ViewsPatcherMixin, mock_metrics
from basket.news.utils import email_block_list_cache

none_mock = Mock(return_value=None)


@patch.object(tasks, "update_user_meta")
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
        uum_mock.delay.assert_called_with_subset(
            "the-dudes-token-man",
            {"country": "gb"},
        )

    def test_only_send_given_values(self, uum_mock):
        req = self.rf.post("/", {"first_name": "The", "last_name": "Dude"})
        resp = views.user_meta(req, "the-dudes-token-man")
        assert resp.status_code == 200
        uum_mock.delay.assert_called_with_subset(
            "the-dudes-token-man",
            {"first_name": "The", "last_name": "Dude"},
        )


class TestIsToken(TestCase):
    def test_invalid_tokens(self):
        self.assertFalse(views.is_token("the dude"))
        self.assertFalse(views.is_token("abcdef-1234"))
        self.assertFalse(views.is_token("abcdef-abcdef-abcdef-deadbeef_123456"))

    def test_valid_tokens(self):
        self.assertTrue(views.is_token("abcdef-abcdef-abcdef-deadbeef-123456"))
        self.assertTrue(views.is_token(utils.generate_token()))


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

    @patch("basket.news.views.is_token")
    def test_invalid_token(self, mock_is_token):
        """Should return proper error for invalid token."""
        mock_is_token.return_value = False
        resp = self.client.post(reverse("subscribe"), {"newsletters": "os", "token": "abc123"})
        mock_is_token.assert_called_with("abc123")
        json_resp = resp.json()
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(json_resp["status"], "error")
        self.assertEqual(json_resp["code"], errors.BASKET_INVALID_TOKEN)

    @patch("basket.news.views.update_user_task")
    def test_non_ascii_email(self, update_user_mock):
        """Should be able to accept valid email including non-ascii chars."""
        req = self.rf.post(
            "/news/subscribe/",
            data={"email": "dude@黒川.日本", "newsletters": "firefox-os"},
        )
        views.subscribe(req)
        update_user_mock.assert_called_with_subset(
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
            "/news/subscribe/",
            data={"email": "", "newsletters": "firefox-os"},
        )
        resp = views.subscribe(req)
        resp_data = json.loads(resp.content)
        self.assertEqual(resp_data["status"], "error")
        self.assertEqual(resp_data["code"], errors.BASKET_USAGE_ERROR)
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


class SubscribeTests(ViewsPatcherMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        self._patch_views("update_user_task")
        self._patch_views("process_email")
        self._patch_views("is_token")
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
        self.update_user_task.assert_called_with_subset(
            request,
            SUBSCRIBE,
            data=update_data,
            optin=False,
            sync=False,
        )

    def test_sync_invalid_api_key(self):
        """
        If sync is set to 'Y' and the request has an invalid API key,
        return a 401.
        """
        request = self.factory.post(
            "/",
            {"newsletters": "asdf", "sync": "Y", "email": "dude@example.com"},
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

    def test_invalid_token_response(self):
        """
        If `is_token` returns `False`, return an invalid token response.
        """
        request_data = {"newsletters": "asdf", "token": "abc123"}
        request = self.factory.post("/", request_data)
        self.is_token.return_value = False

        with patch("basket.news.views.invalid_token_response") as invalid_token_response:
            response = views.subscribe(request)
            self.assertEqual(response, invalid_token_response.return_value)
            self.is_token.assert_called_with(request_data["token"])
            invalid_token_response.assert_called()

    @patch("basket.news.views.get_user_data")
    def test_token_finds_no_user(self, get_user_data_mock):
        """Test no user found for token."""
        get_user_data_mock.return_value = None  # No user found.
        self.process_email.return_value = None
        request_data = {
            "newsletters": "news,lets",
            "optin": "N",
            "sync": "N",
            "token": str(uuid.uuid4()),
            "first_name": "The",
            "last_name": "Dude",
        }

        request = self.factory.post("/", request_data)
        response = views.subscribe(request)

        self.assert_response_error(response, 400, errors.BASKET_INVALID_TOKEN)
        self.is_token.assert_called_with(request_data["token"])
        self.process_email.assert_called_with(None)
        self.update_user_task.assert_not_called()

    @patch("basket.news.utils.get_email_block_list")
    @mock_metrics
    def test_blocked_email(self, metricsmock, get_block_list_mock):
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
        metricsmock.assert_incr_once("news.views.subscribe", tags=["info:email_blocked"])

    @mock_metrics
    def test_no_source_url_referrer(self, metricsmock):
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
            "/",
            request_data,
            HTTP_REFERER=update_data["source_url"],
        )

        response = views.subscribe(request)

        self.assertEqual(response, self.update_user_task.return_value)
        self.process_email.assert_called_with(request_data["email"])
        self.update_user_task.assert_called_with_subset(
            request,
            SUBSCRIBE,
            data=update_data,
            optin=False,
            sync=False,
        )
        metricsmock.assert_incr_once("news.views.subscribe", tags=["info:use_referrer"])

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
            "/",
            request_data,
            HTTP_REFERER="https://example.com/donnie",
        )

        response = views.subscribe(request)

        self.assertEqual(response, self.update_user_task.return_value)
        self.process_email.assert_called_with(request_data["email"])
        self.update_user_task.assert_called_with_subset(
            request,
            SUBSCRIBE,
            data=update_data,
            optin=False,
            sync=False,
        )

    def test_success_with_email(self):
        """Test basic success case with no optin or sync."""
        request_data = {
            "newsletters": "news,lets",
            "optin": "N",
            "sync": "N",
            # Throwing `format` in here to ensure backwards compatibility.
            "format": "H",
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
        self.update_user_task.assert_called_with_subset(
            request,
            SUBSCRIBE,
            data=update_data,
            optin=False,
            sync=False,
        )

    @patch("basket.news.views.get_user_data")
    def test_success_with_token(self, get_user_data_mock):
        """Test basic success case with no optin or sync."""
        email = "dude@example.com"
        get_user_data_mock.return_value = {"email": email}
        self.process_email.return_value = email
        request_data = {
            "newsletters": "news,lets",
            "optin": "N",
            "sync": "N",
            "token": str(uuid.uuid4()),
            "first_name": "The",
            "last_name": "Dude",
        }
        update_data = request_data.copy()
        for k in ("optin", "sync", "token"):
            del update_data[k]
        update_data["email"] = email

        request = self.factory.post("/", request_data)
        response = views.subscribe(request)

        self.assertEqual(response, self.update_user_task.return_value)
        self.is_token.assert_called_with(request_data["token"])
        self.process_email.assert_called_with(email)
        self.update_user_task.assert_called_with_subset(
            request,
            SUBSCRIBE,
            data=update_data,
            optin=False,
            sync=False,
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
        self.update_user_task.assert_called_with_subset(
            request,
            SUBSCRIBE,
            data=update_data,
            optin=True,
            sync=True,
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
        self.update_user_task.assert_called_with_subset(
            request,
            SUBSCRIBE,
            data=update_data,
            optin=True,
            sync=True,
        )

    def test_ignores_extraneous_request_keys(self):
        """Test basic success case, ignores any unexpected keys in the request body."""
        request_data = {
            "newsletters": "news,lets",
            "email": "dude@example.com",
            "first_name": "The",
            "last_name": "Dude",
            # the keys below are not allowed and should be ignored
            "fxa_id": "123",
            "optout": "Y",
            "test": "example",
        }
        update_data = request_data.copy()
        del update_data["fxa_id"]
        del update_data["optout"]
        del update_data["test"]
        self.process_email.return_value = update_data["email"]
        request = self.factory.post("/", request_data)

        response = views.subscribe(request)

        self.assertEqual(response, self.update_user_task.return_value)
        self.process_email.assert_called_with(request_data["email"])
        self.update_user_task.assert_called_with_subset(
            request,
            SUBSCRIBE,
            data=update_data,
        )


class TestRatelimit(TestCase):
    @mock_metrics
    def test_ratelimit_view(self, metricsmock):
        # The django-ratelimit middleware will call the view defined by `RATELIMIT_VIEW`.
        # We want to test it here so we call it directly.
        req = RequestFactory().get("/")
        req.path = "/path/to/test/"

        resp = views.ratelimited(req, Ratelimited())

        assert resp.status_code == 429
        metricsmock.assert_incr_once("news.views.ratelimited", tags=["path:path.to.test"])

    @mock_metrics
    def test_ratelimit_view_token_filter(self, metricsmock):
        # The django-ratelimit middleware will call the view defined by `RATELIMIT_VIEW`.
        # We want to test it here so we call it directly.
        token = str(uuid.uuid4())
        req = RequestFactory().get("/")
        req.path = f"/path/to/test/{token}/included/"

        resp = views.ratelimited(req, Ratelimited())

        assert resp.status_code == 429
        metricsmock.assert_incr_once("news.views.ratelimited", tags=["path:path.to.test.included"])


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
            slug="slug3",
            vendor_id="VENDOR3",
            private=True,
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
        expect = {"en-US", "fr", "de"}
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
        self.assertEqual({"VEND1", "VEND2"}, vendor_ids2)

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
    @patch("basket.news.tasks.send_recovery_message.delay", autospec=True)
    def test_blocked_email(
        self,
        mock_send_recovery_message_task,
        mock_get_email_block_list,
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
    @patch("basket.news.tasks.send_recovery_message.delay", autospec=True)
    def test_known_email(self, mock_send_recovery_message_task, mock_get_user_data):
        """email provided - pass to the task, return 200"""
        email = "dude@example.com"
        mock_get_user_data.return_value = {"token": "el-dudarino", "email_id": "fed654"}
        # It should pass the email to the task
        resp = self.client.post(self.url, {"email": email})
        self.assertEqual(200, resp.status_code)
        mock_send_recovery_message_task.assert_called_with(
            email,
            "el-dudarino",
            "en",
            "fed654",
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


class CommonVoiceGoalsTests(ViewsPatcherMixin, TasksPatcherMixin, TestCase):
    def setUp(self):
        self.rf = RequestFactory()

        self._patch_views("has_valid_api_key")
        self._patch_tasks("record_common_voice_update")

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
class FxAPrefCenterOauthCallbackTests(ViewsPatcherMixin, TasksPatcherMixin, TestCase):
    FXA_ERROR_URL = "https://www.mozilla.org/newsletter/recovery/?fxa_error=1"

    def setUp(self):
        self.client = Client()
        self._patch_views("get_user_data")
        self._patch_views("get_fxa_clients")
        self._patch_views("sentry_sdk")
        self._patch_tasks("upsert_contact")

    @mock_metrics
    def test_no_session_state(self, metricsmock):
        """Should return a redirect to error page"""
        resp = self.client.get("/fxa/callback/")
        assert resp.status_code == 302
        assert resp["location"] == self.FXA_ERROR_URL
        metricsmock.assert_incr_once("news.views.fxa_callback", tags=["status:error", "error:no_sess_state"])

    @mock_metrics
    def test_no_returned_state(self, metricsmock):
        """Should return a redirect to error page"""
        session = self.client.session
        session["fxa_state"] = "thedude"
        session.save()
        resp = self.client.get("/fxa/callback/", {"code": "thecode"})
        assert resp.status_code == 302
        assert resp["location"] == self.FXA_ERROR_URL
        metricsmock.assert_incr_once("news.views.fxa_callback", tags=["status:error", "error:no_code_or_state"])

    @mock_metrics
    def test_no_returned_code(self, metricsmock):
        """Should return a redirect to error page"""
        session = self.client.session
        session["fxa_state"] = "thedude"
        session.save()
        resp = self.client.get("/fxa/callback/", {"state": "thedude"})
        assert resp.status_code == 302
        assert resp["location"] == self.FXA_ERROR_URL
        metricsmock.assert_incr_once("news.views.fxa_callback", tags=["status:error", "error:no_code_or_state"])

    @mock_metrics
    def test_session_and_request_state_no_match(self, metricsmock):
        """Should return a redirect to error page"""
        session = self.client.session
        session["fxa_state"] = "thedude"
        session.save()
        # no state
        resp = self.client.get("/fxa/callback/", {"code": "thecode", "state": "walter"})
        assert resp.status_code == 302
        assert resp["location"] == self.FXA_ERROR_URL
        metricsmock.assert_incr_once("news.views.fxa_callback", tags=["status:error", "error:no_state_match"])

    @mock_metrics
    def test_fxa_communication_issue(self, metricsmock):
        """Should return a redirect to error page"""
        fxa_oauth_mock = Mock()
        self.get_fxa_clients.return_value = fxa_oauth_mock, Mock()
        fxa_oauth_mock.trade_code.side_effect = RuntimeError
        session = self.client.session
        session["fxa_state"] = "thedude"
        session.save()
        # no state
        resp = self.client.get(
            "/fxa/callback/",
            {"code": "thecode", "state": "thedude"},
        )
        assert resp.status_code == 302
        assert resp["location"] == self.FXA_ERROR_URL
        metricsmock.assert_incr_once("news.views.fxa_callback", tags=["status:error", "error:fxa_comm"])
        self.sentry_sdk.capture_exception.assert_called()

    @mock_metrics
    def test_existing_user(self, metricsmock):
        """Should return a redirect to email pref center"""
        fxa_oauth_mock, fxa_profile_mock = Mock(), Mock()
        fxa_oauth_mock.trade_code.return_value = {"access_token": "access-token"}
        fxa_profile_mock.get_profile.return_value = {"email": "dude@example.com", "uid": "abc123"}
        self.get_fxa_clients.return_value = fxa_oauth_mock, fxa_profile_mock
        self.get_user_data.return_value = {"token": "the-token"}
        session = self.client.session
        session["fxa_state"] = "thedude"
        session.save()
        # no state
        resp = self.client.get(
            "/fxa/callback/",
            {"code": "thecode", "state": "thedude"},
        )
        assert resp.status_code == 302
        fxa_oauth_mock.trade_code.assert_called_with(
            "thecode",
            ttl=settings.FXA_OAUTH_TOKEN_TTL,
        )
        fxa_profile_mock.get_profile.assert_called_with("access-token")
        metricsmock.assert_incr_once("news.views.fxa_callback", tags=["status:success"])
        assert resp["location"] == "https://www.mozilla.org/newsletter/existing/the-token/?fxa=1"
        self.get_user_data.assert_called_with_subset(email="dude@example.com", fxa_id="abc123")

    @mock_metrics
    def test_new_user_with_locale(self, metricsmock):
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
            "/fxa/callback/",
            {"code": "thecode", "state": "thedude"},
        )
        assert resp.status_code == 302
        fxa_oauth_mock.trade_code.assert_called_with(
            "thecode",
            ttl=settings.FXA_OAUTH_TOKEN_TTL,
        )
        fxa_profile_mock.get_profile.assert_called_with("access-token")
        metricsmock.assert_incr_once("news.views.fxa_callback", tags=["status:success"])
        assert resp["location"] == "https://www.mozilla.org/newsletter/existing/the-new-token/?fxa=1"
        self.get_user_data.assert_called_with_subset(email="dude@example.com", fxa_id=None)
        self.upsert_contact.assert_called_with_subset(
            SUBSCRIBE,
            {
                "email": "dude@example.com",
                "optin": True,
                "newsletters": [settings.FXA_REGISTER_NEWSLETTER],
                "source_url": settings.FXA_REGISTER_SOURCE_URL + "?utm_source=basket-fxa-oauth",
                "lang": "other",
                "fxa_lang": "en,en-US",
            },
            None,
        )

    @mock_metrics
    def test_new_user_without_locale(self, metricsmock):
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
            "/fxa/callback/",
            {"code": "thecode", "state": "thedude"},
        )
        assert resp.status_code == 302
        fxa_oauth_mock.trade_code.assert_called_with(
            "thecode",
            ttl=settings.FXA_OAUTH_TOKEN_TTL,
        )
        fxa_profile_mock.get_profile.assert_called_with("access-token")
        metricsmock.assert_incr_once("news.views.fxa_callback", tags=["status:success"])
        assert resp["location"] == "https://www.mozilla.org/newsletter/existing/the-new-token/?fxa=1"
        self.get_user_data.assert_called_with_subset(email="dude@example.com", fxa_id=None)
        self.upsert_contact.assert_called_with_subset(
            SUBSCRIBE,
            {
                "email": "dude@example.com",
                "optin": True,
                "newsletters": [settings.FXA_REGISTER_NEWSLETTER],
                "source_url": settings.FXA_REGISTER_SOURCE_URL + "?utm_source=basket-fxa-oauth",
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
        self.get_fxa_authorization_url.return_value = good_redirect = "https://example.com/oauth"
        self.generate_fxa_state.return_value = "the-dude-abides"
        resp = self.client.get("/fxa/")
        self.get_fxa_authorization_url.assert_called_with(
            "the-dude-abides",
            "http://testserver/fxa/callback/",
            None,
        )
        assert resp.status_code == 302
        assert resp["location"] == good_redirect

    def test_get_redirect_url_with_email(self):
        self.get_fxa_authorization_url.return_value = good_redirect = "https://example.com/oauth"
        self.generate_fxa_state.return_value = "the-dude-abides"
        resp = self.client.get("/fxa/?email=dude%40example.com")
        self.get_fxa_authorization_url.assert_called_with(
            "the-dude-abides",
            "http://testserver/fxa/callback/",
            "dude@example.com",
        )
        assert resp.status_code == 302
        assert resp["location"] == good_redirect

import json
from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory, TestCase

from ratelimit.exceptions import Ratelimited

from basket import errors
from basket.news import views
from basket.news.tests import TasksPatcherMixin
from basket.news.utils import SET, SUBSCRIBE, UNSUBSCRIBE


class UpdateUserTaskTests(TestCase, TasksPatcherMixin):
    def setUp(self):
        self.factory = RequestFactory()

        self._patch_tasks("upsert_user")
        self._patch_tasks("upsert_contact")

        cache.clear()

    def assert_response_error(self, response, status_code, basket_code):
        self.assertEqual(response.status_code, status_code)
        response_data = json.loads(response.content)
        self.assertEqual(response_data["code"], basket_code)

    def assert_response_ok(self, response, **kwargs):
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertEqual(response_data["status"], "ok")

        del response_data["status"]
        self.assertEqual(response_data, kwargs)

    def test_invalid_newsletter(self):
        """If an invalid newsletter is given, return a 400 error."""
        request = self.factory.post("/")

        with patch("basket.news.views.newsletter_slugs") as newsletter_slugs:
            newsletter_slugs.return_value = ["foo", "baz"]
            response = views.update_user_task(
                request,
                SUBSCRIBE,
                {"newsletters": "foo,bar"},
            )

            self.assert_response_error(response, 400, errors.BASKET_INVALID_NEWSLETTER)

    @patch("basket.news.views.get_best_language")
    @patch("basket.news.utils.newsletter_languages")
    def test_accept_lang(self, nl_mock, get_best_language_mock):
        """If accept_lang param is provided, should set the lang in data."""
        get_best_language_mock.return_value = "pt"
        nl_mock.return_value = ["pt", "en", "de"]
        request = self.factory.post("/")
        data = {"email": "dude@example.com", "accept_lang": "pt-pt,fr;q=0.8"}
        after_data = {"email": "dude@example.com", "lang": "pt"}

        response = views.update_user_task(request, SUBSCRIBE, data, sync=False)
        self.assert_response_ok(response)
        self.upsert_user.delay.assert_called_with(SUBSCRIBE, after_data)

    @patch("basket.news.utils.get_best_language")
    @patch("basket.news.utils.newsletter_languages")
    def test_accept_lang_header(self, nl_mock, get_best_language_mock):
        """If accept-language header is provided, should set the lang in data."""
        get_best_language_mock.return_value = "pt"
        nl_mock.return_value = ["pt", "en", "de"]
        request = self.factory.post("/", HTTP_ACCEPT_LANGUAGE="pt-pt,fr;q=0.8")
        data = {"email": "dude@example.com"}
        after_data = {"email": "dude@example.com", "lang": "pt"}

        response = views.update_user_task(request, SUBSCRIBE, data, sync=False)
        self.assert_response_ok(response)
        self.upsert_user.delay.assert_called_with(SUBSCRIBE, after_data)

    @patch("basket.news.utils.get_best_language")
    @patch("basket.news.utils.newsletter_languages")
    def test_lang_overrides_accept_lang(self, nl_mock, get_best_language_mock):
        """
        If lang is provided it was from the user, and accept_lang isn't as
        reliable, so we should prefer lang.
        """
        get_best_language_mock.return_value = "pt-BR"
        nl_mock.return_value = ["pt", "en", "de"]
        request = self.factory.post("/")
        data = {"email": "a@example.com", "lang": "de", "accept_lang": "pt-BR"}

        response = views.update_user_task(request, SUBSCRIBE, data, sync=False)
        self.assert_response_ok(response)
        # basically asserts that the data['lang'] value wasn't changed.
        self.upsert_user.delay.assert_called_with(SUBSCRIBE, data)

    @patch("basket.news.utils.get_best_language")
    @patch("basket.news.utils.newsletter_languages")
    def test_lang_default_if_not_in_list(self, nl_mock, get_best_language_mock):
        """
        If lang is provided it was from the user, and accept_lang isn't as
        reliable, so we should prefer lang.
        """
        get_best_language_mock.return_value = "pt-BR"
        nl_mock.return_value = ["pt", "en", "de"]
        request = self.factory.post("/")
        data = {"email": "a@example.com", "lang": "hi"}
        after_data = {"email": "a@example.com", "lang": "en"}

        response = views.update_user_task(request, SUBSCRIBE, data, sync=False)
        self.assert_response_ok(response)
        # basically asserts that the data['lang'] value wasn't changed.
        self.upsert_user.delay.assert_called_with(SUBSCRIBE, after_data)

    def test_missing_email(self):
        """
        If the email is missing, return a 400 error.
        """
        request = self.factory.post("/")
        response = views.update_user_task(request, SUBSCRIBE)

        self.assert_response_error(response, 400, errors.BASKET_USAGE_ERROR)

    def test_success_no_sync(self):
        """
        If sync is False, do not generate a token and return an OK response
        without a token.
        """
        request = self.factory.post("/")
        data = {"email": "a@example.com", "first_name": "The", "last_name": "Dude"}

        response = views.update_user_task(request, SUBSCRIBE, data, sync=False)
        self.assert_response_ok(response)
        self.upsert_user.delay.assert_called_with(SUBSCRIBE, data)
        self.assertFalse(self.upsert_contact.called)

    def test_success_with_valid_newsletters(self):
        """
        If the specified newsletters are valid, return an OK response.
        """
        request = self.factory.post("/")
        data = {"email": "a@example.com", "newsletters": "foo,bar"}

        with patch("basket.news.views.newsletter_and_group_slugs") as newsletter_slugs:
            newsletter_slugs.return_value = ["foo", "bar"]
            response = views.update_user_task(request, SUBSCRIBE, data, sync=False)
            self.assert_response_ok(response)

    def test_success_with_transactional_message(self):
        """
        If the specified newsletters are not newsletters, but transactional.
        """
        request = self.factory.post("/")
        data = {"email": "a@example.com", "newsletters": "tx-foo"}

        with patch("basket.news.models.BrazeTxEmailMessage.objects.get_tx_message_ids") as get_tx_message_ids:
            get_tx_message_ids.return_value = ["tx-foo"]
            response = views.update_user_task(request, SUBSCRIBE, data, sync=False)
            self.assert_response_ok(response)

    def test_success_with_valid_lang(self):
        """If the specified language is valid, return an OK response."""
        request = self.factory.post("/")
        data = {"email": "a@example.com", "lang": "pt-BR"}

        with patch(
            "basket.news.views.language_code_is_valid",
        ) as mock_language_code_is_valid:
            mock_language_code_is_valid.return_value = True
            response = views.update_user_task(request, SUBSCRIBE, data, sync=False)
            self.assert_response_ok(response)

    def test_success_with_request_data(self):
        """
        If no data is provided, fall back to using the POST data from
        the request.
        """
        data = {"email": "a@example.com", "lang": "en"}
        request = self.factory.post("/", data)
        response = views.update_user_task(request, SUBSCRIBE, sync=False)

        self.assert_response_ok(response)
        self.upsert_user.delay.assert_called_with(SUBSCRIBE, data)

    @patch("basket.news.views.get_user_data")
    def test_success_with_sync(self, gud_mock):
        """
        If sync is True look up the user and return an OK response with the
        token and created from the fetched subscriber.
        """
        request = self.factory.post("/")
        data = {"email": "a@example.com"}
        gud_mock.return_value = {"token": "mytoken", "email": "a@example.com"}
        self.upsert_contact.return_value = "mytoken", True

        response = views.update_user_task(request, SUBSCRIBE, data, sync=True)

        self.assert_response_ok(response, token="mytoken", created=True)
        self.upsert_contact.assert_called_with(SUBSCRIBE, data, gud_mock.return_value)

    @patch("basket.news.views.newsletter_slugs")
    @patch("basket.news.views.newsletter_private_slugs")
    @patch("basket.news.views.is_authorized")
    def test_success_with_unsubscribe_private_newsletter(
        self,
        mock_api_key,
        mock_private,
        mock_slugs,
    ):
        """
        Should be able to unsubscribe from a private newsletter regardless.
        """
        mock_private.return_value = ["private"]
        mock_slugs.return_value = ["private", "other"]
        request = self.factory.post("/")
        data = {"token": "mytoken", "newsletters": "private"}
        response = views.update_user_task(request, UNSUBSCRIBE, data)

        self.assert_response_ok(response)
        self.upsert_user.delay.assert_called_with(UNSUBSCRIBE, data)
        mock_api_key.assert_not_called()

    @patch("basket.news.views.newsletter_and_group_slugs")
    @patch("basket.news.views.newsletter_private_slugs")
    @patch("basket.news.views.is_authorized")
    def test_subscribe_private_newsletter_invalid_api_key(
        self,
        mock_api_key,
        mock_private,
        mock_slugs,
    ):
        """
        If calling SUBSCRIBE with a private newsletter and the request has an
        invalid API key, return a 401.
        """
        mock_private.return_value = ["private"]
        mock_slugs.return_value = ["private", "other"]
        data = {"newsletters": "private", "email": "dude@example.com"}
        request = self.factory.post("/", data)
        mock_api_key.return_value = False

        response = views.update_user_task(request, SUBSCRIBE, data)
        self.assert_response_error(response, 401, errors.BASKET_AUTH_ERROR)
        mock_api_key.assert_called_with(request, data["email"])

    @patch("basket.news.views.newsletter_slugs")
    @patch("basket.news.views.newsletter_private_slugs")
    @patch("basket.news.views.is_authorized")
    def test_set_private_newsletter_invalid_api_key(
        self,
        mock_api_key,
        mock_private,
        mock_slugs,
    ):
        """
        If calling SET with a private newsletter, return a 200 since the user
        will only be shown a private newsletter if they are already subscribed.
        """
        mock_private.return_value = ["private"]
        mock_slugs.return_value = ["private", "other"]
        data = {"newsletters": "private", "email": "dude@example.com"}
        request = self.factory.post("/", data)

        response = views.update_user_task(request, SET, data)
        self.assert_response_ok(response)
        mock_api_key.assert_not_called()

    @patch("basket.news.views.newsletter_slugs")
    @patch("basket.news.views.newsletter_and_group_slugs")
    @patch("basket.news.views.newsletter_private_slugs")
    @patch("basket.news.views.is_authorized")
    def test_private_newsletter_success(
        self,
        mock_api_key,
        mock_private,
        mock_group_slugs,
        mock_slugs,
    ):
        """
        If calling SUBSCRIBE or SET with a private newsletter and the request
        has a valid API key, return success.
        """
        mock_private.return_value = ["private"]
        mock_slugs.return_value = ["private", "other"]
        mock_group_slugs.return_value = ["private", "other"]
        data = {"newsletters": "private", "email": "dude@example.com"}
        request = self.factory.post("/", data)
        mock_api_key.return_value = True

        response = views.update_user_task(request, SUBSCRIBE, data)
        self.assert_response_ok(response)
        mock_api_key.assert_called_with(request, data["email"])

        response = views.update_user_task(request, SET, data)
        self.assert_response_ok(response)
        mock_api_key.assert_called_with(request, data["email"])

    def test_rate_limit(self):
        """Should raise Ratelimited if email attempts to sign up for same
        newsletter quickly"""
        views.EMAIL_SUBSCRIBE_RATE_LIMIT = "2/1m"
        request = self.factory.post("/")
        data = {"email": "a@example.com", "newsletters": "foo,bar"}
        with patch("basket.news.views.newsletter_and_group_slugs") as newsletter_slugs:
            newsletter_slugs.return_value = ["foo", "bar"]
            views.update_user_task(request, SUBSCRIBE, data, sync=False)
            response = views.update_user_task(request, SUBSCRIBE, data, sync=False)
            self.assert_response_ok(response)
            with self.assertRaises(Ratelimited):
                views.update_user_task(request, SUBSCRIBE, data, sync=False)

    def test_rate_limit_user_update(self):
        """Should raise Ratelimited if token attempts to update same newsletters
        quickly"""
        views.EMAIL_SUBSCRIBE_RATE_LIMIT = "2/1m"
        request = self.factory.post("/")
        data = {"token": "a@example.com", "newsletters": "foo,bar"}
        with patch("basket.news.views.newsletter_slugs") as newsletter_slugs:
            newsletter_slugs.return_value = ["foo", "bar"]
            views.update_user_task(request, SET, data, sync=False)
            response = views.update_user_task(request, SET, data, sync=False)
            self.assert_response_ok(response)
            with self.assertRaises(Ratelimited):
                views.update_user_task(request, SET, data, sync=False)

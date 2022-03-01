import json

from django.core.cache import cache
from django.test import TestCase, RequestFactory

from basket import errors
from mock import patch, ANY
from ratelimit.exceptions import Ratelimited

from basket.news.utils import SUBSCRIBE, UNSUBSCRIBE, SET
from basket.news import views


class UpdateUserTaskTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        patcher = patch("basket.news.views.upsert_contact")
        self.upsert_contact = patcher.start()
        self.addCleanup(patcher.stop)

        patcher = patch("basket.news.views.upsert_user")
        self.upsert_user = patcher.start()
        self.addCleanup(patcher.stop)

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
        self.upsert_user.delay.assert_called_with(SUBSCRIBE, after_data, start_time=ANY)

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
        self.upsert_user.delay.assert_called_with(SUBSCRIBE, after_data, start_time=ANY)

    @patch("basket.news.utils.get_best_language")
    @patch("basket.news.utils.newsletter_languages")
    def test_lang_overrides_accept_lang(self, nl_mock, get_best_language_mock):
        """
        If lang is provided it was from the user, and accept_lang isn't as reliable, so we should
        prefer lang.
        """
        get_best_language_mock.return_value = "pt-BR"
        nl_mock.return_value = ["pt", "en", "de"]
        request = self.factory.post("/")
        data = {"email": "a@example.com", "lang": "de", "accept_lang": "pt-BR"}

        response = views.update_user_task(request, SUBSCRIBE, data, sync=False)
        self.assert_response_ok(response)
        # basically asserts that the data['lang'] value wasn't changed.
        self.upsert_user.delay.assert_called_with(SUBSCRIBE, data, start_time=ANY)

    @patch("basket.news.utils.get_best_language")
    @patch("basket.news.utils.newsletter_languages")
    def test_lang_default_if_not_in_list(self, nl_mock, get_best_language_mock):
        """
        If lang is provided it was from the user, and accept_lang isn't as reliable, so we should
        prefer lang.
        """
        get_best_language_mock.return_value = "pt-BR"
        nl_mock.return_value = ["pt", "en", "de"]
        request = self.factory.post("/")
        data = {"email": "a@example.com", "lang": "hi"}
        after_data = {"email": "a@example.com", "lang": "en"}

        response = views.update_user_task(request, SUBSCRIBE, data, sync=False)
        self.assert_response_ok(response)
        # basically asserts that the data['lang'] value wasn't changed.
        self.upsert_user.delay.assert_called_with(SUBSCRIBE, after_data, start_time=ANY)

    def test_missing_email(self):
        """
        If the email is missing, return a 400 error.
        """
        request = self.factory.post("/")
        response = views.update_user_task(request, SUBSCRIBE)

        self.assert_response_error(response, 400, errors.BASKET_USAGE_ERROR)

    def test_success_no_sync(self):
        """
        If sync is False, do not generate a token via get_or_create_user_data
        and return an OK response without a token.
        """
        request = self.factory.post("/")
        data = {"email": "a@example.com", "first_name": "The", "last_name": "Dude"}

        response = views.update_user_task(request, SUBSCRIBE, data, sync=False)
        self.assert_response_ok(response)
        self.upsert_user.delay.assert_called_with(SUBSCRIBE, data, start_time=ANY)
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
        self.upsert_user.delay.assert_called_with(SUBSCRIBE, data, start_time=ANY)

    @patch("basket.news.views.get_user_data")
    def test_success_with_sync(self, gud_mock):
        """
        If sync is True look up the user with get_or_create_user_data and
        return an OK response with the token and created from the fetched subscriber.
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
    def test_success_with_unsubscribe_private_newsletter(
        self,
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
        self.upsert_user.delay.assert_called_with(UNSUBSCRIBE, data, start_time=ANY)

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
        If subscribing to a private newsletter and the request has an invalid API key,
        return a 401.
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
        If subscribing to a private newsletter and the request has an invalid API key,
        return a 401.
        """
        mock_private.return_value = ["private"]
        mock_slugs.return_value = ["private", "other"]
        data = {"newsletters": "private", "email": "dude@example.com"}
        request = self.factory.post("/", data)
        mock_api_key.return_value = False

        response = views.update_user_task(request, SET, data)
        self.assert_response_error(response, 401, errors.BASKET_AUTH_ERROR)
        mock_api_key.assert_called_with(request, data["email"])

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
        If subscribing to a private newsletter and the request has an invalid API key,
        return a 401.
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
        """Should raise Ratelimited if email attempts to sign up for same newsletter quickly"""
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
        """Should raise Ratelimited if token attempts to update same newsletters quickly"""
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

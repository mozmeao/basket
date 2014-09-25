import json

from django.test import TestCase
from django.test.client import RequestFactory

from basket import errors
from mock import Mock, patch

from news import tasks
from news.tasks import SUBSCRIBE
from news.utils import (
    get_accept_languages,
    get_best_language,
    language_code_is_valid,
    update_user_task
)


class UpdateUserTaskTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        patcher = patch('news.utils.lookup_subscriber')
        self.lookup_subscriber = patcher.start()
        self.addCleanup(patcher.stop)

        patcher = patch.object(tasks, 'update_user')
        self.update_user = patcher.start()
        self.addCleanup(patcher.stop)

    def assert_response_error(self, response, status_code, basket_code):
        self.assertEqual(response.status_code, status_code)
        response_data = json.loads(response.content)
        self.assertEqual(response_data['code'], basket_code)

    def assert_response_ok(self, response, **kwargs):
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertEqual(response_data['status'], 'ok')

        del response_data['status']
        self.assertEqual(response_data, kwargs)

    def test_invalid_newsletter(self):
        """If an invalid newsletter is given, return a 400 error."""
        request = self.factory.post('/')

        with patch('news.utils.newsletter_slugs') as newsletter_slugs:
            newsletter_slugs.return_value = ['foo', 'baz']
            response = update_user_task(request, SUBSCRIBE, {'newsletters': 'foo,bar'})

            self.assert_response_error(response, 400, errors.BASKET_INVALID_NEWSLETTER)

    def test_invalid_lang(self):
        """If the given lang is invalid, return a 400 error."""
        request = self.factory.post('/')

        with patch('news.utils.language_code_is_valid') as mock_language_code_is_valid:
            mock_language_code_is_valid.return_value = False
            response = update_user_task(request, SUBSCRIBE, {'lang': 'pt-BR'})

            self.assert_response_error(response, 400, errors.BASKET_INVALID_LANGUAGE)
            mock_language_code_is_valid.assert_called_with('pt-BR')

    def test_missing_email_and_sub(self):
        """
        If both the email and subscriber are missing, return a 400
        error.
        """
        request = self.factory.post('/')
        response = update_user_task(request, SUBSCRIBE)

        self.assert_response_error(response, 400, errors.BASKET_USAGE_ERROR)

    def test_success_no_sync(self):
        """
        If sync is False, do not generate a token via lookup_subscriber
        and return an OK response without a token.
        """
        request = self.factory.post('/')
        data = {'email': 'a@example.com'}

        response = update_user_task(request, SUBSCRIBE, data, sync=False)
        self.assert_response_ok(response)
        self.update_user.delay.assert_called_with(data, 'a@example.com', None, SUBSCRIBE, True)
        self.assertFalse(self.lookup_subscriber.called)

    def test_success_with_valid_newsletters(self):
        """
        If the specified newsletters are valid, return an OK response.
        """
        request = self.factory.post('/')
        data = {'email': 'a@example.com', 'newsletters': 'foo,bar'}

        with patch('news.utils.newsletter_slugs') as newsletter_slugs:
            newsletter_slugs.return_value = ['foo', 'bar']
            response = update_user_task(request, SUBSCRIBE, data, sync=False)
            self.assert_response_ok(response)

    def test_success_with_valid_lang(self):
        """If the specified language is valid, return an OK response."""
        request = self.factory.post('/')
        data = {'email': 'a@example.com', 'lang': 'pt-BR'}

        with patch('news.utils.language_code_is_valid') as mock_language_code_is_valid:
            mock_language_code_is_valid.return_value = True
            response = update_user_task(request, SUBSCRIBE, data, sync=False)
            self.assert_response_ok(response)

    def test_success_with_subscriber(self):
        """
        If no email is given but a subscriber is, use the subscriber's
        email.
        """
        request = self.factory.post('/')
        request.subscriber = Mock(email='a@example.com')
        response = update_user_task(request, SUBSCRIBE, {}, sync=False)

        self.assert_response_ok(response)
        self.update_user.delay.assert_called_with({}, 'a@example.com', None, SUBSCRIBE, True)

    def test_success_with_request_data(self):
        """
        If no data is provided, fall back to using the POST data from
        the request.
        """
        data = {'email': 'a@example.com'}
        request = self.factory.post('/', data)
        response = update_user_task(request, SUBSCRIBE, sync=False)

        self.assert_response_ok(response)
        self.update_user.delay.assert_called_with(data, 'a@example.com', None, SUBSCRIBE, True)

    def test_success_with_sync_and_subscriber(self):
        """
        If sync is True, and a subscriber is provided, do not call
        lookup_subscriber and return an OK response with the token and
        created == False.
        """
        request = self.factory.post('/')
        request.subscriber = Mock(email='a@example.com', token='mytoken')
        response = update_user_task(request, SUBSCRIBE, {}, sync=True)

        self.assert_response_ok(response, token='mytoken', created=False)
        self.update_user.delay.assert_called_with({}, 'a@example.com', 'mytoken', SUBSCRIBE, True)

    def test_success_with_sync_no_subscriber(self):
        """
        If sync is True, and a subscriber is not provided, look them up
        with lookup_subscriber and return an OK response with the token
        and created from the fetched subscriber.
        """
        request = self.factory.post('/')
        data = {'email': 'a@example.com'}
        subscriber = Mock(email='a@example.com', token='mytoken')
        self.lookup_subscriber.return_value = subscriber, None, True

        response = update_user_task(request, SUBSCRIBE, data, sync=True)

        self.assert_response_ok(response, token='mytoken', created=True)
        self.update_user.delay.assert_called_with(data, 'a@example.com', 'mytoken', SUBSCRIBE, True)


class TestGetAcceptLanguages(TestCase):
    # mostly stolen from bedrock

    def setUp(self):
        patcher = patch('news.utils.newsletter_languages', return_value=[
            'de', 'en', 'es', 'fr', 'id', 'pt-BR', 'ru', 'pl', 'hu'])
        self.addCleanup(patcher.stop)
        patcher.start()

    def _test(self, accept_lang, good_list):
        self.assertListEqual(get_accept_languages(accept_lang), good_list)

    def test_valid_lang_codes(self):
        """
        Should return a list of valid lang codes
        """
        self._test('fr-FR', ['fr'])
        self._test('en-us,en;q=0.5', ['en'])
        self._test('pt-pt,fr;q=0.8,it-it;q=0.5,de;q=0.3',
                   ['pt-PT', 'fr', 'it-IT', 'de'])
        self._test('ja-JP-mac,ja-JP;q=0.7,ja;q=0.3', ['ja-JP', 'ja'])
        self._test('foo,bar;q=0.5', ['foo', 'bar'])

    def test_invalid_lang_codes(self):
        """
        Should return a list of valid lang codes or an empty list
        """
        self._test('', [])
        self._test('en_us,en*;q=0.5', [])
        self._test('Chinese,zh-cn;q=0.5', ['zh-CN'])


class GetBestLanguageTests(TestCase):
    def setUp(self):
        patcher = patch('news.utils.newsletter_languages', return_value=[
            'de', 'en', 'es', 'fr', 'id', 'pt-BR', 'ru', 'pl', 'hu'])
        self.addCleanup(patcher.stop)
        patcher.start()

    def _test(self, langs_list, expected_lang):
        self.assertEqual(get_best_language(langs_list), expected_lang)

    def test_returns_first_good_lang(self):
        """Should return first language in the list that a newsletter supports."""
        self._test(['zh-TW', 'es', 'de', 'en'], 'es')
        self._test(['pt-PT', 'zh-TW', 'pt-BR', 'en'], 'pt-BR')

    def test_returns_first_lang_no_good(self):
        """Should return the first in the list if no supported are found."""
        self._test(['pt-PT', 'zh-TW', 'zh-CN', 'ar'], 'pt-PT')

    def test_no_langs(self):
        """Should return none if no langs given."""
        self._test([], None)


class TestLanguageCodeIsValid(TestCase):
    def test_empty_string(self):
        """Empty string is accepted as a language code"""
        self.assertTrue(language_code_is_valid(''))

    def test_none(self):
        """None is a TypeError"""
        with self.assertRaises(TypeError):
            language_code_is_valid(None)

    def test_zero(self):
        """0 is a TypeError"""
        with self.assertRaises(TypeError):
            language_code_is_valid(0)

    def test_exact_2_letter(self):
        """2-letter code that's in the list is valid"""
        self.assertTrue(language_code_is_valid('az'))

    def test_exact_3_letter(self):
        """3-letter code is valid.

        There are a few of these."""
        self.assertTrue(language_code_is_valid('azq'))

    def test_exact_5_letter(self):
        """5-letter code that's in the list is valid"""
        self.assertTrue(language_code_is_valid('az-BY'))

    def test_case_insensitive(self):
        """Matching is not case sensitive"""
        self.assertTrue(language_code_is_valid('az-BY'))
        self.assertTrue(language_code_is_valid('aZ'))
        self.assertTrue(language_code_is_valid('QW'))

    def test_wrong_length(self):
        """A code that's not a valid length is not valid."""
        self.assertFalse(language_code_is_valid('az-'))
        self.assertFalse(language_code_is_valid('a'))
        self.assertFalse(language_code_is_valid('azqr'))
        self.assertFalse(language_code_is_valid('az-BY2'))

    def test_wrong_format(self):
        """A code that's not a valid format is not valid."""
        self.assertFalse(language_code_is_valid('a2'))
        self.assertFalse(language_code_is_valid('asdfj'))
        self.assertFalse(language_code_is_valid('az_BY'))

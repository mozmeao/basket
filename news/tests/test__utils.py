# -*- coding: utf8 -*-

import json

from django.test import TestCase
from django.test.client import RequestFactory

from basket import errors
from mock import Mock, patch

from news import tasks
from news.models import BlockedEmail
from news.tasks import SUBSCRIBE
from news.utils import (
    email_block_list_cache,
    email_is_blocked,
    EmailValidationError,
    get_accept_languages,
    get_best_language,
    get_email_block_list,
    language_code_is_valid,
    validate_email,
)
from news.views import update_user_task


class EmailIsBlockedTests(TestCase):
    def tearDown(self):
        email_block_list_cache.clear()

    def test_email_block_list(self):
        """Should return a list from the database."""
        BlockedEmail.objects.create(email_domain='stuff.web')
        BlockedEmail.objects.create(email_domain='whatnot.dude')
        BlockedEmail.objects.create(email_domain='.ninja')
        blocklist = get_email_block_list()
        expected = set(['stuff.web', 'whatnot.dude', '.ninja'])
        self.assertSetEqual(set(blocklist), expected)

    @patch('news.utils.BlockedEmail')
    def test_email_is_blocked(self, BlockedEmailMock):
        """Asking if blocked should only hit the DB once."""
        BlockedEmailMock.objects.values_list.return_value = ['.ninja', 'stuff.web']
        self.assertTrue(email_is_blocked('dude@bowling.ninja'))
        self.assertTrue(email_is_blocked('walter@stuff.web'))
        self.assertFalse(email_is_blocked('donnie@example.com'))
        self.assertEqual(BlockedEmailMock.objects.values_list.call_count, 1)


class UpdateUserTaskTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        patcher = patch('news.utils.get_or_create_user_data')
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

    @patch('news.utils.get_best_language')
    def test_accept_lang(self, get_best_language_mock):
        """If accept_lang param is provided, should set the lang in data."""
        get_best_language_mock.return_value = 'pt'
        request = self.factory.post('/')
        data = {'email': 'dude@example.com', 'accept_lang': 'pt-pt,fr;q=0.8'}
        after_data = {'email': 'dude@example.com', 'lang': 'pt'}

        response = update_user_task(request, SUBSCRIBE, data, sync=False)
        self.assert_response_ok(response)
        self.update_user.delay.assert_called_with(after_data, 'dude@example.com',
                                                  None, SUBSCRIBE, True)
        self.assertFalse(self.lookup_subscriber.called)

    def test_invalid_accept_lang(self):
        """If accept_lang param is provided but invalid, return a 400."""
        request = self.factory.post('/')
        data = {'email': 'dude@example.com', 'accept_lang': 'the dude minds, man'}

        response = update_user_task(request, SUBSCRIBE, data, sync=False)
        self.assert_response_error(response, 400, errors.BASKET_INVALID_LANGUAGE)
        self.assertFalse(self.update_user.delay.called)
        self.assertFalse(self.lookup_subscriber.called)

    @patch('news.utils.get_best_language')
    def test_lang_overrides_accept_lang(self, get_best_language_mock):
        """
        If lang is provided it was from the user, and accept_lang isn't as reliable, so we should
        prefer lang.
        """
        get_best_language_mock.return_value = 'pt-BR'
        request = self.factory.post('/')
        data = {'email': 'a@example.com',
                'lang': 'de',
                'accept_lang': 'pt-BR'}

        response = update_user_task(request, SUBSCRIBE, data, sync=False)
        self.assert_response_ok(response)
        # basically asserts that the data['lang'] value wasn't changed.
        self.update_user.delay.assert_called_with(data, 'a@example.com', None, SUBSCRIBE, True)
        self.assertFalse(self.lookup_subscriber.called)

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
        If sync is False, do not generate a token via get_or_create_user_data
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

        with patch('news.utils.newsletter_and_group_slugs') as newsletter_slugs:
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
        get_or_create_user_data and return an OK response with the token and
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
        with get_or_create_user_data and return an OK response with the token
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

    def test_invalid_lang_codes_underscores(self):
        """
        Even though 'en_US' is invalid according to the spec, we get what it means.
        Let's accept it. Bug 1102652.
        """
        self._test('en_US', ['en'])
        self._test('pt_pt,fr;q=0.8,it_it;q=0.5,de;q=0.3',
                   ['pt-PT', 'fr', 'it-IT', 'de'])

    def test_invalid_lang_codes(self):
        """
        Should return a list of valid lang codes or an empty list
        """
        self._test('', [])
        self._test('en/us,en*;q=0.5', [])
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

    def test_returns_first_good_lang_2_letter(self):
        """Should return first 2 letter prefix language in the list that a newsletter supports."""
        self._test(['pt-PT', 'zh-TW', 'es-AR', 'ar'], 'es')

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


class TestValidateEmail(TestCase):
    def test_non_ascii_email_domain(self):
        """Should not raise exception, and should validate for non-ascii domains."""
        self.assertIsNone(validate_email(u'dude@黒川.日本'))
        self.assertIsNone(validate_email('dude@黒川.日本'))

    def test_valid_email(self):
        """Should return None for valid email."""
        self.assertIsNone(validate_email('dude@example.com'))
        self.assertIsNone(validate_email('dude@example.coop'))
        self.assertIsNone(validate_email('dude@example.biz'))

    def test_invalid_email(self):
        """Should raise exception for invalid email."""
        with self.assertRaises(EmailValidationError):
            validate_email('dude@home@example.com')

        with self.assertRaises(EmailValidationError):
            validate_email('')

        with self.assertRaises(EmailValidationError):
            validate_email(None)

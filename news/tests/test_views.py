# -*- coding: utf8 -*-

import json

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.urlresolvers import reverse
from django.test import TestCase
from django.test.client import RequestFactory

from basket import errors
from mock import Mock, patch

from news import models, views, utils
from news.models import APIUser
from news.newsletters import newsletter_languages, newsletter_fields
from news.tasks import SUBSCRIBE
from news.utils import email_block_list_cache


none_mock = Mock(return_value=None)


class GetInvolvedTests(TestCase):
    def setUp(self):
        self.interest = models.Interest.objects.create(title='Bowling',
                                                       interest_id='bowling')
        self.rf = RequestFactory()
        self.base_data = {
            'email': 'dude@example.com',
            'lang': 'en',
            'country': 'us',
            'name': 'The Dude',
            'interest_id': 'bowling',
            'format': 'T',
        }

        patcher = patch('news.views.validate_email')
        self.addCleanup(patcher.stop)
        self.validate_email = patcher.start()

        patcher = patch('news.views.update_get_involved')
        self.addCleanup(patcher.stop)
        self.update_get_involved = patcher.start()

    def tearDown(self):
        email_block_list_cache.clear()

    def _request(self, data):
        req = self.rf.post('/', data)
        resp = views.get_involved(req)
        return json.loads(resp.content)

    def test_successful_submission(self):
        resp = self._request(self.base_data)
        self.validate_email.assert_called_with(self.base_data['email'])
        self.assertEqual(resp['status'], 'ok', resp)
        self.update_get_involved.delay.assert_called_with('bowling', 'en', 'The Dude',
                                                          'dude@example.com', 'us', 'T',
                                                          False, None, None)

    @patch('news.utils.get_email_block_list')
    def test_blocked_email(self, get_email_block_mock):
        get_email_block_mock.return_value = ['example.com']
        resp = self._request(self.base_data)
        self.assertEqual(resp['status'], 'ok', resp)
        self.assertFalse(self.update_get_involved.delay.called)

    def test_requires_valid_interest(self):
        """Should only submit successfully with a valid interest_id."""
        self.base_data['interest_id'] = 'takin-it-easy'
        resp = self._request(self.base_data)
        self.assertEqual(resp['status'], 'error', resp)
        self.assertEqual(resp['desc'], 'invalid interest_id', resp)
        self.assertFalse(self.update_get_involved.called)

        del self.base_data['interest_id']
        resp = self._request(self.base_data)
        self.assertEqual(resp['status'], 'error', resp)
        self.assertEqual(resp['desc'], 'interest_id is required', resp)
        self.assertFalse(self.update_get_involved.called)

    def test_requires_valid_email(self):
        """Should only submit successfully with a valid email."""
        self.validate_email.side_effect = views.EmailValidationError('invalid email')
        resp = self._request(self.base_data)
        self.assertEqual(resp['status'], 'error', resp)
        self.assertEqual(resp['code'], errors.BASKET_INVALID_EMAIL, resp)
        self.validate_email.assert_called_with(self.base_data['email'])
        self.assertFalse(self.update_get_involved.called)

        del self.base_data['email']
        resp = self._request(self.base_data)
        self.assertEqual(resp['status'], 'error', resp)
        self.assertEqual(resp['desc'], 'email is required', resp)
        self.assertFalse(self.update_get_involved.called)

    def test_requires_valid_lang(self):
        """Should only submit successfully with a valid lang."""
        self.base_data['lang'] = 'this is not a lang'
        resp = self._request(self.base_data)
        self.assertEqual(resp['status'], 'error', resp)
        self.assertEqual(resp['desc'], 'invalid language', resp)
        self.assertFalse(self.update_get_involved.called)

        del self.base_data['lang']
        resp = self._request(self.base_data)
        self.assertEqual(resp['status'], 'error', resp)
        self.assertEqual(resp['desc'], 'lang is required', resp)
        self.assertFalse(self.update_get_involved.called)

    def test_requires_name(self):
        """Should only submit successfully with a name provided."""
        del self.base_data['name']
        resp = self._request(self.base_data)
        self.assertEqual(resp['status'], 'error', resp)
        self.assertEqual(resp['desc'], 'name is required', resp)
        self.assertFalse(self.update_get_involved.called)

    def test_requires_country(self):
        """Should only submit successfully with a country provided."""
        del self.base_data['country']
        resp = self._request(self.base_data)
        self.assertEqual(resp['status'], 'error', resp)
        self.assertEqual(resp['desc'], 'country is required', resp)
        self.assertFalse(self.update_get_involved.called)

    def test_optional_parameters(self):
        """Should pass through optional parameters."""
        self.base_data.update({
            'subscribe': 'ok',
            'message': 'I like bowling',
            'source_url': 'https://arewebowlingyet.com/',
        })

        resp = self._request(self.base_data)
        self.assertEqual(resp['status'], 'ok', resp)
        self.update_get_involved.delay.assert_called_with('bowling', 'en', 'The Dude',
                                                          'dude@example.com', 'us', 'T',
                                                          'ok', 'I like bowling',
                                                          'https://arewebowlingyet.com/')


@patch('news.views.update_fxa_info')
class FxAccountsTest(TestCase):
    def ssl_post(self, url, params=None, **extra):
        """Fake a post that used SSL"""
        extra['wsgi.url_scheme'] = 'https'
        params = params or {}
        return self.client.post(url, data=params, **extra)

    def test_requires_ssl(self, fxa_mock):
        """fxa-register requires SSL"""
        resp = self.client.post('/news/fxa-register/', {
            'email': 'dude@example.com',
            'fxa_id': 'the dude has a Fx account.',
            'accept_lang': 'de',
        })
        self.assertEqual(resp.status_code, 401, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(errors.BASKET_SSL_REQUIRED, data['code'])
        self.assertFalse(fxa_mock.delay.called)

    def test_requires_api_key(self, fxa_mock):
        """fxa-register requires API key"""
        # Use SSL but no API key
        resp = self.ssl_post('/news/fxa-register/', {
            'email': 'dude@example.com',
            'fxa_id': 'the dude has a Fx account.'
        })
        self.assertEqual(resp.status_code, 401, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(errors.BASKET_AUTH_ERROR, data['code'])
        self.assertFalse(fxa_mock.delay.called)

    def test_requires_fxa_id(self, fxa_mock):
        """fxa-register requires Firefox Account ID"""
        auth = APIUser.objects.create(name="test")
        resp = self.ssl_post('/news/fxa-register/', {
            'email': 'dude@example.com',
            'accept_lang': 'de',
            'api-key': auth.api_key,
        })
        self.assertEqual(resp.status_code, 401, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(errors.BASKET_USAGE_ERROR, data['code'])
        self.assertFalse(fxa_mock.delay.called)

    def test_requires_email(self, fxa_mock):
        """fxa-register requires email address"""
        auth = APIUser.objects.create(name="test")
        resp = self.ssl_post('/news/fxa-register/', {
            'fxa_id': 'the dude has a Fx account.',
            'accept_lang': 'de',
            'api-key': auth.api_key,
        })
        self.assertEqual(resp.status_code, 401, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(errors.BASKET_USAGE_ERROR, data['code'])
        self.assertFalse(fxa_mock.delay.called)

    def test_requires_lang(self, fxa_mock):
        """fxa-register requires language"""
        auth = APIUser.objects.create(name="test")
        resp = self.ssl_post('/news/fxa-register/', {
            'email': 'dude@example.com',
            'fxa_id': 'the dude has a Fx account.',
            'api-key': auth.api_key,
        })
        self.assertEqual(resp.status_code, 401, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(errors.BASKET_USAGE_ERROR, data['code'])
        self.assertFalse(fxa_mock.delay.called)

    def test_requires_valid_lang(self, fxa_mock):
        """fxa-register requires language"""
        auth = APIUser.objects.create(name="test")
        resp = self.ssl_post('/news/fxa-register/', {
            'email': 'dude@example.com',
            'fxa_id': 'the dude has a Fx account.',
            'accept_lang': 'Phones ringing Dude.',
            'api-key': auth.api_key,
        })
        self.assertEqual(resp.status_code, 400, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(errors.BASKET_INVALID_LANGUAGE, data['code'])
        self.assertFalse(fxa_mock.delay.called)

    def test_with_ssl_and_api_key(self, fxa_mock):
        """fxa-register should succeed with SSL, API Key, and data."""
        auth = APIUser.objects.create(name="test")
        request_data = {
            'email': 'dude@example.com',
            'fxa_id': 'the dude has a Fx account.',
            'api-key': auth.api_key,
            'accept_lang': 'de',
            'source_url': 'https://el-dudarino.org',
        }
        resp = self.ssl_post('/news/fxa-register/', request_data)
        self.assertEqual(resp.status_code, 200, resp.content)
        data = json.loads(resp.content)
        self.assertEqual('ok', data['status'])
        fxa_mock.delay.assert_called_once_with(request_data['email'], 'de',
                                               request_data['fxa_id'],
                                               source_url='https://el-dudarino.org')

    def test_skip_welcome(self, fxa_mock):
        """Should pass skip_welcome to the task."""
        auth = APIUser.objects.create(name="test")
        request_data = {
            'email': 'dude@example.com',
            'fxa_id': 'the dude has a Fx account.',
            'api-key': auth.api_key,
            'accept_lang': 'de',
            'skip_welcome': 'y',
        }
        resp = self.ssl_post('/news/fxa-register/', request_data)
        self.assertEqual(resp.status_code, 200, resp.content)
        data = json.loads(resp.content)
        self.assertEqual('ok', data['status'])
        fxa_mock.delay.assert_called_once_with(request_data['email'], 'de',
                                               request_data['fxa_id'], skip_welcome=True)


@patch.dict('news.newsletters.SMS_MESSAGES', {'SMS_Android': 'My_Sherona'})
class SubscribeSMSTests(TestCase):
    def setUp(self):
        cache.clear()
        self.rf = RequestFactory()
        patcher = patch.object(views, 'add_sms_user')
        self.add_sms_user = patcher.start()
        self.addCleanup(patcher.stop)

    def _request(self, **data):
        return views.subscribe_sms(self.rf.post('/', data))

    def test_valid_subscribe(self):
        self._request(mobile_number='9198675309')
        self.add_sms_user.delay.assert_called_with('SMS_Android', '19198675309', False)

    def test_invalid_number(self):
        resp = self._request(mobile_number='9198675309999')
        self.assertFalse(self.add_sms_user.delay.called)
        self.assertEqual(resp.status_code, 400, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(errors.BASKET_USAGE_ERROR, data['code'])
        self.assertIn('mobile_number', data['desc'])

    def test_missing_number(self):
        resp = self._request()
        self.assertFalse(self.add_sms_user.delay.called)
        self.assertEqual(resp.status_code, 400, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(errors.BASKET_USAGE_ERROR, data['code'])
        self.assertIn('mobile_number', data['desc'])

    def test_invalid_message_name(self):
        resp = self._request(mobile_number='9198675309', msg_name='The_DUDE')
        self.assertFalse(self.add_sms_user.delay.called)
        self.assertEqual(resp.status_code, 400, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(errors.BASKET_USAGE_ERROR, data['code'])
        self.assertIn('msg_name', data['desc'])

    def test_phone_number_rate_limit(self):
        self.client.post('/news/subscribe_sms/', {'mobile_number': '9198675309'})
        self.add_sms_user.delay.assert_called_with('SMS_Android', '19198675309', False)
        self.add_sms_user.reset_mock()

        resp = self.client.post('/news/subscribe_sms/', {'mobile_number': '9198675309'})
        data = json.loads(resp.content)
        self.assertEqual(data, {
            'status': 'error',
            'desc': 'rate limit reached',
            'code': errors.BASKET_USAGE_ERROR,
        })
        self.assertFalse(self.add_sms_user.delay.called)


@patch('news.views.validate_email', none_mock)
@patch('news.views.update_user_task')
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
        req = self.rf.generic('POST', '/news/subscribe/',
                              data='email=dude+abides@example.com&newsletters=firefox-os',
                              content_type='text/plain; charset=UTF-8')
        self.assertFalse(bool(req.POST))
        views.subscribe(req)
        update_user_mock.assert_called_with(req, views.SUBSCRIBE, data={
            'email': 'dude+abides@example.com',
            'newsletters': 'firefox-os',
        }, optin=False, sync=False)


class SubscribeEmailValidationTest(TestCase):
    email = 'dude@example.com'
    data = {
        'email': email,
        'newsletters': 'os',
    }
    view = 'subscribe'

    def setUp(self):
        self.rf = RequestFactory()

    @patch('news.views.validate_email')
    def test_invalid_email(self, mock_validate):
        """Should return proper error for invalid email."""
        mock_validate.side_effect = utils.EmailValidationError('Invalid email')
        view = getattr(views, self.view)
        resp = view(self.rf.post('/', self.data))
        resp_data = json.loads(resp.content)
        mock_validate.assert_called_with(self.email)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp_data['status'], 'error')
        self.assertEqual(resp_data['code'], errors.BASKET_INVALID_EMAIL)
        self.assertNotIn('suggestion', resp_data)

    @patch('news.views.validate_email')
    def test_invalid_email_suggestion(self, mock_validate):
        """Should return proper error for invalid email."""
        mock_validate.side_effect = utils.EmailValidationError('Invalid email',
                                                               'walter@example.com')
        view = getattr(views, self.view)
        resp = view(self.rf.post('/', self.data))
        resp_data = json.loads(resp.content)
        mock_validate.assert_called_with(self.email)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp_data['status'], 'error')
        self.assertEqual(resp_data['code'], errors.BASKET_INVALID_EMAIL)
        self.assertEqual(resp_data['suggestion'], 'walter@example.com')

    @patch('news.views.update_user_task')
    def test_non_ascii_email_fxos_malformed_post(self, update_user_mock):
        """Should be able to parse data from the raw request body including non-ascii chars."""
        req = self.rf.generic('POST', '/news/subscribe/',
                              data='email=dude@黒川.日本&newsletters=firefox-os',
                              content_type='text/plain; charset=UTF-8')
        views.subscribe(req)
        update_user_mock.assert_called_with(req, views.SUBSCRIBE, data={
            'email': u'dude@黒川.日本',
            'newsletters': 'firefox-os',
        }, optin=False, sync=False)

    @patch('news.views.update_user_task')
    def test_non_ascii_email(self, update_user_mock):
        """Should be able to accept valid email including non-ascii chars."""
        req = self.rf.post('/news/subscribe/', data={'email': 'dude@黒川.日本',
                                                     'newsletters': 'firefox-os'})
        views.subscribe(req)
        update_user_mock.assert_called_with(req, views.SUBSCRIBE, data={
            'email': u'dude@黒川.日本',
            'newsletters': 'firefox-os',
        }, optin=False, sync=False)

    @patch('news.views.update_user_task')
    def test_empty_email_invalid(self, update_user_mock):
        """Should report an error for missing or empty value."""
        req = self.rf.post('/news/subscribe/', data={'email': '',
                                                     'newsletters': 'firefox-os'})
        resp = views.subscribe(req)
        resp_data = json.loads(resp.content)
        self.assertEqual(resp_data['status'], 'error')
        self.assertEqual(resp_data['code'], errors.BASKET_INVALID_EMAIL)
        self.assertFalse(update_user_mock.called)

        # no email at all
        req = self.rf.post('/news/subscribe/', data={'newsletters': 'firefox-os'})
        resp = views.subscribe(req)
        resp_data = json.loads(resp.content)
        self.assertEqual(resp_data['status'], 'error')
        self.assertEqual(resp_data['code'], errors.BASKET_USAGE_ERROR)
        self.assertFalse(update_user_mock.called)


class RecoveryMessageEmailValidationTest(SubscribeEmailValidationTest):
    view = 'send_recovery_message'


class ViewsPatcherMixin(object):
    def _patch_views(self, name):
        patcher = patch('news.views.' + name)
        setattr(self, name, patcher.start())
        self.addCleanup(patcher.stop)


class SubscribeTests(ViewsPatcherMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        self._patch_views('update_user_task')
        self._patch_views('validate_email')
        self._patch_views('has_valid_api_key')

    def tearDown(self):
        cache.clear()
        email_block_list_cache.clear()

    def assert_response_error(self, response, status_code, basket_code):
        self.assertEqual(response.status_code, status_code)
        response_data = json.loads(response.content)
        self.assertEqual(response_data['code'], basket_code)

    def test_newsletters_missing(self):
        """If the newsletters param is missing, return a 400."""
        request = self.factory.post('/')
        response = views.subscribe(request)
        self.assert_response_error(response, 400, errors.BASKET_USAGE_ERROR)

    def test_optin_ssl_required(self):
        """
        If optin is 'Y' but the request isn't HTTPS, disable optin.
        """
        request_data = {'newsletters': 'asdf', 'optin': 'Y', 'email': 'dude@example.com'}
        request = self.factory.post('/', request_data)
        request.is_secure = lambda: False
        self.has_valid_api_key.return_value = True

        response = views.subscribe(request)
        self.assertEqual(response, self.update_user_task.return_value)
        self.update_user_task.assert_called_with(request, SUBSCRIBE, data=request_data,
                                                 optin=False, sync=False)

    def test_optin_valid_api_key_required(self):
        """
        If optin is 'Y' but the API key isn't valid, disable optin.
        """
        request_data = {'newsletters': 'asdf', 'optin': 'Y', 'email': 'dude@example.com'}
        request = self.factory.post('/', request_data)
        request.is_secure = lambda: True
        self.has_valid_api_key.return_value = False

        response = views.subscribe(request)
        self.assertEqual(response, self.update_user_task.return_value)
        self.update_user_task.assert_called_with(request, SUBSCRIBE, data=request_data,
                                                 optin=False, sync=False)

    def test_sync_ssl_required(self):
        """
        If sync set to 'Y' and the request isn't HTTPS, return a 401.
        """
        request = self.factory.post('/', {'newsletters': 'asdf', 'sync': 'Y',
                                          'email': 'dude@example.com'})
        request.is_secure = lambda: False
        response = views.subscribe(request)
        self.assert_response_error(response, 401, errors.BASKET_SSL_REQUIRED)

    def test_sync_invalid_api_key(self):
        """
        If sync is set to 'Y' and the request has an invalid API key,
        return a 401.
        """
        request = self.factory.post('/', {'newsletters': 'asdf', 'sync': 'Y',
                                          'email': 'dude@example.com'})
        request.is_secure = lambda: True
        self.has_valid_api_key.return_value = False

        response = views.subscribe(request)
        self.assert_response_error(response, 401, errors.BASKET_AUTH_ERROR)
        self.has_valid_api_key.assert_called_with(request)

    def test_email_validation_error(self):
        """
        If validate_email raises an EmailValidationError, return an
        invalid email response.
        """
        request_data = {'newsletters': 'asdf', 'email': 'dude@example.com'}
        request = self.factory.post('/', request_data)
        error = utils.EmailValidationError('blah')
        self.validate_email.side_effect = error

        with patch('news.views.invalid_email_response') as invalid_email_response:
            response = views.subscribe(request)
            self.assertEqual(response, invalid_email_response.return_value)
            self.validate_email.assert_called_with(request_data['email'])
            invalid_email_response.assert_called_with(error)

    @patch('news.utils.get_email_block_list')
    def test_blocked_email(self, get_block_list_mock):
        """Test basic success case with no optin or sync."""
        get_block_list_mock.return_value = ['example.com']
        request_data = {'newsletters': 'news,lets', 'optin': 'N', 'sync': 'N',
                        'email': 'dude@example.com'}
        request = self.factory.post('/', request_data)

        response = views.subscribe(request)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.update_user_task.called)

    def test_success(self):
        """Test basic success case with no optin or sync."""
        request_data = {'newsletters': 'news,lets', 'optin': 'N', 'sync': 'N',
                        'email': 'dude@example.com', 'first_name': 'The', 'last_name': 'Dude'}
        request = self.factory.post('/', request_data)

        response = views.subscribe(request)

        self.assertEqual(response, self.update_user_task.return_value)
        self.validate_email.assert_called_with(request_data['email'])
        self.update_user_task.assert_called_with(request, SUBSCRIBE, data=request_data,
                                                 optin=False, sync=False)

    def test_success_sync_optin(self):
        """Test success case with optin and sync."""
        request_data = {'newsletters': 'news,lets', 'optin': 'Y', 'sync': 'Y',
                        'email': 'dude@example.com'}
        request = self.factory.post('/', request_data)
        request.is_secure = lambda: True
        self.has_valid_api_key.return_value = True

        response = views.subscribe(request)

        self.has_valid_api_key.assert_called_with(request)
        self.assertEqual(response, self.update_user_task.return_value)
        self.validate_email.assert_called_with('dude@example.com')
        self.update_user_task.assert_called_with(request, SUBSCRIBE, data=request_data,
                                                     optin=True, sync=True)

    def test_success_sync_optin_lowercase(self):
        """Test success case with optin and sync, using lowercase y."""
        request_data = {'newsletters': 'news,lets', 'optin': 'y', 'sync': 'y',
                        'email': 'dude@example.com'}
        request = self.factory.post('/', request_data)
        request.is_secure = lambda: True

        with patch('news.views.has_valid_api_key') as has_valid_api_key:
            has_valid_api_key.return_value = True
            response = views.subscribe(request)
            has_valid_api_key.assert_called_with(request)

            self.assertEqual(response, self.update_user_task.return_value)
            self.validate_email.assert_called_with('dude@example.com')
            self.update_user_task.assert_called_with(request, SUBSCRIBE, data=request_data,
                                                     optin=True, sync=True)


class TestRateLimitingFunctions(ViewsPatcherMixin, TestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def test_ip_rate_limit_key(self):
        req = self.rf.get('/', HTTP_X_CLUSTER_CLIENT_IP='1.1.1.1', REMOTE_ADDR='2.2.2.2')
        self.assertEqual(views.ip_rate_limit_key(None, req), '1.1.1.1')

    def test_ip_rate_limit_key_fallback(self):
        req = self.rf.get('/', REMOTE_ADDR='2.2.2.2')
        self.assertEqual(views.ip_rate_limit_key(None, req), '2.2.2.2')

    def test_source_ip_rate_limit_key_no_header(self):
        req = self.rf.get('/')
        self.assertIsNone(views.source_ip_rate_limit_key(None, req))

    def test_source_ip_rate_limit_key(self):
        req = self.rf.get('/', HTTP_X_SOURCE_IP='2.2.2.2')
        self.assertEqual(views.source_ip_rate_limit_key(None, req), '2.2.2.2')

    def test_ip_rate_limit_rate(self):
        req = self.rf.get('/', HTTP_X_CLUSTER_CLIENT_IP='1.1.1.1')
        self.assertEqual(views.ip_rate_limit_rate(None, req), '40/m')

    def test_ip_rate_limit_rate_internal(self):
        req = self.rf.get('/', HTTP_X_CLUSTER_CLIENT_IP='10.1.1.1')
        self.assertEqual(views.ip_rate_limit_rate(None, req), '400/m')

    def test_source_ip_rate_limit_rate_no_header(self):
        req = self.rf.get('/')
        self.assertIsNone(views.source_ip_rate_limit_rate(None, req))

    def test_source_ip_rate_limit_rate(self):
        req = self.rf.get('/', HTTP_X_SOURCE_IP='2.2.2.2')
        self.assertEqual(views.source_ip_rate_limit_rate(None, req), '40/m')


class TestNewslettersAPI(TestCase):
    def setUp(self):
        self.url = reverse('newsletters_api')
        self.rf = RequestFactory()

    def test_newsletters_view(self):
        # We can fetch the newsletter data
        nl1 = models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=False,
            languages='en-US,fr',
            vendor_id='VENDOR1',
        )

        models.Newsletter.objects.create(slug='slug2', vendor_id='VENDOR2')
        models.Newsletter.objects.create(slug='slug3', vendor_id='VENDOR3', private=True)

        req = self.rf.get(self.url)
        resp = views.newsletters(req)
        data = json.loads(resp.content)
        newsletters = data['newsletters']
        self.assertEqual(3, len(newsletters))
        # Find the 'slug' newsletter in the response
        obj = newsletters['slug']

        self.assertTrue(newsletters['slug3']['private'])
        self.assertEqual(nl1.title, obj['title'])
        self.assertEqual(nl1.active, obj['active'])
        for lang in ['en-US', 'fr']:
            self.assertIn(lang, obj['languages'])

    def test_strip_languages(self):
        # If someone edits Newsletter and puts whitespace in the languages
        # field, we strip it on save
        nl1 = models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=False,
            languages='en-US, fr, de ',
            vendor_id='VENDOR1',
        )
        nl1 = models.Newsletter.objects.get(id=nl1.id)
        self.assertEqual('en-US,fr,de', nl1.languages)

    def test_newsletter_languages(self):
        # newsletter_languages() returns the set of languages
        # of the newsletters
        # (Note that newsletter_languages() is not part of the external
        # API, but is used internally)
        models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=False,
            languages='en-US',
            vendor_id='VENDOR1',
        )
        models.Newsletter.objects.create(
            slug='slug2',
            title='title',
            active=False,
            languages='fr, de ',
            vendor_id='VENDOR2',
        )
        models.Newsletter.objects.create(
            slug='slug3',
            title='title',
            active=False,
            languages='en-US, fr',
            vendor_id='VENDOR3',
        )
        expect = set(['en-US', 'fr', 'de'])
        self.assertEqual(expect, newsletter_languages())

    def test_newsletters_cached(self):
        models.Newsletter.objects.create(
            slug='slug',
            title='title',
            vendor_id='VEND1',
            active=False,
            languages='en-US, fr, de ',
        )
        # This should get the data cached
        newsletter_fields()
        # Now request it again and it shouldn't have to generate the
        # data from scratch.
        with patch('news.newsletters._get_newsletters_data') as get:
            newsletter_fields()
        self.assertFalse(get.called)

    def test_cache_clearing(self):
        # Our caching of newsletter data doesn't result in wrong answers
        # when newsletters change
        models.Newsletter.objects.create(
            slug='slug',
            title='title',
            vendor_id='VEND1',
            active=False,
            languages='en-US, fr, de ',
        )
        vendor_ids = newsletter_fields()
        self.assertEqual([u'VEND1'], vendor_ids)
        # Now add another newsletter
        models.Newsletter.objects.create(
            slug='slug2',
            title='title2',
            vendor_id='VEND2',
            active=False,
            languages='en-US, fr, de ',
        )
        vendor_ids2 = set(newsletter_fields())
        self.assertEqual(set([u'VEND1', u'VEND2']), vendor_ids2)

    def test_cache_clear_on_delete(self):
        # Our caching of newsletter data doesn't result in wrong answers
        # when newsletters are deleted
        nl1 = models.Newsletter.objects.create(
            slug='slug',
            title='title',
            vendor_id='VEND1',
            active=False,
            languages='en-US, fr, de ',
        )
        vendor_ids = newsletter_fields()
        self.assertEqual([u'VEND1'], vendor_ids)
        # Now delete it
        nl1.delete()
        vendor_ids = newsletter_fields()
        self.assertEqual([], vendor_ids)


class RecoveryViewTest(TestCase):
    # See the task tests for more
    def setUp(self):
        self.url = reverse('send_recovery_message')

    def tearDown(self):
        email_block_list_cache.clear()

    def test_no_email(self):
        """email not provided - return 400"""
        resp = self.client.post(self.url, {})
        self.assertEqual(400, resp.status_code)

    def test_bad_email(self):
        """Invalid email should return 400"""
        resp = self.client.post(self.url, {'email': 'not_an_email'})
        self.assertEqual(400, resp.status_code)

    @patch('news.views.validate_email', none_mock)
    @patch('news.views.get_user_data', autospec=True)
    def test_unknown_email(self, mock_get_user_data):
        """Unknown email should return 404"""
        email = 'dude@example.com'
        mock_get_user_data.return_value = None
        resp = self.client.post(self.url, {'email': email})
        self.assertEqual(404, resp.status_code)

    @patch('news.utils.get_email_block_list')
    @patch('news.views.send_recovery_message_task.delay', autospec=True)
    def test_blocked_email(self, mock_send_recovery_message_task,
                           mock_get_email_block_list):
        """email provided - pass to the task, return 200"""
        email = 'dude@example.com'
        mock_get_email_block_list.return_value = ['example.com']
        # It should pass the email to the task
        resp = self.client.post(self.url, {'email': email})
        self.assertEqual(200, resp.status_code)
        self.assertFalse(mock_send_recovery_message_task.called)

    @patch('news.views.validate_email', none_mock)
    @patch('news.views.get_user_data', autospec=True)
    @patch('news.views.send_recovery_message_task.delay', autospec=True)
    def test_known_email(self, mock_send_recovery_message_task,
                         mock_get_user_data):
        """email provided - pass to the task, return 200"""
        email = 'dude@example.com'
        mock_get_user_data.return_value = {'dummy': 2}
        # It should pass the email to the task
        resp = self.client.post(self.url, {'email': email})
        self.assertEqual(200, resp.status_code)
        mock_send_recovery_message_task.assert_called_with(email)


class TestValidateEmail(TestCase):
    email = 'dude@example.com'

    def test_valid_email(self):
        """Should return without raising an exception for a valid email."""
        self.assertIsNone(utils.validate_email(self.email))

    @patch('news.utils.dj_validate_email')
    def test_invalid_email(self, dj_validate_email):
        """Should raise an exception for an invalid email."""
        dj_validate_email.side_effect = ValidationError('Invalid email')
        with self.assertRaises(utils.EmailValidationError):
            utils.validate_email(self.email)

import json
from django.test.utils import override_settings

from django.conf import settings
from django.core.urlresolvers import reverse
from django.http import HttpResponse
from django.test import TestCase
from django.test.client import RequestFactory

from mock import ANY, call, patch

from basket import errors

from news import models, tasks, views
from news.backends.common import NewsletterException
from news.models import Newsletter, APIUser
from news.utils import look_for_user, get_user_data


class UpdateFxAInfoTest(TestCase):
    def setUp(self):
        patcher = patch.object(tasks, 'send_message')
        self.addCleanup(patcher.stop)
        self.send_message = patcher.start()

        patcher = patch.object(tasks, 'apply_updates')
        self.addCleanup(patcher.stop)
        self.apply_updates = patcher.start()

        patcher = patch.object(tasks, 'get_external_user_data')
        self.addCleanup(patcher.stop)
        self.get_external_user_data = patcher.start()

    def test_new_user(self):
        """Adding a new user to the DB should add fxa_id."""
        self.get_external_user_data.return_value = None
        email = 'dude@example.com'
        fxa_id = 'the fxa abides'

        tasks.update_fxa_info(email, 'de', fxa_id)
        sub = models.Subscriber.objects.get(email=email)
        self.assertEqual(sub.fxa_id, fxa_id)

        self.apply_updates.assert_called_once_with(settings.EXACTTARGET_DATA, {
            'EMAIL_ADDRESS_': email,
            'TOKEN': sub.token,
            'FXA_ID': fxa_id,
            'FXA_LANGUAGE_ISO2': 'de',
            'SOURCE_URL': 'https://accounts.firefox.com',
            'MODIFIED_DATE_': ANY,
        })
        self.get_external_user_data.assert_called_with(email=email)
        self.send_message.assert_called_with('de_{0}'.format(tasks.FXACCOUNT_WELCOME),
                                             email, sub.token, 'H')

    def test_user_in_et_not_basket(self):
        """A user could exist in basket but not ET, should still work."""
        self.get_external_user_data.return_value = None
        email = 'dude@example.com'
        fxa_id = 'the fxa abides'

        models.Subscriber.objects.create(email=email)
        tasks.update_fxa_info(email, 'de', fxa_id)
        sub = models.Subscriber.objects.get(email=email)
        self.assertEqual(sub.fxa_id, fxa_id)

        self.apply_updates.assert_called_once_with(settings.EXACTTARGET_DATA, {
            'EMAIL_ADDRESS_': email,
            'TOKEN': sub.token,
            'FXA_ID': fxa_id,
            'FXA_LANGUAGE_ISO2': 'de',
            'SOURCE_URL': 'https://accounts.firefox.com',
            'MODIFIED_DATE_': ANY,
        })
        self.get_external_user_data.assert_called_with(email=email)
        self.send_message.assert_called_with('de_{0}'.format(tasks.FXACCOUNT_WELCOME),
                                             email, sub.token, 'H')

    def test_existing_user_not_in_basket(self):
        """Adding a user already in ET but not basket should preserve token."""
        email = 'dude@example.com'
        fxa_id = 'the fxa abides'
        token = 'hehe... you said **token**.'
        self.get_external_user_data.return_value = {
            'email': email,
            'token': token,
            'lang': 'de',
            'format': '',
        }
        tasks.update_fxa_info(email, 'de', fxa_id)
        sub = models.Subscriber.objects.get(email=email)
        self.assertEqual(sub.fxa_id, fxa_id)
        self.assertEqual(sub.token, token)

        self.apply_updates.assert_called_once_with(settings.EXACTTARGET_DATA, {
            'EMAIL_ADDRESS_': email,
            'TOKEN': token,
            'FXA_ID': fxa_id,
            'MODIFIED_DATE_': ANY,
            'FXA_LANGUAGE_ISO2': 'de',
        })
        self.get_external_user_data.assert_called_with(email=email)
        self.send_message.assert_called_with('de_{0}'.format(tasks.FXACCOUNT_WELCOME),
                                             email, sub.token, '')

    def test_existing_user(self):
        """Adding a fxa_id to an existing user shouldn't modify other things."""
        email = 'dude@example.com'
        fxa_id = 'the fxa abides'
        old_sub = models.Subscriber.objects.create(email=email)
        self.get_external_user_data.return_value = {
            'email': email,
            'token': old_sub.token,
            'lang': 'de',
            'format': 'T',
        }
        tasks.update_fxa_info(email, 'de', fxa_id)
        sub = models.Subscriber.objects.get(email=email)
        self.assertEqual(sub.fxa_id, fxa_id)

        self.apply_updates.assert_called_once_with(settings.EXACTTARGET_DATA, {
            'EMAIL_ADDRESS_': email,
            'TOKEN': old_sub.token,
            'FXA_ID': fxa_id,
            'MODIFIED_DATE_': ANY,
            'FXA_LANGUAGE_ISO2': 'de',
        })
        self.send_message.assert_called_with('de_{0}_T'.format(tasks.FXACCOUNT_WELCOME),
                                             email, sub.token, 'T')


class UpdateGetInvolvedTests(TestCase):
    def setUp(self):
        patcher = patch.object(tasks, 'send_message')
        self.addCleanup(patcher.stop)
        self.send_message = patcher.start()

        patcher = patch.object(tasks, 'send_welcomes')
        self.addCleanup(patcher.stop)
        self.send_welcomes = patcher.start()

        patcher = patch.object(tasks, 'apply_updates')
        self.addCleanup(patcher.stop)
        self.apply_updates = patcher.start()

        patcher = patch('news.tasks.get_user_data')
        self.addCleanup(patcher.stop)
        self.get_user_data = patcher.start()

        self.interest = models.Interest.objects.create(title='Bowling',
                                                       interest_id='bowling',
                                                       _welcome_id='welcome_bowling')
        Newsletter.objects.create(slug='about-mozilla', vendor_id='ABOUT_MOZILLA')
        Newsletter.objects.create(slug='get-involved', vendor_id='GET_INVOLVED')

    @override_settings(EXACTTARGET_DATA='DATA_FOR_DUDE',
                       EXACTTARGET_INTERESTS='DUDE_IS_INTERESTED')
    def test_new_user_interested(self):
        """Successful submission of the form for new user."""
        email = 'walter@example.com'
        self.get_user_data.return_value = None
        tasks.update_get_involved('bowling', 'en', 'Walter', email,
                                  'US', 'Y', 'It really tied the room together.', None)
        token = models.Subscriber.objects.get(email=email).token
        self.apply_updates.assert_has_calls([
            call(settings.EXACTTARGET_DATA, {
                'EMAIL_ADDRESS_': email,
                'MODIFIED_DATE_': ANY,
                'LANGUAGE_ISO2': 'en',
                'COUNTRY_': 'US',
                'TOKEN': token,
                'ABOUT_MOZILLA_FLG': 'Y',
                'ABOUT_MOZILLA_DATE': ANY,
            }),
            call(settings.EXACTTARGET_INTERESTS, {
                'TOKEN': token,
                'INTEREST': 'bowling',
            }),
        ])
        self.send_message.assert_called_with('en_welcome_bowling', email, token, 'H')
        self.send_welcomes.assert_called_once_with({
            'email': email,
            'token': token,
            'lang': 'en',
        }, ['about-mozilla'], 'H')

    @override_settings(EXACTTARGET_DATA='DATA_FOR_DUDE',
                       EXACTTARGET_INTERESTS='DUDE_IS_INTERESTED')
    def test_existing_user_interested(self):
        """Successful submission of the form for existing newsletter user."""
        email = 'walter@example.com'
        sub = models.Subscriber.objects.create(email=email)
        token = sub.token
        self.get_user_data.return_value = {
            'format': 'T',
            'token': token,
            'newsletters': ['about-mozilla', 'mozilla-and-you'],
        }
        tasks.update_get_involved('bowling', 'en', 'Walter', email,
                                  'US', 'Y', 'It really tied the room together.', None)
        self.apply_updates.assert_has_calls([
            call(settings.EXACTTARGET_DATA, {
                'EMAIL_ADDRESS_': 'walter@example.com',
                'MODIFIED_DATE_': ANY,
                'LANGUAGE_ISO2': 'en',
                'COUNTRY_': 'US',
                'TOKEN': token,
            }),
            call(settings.EXACTTARGET_INTERESTS, {
                'TOKEN': token,
                'INTEREST': 'bowling',
            }),
        ])
        self.send_message.assert_called_with('en_welcome_bowling_T', email, token, 'T')
        # not called because 'about-mozilla' already in newsletters
        self.assertFalse(self.send_welcomes.called)

    @override_settings(EXACTTARGET_DATA='DATA_FOR_DUDE',
                       EXACTTARGET_INTERESTS='DUDE_IS_INTERESTED')
    def test_new_user_interested_no_sub(self):
        """Successful submission of the form for new user without newsletter subscription."""
        email = 'walter@example.com'
        self.get_user_data.return_value = None
        tasks.update_get_involved('bowling', 'en', 'Walter', email,
                                  'US', False, 'It really tied the room together.', None)
        token = models.Subscriber.objects.get(email=email).token
        self.apply_updates.assert_has_calls([
            call(settings.EXACTTARGET_DATA, {
                'EMAIL_ADDRESS_': email,
                'MODIFIED_DATE_': ANY,
                'LANGUAGE_ISO2': 'en',
                'COUNTRY_': 'US',
                'TOKEN': token,
            }),
            call(settings.EXACTTARGET_INTERESTS, {
                'TOKEN': token,
                'INTEREST': 'bowling',
            }),
        ])
        self.send_message.assert_called_with('en_welcome_bowling', email, token, 'H')
        self.assertFalse(self.send_welcomes.called)


class DebugUserTest(TestCase):
    def setUp(self):
        self.sub = models.Subscriber.objects.create(email='dude@example.com')

    @patch('news.views.get_user_data')
    def test_basket_data_included(self, et_mock):
        """
        The token from the basket DB should be included, and can be
        different from that returned by ET
        """
        et_mock.return_value = {
            'email': self.sub.email,
            'token': 'not-the-users-basket-token',
        }
        resp = self.client.get('/news/debug-user/', {
            'email': self.sub.email,
            'supertoken': settings.SUPERTOKEN,
        })
        resp_data = json.loads(resp.content)
        self.assertEqual(resp_data['basket_token'], self.sub.token)
        self.assertNotEqual(resp_data['token'], self.sub.token)
        self.assertTrue(resp_data['in_basket'])

    @patch('news.views.get_user_data')
    def test_user_not_in_basket(self, et_mock):
        """
        It's possible the user is in ET but not basket. Response should
        indicate that.
        """
        et_mock.return_value = {
            'email': 'donnie@example.com',
            'token': 'not-the-users-basket-token',
        }
        resp = self.client.get('/news/debug-user/', {
            'email': 'donnie@example.com',
            'supertoken': settings.SUPERTOKEN,
        })
        resp_data = json.loads(resp.content)
        self.assertEqual(resp_data['token'], 'not-the-users-basket-token')
        self.assertFalse(resp_data['in_basket'])


class TestLookForUser(TestCase):
    def test_subscriptions(self):
        """
        look_for_user returns the right list of subscribed newsletters
        """
        Newsletter.objects.create(slug='n1', vendor_id='NEWSLETTER1')
        Newsletter.objects.create(slug='n2', vendor_id='NEWSLETTER2')
        fields = ['NEWSLETTER1_FLG', 'NEWSLETTER2_FLG']
        with patch('news.utils.ExactTargetDataExt') as et_ext:
            data_ext = et_ext()
            data_ext.get_record.return_value = {
                'EMAIL_ADDRESS_': 'dude@example.com',
                'EMAIL_FORMAT_': 'HTML',
                'COUNTRY_': 'us',
                'LANGUAGE_ISO2': 'en',
                'TOKEN': 'asdf',
                'CREATED_DATE_': 'Yesterday',
                'NEWSLETTER1_FLG': 'Y',
                'NEWSLETTER2_FLG': 'Y',
            }
            result = look_for_user(database='DUMMY', email='EMAIL',
                                   token='TOKEN', fields=fields)
        expected_result = {
            'newsletters': [u'n1', u'n2'],
            'status': 'ok',
            'country': 'us',
            'lang': 'en',
            'token': 'asdf',
            'created-date': 'Yesterday',
            'email': 'dude@example.com',
            'format': 'HTML',
        }
        self.assertEqual(expected_result, result)

    def test_unset_lang(self):
        """
        If lang is not set in ET, look_for_user returns '', not None.
        """
        # ET returns None if the database has NULL.
        Newsletter.objects.create(slug='n1', vendor_id='NEWSLETTER1')
        Newsletter.objects.create(slug='n2', vendor_id='NEWSLETTER2')
        fields = ['NEWSLETTER1_FLG', 'NEWSLETTER2_FLG']
        with patch('news.utils.ExactTargetDataExt') as et_ext:
            data_ext = et_ext()
            data_ext.get_record.return_value = {
                'EMAIL_ADDRESS_': 'dude@example.com',
                'EMAIL_FORMAT_': 'HTML',
                'COUNTRY_': 'us',
                'LANGUAGE_ISO2': None,
                'TOKEN': 'asdf',
                'CREATED_DATE_': 'Yesterday',
                'NEWSLETTER1_FLG': 'Y',
                'NEWSLETTER2_FLG': 'Y',
            }
            result = look_for_user(database='DUMMY', email='EMAIL',
                                   token='TOKEN', fields=fields)
        expected_result = {
            'newsletters': [u'n1', u'n2'],
            'status': 'ok',
            'country': 'us',
            'lang': '',
            'token': 'asdf',
            'created-date': 'Yesterday',
            'email': 'dude@example.com',
            'format': 'HTML',
        }
        self.assertEqual(expected_result, result)


class TestGetUserData(TestCase):

    def check_get_user(self,
                       master,
                       optin,
                       confirm,
                       error,
                       expected_result):
        """
        Call get_user_data with the given conditions and verify
        that the return value matches the expected result.
        The expected result can include `ANY` values for don't-cares.

        :param master: What should be returned if we query the master DB
        :param optin: What should be returned if we query the opt-in DB
        :param confirm: What should be returned if we query the confirmed DB
        :param error: Exception to raise
        :param expected_result: Expected return value of get_user_data, or
            expected exception raised if any
        """

        # Use this method to mock look_for_user so that we can return
        # different values given the input arguments
        def mock_look_for_user(database, email, token, fields):
            if error:
                raise error
            if database == settings.EXACTTARGET_DATA:
                return master
            elif database == settings.EXACTTARGET_OPTIN_STAGE:
                return optin
            elif database == settings.EXACTTARGET_CONFIRMATION:
                return optin
            else:
                raise Exception("INVALID INPUT TO mock_look_for_user - "
                                "database %r unknown" % database)

        with patch('news.utils.look_for_user') as look_for_user:
            look_for_user.side_effect = mock_look_for_user
            result = get_user_data()

        self.assertEqual(expected_result, result)

    def test_setting_are_sane(self):
        # This is more to test that the settings are sane for running the
        # tests and complain loudly, than to test the code.
        # We need settings for the data table names,
        # and also verify that all the table name settings are
        # different.
        self.assertTrue(hasattr(settings, 'EXACTTARGET_DATA'))
        self.assertTrue(settings.EXACTTARGET_DATA)
        self.assertTrue(hasattr(settings, 'EXACTTARGET_OPTIN_STAGE'))
        self.assertTrue(settings.EXACTTARGET_OPTIN_STAGE)
        self.assertTrue(hasattr(settings, 'EXACTTARGET_CONFIRMATION'))
        self.assertTrue(settings.EXACTTARGET_CONFIRMATION)
        self.assertNotEqual(settings.EXACTTARGET_DATA,
                            settings.EXACTTARGET_OPTIN_STAGE)
        self.assertNotEqual(settings.EXACTTARGET_DATA,
                            settings.EXACTTARGET_CONFIRMATION)
        self.assertNotEqual(settings.EXACTTARGET_OPTIN_STAGE,
                            settings.EXACTTARGET_CONFIRMATION)

    def test_not_in_et(self):
        # User not in Exact Target, return None
        self.check_get_user(None, None, None, False, None)

    def test_et_error(self):
        # Error calling Exact Target, return error code
        err_msg = "Mock error for testing"
        error = NewsletterException(err_msg)
        expected = {
            'status': 'error',
            'desc': err_msg,
            'status_code': 400,
            'code': errors.BASKET_NETWORK_FAILURE,
        }
        self.check_get_user(ANY, ANY, ANY, error, expected)

    def test_in_master(self):
        """
        If user is in master, get_user_data returns whatever
        look_for_user returns.
        """
        mock_user = {'dummy': 'Just a dummy user'}
        self.check_get_user(mock_user, ANY, ANY, False, mock_user)

    def test_in_opt_in(self):
        """
        If user is in opt_in, get_user_data returns whatever
        look_for_user returns.
        """
        mock_user = {'token': 'Just a dummy user'}
        self.check_get_user(None, mock_user, ANY, False, mock_user)


class UserTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_user_set(self):
        """If the user view is sent a POST request, it should attempt to update
        the user's info.
        """
        subscriber = models.Subscriber(email='test@example.com', token='asdf')
        subscriber.save()

        request = self.factory.post('/news/user/asdf/', {'fake': 'data'})
        with patch.object(views, 'update_user_task') as update_user_task:
            update_user_task.return_value = HttpResponse()
            views.user(request, 'asdf')
            update_user_task.assert_called_with(request, tasks.SET)

    def test_user_set_bad_language(self):
        """If the user view is sent a POST request with an invalid
        language, it fails.
        """
        subscriber = models.Subscriber(email='test@example.com', token='asdf')
        subscriber.save()

        resp = self.client.post('/news/user/asdf/',
                                {'fake': 'data', 'lang': '55'})
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'error')
        self.assertEqual(data['desc'], 'invalid language')

    @patch('news.utils.ExactTargetDataExt')
    def test_missing_user_created(self, et_ext):
        """
        If a user is in ET but not Basket, it should be created.
        """
        data_ext = et_ext()
        data_ext.get_record.return_value = {
            'EMAIL_ADDRESS_': 'dude@example.com',
            'EMAIL_FORMAT_': 'HTML',
            'COUNTRY_': 'us',
            'LANGUAGE_ISO2': 'en',
            'TOKEN': 'asdf',
            'CREATED_DATE_': 'Yesterday',
        }
        with self.assertRaises(models.Subscriber.DoesNotExist):
            models.Subscriber.objects.get(email='dude@example.com')

        resp = self.client.get('/news/user/asdf/')
        self.assertEqual(data_ext.get_record.call_count, 1)
        self.assertEqual(resp.status_code, 200)
        sub = models.Subscriber.objects.get(email='dude@example.com')
        self.assertEqual(sub.token, 'asdf')

    @patch('news.utils.ExactTargetDataExt')
    def test_user_not_in_et(self, et_ext):
        """A user not found in ET should produce an error response."""
        data_ext = et_ext()
        data_ext.get_record.side_effect = NewsletterException('DANGER!')
        models.Subscriber.objects.create(email='dude@example.com',
                                         token='asdfjkl')
        resp = self.client.get('/news/user/asdfjkl/')
        self.assertEqual(resp.status_code, 400)
        resp_data = json.loads(resp.content)
        self.assertDictEqual(resp_data, {
            'status': 'error',
            'desc': 'DANGER!',
            'code': errors.BASKET_NETWORK_FAILURE,
        })


class TestLookupUser(TestCase):
    """test for API lookup-user"""
    # Keep in mind that this API requires SSL. We make it look like an
    # SSL request by adding {'wsgi.url_scheme': 'https'} to the arguments
    # of the client.get

    def setUp(self):
        self.auth = APIUser.objects.create(name="test")
        self.user_data = {'status': 'ok'}
        self.url = reverse('lookup_user')

    def ssl_get(self, params=None, **extra):
        extra['wsgi.url_scheme'] = 'https'
        params = params or {}
        return self.client.get(self.url, data=params, **extra)

    def test_no_parms(self):
        """Passing no parms is a 400 error"""
        rsp = self.ssl_get()
        self.assertEqual(400, rsp.status_code, rsp.content)

    def test_both_parms(self):
        """Passing both parms is a 400 error"""
        params = {
            'token': 'dummy',
            'email': 'dummy@example.com',
        }
        rsp = self.ssl_get(params=params)
        self.assertEqual(400, rsp.status_code, rsp.content)

    def test_not_ssl(self):
        """Without SSL, immediate 401"""
        rsp = self.client.get(self.url)
        self.assertEqual(401, rsp.status_code, rsp.content)

    @patch('news.views.get_user_data')
    def test_with_token(self, get_user_data):
        """Passing a token gets back that user's data"""
        get_user_data.return_value = self.user_data
        params = {
            'token': 'dummy',
        }
        rsp = self.ssl_get(params=params)
        self.assertEqual(200, rsp.status_code, rsp.content)
        self.assertEqual(self.user_data, json.loads(rsp.content))

    def test_with_email_no_api_key(self):
        """Passing email without api key is a 401"""
        params = {
            'email': 'mail@example.com',
        }
        rsp = self.ssl_get(params)
        self.assertEqual(401, rsp.status_code, rsp.content)

    def test_with_email_disabled_auth(self):
        """Passing email with a disabled api key is a 401"""
        self.auth.enabled = False
        self.auth.save()
        params = {
            'email': 'mail@example.com',
            'api-key': self.auth.api_key,
        }
        rsp = self.ssl_get(params)
        self.assertEqual(401, rsp.status_code, rsp.content)

    def test_with_email_bad_auth(self):
        """Passing email with bad api key is a 401"""
        params = {
            'email': 'mail@example.com',
            'api-key': 'BAD KEY',
        }
        rsp = self.ssl_get(params)
        self.assertEqual(401, rsp.status_code, rsp.content)

    @patch('news.views.get_user_data')
    def test_with_email_and_auth_parm(self, get_user_data):
        """Passing email and valid api key parm gets user's data"""
        params = {
            'email': 'mail@example.com',
            'api-key': self.auth.api_key,
        }
        get_user_data.return_value = self.user_data
        rsp = self.ssl_get(params)
        self.assertEqual(200, rsp.status_code, rsp.content)
        self.assertEqual(self.user_data, json.loads(rsp.content))

    @patch('news.views.get_user_data')
    def test_with_email_and_auth_header(self, get_user_data):
        """Passing email and valid api key header gets user's data"""
        params = {
            'email': 'mail@example.com',
        }
        get_user_data.return_value = self.user_data
        rsp = self.ssl_get(params, HTTP_X_API_KEY=self.auth.api_key)
        self.assertEqual(200, rsp.status_code, rsp.content)
        self.assertEqual(self.user_data, json.loads(rsp.content))

    @patch('news.views.get_user_data')
    def test_no_user(self, get_user_data):
        """If no such user, returns 404"""
        get_user_data.return_value = None
        params = {
            'email': 'mail@example.com',
            'api-key': self.auth.api_key,
        }
        rsp = self.ssl_get(params)
        self.assertEqual(404, rsp.status_code, rsp.content)

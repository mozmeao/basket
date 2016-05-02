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
from news.utils import look_for_user, get_user_data, SET, generate_token


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
        """Adding a new user should add fxa_id."""
        self.get_external_user_data.return_value = None
        email = 'dude@example.com'
        fxa_id = 'the fxa abides'

        tasks.update_fxa_info(email, 'de', fxa_id)

        self.apply_updates.assert_called_once_with(settings.EXACTTARGET_DATA, {
            'EMAIL_ADDRESS_': email,
            'TOKEN': ANY,
            'FXA_ID': fxa_id,
            'FXA_LANGUAGE_ISO2': 'de',
            'SOURCE_URL': 'https://accounts.firefox.com',
            'MODIFIED_DATE_': ANY,
        })
        self.get_external_user_data.assert_called_with(email=email)
        self.send_message.delay.assert_called_with('de_{0}'.format(tasks.FXACCOUNT_WELCOME),
                                                   email, ANY, 'H')

    def test_skip_welcome(self):
        """Passing skip_welcome should add user but not send welcome."""
        self.get_external_user_data.return_value = None
        email = 'dude@example.com'
        fxa_id = 'the fxa abides'

        tasks.update_fxa_info(email, 'de', fxa_id, skip_welcome=True)
        self.apply_updates.assert_called_once_with(settings.EXACTTARGET_DATA, {
            'EMAIL_ADDRESS_': email,
            'TOKEN': ANY,
            'FXA_ID': fxa_id,
            'FXA_LANGUAGE_ISO2': 'de',
            'SOURCE_URL': 'https://accounts.firefox.com',
            'MODIFIED_DATE_': ANY,
        })
        self.get_external_user_data.assert_called_with(email=email)
        self.assertFalse(self.send_message.delay.called)

    def test_existing_user(self):
        """Adding a fxa_id to an existing user shouldn't modify other things."""
        email = 'dude@example.com'
        fxa_id = 'the fxa abides'
        token = 'the dudes token, man'
        self.get_external_user_data.return_value = {
            'email': email,
            'token': token,
            'lang': 'de',
            'format': 'T',
        }
        tasks.update_fxa_info(email, 'de', fxa_id)

        self.apply_updates.assert_called_once_with(settings.EXACTTARGET_DATA, {
            'EMAIL_ADDRESS_': email,
            'TOKEN': token,
            'FXA_ID': fxa_id,
            'MODIFIED_DATE_': ANY,
            'FXA_LANGUAGE_ISO2': 'de',
        })
        self.send_message.delay.assert_called_with('de_{0}_T'.format(tasks.FXACCOUNT_WELCOME),
                                                   email, token, 'T')


@override_settings(EXACTTARGET_DATA='DATA_FOR_DUDE',
                   EXACTTARGET_INTERESTS='DUDE_IS_INTERESTED')
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

        patcher = patch.object(models.Interest, 'notify_stewards')
        self.addCleanup(patcher.stop)
        self.notify_stewards = patcher.start()

        self.interest = models.Interest.objects.create(title='Bowling',
                                                       interest_id='bowling',
                                                       _welcome_id='welcome_bowling')
        Newsletter.objects.create(slug='mozilla-and-you', vendor_id='MOZILLA_AND_YOU')
        Newsletter.objects.create(slug='about-mozilla', vendor_id='ABOUT_MOZILLA')
        Newsletter.objects.create(slug='get-involved', vendor_id='GET_INVOLVED')

    def test_new_user_interested(self):
        """Successful submission of the form for new user."""
        email = 'walter@example.com'
        self.get_user_data.return_value = None
        tasks.update_get_involved('bowling', 'en', 'Walter', email,
                                  'US', 'T', 'Y', 'It really tied the room together.', None)
        self.apply_updates.assert_has_calls([
            call(settings.EXACTTARGET_DATA, {
                'EMAIL_ADDRESS_': email,
                'MODIFIED_DATE_': ANY,
                'LANGUAGE_ISO2': 'en',
                'COUNTRY_': 'US',
                'TOKEN': ANY,
                'EMAIL_FORMAT_': 'T',
                'ABOUT_MOZILLA_FLG': 'Y',
                'ABOUT_MOZILLA_DATE': ANY,
                'GET_INVOLVED_FLG': 'Y',
                'GET_INVOLVED_DATE': ANY,
            }),
            call(settings.EXACTTARGET_INTERESTS, {
                'TOKEN': ANY,
                'INTEREST': 'bowling',
            }),
        ])
        self.send_message.delay.assert_called_with('en_welcome_bowling_T', email, ANY, 'T')
        self.send_welcomes.assert_called_once_with({
            'email': email,
            'token': ANY,
            'lang': 'en',
        }, ['about-mozilla'], 'T')
        self.interest.notify_stewards.assert_called_with('Walter', email, 'en',
                                                         'It really tied the room together.')

    def test_exact_target_error(self):
        """Successful submission of the form for new user, but ET has a problem."""
        self.get_user_data.side_effect = NewsletterException('Stuffs broke yo.')
        with self.assertRaises(NewsletterException):
            tasks.update_get_involved('bowling', 'en', 'Walter', 'walter@example.com',
                                      'US', 'T', 'Y', 'It really tied the room together.', None)

        self.assertFalse(self.send_message.called)
        self.assertFalse(self.send_welcomes.called)
        self.assertFalse(self.interest.notify_stewards.called)

    def test_existing_user_interested(self):
        """Successful submission of the form for existing newsletter user."""
        email = 'walter@example.com'
        token = 'the dudes token, man'
        self.get_user_data.return_value = {
            'status': 'ok',
            'format': 'T',
            'token': token,
            'newsletters': ['about-mozilla', 'mozilla-and-you', 'get-involved'],
        }
        tasks.update_get_involved('bowling', 'en', 'Walter', email,
                                  'US', 'T', 'Y', 'It really tied the room together.', None)
        self.apply_updates.assert_has_calls([
            call(settings.EXACTTARGET_DATA, {
                'EMAIL_ADDRESS_': 'walter@example.com',
                'MODIFIED_DATE_': ANY,
                'LANGUAGE_ISO2': 'en',
                'COUNTRY_': 'US',
                'TOKEN': token,
                'GET_INVOLVED_FLG': 'Y',
            }),
            call(settings.EXACTTARGET_INTERESTS, {
                'TOKEN': token,
                'INTEREST': 'bowling',
            }),
        ])
        self.send_message.delay.assert_called_with('en_welcome_bowling_T', email, token, 'T')
        # not called because 'about-mozilla' already in newsletters
        self.assertFalse(self.send_welcomes.called)
        self.interest.notify_stewards.assert_called_with('Walter', email, 'en',
                                                         'It really tied the room together.')

    def test_existing_user_interested_no_newsletter(self):
        """
        Successful submission of the form for existing newsletter user not
        subscribed to get-involved.
        """
        email = 'walter@example.com'
        token = 'the dudes token, man'
        self.get_user_data.return_value = {
            'status': 'ok',
            'format': 'T',
            'token': token,
            'newsletters': ['mozilla-and-you'],
        }
        tasks.update_get_involved('bowling', 'en', 'Walter', email,
                                  'US', 'T', 'Y', 'It really tied the room together.', None)
        self.apply_updates.assert_has_calls([
            call(settings.EXACTTARGET_DATA, {
                'EMAIL_ADDRESS_': 'walter@example.com',
                'MODIFIED_DATE_': ANY,
                'LANGUAGE_ISO2': 'en',
                'COUNTRY_': 'US',
                'TOKEN': token,
                'ABOUT_MOZILLA_FLG': 'Y',
                'ABOUT_MOZILLA_DATE': ANY,
                'GET_INVOLVED_FLG': 'Y',
                'GET_INVOLVED_DATE': ANY,
            }),
            call(settings.EXACTTARGET_INTERESTS, {
                'TOKEN': token,
                'INTEREST': 'bowling',
            }),
        ])
        self.send_message.delay.assert_called_with('en_welcome_bowling_T', email, token, 'T')
        self.send_welcomes.assert_called_once_with(self.get_user_data.return_value,
                                                   ['about-mozilla'], 'T')
        self.interest.notify_stewards.assert_called_with('Walter', email, 'en',
                                                         'It really tied the room together.')

    def test_new_user_interested_no_sub(self):
        """Successful submission of the form for new user without newsletter subscription."""
        email = 'walter@example.com'
        self.get_user_data.return_value = None
        tasks.update_get_involved('bowling', 'en', 'Walter', email,
                                  'US', 'H', False, 'It really tied the room together.', None)
        token = ANY
        self.apply_updates.assert_has_calls([
            call(settings.EXACTTARGET_DATA, {
                'EMAIL_ADDRESS_': email,
                'MODIFIED_DATE_': ANY,
                'LANGUAGE_ISO2': 'en',
                'COUNTRY_': 'US',
                'TOKEN': token,
                'EMAIL_FORMAT_': 'H',
                'GET_INVOLVED_FLG': 'Y',
                'GET_INVOLVED_DATE': ANY,
            }),
            call(settings.EXACTTARGET_INTERESTS, {
                'TOKEN': token,
                'INTEREST': 'bowling',
            }),
        ])
        self.send_message.delay.assert_called_with('en_welcome_bowling', email, token, 'H')
        self.assertFalse(self.send_welcomes.called)
        self.interest.notify_stewards.assert_called_with('Walter', email, 'en',
                                                         'It really tied the room together.')


class TestLookForUser(TestCase):
    def test_subscriptions(self):
        """
        look_for_user returns the right list of subscribed newsletters
        """
        Newsletter.objects.create(slug='n1', vendor_id='NEWSLETTER1')
        Newsletter.objects.create(slug='n2', vendor_id='NEWSLETTER2')
        fields = ['NEWSLETTER1_FLG', 'NEWSLETTER2_FLG']
        with patch('news.utils.sfmc') as sfmc_mock:
            sfmc_mock.get_row.return_value = {
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
        with patch('news.utils.sfmc') as sfmc_mock:
            sfmc_mock.get_row.return_value = {
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


@override_settings(EXACTTARGET_DATA='data',
                   EXACTTARGET_OPTIN_STAGE='optin',
                   EXACTTARGET_CONFIRMATION='confirmation')
class TestGetUserData(TestCase):

    def check_get_user(self, master, optin, confirm, error, expected_result):
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

        with patch('news.utils.look_for_user') as look_for_user_mock:
            look_for_user_mock.side_effect = mock_look_for_user
            result = get_user_data()

        self.assertEqual(expected_result, result)

    def test_not_in_et(self):
        # User not in Exact Target, return None
        self.check_get_user(None, None, None, False, None)

    @patch('news.utils.look_for_user')
    def test_et_error(self, look_for_user_mock):
        # Error calling Exact Target, return error code
        err_msg = 'Stuffs broke yo.'
        look_for_user_mock.side_effect = NewsletterException(err_msg)
        with self.assertRaises(NewsletterException) as exc_manager:
            get_user_data()

        exc = exc_manager.exception
        self.assertEqual(str(exc), err_msg)
        self.assertEqual(exc.error_code, errors.BASKET_NETWORK_FAILURE)
        self.assertEqual(exc.status_code, 400)

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

    @patch('news.utils.look_for_user')
    def test_look_for_user_called_correctly_confirmation(self, mock_look_for_user):
        """
        If user is looked for by email, is not in master
        but is in opt_in, make sure confirmation is called
        correctly, and that if not in confirmation return a "pending" state.
        """
        mock_look_for_user.side_effect = [None, {'token': 'dude'}, None]
        result = get_user_data(email='dude@example.com')
        self.assertTrue(result['pending'])
        self.assertFalse(result['master'])
        self.assertFalse(result['confirmed'])
        # must be called with token returned from previous call only
        mock_look_for_user.assert_called_with(settings.EXACTTARGET_CONFIRMATION,
                                              None, 'dude', ['Token'])


class UserTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_user_set(self):
        """If the user view is sent a POST request, it should attempt to update
        the user's info.
        """
        request = self.factory.post('/news/user/asdf/', {'fake': 'data'})
        with patch.object(views, 'update_user_task') as update_user_task:
            update_user_task.return_value = HttpResponse()
            views.user(request, 'asdf')
            update_user_task.assert_called_with(request, SET, data={'fake': 'data',
                                                                    'token': 'asdf'})

    def test_user_set_bad_language(self):
        """If the user view is sent a POST request with an invalid
        language, it fails.
        """
        token = generate_token()
        resp = self.client.post('/news/user/{}/'.format(token),
                                {'fake': 'data', 'lang': '55'})
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'error')
        self.assertEqual(data['desc'], 'invalid language')

    @patch('news.utils.sfmc')
    def test_user_not_in_et(self, sfmc_mock):
        """A user not found in ET should produce an error response."""
        sfmc_mock.get_row.side_effect = NewsletterException('DANGER!')
        token = generate_token()
        resp = self.client.get('/news/user/{}/'.format(token))
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

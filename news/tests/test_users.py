import json

from django.conf import settings
from django.test import TestCase

from mock import patch, ANY

from news import models, tasks
from news.backends.common import NewsletterException
from news.models import Newsletter
from news.views import look_for_user, get_user_data


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
        with patch('news.views.ExactTargetDataExt') as et_ext:
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
        with patch('news.views.ExactTargetDataExt') as et_ext:
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

        with patch('news.views.look_for_user') as look_for_user:
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
    @patch('news.views.update_user.delay')
    def test_user_set(self, update_user):
        """If the user view is sent a POST request, it should attempt to update
        the user's info.
        """
        subscriber = models.Subscriber(email='test@example.com', token='asdf')
        subscriber.save()

        self.client.post('/news/user/asdf/', {'fake': 'data'})
        update_user.assert_called_with({'fake': ['data']},
                                       'test@example.com',
                                       'asdf', False, tasks.SET, True)

    def test_user_set_bad_language(self):
        """If the user view is sent a POST request with an invalid
        language, it fails.
        """
        subscriber = models.Subscriber(email='test@example.com', token='asdf')
        subscriber.save()

        resp = self.client.post('/news/user/asdf/',
                                {'fake': 'data', 'lang': 'zz'})
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'error')
        self.assertEqual(data['desc'], 'invalid language')

    @patch('news.views.ExactTargetDataExt')
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

    @patch('news.views.ExactTargetDataExt')
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
        })

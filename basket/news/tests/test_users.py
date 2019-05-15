import json

from django.core.urlresolvers import reverse
from django.http import HttpResponse
from django.test import TestCase
from django.test.client import RequestFactory

from mock import patch

from basket import errors

from basket.news import views
from basket.news.backends.common import NewsletterException, NewsletterNoResultsException
from basket.news.models import APIUser
from basket.news.utils import SET, generate_token


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
            update_user_task.assert_called_with(request, SET, {'fake': 'data',
                                                               'token': 'asdf'})

    @patch('basket.news.utils.sfdc')
    def test_user_not_in_sf(self, sfdc_mock):
        """A user not found in SFDC should produce an error response."""
        sfdc_mock.get.side_effect = NewsletterException('DANGER!')
        token = generate_token()
        resp = self.client.get('/news/user/{}/'.format(token))
        self.assertEqual(resp.status_code, 400)
        resp_data = json.loads(resp.content)
        self.assertDictEqual(resp_data, {
            'status': 'error',
            'desc': 'DANGER!',
            'code': errors.BASKET_UNKNOWN_ERROR,
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

    def get(self, params=None, **extra):
        params = params or {}
        return self.client.get(self.url, data=params, **extra)

    def test_no_parms(self):
        """Passing no parms is a 400 error"""
        rsp = self.get()
        self.assertEqual(400, rsp.status_code, rsp.content)

    def test_both_parms(self):
        """Passing both parms is a 400 error"""
        params = {
            'token': 'dummy',
            'email': 'dummy@example.com',
        }
        rsp = self.get(params=params)
        self.assertEqual(400, rsp.status_code, rsp.content)

    @patch('basket.news.utils.sfdc')
    @patch('basket.news.utils.sfmc')
    def test_with_token(self, sfmc_mock, sfdc_mock):
        """Passing a token gets back that user's data"""
        sfdc_mock.get.return_value = self.user_data
        params = {
            'token': 'dummy',
        }
        rsp = self.get(params=params)
        self.assertEqual(200, rsp.status_code, rsp.content)
        self.assertEqual(self.user_data, json.loads(rsp.content))
        sfmc_mock.get_row.assert_not_called()

    @patch('basket.news.utils.sfdc')
    @patch('basket.news.utils.sfmc')
    def test_get_fxa_status(self, sfmc_mock, sfdc_mock):
        """Should request FxA status from SFMC"""
        user_data = self.user_data.copy()
        user_data['email'] = 'hisdudeness@example.com'
        sfdc_mock.get.return_value = user_data
        response = user_data.copy()
        response['has_fxa'] = True
        params = {
            'token': 'dummy',
            'fxa': '1',
        }
        rsp = self.get(params=params)
        sfmc_mock.get_row.assert_called_with('Firefox_Account_ID', ['FXA_ID'], email=user_data['email'])
        self.assertEqual(200, rsp.status_code, rsp.content)
        self.assertEqual(response, json.loads(rsp.content))

    @patch('basket.news.utils.sfdc')
    @patch('basket.news.utils.sfmc')
    def test_get_fxa_status_false(self, sfmc_mock, sfdc_mock):
        """Should request FxA status from SFMC"""
        user_data = self.user_data.copy()
        user_data['email'] = 'hisdudeness@example.com'
        sfdc_mock.get.return_value = user_data
        response = user_data.copy()
        response['has_fxa'] = False
        sfmc_mock.get_row.side_effect = NewsletterNoResultsException
        params = {
            'token': 'dummy',
            'fxa': '1',
        }
        rsp = self.get(params=params)
        sfmc_mock.get_row.assert_called_with('Firefox_Account_ID', ['FXA_ID'], email=user_data['email'])
        self.assertEqual(200, rsp.status_code, rsp.content)
        self.assertEqual(response, json.loads(rsp.content))

    @patch('basket.news.utils.sfdc')
    @patch('basket.news.utils.sfmc')
    def test_get_fxa_status_error(self, sfmc_mock, sfdc_mock):
        """Should request FxA status from SFMC"""
        user_data = self.user_data.copy()
        user_data['email'] = 'hisdudeness@example.com'
        sfdc_mock.get.return_value = user_data
        sfmc_mock.get_row.side_effect = NewsletterException
        params = {
            'token': 'dummy',
            'fxa': '1',
        }
        rsp = self.get(params=params)
        sfmc_mock.get_row.assert_called_with('Firefox_Account_ID', ['FXA_ID'], email=user_data['email'])
        self.assertEqual(200, rsp.status_code, rsp.content)
        # should not contain 'has_fxa' at all on general error
        self.assertEqual(user_data, json.loads(rsp.content))

    def test_with_email_no_api_key(self):
        """Passing email without api key is a 401"""
        params = {
            'email': 'mail@example.com',
        }
        rsp = self.get(params)
        self.assertEqual(401, rsp.status_code, rsp.content)

    def test_with_email_disabled_auth(self):
        """Passing email with a disabled api key is a 401"""
        self.auth.enabled = False
        self.auth.save()
        params = {
            'email': 'mail@example.com',
            'api-key': self.auth.api_key,
        }
        rsp = self.get(params)
        self.assertEqual(401, rsp.status_code, rsp.content)

    def test_with_email_bad_auth(self):
        """Passing email with bad api key is a 401"""
        params = {
            'email': 'mail@example.com',
            'api-key': 'BAD KEY',
        }
        rsp = self.get(params)
        self.assertEqual(401, rsp.status_code, rsp.content)

    @patch('basket.news.views.get_user_data')
    def test_with_email_and_auth_parm(self, get_user_data):
        """Passing email and valid api key parm gets user's data"""
        params = {
            'email': 'mail@example.com',
            'api-key': self.auth.api_key,
        }
        get_user_data.return_value = self.user_data
        rsp = self.get(params)
        self.assertEqual(200, rsp.status_code, rsp.content)
        self.assertEqual(self.user_data, json.loads(rsp.content))

    @patch('basket.news.views.get_user_data')
    def test_with_email_and_auth_header(self, get_user_data):
        """Passing email and valid api key header gets user's data"""
        params = {
            'email': 'mail@example.com',
        }
        get_user_data.return_value = self.user_data
        rsp = self.get(params, HTTP_X_API_KEY=self.auth.api_key)
        self.assertEqual(200, rsp.status_code, rsp.content)
        self.assertEqual(self.user_data, json.loads(rsp.content))

    @patch('basket.news.views.get_user_data')
    def test_no_user(self, get_user_data):
        """If no such user, returns 404"""
        get_user_data.return_value = None
        params = {
            'email': 'mail@example.com',
            'api-key': self.auth.api_key,
        }
        rsp = self.get(params)
        self.assertEqual(404, rsp.status_code, rsp.content)

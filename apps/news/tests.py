import json

from django.conf import settings
from django.test import TestCase

from mock import patch
from test_utils import RequestFactory

from news import views
from news import tasks
from news.backends.exacttarget import NewsletterException
from news.models import Subscriber


class SubscriberTest(TestCase):
    def test_get_and_sync_creates(self):
        """
        Subscriber.objects.get_and_sync() should create if email doesn't exist.
        """
        with self.assertRaises(Subscriber.DoesNotExist):
            Subscriber.objects.get(email='dude@example.com')

        Subscriber.objects.get_and_sync('dude@example.com', 'asdfjkl')
        sub = Subscriber.objects.get(email='dude@example.com')
        self.assertEqual(sub.token, 'asdfjkl')

    def test_get_and_sync_updates(self):
        """
        Subscriber.objects.get_and_sync() should update token if it doesn't
        match.
        """
        Subscriber.objects.create(email='dude@example.com',
                                  token='asdf')

        Subscriber.objects.get_and_sync('dude@example.com', 'asdfjkl')
        sub = Subscriber.objects.get(email='dude@example.com')
        self.assertEqual(sub.token, 'asdfjkl')


class UserTest(TestCase):
    @patch('news.views.update_user.delay')
    def test_user_set(self, update_user):
        """If the user view is sent a POST request, it should attempt to update
        the user's info.
        """
        subscriber = Subscriber(email='test@example.com', token='asdf')
        subscriber.save()

        self.client.post('/news/user/asdf/', {'fake': 'data'})
        update_user.assert_called_with({'fake': ['data']},
                                       'test@example.com',
                                       'asdf', False, tasks.SET, True)

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
        with self.assertRaises(Subscriber.DoesNotExist):
            Subscriber.objects.get(email='dude@example.com')

        resp = self.client.get('/news/user/asdf/')
        self.assertEqual(data_ext.get_record.call_count, 1)
        self.assertEqual(resp.status_code, 200)
        sub = Subscriber.objects.get(email='dude@example.com')
        self.assertEqual(sub.token, 'asdf')

    @patch('news.views.ExactTargetDataExt')
    def test_user_not_in_et(self, et_ext):
        """A user not found in ET should produce an error response."""
        data_ext = et_ext()
        data_ext.get_record.side_effect = NewsletterException('DANGER!')
        Subscriber.objects.create(email='dude@example.com', token='asdfjkl')
        resp = self.client.get('/news/user/asdfjkl/')
        self.assertEqual(resp.status_code, 400)
        resp_data = json.loads(resp.content)
        self.assertDictEqual(resp_data, {
            'status': 'error',
            'desc': 'DANGER!',
        })


class DebugUserTest(TestCase):
    def setUp(self):
        self.sub = Subscriber.objects.create(email='dude@example.com')

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


class UpdatePhonebookTest(TestCase):
    def setUp(self):
        self.sub = Subscriber.objects.create(email='dude@example.com')
        self.url = '/news/custom_update_phonebook/%s/' % self.sub.token

    @patch('news.views.update_phonebook.delay')
    def test_update_phonebook(self, pb_mock):
        """
        Should call the task with the user's information.
        """
        data = {
            'city': 'Durham',
            'country': 'US',
            'WEB_DEVELOPMENT': 'y',
            'DOES_NOT_EXIST': 'y',
        }
        self.client.post(self.url, data)
        pb_mock.assert_called_with(data, self.sub.email, self.sub.token)

    @patch('news.tasks.ExactTarget')
    def test_update_phonebook_task(self, et_mock):
        """
        Should call Exact Target only with the approved information.
        """
        et = et_mock()
        data = {
            'city': 'Durham',
            'country': 'US',
            'WEB_DEVELOPMENT': 'y',
            'DOES_NOT_EXIST': 'y',
        }
        record = {
            'EMAIL_ADDRESS': self.sub.email,
            'TOKEN': self.sub.token,
            'CITY': 'Durham',
            'COUNTRY': 'US',
            'WEB_DEVELOPMENT': 'y',
        }
        self.client.post(self.url, data)
        et.data_ext().add_record.assert_called_with('PHONEBOOK',
                                                    record.keys(),
                                                    record.values())


class UpdateUserTest(TestCase):
    def setUp(self):
        self.sub = Subscriber.objects.create(email='dude@example.com')
        self.rf = RequestFactory()

    @patch('news.views.update_user.delay')
    def test_update_user_task_helper(self, uu_mock):
        """
        `update_user` should always get an email and token.
        """
        req = self.rf.post('/testing/', {'stuff': 'whanot'})
        req.subscriber = self.sub
        resp = views.update_user_task(req, tasks.SUBSCRIBE)
        resp_data = json.loads(resp.content)
        self.assertDictEqual(resp_data, {
            'status': 'ok',
            'token': self.sub.token,
            'created': False,
        })
        uu_mock.assert_called_with({'stuff': ['whanot']},
                                   self.sub.email, self.sub.token,
                                   False, tasks.SUBSCRIBE, True)

    @patch('news.views.update_user.delay')
    def test_update_user_task_helper_no_sub(self, uu_mock):
        """
        Should find sub from submitted email when not provided.
        """
        req = self.rf.post('/testing/', {'email': self.sub.email})
        resp = views.update_user_task(req, tasks.SUBSCRIBE)
        resp_data = json.loads(resp.content)
        self.assertDictEqual(resp_data, {
            'status': 'ok',
            'token': self.sub.token,
            'created': False,
        })
        uu_mock.assert_called_with({'email': [self.sub.email]},
                                   self.sub.email, self.sub.token,
                                   False, tasks.SUBSCRIBE, True)

    @patch('news.views.update_user.delay')
    def test_update_user_task_helper_create(self, uu_mock):
        """
        Should create a user and tell the task about it if email not known.
        """
        req = self.rf.post('/testing/', {'email': 'donnie@example.com'})
        resp = views.update_user_task(req, tasks.SUBSCRIBE)
        sub = Subscriber.objects.get(email='donnie@example.com')
        resp_data = json.loads(resp.content)
        self.assertDictEqual(resp_data, {
            'status': 'ok',
            'token': sub.token,
            'created': True,
        })
        uu_mock.assert_called_with({'email': [sub.email]},
                                   sub.email, sub.token,
                                   True, tasks.SUBSCRIBE, True)

    @patch('news.views.update_user.delay')
    def test_update_user_task_helper_error(self, uu_mock):
        """
        Should not call the task if no email or token provided.
        """
        req = self.rf.post('/testing/', {'stuff': 'whanot'})
        resp = views.update_user_task(req, tasks.SUBSCRIBE)
        self.assertFalse(uu_mock.called)
        self.assertEqual(resp.status_code, 400)
        errors = json.loads(resp.content)
        self.assertEqual(errors['status'], 'error')

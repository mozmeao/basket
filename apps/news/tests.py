import json

from django.test import TestCase

from mock import patch
from test_utils import RequestFactory

from news import views
from news import tasks
from news.models import Subscriber


class UserTest(TestCase):
    @patch('news.views.update_user')
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


class UpdatePhonebookTest(TestCase):
    def setUp(self):
        self.sub = Subscriber.objects.create(email='dude@example.com')
        self.url = '/news/custom_update_phonebook/%s/' % self.sub.token

    @patch('news.views.update_phonebook')
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

    @patch('news.views.update_user')
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

    @patch('news.views.update_user')
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

    @patch('news.views.update_user')
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

    @patch('news.views.update_user')
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

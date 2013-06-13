import datetime
import json
from uuid import uuid4

from django.conf import settings
from django.core.urlresolvers import reverse
from django.test import TestCase
from django.utils.unittest import skip

from mock import ANY, Mock, patch
from test_utils import RequestFactory

from news import models, tasks, views
from news.backends.exacttarget import NewsletterException
from news.newsletters import newsletter_fields, newsletter_languages
from news.tasks import (FFAY_VENDOR_ID, FFOS_VENDOR_ID,
                        SET, SUBSCRIBE, UNSUBSCRIBE,
                        UU_ALREADY_CONFIRMED,
                        UU_EXEMPT_NEW, UU_EXEMPT_PENDING,
                        UU_MUST_CONFIRM_NEW, UU_MUST_CONFIRM_PENDING,
                        RetryTask,
                        confirm_user, update_user)
from news.views import get_user_data, language_code_is_valid


class SubscriberTest(TestCase):
    def test_get_and_sync_creates(self):
        """
        Subscriber.objects.get_and_sync() should create if email doesn't exist.
        """
        with self.assertRaises(models.Subscriber.DoesNotExist):
            models.Subscriber.objects.get(email='dude@example.com')

        models.Subscriber.objects.get_and_sync('dude@example.com', 'asdfjkl')
        sub = models.Subscriber.objects.get(email='dude@example.com')
        self.assertEqual(sub.token, 'asdfjkl')

    def test_get_and_sync_updates(self):
        """
        Subscriber.objects.get_and_sync() should update token if it doesn't
        match.
        """
        models.Subscriber.objects.create(email='dude@example.com',
                                         token='asdf')

        models.Subscriber.objects.get_and_sync('dude@example.com', 'asdfjkl')
        sub = models.Subscriber.objects.get(email='dude@example.com')
        self.assertEqual(sub.token, 'asdfjkl')


class SubscribeTest(TestCase):
    fixtures = ['newsletters']

    def test_no_newsletters_error(self):
        """
        Should return an error and not create a subscriber if
        no newsletters were specified.
        """
        resp = self.client.post('/news/subscribe/', {
            'email': 'dude@example.com',
        })
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'error')
        self.assertEqual(data['desc'], 'newsletters is missing')
        with self.assertRaises(models.Subscriber.DoesNotExist):
            models.Subscriber.objects.get(email='dude@example.com')

        resp = self.client.post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': '',
        })
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'error')
        self.assertEqual(data['desc'], 'newsletters is missing')
        with self.assertRaises(models.Subscriber.DoesNotExist):
            models.Subscriber.objects.get(email='dude@example.com')

    def test_invalid_newsletters_error(self):
        """
        Should return an error and not create a subscriber if
        newsletters are invalid.
        """
        resp = self.client.post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': 'mozilla-and-you,does-not-exist',
        })
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'error')
        self.assertEqual(data['desc'], 'invalid newsletter')
        with self.assertRaises(models.Subscriber.DoesNotExist):
            models.Subscriber.objects.get(email='dude@example.com')

    def test_invalid_language_error(self):
        """
        Should return an error and not create a subscriber if
        language invalid.
        """
        resp = self.client.post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': 'mozilla-and-you',
            'lang': 'zz'
        })
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'error')
        self.assertEqual(data['desc'], 'invalid language')
        with self.assertRaises(models.Subscriber.DoesNotExist):
            models.Subscriber.objects.get(email='dude@example.com')

    @patch('news.views.get_user_data')
    @patch('news.views.update_user.delay')
    def test_blank_language_okay(self, uu_mock, get_user_data):
        """
        Should work if language is left blank.
        """
        get_user_data.return_value = None  # new user
        resp = self.client.post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': 'mozilla-and-you',
            'lang': ''
        })
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'ok')
        sub = models.Subscriber.objects.get(email='dude@example.com')
        uu_mock.assert_called_with(ANY, sub.email, sub.token,
                                   True, views.SUBSCRIBE, True)

    @patch('news.views.get_user_data')
    @patch('news.views.update_user.delay')
    def test_subscribe_success(self, uu_mock, get_user_data):
        """Subscription should work."""
        get_user_data.return_value = None  # new user
        resp = self.client.post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': 'mozilla-and-you',
        })
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'ok')
        sub = models.Subscriber.objects.get(email='dude@example.com')
        uu_mock.assert_called_with(ANY, sub.email, sub.token,
                                   True, views.SUBSCRIBE, True)


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


class UpdatePhonebookTest(TestCase):
    def setUp(self):
        self.sub = models.Subscriber.objects.create(email='dude@example.com')
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


class UpdateStudentAmbassadorsTest(TestCase):
    def setUp(self):
        self.sub = models.Subscriber.objects.create(email='dude@example.com')
        self.url = '/news/custom_update_student_ambassadors/%s/' % \
                   self.sub.token
        self.data = {'FIRST_NAME': 'Foo',
                     'LAST_NAME': 'Bar',
                     'STUDENTS_CURRENT_STATUS': 'student',
                     'STUDENTS_SCHOOL': 'tuc',
                     'STUDENTS_GRAD_YEAR': '2014',
                     'STUDENTS_MAJOR': 'computer engineering',
                     'COUNTRY': 'GR',
                     'STUDENTS_CITY': 'Athens',
                     'STUDENTS_ALLOW_SHARE': 'N'}

    @patch('news.views.update_student_ambassadors.delay')
    def test_update_phonebook(self, pb_mock):
        """
        Should call the task with the user's information.
        """
        self.client.post(self.url, self.data)
        pb_mock.assert_called_with(self.data, self.sub.email, self.sub.token)

    @patch('news.tasks.ExactTarget')
    def test_update_phonebook_task(self, et_mock):
        """
        Should call Exact Target only with the approved information.
        """
        et = et_mock()
        record = self.data.copy()
        record.update({'EMAIL_ADDRESS': self.sub.email,
                       'TOKEN': self.sub.token})
        self.client.post(self.url, self.data)
        et.data_ext().add_record.assert_called_with('Student_Ambassadors',
                                                    record.keys(),
                                                    record.values())


class UpdateUserTest(TestCase):
    def setUp(self):
        self.sub = models.Subscriber.objects.create(email='dude@example.com')
        self.rf = RequestFactory()
        self.user_data = {
            'EMAIL_ADDRESS_': 'dude@example.com',
            'EMAIL_FORMAT_': 'H',
            'COUNTRY_': 'us',
            'LANGUAGE_ISO2': 'en',
            'TOKEN': 'token',
            'CREATED_DATE_': datetime.datetime.now(),
            'TITLE_UNKNOWN_FLG': 'Y',
        }
        # User data in format that get_user_data() returns it
        self.get_user_data = {
            'email': 'dude@example.com',
            'format': 'H',
            'country': 'us',
            'lang': 'en',
            'token': 'token',
            'newsletters': ['slug'],
            'confirmed': True,
            'master': True,
            'pending': False,
            'status': 'ok',
        }

    @patch('news.views.update_user.delay')
    def test_update_user_task_helper(self, uu_mock):
        """
        `update_user` should always get an email and token.
        """
        # Fake an incoming request which we've already looked up and
        # found a corresponding subscriber for
        req = self.rf.post('/testing/', {'stuff': 'whanot'})
        req.subscriber = self.sub
        # Call update_user to subscribe
        resp = views.update_user_task(req, tasks.SUBSCRIBE)
        resp_data = json.loads(resp.content)
        # We should get back 'ok' status and the token from that
        # subscriber.
        self.assertDictEqual(resp_data, {
            'status': 'ok',
            'token': self.sub.token,
            'created': False,
        })
        # We should have called update_user with the email, token,
        # created=False, type=SUBSCRIBE, optin=True
        uu_mock.assert_called_with({'stuff': ['whanot']},
                                   self.sub.email, self.sub.token,
                                   False, tasks.SUBSCRIBE, True)

    @patch('news.views.update_user.delay')
    def test_update_user_task_helper_no_sub(self, uu_mock):
        """
        Should find sub from submitted email when not provided.
        """
        # Request, pretend we were untable to find a subscriber
        # so we don't set req.subscriber
        req = self.rf.post('/testing/', {'email': self.sub.email})
        # See what update_user does
        resp = views.update_user_task(req, tasks.SUBSCRIBE)
        # Should be okay
        self.assertEqual(200, resp.status_code)
        resp_data = json.loads(resp.content)
        # Should have found the token for the given email
        self.assertDictEqual(resp_data, {
            'status': 'ok',
            'token': self.sub.token,
            'created': False,
        })
        # We should have called update_user with the email, token,
        # created=False, type=SUBSCRIBE, optin=True
        uu_mock.assert_called_with({'email': [self.sub.email]},
                                   self.sub.email, self.sub.token,
                                   False, tasks.SUBSCRIBE, True)

    @patch('news.views.look_for_user')
    @patch('news.views.update_user.delay')
    def test_update_user_task_helper_create(self, uu_mock, look_for_user):
        """
        Should create a user and tell the task about it if email not known.
        """
        # Pretend we are unable to find the user in ET
        look_for_user.return_value = None
        # Pass in a new email
        req = self.rf.post('/testing/', {'email': 'donnie@example.com'})
        resp = views.update_user_task(req, tasks.SUBSCRIBE)
        # Should work
        self.assertEqual(200, resp.status_code)
        # There should be a new subscriber for this email
        sub = models.Subscriber.objects.get(email='donnie@example.com')
        resp_data = json.loads(resp.content)
        # The call should have returned the subscriber's new token
        self.assertDictEqual(resp_data, {
            'status': 'ok',
            'token': sub.token,
            'created': True,
        })
        # We should have called update_user with the email, token,
        # created=False, type=SUBSCRIBE, optin=True
        uu_mock.assert_called_with({'email': [sub.email]},
                                   sub.email, sub.token,
                                   True, tasks.SUBSCRIBE, True)

    @patch('news.views.update_user.delay')
    def test_update_user_task_helper_error(self, uu_mock):
        """
        Should not call the task if no email or token provided.
        """
        # Pretend there was no email given - bad request
        req = self.rf.post('/testing/', {'stuff': 'whanot'})
        resp = views.update_user_task(req, tasks.SUBSCRIBE)
        # We don't try to call update_user
        self.assertFalse(uu_mock.called)
        # We respond with a 400
        self.assertEqual(resp.status_code, 400)
        errors = json.loads(resp.content)
        # The response also says there was an error
        self.assertEqual(errors['status'], 'error')
        # and has a useful error description
        self.assertEqual(errors['desc'],
                         u'An email address or token is required.')

    @patch('news.tasks.apply_updates')
    @patch('news.tasks.send_message')
    @patch('news.views.get_user_data')
    def test_update_send_newsletter_welcome(self, get_user_data, send_message,
                                            apply_updates):
        # When we subscribe to one newsletter, and no confirmation is
        # needed, we send that newsletter's particular welcome message

        # User already exists in ET and is confirmed
        # User does not subscribe to anything yet
        self.get_user_data['confirmed'] = True
        self.get_user_data['newsletters'] = []
        self.get_user_data['token'] = self.sub.token
        get_user_data.return_value = self.get_user_data

        # A newsletter with a welcome message
        welcome_id = "TEST_WELCOME"
        nl = models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=True,
            languages='en,fr',
            welcome=welcome_id,
            vendor_id='VENDOR1',
        )
        data = {
            'country': 'US',
            'format': 'H',
            'newsletters': nl.slug,
            'trigger_welcome': 'Y',
        }
        rc = update_user(data=data,
                         email=self.sub.email,
                         token=self.sub.token,
                         created=True,
                         type=SUBSCRIBE,
                         optin=True)
        self.assertEqual(UU_ALREADY_CONFIRMED, rc)
        apply_updates.assert_called()
        # The welcome should have been sent
        send_message.assert_called()
        send_message.assert_called_with('EN_' + welcome_id, self.sub.email,
                                        self.sub.token, 'H')

    @patch('news.views.get_user_data')
    @patch('news.views.ExactTargetDataExt')
    @patch('news.tasks.ExactTarget')
    def test_update_send_welcome(self, et_mock, etde_mock, get_user_data):
        """
        Update sends default welcome if newsletter has none,
        or, we can specify a particular welcome
        """
        et = et_mock()
        # Newsletter with no defined welcome message
        nl1 = models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=True,
            languages='en-US,fr',
            vendor_id='VENDOR1',
        )
        data = {
            'country': 'US',
            'newsletters': nl1.slug,
        }

        self.get_user_data['token'] = self.sub.token
        self.get_user_data['newsletters'] = []
        get_user_data.return_value = self.get_user_data

        rc = update_user(data=data, email=self.sub.email,
                         token=self.sub.token,
                         created=True,
                         type=SUBSCRIBE, optin=True)
        self.assertEqual(UU_ALREADY_CONFIRMED, rc)
        et.trigger_send.assert_called_with(
            'EN_' + settings.DEFAULT_WELCOME_MESSAGE_ID,
            {
                'EMAIL_FORMAT_': 'H',
                'EMAIL_ADDRESS_': self.sub.email,
                'TOKEN': self.sub.token,
            },
        )

        # FIXME? I think we don't need the ability for the caller
        # to override the welcome message
        # Can specify a different welcome
        # welcome = 'MyWelcome_H'
        # data['welcome_message'] = welcome
        # update_user(data=data, email=self.sub.email,
        #             token=self.sub.token,
        #             created=True,
        #             type=SUBSCRIBE, optin=True)
        # et.trigger_send.assert_called_with(
        #     welcome,
        #     {
        #         'EMAIL_FORMAT_': 'H',
        #         'EMAIL_ADDRESS_': self.sub.email,
        #         'TOKEN': self.sub.token,
        #     },
        # )

    @patch('news.tasks.apply_updates')
    @patch('news.tasks.send_message')
    @patch('news.views.get_user_data')
    def test_update_send_newsletters_welcome(self, get_user_data,
                                             send_message,
                                             apply_updates):
        # If we subscribe to multiple newsletters, and no confirmation is
        # needed, we send each of their welcome messages
        get_user_data.return_value = None  # Does not exist yet
        nl1 = models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=True,
            languages='en,fr',
            welcome="WELCOME1",
            vendor_id='VENDOR1',
        )
        nl2 = models.Newsletter.objects.create(
            slug='slug2',
            title='title',
            active=True,
            languages='en,fr',
            welcome="WELCOME2",
            vendor_id='VENDOR2',
        )
        data = {
            'country': 'US',
            'lang': 'en',
            'format': 'H',
            'newsletters': "%s,%s" % (nl1.slug, nl2.slug),
            'trigger_welcome': 'Y',
        }
        rc = update_user(data=data,
                         email=self.sub.email,
                         token=self.sub.token,
                         created=True,
                         type=SUBSCRIBE,
                         optin=True)
        self.assertEqual(UU_EXEMPT_NEW, rc)
        self.assertEqual(2, send_message.call_count)
        calls_args = [x[0] for x in send_message.call_args_list]
        self.assertIn(('EN_WELCOME1', self.sub.email, self.sub.token, 'H'),
                      calls_args)
        self.assertIn(('EN_WELCOME2', self.sub.email, self.sub.token, 'H'),
                      calls_args)

    @patch('news.tasks.apply_updates')
    @patch('news.tasks.send_message')
    @patch('news.views.get_user_data')
    def test_update_user_works_with_no_welcome(self, get_user_data,
                                               send_message,
                                               apply_updates):
        """update_user was throwing errors when asked not to send a welcome"""
        nl1 = models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=True,
            languages='en-US,fr',
            vendor_id='VENDOR1',
        )
        data = {
            'country': 'US',
            'format': 'H',
            'newsletters': nl1.slug,
            'trigger_welcome': 'N',
            'format': 'T',
            'lang': 'en',
        }
        self.get_user_data['confirmed'] = True
        get_user_data.return_value = self.get_user_data
        rc = update_user(data=data, email=self.sub.email,
                         token=self.sub.token,
                         created=True,
                         type=SUBSCRIBE, optin=True)
        self.assertEqual(UU_ALREADY_CONFIRMED, rc)
        apply_updates.assert_called()
        send_message.assert_called()

    @patch('news.tasks.apply_updates')
    @patch('news.tasks.send_message')
    @patch('news.views.get_user_data')
    def test_ffos_welcome(self, get_user_data, send_message, apply_updates):
        """If the user has subscribed to Firefox OS,
        then we send the welcome for Firefox OS but not for Firefox & You.
        (identified by their vendor IDs).
        """
        get_user_data.return_value = None  # User does not exist yet
        nl1 = models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=True,
            languages='en,fr',
            welcome="FFOS_WELCOME",
            vendor_id=FFOS_VENDOR_ID,
        )
        nl2 = models.Newsletter.objects.create(
            slug='slug2',
            title='title',
            active=True,
            languages='en,fr',
            welcome="FF&Y_WELCOME",
            vendor_id=FFAY_VENDOR_ID,
        )
        data = {
            'country': 'US',
            'lang': 'en',
            'newsletters': "%s,%s" % (nl1.slug, nl2.slug),
            'trigger_welcome': 'Y',
        }
        rc = update_user(data=data,
                         email=self.sub.email,
                         token=self.sub.token,
                         created=True,
                         type=SUBSCRIBE,
                         optin=True)
        self.assertEqual(UU_EXEMPT_NEW, rc)
        self.assertEqual(1, send_message.call_count)
        calls_args = [x[0] for x in send_message.call_args_list]
        self.assertIn(('EN_FFOS_WELCOME', self.sub.email, self.sub.token, 'H'),
                      calls_args)
        self.assertNotIn(('EN_FF&Y_WELCOME', self.sub.email,
                          self.sub.token, 'H'),
                         calls_args)

    @patch('news.tasks.apply_updates')
    @patch('news.tasks.send_message')
    @patch('news.views.get_user_data')
    @patch('news.views.newsletter_fields')
    @patch('news.tasks.ExactTarget')
    def test_update_user_set_works_if_no_newsletters(self, et_mock,
                                                     newsletter_fields,
                                                     get_user_data,
                                                     send_message,
                                                     apply_updates):
        """
        A blank `newsletters` field when the update type is SET indicates
        that the person wishes to unsubscribe from all newsletters. This has
        caused exceptions because '' is not a valid newsletter name.
        """
        et = et_mock()
        nl1 = models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=True,
            languages='en-US,fr',
            vendor_id='TITLE_UNKNOWN',
        )
        data = {
            'lang': 'en',
            'country': 'US',
            'newsletters': '',
            'format': 'H',
        }

        newsletter_fields.return_value = [nl1.vendor_id]

        # Mock user data - we want our user subbed to our newsletter to start
        self.get_user_data['confirmed'] = True
        self.get_user_data['newsletters'] = ['slug']
        get_user_data.return_value = self.get_user_data

        rc = update_user(data, self.sub.email, self.sub.token,
                         False, SET, True)
        self.assertEqual(UU_ALREADY_CONFIRMED, rc)
        # no welcome should be triggered for SET
        self.assertFalse(et.trigger_send.called)
        # We should have looked up the user's data
        get_user_data.assert_called()
        # We'll specifically unsubscribe each newsletter the user is
        # subscribed to.
        apply_updates.assert_called_with(settings.EXACTTARGET_DATA,
                                         {'EMAIL_FORMAT_': 'H',
                                          'EMAIL_ADDRESS_': 'dude@example.com',
                                          'LANGUAGE_ISO2': 'en',
                                          'TOKEN': ANY,
                                          'MODIFIED_DATE_': ANY,
                                          'EMAIL_PERMISSION_STATUS_': 'I',
                                          'COUNTRY_': 'US',
                                          'TITLE_UNKNOWN_FLG': 'N',
                                          'TITLE_UNKNOWN_DATE': ANY,
                                          })

    @patch('news.tasks.apply_updates')
    @patch('news.tasks.send_message')
    @patch('news.views.get_user_data')
    @patch('news.views.newsletter_fields')
    @patch('news.views.ExactTargetDataExt')
    @patch('news.tasks.ExactTarget')
    def test_resubscribe_doesnt_update_newsletter(self, et_mock, etde_mock,
                                                  newsletter_fields,
                                                  get_user_data,
                                                  send_message,
                                                  apply_updates):
        """
        When subscribing to things the user is already subscribed to, we
        do not pass that newsletter's _FLG and _DATE to ET because we
        don't want that newsletter's _DATE to be updated for no reason.
        """
        et_mock()
        etde = etde_mock()
        nl1 = models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=True,
            languages='en-US,fr',
            vendor_id='TITLE_UNKNOWN',
        )
        # We're going to ask to subscribe to this one again
        data = {
            'lang': 'en',
            'country': 'US',
            'newsletters': 'slug',
            'format': 'H',
        }

        get_user_data.return_value = self.get_user_data

        newsletter_fields.return_value = [nl1.vendor_id]

        # Mock user data - we want our user subbed to our newsletter to start
        etde.get_record.return_value = self.user_data

        rc = update_user(data, self.sub.email, self.sub.token,
                         False, SUBSCRIBE, True)
        self.assertEqual(UU_ALREADY_CONFIRMED, rc)
        # We should have looked up the user's data
        get_user_data.assert_called()
        # We should not have mentioned this newsletter in our call to ET
        apply_updates.assert_called_with(settings.EXACTTARGET_DATA,
                                         {'EMAIL_FORMAT_': 'H',
                                          'EMAIL_ADDRESS_': 'dude@example.com',
                                          'LANGUAGE_ISO2': 'en',
                                          'TOKEN': ANY,
                                          'MODIFIED_DATE_': ANY,
                                          'EMAIL_PERMISSION_STATUS_': 'I',
                                          'COUNTRY_': 'US',
                                          })

    @patch('news.views.get_user_data')
    @patch('news.views.newsletter_fields')
    @patch('news.tasks.ExactTarget')
    def test_set_doesnt_update_newsletter(self, et_mock,
                                          newsletter_fields,
                                          get_user_data):
        """
        When setting the newsletters to ones the user is already subscribed
        to, we do not pass that newsletter's _FLG and _DATE to ET because we
        don't want that newsletter's _DATE to be updated for no reason.
        """
        et = et_mock()
        nl1 = models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=True,
            languages='en-US,fr',
            vendor_id='TITLE_UNKNOWN',
        )
        # We're going to ask to subscribe to this one again
        data = {
            'lang': 'en',
            'country': 'US',
            'newsletters': 'slug',
            'format': 'H',
        }

        newsletter_fields.return_value = [nl1.vendor_id]

        # Mock user data - we want our user subbed to our newsletter to start
        get_user_data.return_value = self.get_user_data
        #etde.get_record.return_value = self.user_data

        update_user(data, self.sub.email, self.sub.token, False, SET, True)
        # We should have looked up the user's data
        self.assertTrue(get_user_data.called)
        # We should not have mentioned this newsletter in our call to ET
        et.data_ext.return_value.add_record.assert_called_with(
            ANY,
            ['EMAIL_FORMAT_', 'EMAIL_ADDRESS_', 'LANGUAGE_ISO2',
             'TOKEN', 'MODIFIED_DATE_',
             'EMAIL_PERMISSION_STATUS_', 'COUNTRY_'],
            ['H', 'dude@example.com', 'en',
             ANY, ANY,
             'I', 'US'],
        )

    @skip("FIXME: What should we do if we can't talk to ET")  # FIXME
    @patch('news.tasks.ExactTarget')
    @patch('news.views.get_user_data')
    def test_set_does_update_newsletter_on_error(self, get_user_mock, et_mock):
        """
        When setting the newsletters it should ensure that they're set right
        if we can't get the user's data for some reason.
        """
        get_user_mock.return_value = {
            'status': 'error',
        }
        et = et_mock()
        models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=True,
            languages='en-US,fr',
            vendor_id='TITLE_UNKNOWN',
        )
        # We're going to ask to subscribe to this one again
        data = {
            'lang': 'en',
            'country': 'US',
            'newsletters': 'slug',
            'format': 'H',
        }

        update_user(data, self.sub.email, self.sub.token, False, SET, True)
        # We should have mentioned this newsletter in our call to ET
        et.data_ext.return_value.add_record.assert_called_with(
            ANY,
            ['EMAIL_FORMAT_', 'EMAIL_ADDRESS_', 'LANGUAGE_ISO2',
             'TITLE_UNKNOWN_FLG', 'TOKEN', 'MODIFIED_DATE_',
             'EMAIL_PERMISSION_STATUS_', 'TITLE_UNKNOWN_DATE', 'COUNTRY_'],
            ['H', 'dude@example.com', 'en',
             'Y', ANY, ANY,
             'I', ANY, 'US'],
        )

    @skip("FIXME: What should we do if we can't talk to ET")  # FIXME
    @patch('news.tasks.ExactTarget')
    @patch('news.views.get_user_data')
    def test_unsub_is_not_careful_on_error(self, get_user_mock, et_mock):
        """
        When unsubscribing, we unsubscribe from the requested lists if we can't
        get user_data for some reason.
        """
        get_user_mock.return_value = {
            'status': 'error',
        }
        et = et_mock()
        models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=True,
            languages='en-US,fr',
            vendor_id='TITLE_UNKNOWN',
        )
        models.Newsletter.objects.create(
            slug='slug2',
            title='title2',
            active=True,
            languages='en-US,fr',
            vendor_id='TITLE2_UNKNOWN',
        )
        # We're going to ask to unsubscribe from both
        data = {
            'lang': 'en',
            'country': 'US',
            'newsletters': 'slug,slug2',
            'format': 'H',
        }

        update_user(data, self.sub.email, self.sub.token, False, UNSUBSCRIBE,
                    True)
        # We should mention both TITLE_UNKNOWN, and TITLE2_UNKNOWN
        et.data_ext.return_value.add_record.assert_called_with(
            ANY,
            ['EMAIL_FORMAT_', 'EMAIL_ADDRESS_', u'TITLE2_UNKNOWN_FLG',
             'LANGUAGE_ISO2', u'TITLE2_UNKNOWN_DATE', u'TITLE_UNKNOWN_FLG',
             'TOKEN', 'MODIFIED_DATE_', 'EMAIL_PERMISSION_STATUS_',
             u'TITLE_UNKNOWN_DATE', 'COUNTRY_'],
            ['H', 'dude@example.com', 'N', 'en', ANY, 'N', ANY, ANY, 'I',
             ANY, 'US'],
        )

    @patch('news.views.get_user_data')
    @patch('news.views.newsletter_fields')
    @patch('news.views.ExactTargetDataExt')
    @patch('news.tasks.ExactTarget')
    def test_unsub_is_careful(self, et_mock, etde_mock, newsletter_fields,
                              get_user_data):
        """
        When unsubscribing, we only unsubscribe things the user is
        currently subscribed to.
        """
        et = et_mock()
        etde = etde_mock()
        nl1 = models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=True,
            languages='en-US,fr',
            vendor_id='TITLE_UNKNOWN',
        )
        nl2 = models.Newsletter.objects.create(
            slug='slug2',
            title='title2',
            active=True,
            languages='en-US,fr',
            vendor_id='TITLE2_UNKNOWN',
        )
        # We're going to ask to unsubscribe from both
        data = {
            'lang': 'en',
            'country': 'US',
            'newsletters': 'slug,slug2',
            'format': 'H',
        }
        get_user_data.return_value = self.get_user_data

        newsletter_fields.return_value = [nl1.vendor_id, nl2.vendor_id]

        # We're only subscribed to TITLE_UNKNOWN though, not the other one
        etde.get_record.return_value = self.user_data

        rc = update_user(data, self.sub.email, self.sub.token, False,
                         UNSUBSCRIBE, True)
        self.assertEqual(UU_ALREADY_CONFIRMED, rc)
        # We should have looked up the user's data
        self.assertTrue(get_user_data.called)
        # We should only mention TITLE_UNKNOWN, not TITLE2_UNKNOWN
        et.data_ext.return_value.add_record.assert_called_with(
            ANY,
            ['EMAIL_FORMAT_', 'EMAIL_ADDRESS_', 'LANGUAGE_ISO2',
             u'TITLE_UNKNOWN_FLG', 'TOKEN', 'MODIFIED_DATE_',
             'EMAIL_PERMISSION_STATUS_', u'TITLE_UNKNOWN_DATE', 'COUNTRY_'],
            ['H', 'dude@example.com', 'en',
             'N', ANY, ANY,
             'I', ANY, 'US'],
        )

    @skip('Do not know what to do in this case')  # FIXME
    @patch('news.tasks.ExactTarget')
    @patch('news.views.get_user_data')
    def test_user_data_error(self, get_user_mock, et_mock):
        """
        Bug 871764: error from user data causing subscription to fail

        FIXME: SO, if we can't talk to ET, what SHOULD we do?
        """
        get_user_mock.return_value = {
            'status': 'error',
            'desc': 'fake error for testing',
        }
        et = et_mock()
        models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=True,
            languages='en-US,fr',
            vendor_id='TITLE_UNKNOWN',
        )
        # We're going to ask to subscribe to this one again
        data = {
            'lang': 'en',
            'country': 'US',
            'newsletters': 'slug',
            'format': 'H',
        }

        with self.assertRaises(RetryTask):
            update_user(data, self.sub.email, self.sub.token, False,
                        SUBSCRIBE, True)
        # We should have mentioned this newsletter in our call to ET
        et.data_ext.return_value.add_record.assert_called_with(
            ANY,
            ['EMAIL_FORMAT_', 'EMAIL_ADDRESS_', 'LANGUAGE_ISO2',
             'TITLE_UNKNOWN_FLG', 'TOKEN', 'MODIFIED_DATE_',
             'EMAIL_PERMISSION_STATUS_', 'TITLE_UNKNOWN_DATE', 'COUNTRY_'],
            ['H', 'dude@example.com', 'en',
             'Y', ANY, ANY,
             'I', ANY, 'US'],
        )

    @patch('news.tasks.ExactTarget')
    @patch('news.views.get_user_data')
    def test_update_user_without_format_doesnt_send_format(self,
                                                           get_user_mock,
                                                           et_mock):
        """
        ET format not changed if update_user call doesn't specify.

        If update_user call doesn't specify a format (e.g. if bedrock
        doesn't get a changed value on a form submission), then Basket
        doesn't send any format to ET.

        It does use the user's choice of format to send them their
        welcome message.
        """
        models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=True,
            languages='en-US,fr',
            vendor_id='TITLE_UNKNOWN',
        )
        get_user_mock.return_value = {
            'status': 'ok',
            'format': 'T',
            'confirmed': True,
            'master': True,
            'email': 'dude@example.com',
            'token': 'foo-token',
        }
        et = et_mock()
        data = {
            'lang': 'en',
            'country': 'US',
            'newsletters': 'slug',
            'trigger_welcome': 'Y',
        }
        update_user(data, self.sub.email, self.sub.token, False, SUBSCRIBE,
                    True)
        # We'll pass no format to ET
        et.data_ext.return_value.add_record.assert_called_with(
            ANY,
            ['EMAIL_ADDRESS_', 'LANGUAGE_ISO2',
             'TITLE_UNKNOWN_FLG', 'TOKEN', 'MODIFIED_DATE_',
             'EMAIL_PERMISSION_STATUS_', 'TITLE_UNKNOWN_DATE', 'COUNTRY_'],
            ['dude@example.com', 'en',
             'Y', ANY, ANY,
             'I', ANY, 'US'],
        )
        # We'll send their welcome in T format because that is the
        # user's preference in ET
        et.trigger_send.assert_called_with(
            'EN_39_T',
            {'EMAIL_FORMAT_': 'T',
             'EMAIL_ADDRESS_': 'dude@example.com',
             'TOKEN': ANY}
        )

    @patch('news.tasks.ExactTarget')
    @patch('news.views.get_user_data')
    def test_update_user_wo_format_or_pref(self,
                                           get_user_mock,
                                           et_mock):
        """
        ET format not changed if update_user call doesn't specify.

        If update_user call doesn't specify a format (e.g. if bedrock
        doesn't get a changed value on a form submission), then Basket
        doesn't send any format to ET.

        If the user does not have any format preference in ET, then
        the welcome is sent in HTML.
        """
        models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=True,
            languages='en-US,fr',
            vendor_id='TITLE_UNKNOWN',
        )
        get_user_mock.return_value = {
            'status': 'ok',
            'confirmed': True,
            'master': True,
            'email': 'dude@example.com',
            'token': 'foo-token',
        }
        et = et_mock()
        data = {
            'lang': 'en',
            'country': 'US',
            'newsletters': 'slug',
            'trigger_welcome': 'Y',
        }
        update_user(data, self.sub.email, self.sub.token, False, SUBSCRIBE,
                    True)
        # We'll pass no format to ET
        et.data_ext.return_value.add_record.assert_called_with(
            ANY,
            ['EMAIL_ADDRESS_', 'LANGUAGE_ISO2',
             'TITLE_UNKNOWN_FLG', 'TOKEN', 'MODIFIED_DATE_',
             'EMAIL_PERMISSION_STATUS_', 'TITLE_UNKNOWN_DATE', 'COUNTRY_'],
            ['dude@example.com', 'en',
             'Y', ANY, ANY,
             'I', ANY, 'US'],
        )
        # We'll send their welcome in H format because that is the
        # default when we have no other preference known.
        et.trigger_send.assert_called_with(
            'EN_39',
            {'EMAIL_FORMAT_': 'H',
             'EMAIL_ADDRESS_': 'dude@example.com',
             'TOKEN': ANY}
        )


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

        req = self.rf.get(self.url)
        resp = views.newsletters(req)
        data = json.loads(resp.content)
        newsletters = data['newsletters']
        self.assertEqual(2, len(newsletters))
        # Find the 'slug' newsletter in the response
        obj = newsletters['slug']

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


class TestGetUserData(TestCase):

    def generic_test(self,
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
        self.generic_test(None, None, None, False, None)

    def test_et_error(self):
        # Error calling Exact Target, return error code
        err_msg = "Mock error for testing"
        error = NewsletterException(err_msg)
        expected = {
            'status': 'error',
            'desc': err_msg,
            'status_code': 400,
        }
        self.generic_test(ANY, ANY, ANY, error, expected)

    def test_in_master(self):
        """
        If user is in master, get_user_data returns whatever
        look_for_user returns.
        """
        mock_user = {'dummy': 'Just a dummy user'}
        self.generic_test(mock_user, ANY, ANY, False, mock_user)

    def test_in_opt_in(self):
        """
        If user is in opt_in, get_user_data returns whatever
        look_for_user returns.
        """
        mock_user = {'token': 'Just a dummy user'}
        self.generic_test(None, mock_user, ANY, False, mock_user)


class TestConfirmationLogic(TestCase):
    def generic_test(self, user_in_basket, user_in_master,
                     user_in_optin, user_in_confirmed,
                     newsletter_with_required_confirmation,
                     newsletter_without_required_confirmation,
                     is_english, type,
                     expected_result):
        # Generic test routine - given a bunch of initial conditions and
        # an expected result, set up the conditions, make the call,
        # and verify we get the expected result.
        email = "dude@example.com"
        token = uuid4()

        if user_in_basket:
            models.Subscriber.objects.create(email=email, token=token)

        # What should get_user_data return?
        user = {}

        if user_in_master or user_in_confirmed or user_in_optin:
            user['status'] = 'ok'
            user['email'] = email
            user['format'] = 'T'
            user['token'] = token
            user['master'] = user_in_master
            user['confirmed'] = user_in_master or user_in_confirmed
            user['pending'] = user_in_optin and not user_in_confirmed
            user['newsletters'] = []   # start with none so whatever we call
                    # update_user with is a new subscription
        else:
            # User not in Exact Target at all
            user = None

        # Call data
        data = {}
        if is_english:
            data['lang'] = 'en'
            data['country'] = 'us'
        else:
            data['lang'] = 'fr'
            data['country'] = 'fr'

        # make some newsletters
        nl_required = models.Newsletter.objects.create(
            slug='slug1',
            vendor_id='VENDOR1',
            requires_double_optin=True,
        )
        nl_not_required = models.Newsletter.objects.create(
            slug='slug2',
            vendor_id='VENDOR2',
            requires_double_optin=False,
        )

        newsletters = []
        if newsletter_with_required_confirmation:
            newsletters.append(nl_required.slug)
        if newsletter_without_required_confirmation:
            newsletters.append(nl_not_required.slug)
        data['newsletters'] = ','.join(newsletters)

        # Mock data from ET
        with patch('news.views.get_user_data') as get_user_data:
            get_user_data.return_value = user

            # Don't actually call ET
            with patch('news.tasks.apply_updates'):
                with patch('news.tasks.send_welcomes'):
                    with patch('news.tasks.send_confirm_notice'):
                        created = not user_in_basket
                        rc = update_user(data, email, token, created, type,
                                         True)
        self.assertEqual(expected_result, rc)

    #
    # Tests for brand new users
    #

    def test_new_english_non_required(self):
        self.generic_test(user_in_basket=False,
                          user_in_master=False,
                          user_in_optin=False,
                          user_in_confirmed=False,
                          newsletter_with_required_confirmation=False,
                          newsletter_without_required_confirmation=True,
                          is_english=True,
                          type=SUBSCRIBE,
                          expected_result=UU_EXEMPT_NEW)

    def test_new_non_english_non_required(self):
        self.generic_test(user_in_basket=False,
                          user_in_master=False,
                          user_in_optin=False,
                          user_in_confirmed=False,
                          newsletter_with_required_confirmation=False,
                          newsletter_without_required_confirmation=True,
                          is_english=False,
                          type=SUBSCRIBE,
                          expected_result=UU_EXEMPT_NEW)

    def test_new_english_required_and_not(self):
        self.generic_test(user_in_basket=False,
                          user_in_master=False,
                          user_in_optin=False,
                          user_in_confirmed=False,
                          newsletter_with_required_confirmation=True,
                          newsletter_without_required_confirmation=True,
                          is_english=True,
                          type=SUBSCRIBE,
                          expected_result=UU_EXEMPT_NEW)

    def test_new_non_english_required_and_not(self):
        self.generic_test(user_in_basket=False,
                          user_in_master=False,
                          user_in_optin=False,
                          user_in_confirmed=False,
                          newsletter_with_required_confirmation=True,
                          newsletter_without_required_confirmation=True,
                          is_english=False,
                          type=SUBSCRIBE,
                          expected_result=UU_EXEMPT_NEW)

    def test_new_non_english_required(self):
        self.generic_test(user_in_basket=False,
                          user_in_master=False,
                          user_in_optin=False,
                          user_in_confirmed=False,
                          newsletter_with_required_confirmation=True,
                          newsletter_without_required_confirmation=False,
                          is_english=False,
                          type=SUBSCRIBE,
                          expected_result=UU_MUST_CONFIRM_NEW)

    #
    # Tests for users already pending confirmation
    #

    def test_pending_english_required(self):
        # Should exempt them and confirm them
        self.generic_test(user_in_basket=False,
                          user_in_master=False,
                          user_in_optin=True,
                          user_in_confirmed=False,
                          newsletter_with_required_confirmation=True,
                          newsletter_without_required_confirmation=False,
                          is_english=True,
                          type=SUBSCRIBE,
                          expected_result=UU_EXEMPT_PENDING)

    def test_pending_english_not_required(self):
        # Should exempt them and confirm them
        self.generic_test(user_in_basket=False,
                          user_in_master=False,
                          user_in_optin=True,
                          user_in_confirmed=False,
                          newsletter_with_required_confirmation=True,
                          newsletter_without_required_confirmation=True,
                          is_english=True,
                          type=SUBSCRIBE,
                          expected_result=UU_EXEMPT_PENDING)

    def test_pending_non_english_required(self):
        # Still have to confirm
        self.generic_test(user_in_basket=False,
                          user_in_master=False,
                          user_in_optin=True,
                          user_in_confirmed=False,
                          newsletter_with_required_confirmation=True,
                          newsletter_without_required_confirmation=False,
                          is_english=False,
                          type=SUBSCRIBE,
                          expected_result=UU_MUST_CONFIRM_PENDING)

    def test_pending_non_english_not_required(self):
        # Should exempt them and confirm them
        self.generic_test(user_in_basket=False,
                          user_in_master=False,
                          user_in_optin=True,
                          user_in_confirmed=False,
                          newsletter_with_required_confirmation=True,
                          newsletter_without_required_confirmation=True,
                          is_english=False,
                          type=SUBSCRIBE,
                          expected_result=UU_EXEMPT_PENDING)

    #
    # Tests for users who have confirmed but not yet been moved to master
    #

    def test_confirmed_english_required(self):
        self.generic_test(user_in_basket=False,
                          user_in_master=False,
                          user_in_optin=True,
                          user_in_confirmed=True,
                          newsletter_with_required_confirmation=True,
                          newsletter_without_required_confirmation=False,
                          is_english=True,
                          type=SUBSCRIBE,
                          expected_result=UU_ALREADY_CONFIRMED)

    def test_confirmed_non_english_required(self):
        self.generic_test(user_in_basket=False,
                          user_in_master=False,
                          user_in_optin=True,
                          user_in_confirmed=True,
                          newsletter_with_required_confirmation=True,
                          newsletter_without_required_confirmation=False,
                          is_english=False,
                          type=SUBSCRIBE,
                          expected_result=UU_ALREADY_CONFIRMED)

    def test_confirmed_english_not_required(self):
        self.generic_test(user_in_basket=False,
                          user_in_master=False,
                          user_in_optin=True,
                          user_in_confirmed=True,
                          newsletter_with_required_confirmation=False,
                          newsletter_without_required_confirmation=True,
                          is_english=True,
                          type=SUBSCRIBE,
                          expected_result=UU_ALREADY_CONFIRMED)

    def test_confirmed_non_english_not_required(self):
        self.generic_test(user_in_basket=False,
                          user_in_master=False,
                          user_in_optin=True,
                          user_in_confirmed=True,
                          newsletter_with_required_confirmation=False,
                          newsletter_without_required_confirmation=True,
                          is_english=False,
                          type=SUBSCRIBE,
                          expected_result=UU_ALREADY_CONFIRMED)
    #
    # Tests for users who are already in master
    #

    def test_master_english_required(self):
        self.generic_test(user_in_basket=False,
                          user_in_master=True,
                          user_in_optin=False,
                          user_in_confirmed=True,
                          newsletter_with_required_confirmation=True,
                          newsletter_without_required_confirmation=False,
                          is_english=True,
                          type=SUBSCRIBE,
                          expected_result=UU_ALREADY_CONFIRMED)

    def test_master_non_english_required(self):
        self.generic_test(user_in_basket=False,
                          user_in_master=True,
                          user_in_optin=False,
                          user_in_confirmed=True,
                          newsletter_with_required_confirmation=True,
                          newsletter_without_required_confirmation=False,
                          is_english=False,
                          type=SUBSCRIBE,
                          expected_result=UU_ALREADY_CONFIRMED)

    def test_master_english_not_required(self):
        self.generic_test(user_in_basket=False,
                          user_in_master=True,
                          user_in_optin=False,
                          user_in_confirmed=True,
                          newsletter_with_required_confirmation=False,
                          newsletter_without_required_confirmation=True,
                          is_english=True,
                          type=SUBSCRIBE,
                          expected_result=UU_ALREADY_CONFIRMED)

    def test_master_non_english_not_required(self):
        self.generic_test(user_in_basket=False,
                          user_in_master=True,
                          user_in_optin=False,
                          user_in_confirmed=True,
                          newsletter_with_required_confirmation=False,
                          newsletter_without_required_confirmation=True,
                          is_english=False,
                          type=SUBSCRIBE,
                          expected_result=UU_ALREADY_CONFIRMED)


class TestLanguageCodeIsValid(TestCase):
    @patch('news.views.newsletter_languages')
    def test_empty_string(self, n_l):
        """Empty string is accepted as a language code"""
        self.assertTrue(language_code_is_valid(''))

    @patch('news.views.newsletter_languages')
    def test_none(self, n_l):
        """None is a TypeError"""
        with self.assertRaises(TypeError):
            language_code_is_valid(None)

    @patch('news.views.newsletter_languages')
    def test_zero(self, n_l):
        """0 is a TypeError"""
        with self.assertRaises(TypeError):
            language_code_is_valid(0)

    @patch('news.views.newsletter_languages')
    def test_exact_2_letter(self, n_l):
        """2-letter code that's in the list is valid"""
        n_l.return_value = ['az']
        self.assertTrue(language_code_is_valid('az'))

    @patch('news.views.newsletter_languages')
    def test_exact_5_letter(self, n_l):
        """5-letter code that's in the list is valid"""
        n_l.return_value = ['az-BY']
        self.assertTrue(language_code_is_valid('az-BY'))

    @patch('news.views.newsletter_languages')
    def test_prefix(self, n_l):
        """2-letter code that's a prefix of something in the list is valid"""
        n_l.return_value = ['az-BY']
        self.assertTrue(language_code_is_valid('az'))

    @patch('news.views.newsletter_languages')
    def test_long_version(self, n_l):
        """5-letter code is valid if an entry in the list is a prefix of it"""
        n_l.return_value = ['az']
        self.assertTrue(language_code_is_valid('az-BY'))

    @patch('news.views.newsletter_languages')
    def test_case_insensitive(self, n_l):
        """Matching is not case sensitive"""
        n_l.return_value = ['aZ', 'Qw-wE']
        self.assertTrue(language_code_is_valid('az-BY'))
        self.assertTrue(language_code_is_valid('az'))
        self.assertTrue(language_code_is_valid('QW'))

    @patch('news.views.newsletter_languages')
    def test_wrong_length(self, n_l):
        """A code that's a prefix of something in the list, but not a valid
        length, is not valid. Or vice-versa."""
        n_l.return_value = ['az-BY']
        self.assertFalse(language_code_is_valid('az-'))
        self.assertFalse(language_code_is_valid('a'))
        self.assertFalse(language_code_is_valid('az-BY2'))

    @patch('news.views.newsletter_languages')
    def test_no_match(self, n_l):
        """Return False if there's no match any way we try."""
        n_l.return_value = ['az']
        self.assertFalse(language_code_is_valid('by'))


@patch('news.tasks.send_welcomes')
@patch('news.tasks.apply_updates')
class TestConfirmTask(TestCase):
    def test_error(self, apply_updates, send_welcomes):
        """
        If user_data shows an error talking to ET, the task raises
        an exception so our task logic will retry
        """
        user_data = {
            'status': 'error',
            'desc': 'TESTERROR',
        }
        token = "TOKEN"
        with self.assertRaises(RetryTask):
            confirm_user(token, user_data)
        self.assertFalse(apply_updates.called)
        self.assertFalse(send_welcomes.called)

    def test_normal(self, apply_updates, send_welcomes):
        """If user_data is okay, and not yet confirmed, the task calls
         the right stuff"""
        user_data = {
            'status': 'ok',
            'confirmed': False,
            'newsletters': Mock(),
            'format': 'ZZ',
        }
        token = "TOKEN"
        confirm_user(token, user_data)
        apply_updates.assert_called_with(settings.EXACTTARGET_CONFIRMATION,
                                         {'TOKEN': token})
        send_welcomes.assert_called_with(user_data, user_data['newsletters'],
                                         user_data['format'])

    def test_already_confirmed(self, apply_updates, send_welcomes):
        """If user_data already confirmed, task does nothing"""
        user_data = {
            'status': 'ok',
            'confirmed': True,
            'newsletters': Mock(),
            'format': 'ZZ',
        }
        token = "TOKEN"
        confirm_user(token, user_data)
        self.assertFalse(apply_updates.called)
        self.assertFalse(send_welcomes.called)

    def test_user_not_found(self, apply_updates, send_welcomes):
        """If we can't find the user, do nothing"""
        # Can't patch get_user_data because confirm_user imports it
        # internally. But we can patch look_for_user, which get_user_data
        # will call
        with patch('news.views.look_for_user') as look_for_user:
            look_for_user.return_value = None
            user_data = None
            token = "TOKEN"
            confirm_user(token, user_data)
        self.assertFalse(apply_updates.called)
        self.assertFalse(send_welcomes.called)

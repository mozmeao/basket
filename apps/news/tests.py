import datetime
import json

from django.conf import settings
from django.core.urlresolvers import reverse
from django.test import TestCase

from mock import ANY, patch
from test_utils import RequestFactory

from news import models, tasks, views
from news.backends.exacttarget import NewsletterException
from news.newsletters import newsletter_fields
from news.tasks import SET, SUBSCRIBE, UNSUBSCRIBE, update_user


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

    @patch('news.views.update_user.delay')
    def test_subscribe_success(self, uu_mock):
        """Subscription should work."""
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
        sub = models.Subscriber.objects.get(email='donnie@example.com')
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

    @patch('news.views.ExactTargetDataExt')
    @patch('news.tasks.ExactTarget')
    def test_update_send_newsletter_welcome(self, et_mock, etde_mock):
        # If we just subscribe to one newsletter, we send that
        # newsletter's particular welcome message
        et = et_mock()
        welcome_id = "TEST_WELCOME"
        nl = models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=True,
            languages='en,fr',
            welcome=welcome_id,
        )
        data = {
            'country': 'US',
            'format': 'H',
            'newsletters': nl.slug,
            'trigger_welcome': 'Y',
        }
        update_user(data=data,
                    email=self.sub.email,
                    token=self.sub.token,
                    created=True,
                    type=SUBSCRIBE,
                    optin=True)
        et.trigger_send.assert_called_with(
            welcome_id,
            {
                'EMAIL_FORMAT_': 'H',
                'EMAIL_ADDRESS_': self.sub.email,
                'TOKEN': self.sub.token,
            },
        )

    @patch('news.views.ExactTargetDataExt')
    @patch('news.tasks.ExactTarget')
    def test_update_send_newsletters_welcome(self, et_mock, etde_mock):
        # If we subscribe to multiple newsletters, even if they
        # have custom welcome messages, we send the default
        et = et_mock()
        nl1 = models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=True,
            languages='en,fr',
            welcome="WELCOME1",
        )
        nl2 = models.Newsletter.objects.create(
            slug='slug2',
            title='title',
            active=True,
            languages='en,fr',
            welcome="WELCOME2",
        )
        data = {
            'country': 'US',
            'format': 'H',
            'newsletters': "%s,%s" % (nl1.slug, nl2.slug),
            'trigger_welcome': 'Y',
        }
        update_user(data=data,
                    email=self.sub.email,
                    token=self.sub.token,
                    created=True,
                    type=SUBSCRIBE,
                    optin=True)
        et.trigger_send.assert_called_with(
            settings.DEFAULT_WELCOME_MESSAGE_ID,
            {
                'EMAIL_FORMAT_': 'H',
                'EMAIL_ADDRESS_': self.sub.email,
                'TOKEN': self.sub.token,
            },
        )

    @patch('news.views.ExactTargetDataExt')
    @patch('news.tasks.ExactTarget')
    def test_update_send_welcome(self, et_mock, etde_mock):
        """
        Update sends default welcome if newsletter has none,
        or, we can specify a particular welcome
        """
        et = et_mock()
        nl1 = models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=True,
            languages='en-US,fr',
        )
        data = {
            'country': 'US',
            'format': 'H',
            'newsletters': nl1.slug,
        }

        update_user(data=data, email=self.sub.email,
                    token=self.sub.token,
                    created=True,
                    type=SUBSCRIBE, optin=True)
        et.trigger_send.assert_called_with(
            settings.DEFAULT_WELCOME_MESSAGE_ID,
            {
                'EMAIL_FORMAT_': 'H',
                'EMAIL_ADDRESS_': self.sub.email,
                'TOKEN': self.sub.token,
            },
        )

        # Can specify a different welcome
        welcome = 'MyWelcome_H'
        data['welcome_message'] = welcome
        update_user(data=data, email=self.sub.email,
                    token=self.sub.token,
                    created=True,
                    type=SUBSCRIBE, optin=True)
        et.trigger_send.assert_called_with(
            welcome,
            {
                'EMAIL_FORMAT_': 'H',
                'EMAIL_ADDRESS_': self.sub.email,
                'TOKEN': self.sub.token,
            },
        )

    @patch('news.views.ExactTargetDataExt')
    @patch('news.tasks.ExactTarget')
    def test_update_user_works_with_no_welcome(self, et_mock, etde_mock):
        """update_user was throwing errors when asked not to send a welcome"""
        et = et_mock()
        nl1 = models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=True,
            languages='en-US,fr',
        )
        data = {
            'country': 'US',
            'newsletters': nl1.slug,
            'trigger_welcome': 'N',
            'format': 'T',
        }

        update_user(data=data, email=self.sub.email,
                    token=self.sub.token,
                    created=True,
                    type=SUBSCRIBE, optin=True)

        self.assertTrue(et.data_ext.return_value.add_record.called)
        self.assertFalse(et.trigger_send.called)

    @patch('news.views.newsletter_fields')
    @patch('news.views.ExactTargetDataExt')
    @patch('news.tasks.ExactTarget')
    def test_update_user_set_works_no_newsletters(self, et_mock, etde_mock,
                                                  newsletter_fields):
        """
        A blank `newsletters` field when the update type is SET indicates
        that the person wishes to unsubscribe from all newsletters. This has
        caused exceptions because '' is not a valid newsletter name.
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
        data = {
            'lang': 'en',
            'country': 'US',
            'newsletters': '',
            'format': 'H',
        }

        newsletter_fields.return_value = [nl1.vendor_id]

        # Mock user data - we want our user subbed to our newsletter to start
        etde.get_record.return_value = self.user_data

        update_user(data, self.sub.email, self.sub.token, False, SET, True)
        # no welcome should be triggered for SET
        self.assertFalse(et.trigger_send.called)
        # We should have looked up the user's data
        self.assertTrue(etde.get_record.called)
        et.data_ext.return_value.add_record.assert_called_with(
            ANY,
            ['EMAIL_FORMAT_', 'EMAIL_ADDRESS_', 'LANGUAGE_ISO2',
             u'TITLE_UNKNOWN_FLG', 'TOKEN', 'MODIFIED_DATE_',
             'EMAIL_PERMISSION_STATUS_', u'TITLE_UNKNOWN_DATE', 'COUNTRY_'],
            ['H', 'dude@example.com', 'en',
             'N', ANY, ANY,
             'I', ANY, 'US'],
        )

    @patch('news.views.newsletter_fields')
    @patch('news.views.ExactTargetDataExt')
    @patch('news.tasks.ExactTarget')
    def test_resubscribe_doesnt_update_newsletter(self, et_mock, etde_mock,
                                                  newsletter_fields):
        """
        When subscribing to things the user is already subscribed to, we
        do not pass that newsletter's _FLG and _DATE to ET because we
        don't want that newsletter's _DATE to be updated for no reason.
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
        # We're going to ask to subscribe to this one again
        data = {
            'lang': 'en',
            'country': 'US',
            'newsletters': 'slug',
            'format': 'H',
        }

        newsletter_fields.return_value = [nl1.vendor_id]

        # Mock user data - we want our user subbed to our newsletter to start
        etde.get_record.return_value = self.user_data

        update_user(data, self.sub.email, self.sub.token, False, SUBSCRIBE,
                    True)
        # We should have looked up the user's data
        self.assertTrue(etde.get_record.called)
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

    @patch('news.views.newsletter_fields')
    @patch('news.views.ExactTargetDataExt')
    @patch('news.tasks.ExactTarget')
    def test_set_doesnt_update_newsletter(self, et_mock, etde_mock,
                                          newsletter_fields):
        """
        When setting the newsletters to ones the user is already subscribed
        to, we do not pass that newsletter's _FLG and _DATE to ET because we
        don't want that newsletter's _DATE to be updated for no reason.
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
        # We're going to ask to subscribe to this one again
        data = {
            'lang': 'en',
            'country': 'US',
            'newsletters': 'slug',
            'format': 'H',
        }

        newsletter_fields.return_value = [nl1.vendor_id]

        # Mock user data - we want our user subbed to our newsletter to start
        etde.get_record.return_value = self.user_data

        update_user(data, self.sub.email, self.sub.token, False, SET, True)
        # We should have looked up the user's data
        self.assertTrue(etde.get_record.called)
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

    @patch('news.views.newsletter_fields')
    @patch('news.views.ExactTargetDataExt')
    @patch('news.tasks.ExactTarget')
    def test_unsub_is_careful(self, et_mock, etde_mock, newsletter_fields):
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

        newsletter_fields.return_value = [nl1.vendor_id, nl2.vendor_id]

        # We're only subscribed to TITLE_UNKNOWN though, not the other one
        etde.get_record.return_value = self.user_data

        update_user(data, self.sub.email, self.sub.token, False, UNSUBSCRIBE,
                    True)
        # We should have looked up the user's data
        self.assertTrue(etde.get_record.called)
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

    @patch('news.tasks.ExactTarget')
    @patch('news.views.get_user_data')
    def test_user_data_error(self, get_user_mock, et_mock):
        """
        Bug 871764: error from user data causing subscription to fail
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

        update_user(data, self.sub.email, self.sub.token, False, SUBSCRIBE,
                    True)
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
            '39_T',
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
            '39',
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
        )

        models.Newsletter.objects.create(slug='slug2')

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
        )
        nl1 = models.Newsletter.objects.get(id=nl1.id)
        self.assertEqual('en-US,fr,de', nl1.languages)

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

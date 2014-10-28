import datetime

from django.conf import settings
from django.test import TestCase
from django.test.client import RequestFactory
from django.utils.unittest import skip

from mock import patch, ANY

from news import models
from news.backends.common import NewsletterException
from news.tasks import (update_user, SUBSCRIBE, UU_EXEMPT_NEW, UU_ALREADY_CONFIRMED, SET,
                        FFOS_VENDOR_ID, FFAY_VENDOR_ID, UNSUBSCRIBE)


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

    @patch('news.tasks.apply_updates')
    @patch('news.tasks.send_message')
    @patch('news.tasks.get_user_data')
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
        }
        rc = update_user(data=data,
                         email=self.sub.email,
                         token=self.sub.token,
                         api_call_type=SUBSCRIBE,
                         optin=True)
        self.assertEqual(UU_ALREADY_CONFIRMED, rc)
        apply_updates.assert_called()
        # The welcome should have been sent
        send_message.delay.assert_called()
        send_message.delay.assert_called_with('en_' + welcome_id, self.sub.email,
                                              self.sub.token, 'H')

    @patch('news.tasks.apply_updates')
    @patch('news.tasks.send_message')
    @patch('news.tasks.get_user_data')
    def test_update_send_no_welcome(self, get_user_data, send_message,
                                    apply_updates):
        """Caller can block sending welcome using trigger_welcome=N
        or anything other than 'Y'"""

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
            'trigger_welcome': 'Nope',
        }
        rc = update_user(data=data,
                         email=self.sub.email,
                         token=self.sub.token,
                         api_call_type=SUBSCRIBE,
                         optin=True)
        self.assertEqual(UU_ALREADY_CONFIRMED, rc)
        # We do subscribe them
        apply_updates.assert_called()
        # The welcome should NOT have been sent
        self.assertFalse(send_message.called)

    @patch('news.tasks.apply_updates')
    @patch('news.tasks.send_message')
    @patch('news.tasks.get_user_data')
    def test_update_SET_no_welcome(self, get_user_data, send_message,
                                   apply_updates):
        """api_call_type=SET sends no welcomes"""

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
        }
        rc = update_user(data=data,
                         email=self.sub.email,
                         token=self.sub.token,
                         api_call_type=SET,
                         optin=True)
        self.assertEqual(UU_ALREADY_CONFIRMED, rc)
        apply_updates.assert_called()
        # The welcome should NOT have been sent
        self.assertFalse(send_message.called)

    @patch('news.tasks.get_user_data')
    @patch('news.utils.ExactTargetDataExt')
    @patch('news.tasks.ExactTarget')
    def test_update_no_welcome_set(self, et_mock, etde_mock, get_user_data):
        """
        Update sends no welcome if newsletter has no welcome set,
        or it's a space.
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
                         api_call_type=SUBSCRIBE, optin=True)
        self.assertEqual(UU_ALREADY_CONFIRMED, rc)
        self.assertFalse(et.trigger_send.called)

        # welcome of ' ' is same as none
        nl1.welcome = ' '
        et.trigger_send.reset_mock()
        rc = update_user(data=data, email=self.sub.email,
                         token=self.sub.token,
                         api_call_type=SUBSCRIBE, optin=True)
        self.assertEqual(UU_ALREADY_CONFIRMED, rc)
        self.assertFalse(et.trigger_send.called)

        # FIXME? I think we don't need the ability for the caller
        # to override the welcome message
        # Can specify a different welcome
        # welcome = 'MyWelcome_H'
        # data['welcome_message'] = welcome
        # update_user(data=data, email=self.sub.email,
        #             token=self.sub.token,
        #             api_call_type=SUBSCRIBE, optin=True)
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
    @patch('news.tasks.get_user_data')
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
        }
        rc = update_user(data=data,
                         email=self.sub.email,
                         token=self.sub.token,
                         api_call_type=SUBSCRIBE,
                         optin=True)
        self.assertEqual(UU_EXEMPT_NEW, rc)
        self.assertEqual(2, send_message.delay.call_count)
        calls_args = [x[0] for x in send_message.delay.call_args_list]
        self.assertIn(('en_WELCOME1', self.sub.email, self.sub.token, 'H'),
                      calls_args)
        self.assertIn(('en_WELCOME2', self.sub.email, self.sub.token, 'H'),
                      calls_args)

    @patch('news.tasks.apply_updates')
    @patch('news.tasks.send_message')
    @patch('news.tasks.get_user_data')
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
                         api_call_type=SUBSCRIBE, optin=True)
        self.assertEqual(UU_ALREADY_CONFIRMED, rc)
        apply_updates.assert_called()
        send_message.delay.assert_called()

    @patch('news.tasks.apply_updates')
    @patch('news.tasks.send_message')
    @patch('news.tasks.get_user_data')
    def test_update_user_works_with_no_lang(self, get_user_data,
                                            send_message,
                                            apply_updates):
        """update_user was ending up with None lang breaking send_welcomes
         when new user and POST data had no lang"""
        nl1 = models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=True,
            languages='en-US,fr',
            vendor_id='VENDOR1',
            welcome='Welcome'
        )
        data = {
            'country': 'US',
            'format': 'H',
            'newsletters': nl1.slug,
            'format': 'T',
        }
        # new user, not in ET yet
        get_user_data.return_value = None
        rc = update_user(data=data, email=self.sub.email,
                         token=self.sub.token,
                         api_call_type=SUBSCRIBE, optin=True)
        self.assertEqual(UU_EXEMPT_NEW, rc)
        apply_updates.assert_called()
        send_message.delay.assert_called_with(u'en_Welcome_T',
                                              self.sub.email,
                                              self.sub.token,
                                              'T')

    @patch('news.tasks.apply_updates')
    @patch('news.tasks.send_message')
    @patch('news.tasks.get_user_data')
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
        }
        rc = update_user(data=data,
                         email=self.sub.email,
                         token=self.sub.token,
                         api_call_type=SUBSCRIBE,
                         optin=True)
        self.assertEqual(UU_EXEMPT_NEW, rc)
        self.assertEqual(1, send_message.delay.call_count)
        calls_args = [x[0] for x in send_message.delay.call_args_list]
        self.assertIn(('en_FFOS_WELCOME', self.sub.email, self.sub.token, 'H'),
                      calls_args)
        self.assertNotIn(('en_FF&Y_WELCOME', self.sub.email,
                          self.sub.token, 'H'),
                         calls_args)

    @patch('news.tasks.apply_updates')
    @patch('news.tasks.send_message')
    @patch('news.tasks.get_user_data')
    @patch('news.utils.newsletter_fields')
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
                         SET, True)
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
    @patch('news.tasks.get_user_data')
    @patch('news.utils.newsletter_fields')
    @patch('news.utils.ExactTargetDataExt')
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
                         SUBSCRIBE, True)
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

    @patch('news.tasks.get_user_data')
    @patch('news.utils.newsletter_fields')
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

        update_user(data, self.sub.email, self.sub.token, SET, True)
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
    @patch('news.tasks.get_user_data')
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

        update_user(data, self.sub.email, self.sub.token, SET, True)
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
    @patch('news.tasks.get_user_data')
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

        update_user(data, self.sub.email, self.sub.token, UNSUBSCRIBE,
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

    @patch('news.tasks.get_user_data')
    @patch('news.utils.newsletter_fields')
    @patch('news.utils.ExactTargetDataExt')
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

        rc = update_user(data, self.sub.email, self.sub.token, UNSUBSCRIBE, True)
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
    @patch('news.tasks.get_user_data')
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

        with self.assertRaises(NewsletterException):
            update_user(data, self.sub.email, self.sub.token, SUBSCRIBE, True)
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
    @patch('news.tasks.get_user_data')
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
            welcome='39',
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
        }
        update_user(data, self.sub.email, self.sub.token, SUBSCRIBE, True)
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
            'en_39_T',
            {'EMAIL_FORMAT_': 'T',
             'EMAIL_ADDRESS_': 'dude@example.com',
             'TOKEN': ANY}
        )

    @patch('news.tasks.ExactTarget')
    @patch('news.tasks.get_user_data')
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
            welcome='39',
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
        }
        update_user(data, self.sub.email, self.sub.token, SUBSCRIBE, True)
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
            'en_39',
            {'EMAIL_FORMAT_': 'H',
             'EMAIL_ADDRESS_': 'dude@example.com',
             'TOKEN': ANY}
        )

import datetime

from django.conf import settings
from django.test import TestCase
from django.test.client import RequestFactory

from mock import patch, ANY

from news import models
from news.tasks import update_user, UU_EXEMPT_NEW, UU_ALREADY_CONFIRMED
from news.utils import SET, SUBSCRIBE, UNSUBSCRIBE, generate_token


class UpdateUserTest(TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.token = generate_token()
        self.email = 'dude@example.com'
        self.user_data = {
            'EMAIL_ADDRESS_': self.email,
            'EMAIL_FORMAT_': 'H',
            'COUNTRY_': 'us',
            'LANGUAGE_ISO2': 'en',
            'TOKEN': 'token',
            'CREATED_DATE_': datetime.datetime.now(),
            'TITLE_UNKNOWN_FLG': 'Y',
        }
        # User data in format that get_user_data() returns it
        self.get_user_data = {
            'email': self.email,
            'format': 'H',
            'country': 'us',
            'lang': 'en',
            'token': self.token,
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
                         email=self.email,
                         token=self.token,
                         api_call_type=SUBSCRIBE,
                         optin=True)
        self.assertEqual(UU_ALREADY_CONFIRMED, rc)
        apply_updates.assert_called()
        # The welcome should have been sent
        send_message.delay.assert_called()
        send_message.delay.assert_called_with('en_' + welcome_id, self.email,
                                              self.token, 'H')

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
                         email=self.email,
                         token=self.token,
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
                         email=self.email,
                         token=self.token,
                         api_call_type=SET,
                         optin=True)
        self.assertEqual(UU_ALREADY_CONFIRMED, rc)
        apply_updates.assert_called()
        # The welcome should NOT have been sent
        self.assertFalse(send_message.called)

    @patch('news.tasks.get_user_data')
    @patch('news.tasks.sfmc')
    def test_update_no_welcome_set(self, sfmc_mock, get_user_data):
        """
        Update sends no welcome if newsletter has no welcome set,
        or it's a space.
        """
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

        self.get_user_data['newsletters'] = []
        get_user_data.return_value = self.get_user_data

        rc = update_user(data=data, email=self.email,
                         token=self.token,
                         api_call_type=SUBSCRIBE, optin=True)
        self.assertEqual(UU_ALREADY_CONFIRMED, rc)
        self.assertFalse(sfmc_mock.send_mail.called)

        # welcome of ' ' is same as none
        nl1.welcome = ' '
        sfmc_mock.send_mail.reset_mock()
        rc = update_user(data=data, email=self.email,
                         token=self.token,
                         api_call_type=SUBSCRIBE, optin=True)
        self.assertEqual(UU_ALREADY_CONFIRMED, rc)
        self.assertFalse(sfmc_mock.send_mail.called)

    @patch('news.tasks.apply_updates')
    @patch('news.tasks.send_message')
    @patch('news.tasks.get_user_data')
    def test_update_first_last_names(self, get_user_data, send_message, apply_updates):
        # sending name fields should result in names being passed to ET
        get_user_data.return_value = None  # Does not exist yet
        nl1 = models.Newsletter.objects.create(
                slug='slug',
                title='title',
                active=True,
                languages='en,fr',
                welcome="WELCOME1",
                vendor_id='VENDOR1',
        )
        data = {
            'country': 'US',
            'lang': 'en',
            'format': 'H',
            'newsletters': "%s" % nl1.slug,
            'first_name': 'The',
            'last_name': 'Dude',
        }
        rc = update_user(data=data,
                         email=self.email,
                         token=self.token,
                         api_call_type=SUBSCRIBE,
                         optin=True)
        self.assertEqual(UU_EXEMPT_NEW, rc)
        send_message.delay.assert_called()
        record = apply_updates.call_args[0][1]
        self.assertEqual(record['FIRST_NAME'], 'The')
        self.assertEqual(record['LAST_NAME'], 'Dude')

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
                         email=self.email,
                         token=self.token,
                         api_call_type=SUBSCRIBE,
                         optin=True)
        self.assertEqual(UU_EXEMPT_NEW, rc)
        self.assertEqual(2, send_message.delay.call_count)
        calls_args = [x[0] for x in send_message.delay.call_args_list]
        self.assertIn(('en_WELCOME1', self.email, self.token, 'H'),
                      calls_args)
        self.assertIn(('en_WELCOME2', self.email, self.token, 'H'),
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
        rc = update_user(data=data, email=self.email,
                         token=self.token,
                         api_call_type=SUBSCRIBE, optin=True)
        self.assertEqual(UU_ALREADY_CONFIRMED, rc)
        apply_updates.assert_called()
        send_message.delay.assert_not_called()

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
        rc = update_user(data=data, email=self.email,
                         token=self.token,
                         api_call_type=SUBSCRIBE, optin=True)
        self.assertEqual(UU_EXEMPT_NEW, rc)
        apply_updates.assert_called()
        send_message.delay.assert_called_with(u'en_Welcome_T',
                                              self.email,
                                              self.token,
                                              'T')

    @patch('news.tasks.apply_updates')
    @patch('news.tasks.send_message')
    @patch('news.tasks.get_user_data')
    @patch('news.utils.newsletter_fields')
    @patch('news.tasks.sfmc')
    def test_update_user_set_works_if_no_newsletters(self, sfmc_mock,
                                                     newsletter_fields,
                                                     get_user_data,
                                                     send_message,
                                                     apply_updates):
        """
        A blank `newsletters` field when the update type is SET indicates
        that the person wishes to unsubscribe from all newsletters. This has
        caused exceptions because '' is not a valid newsletter name.
        """
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

        rc = update_user(data, self.email, self.token,
                         SET, True)
        self.assertEqual(UU_ALREADY_CONFIRMED, rc)
        # no welcome should be triggered for SET
        self.assertFalse(sfmc_mock.send_mail.called)
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
    @patch('news.tasks.sfmc')
    def test_resubscribe_doesnt_update_newsletter(self, sfmc_mock,
                                                  newsletter_fields,
                                                  get_user_data,
                                                  send_message,
                                                  apply_updates):
        """
        When subscribing to things the user is already subscribed to, we
        do not pass that newsletter's _FLG and _DATE to ET because we
        don't want that newsletter's _DATE to be updated for no reason.
        """
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
        sfmc_mock.get_row.return_value = self.user_data

        rc = update_user(data, self.email, self.token,
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
    @patch('news.tasks.sfmc')
    def test_set_doesnt_update_newsletter(self, sfmc_mock,
                                          newsletter_fields,
                                          get_user_data):
        """
        When setting the newsletters to ones the user is already subscribed
        to, we do not pass that newsletter's _FLG and _DATE to ET because we
        don't want that newsletter's _DATE to be updated for no reason.
        """
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
        # etde.get_record.return_value = self.user_data

        update_user(data, self.email, self.token, SET, True)
        # We should have looked up the user's data
        self.assertTrue(get_user_data.called)
        # We should not have mentioned this newsletter in our call to ET
        sfmc_mock.upsert_row.assert_called_with(ANY, {
            'EMAIL_FORMAT_': 'H',
            'EMAIL_ADDRESS_': 'dude@example.com',
            'LANGUAGE_ISO2': 'en',
            'TOKEN': ANY,
            'MODIFIED_DATE_': ANY,
            'EMAIL_PERMISSION_STATUS_': 'I',
            'COUNTRY_': 'US',
        })

    @patch('news.tasks.get_user_data')
    @patch('news.utils.newsletter_fields')
    @patch('news.tasks.sfmc')
    def test_unsub_is_careful(self, sfmc_mock, newsletter_fields, get_user_data):
        """
        When unsubscribing, we only unsubscribe things the user is
        currently subscribed to.
        """
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
        sfmc_mock.get_row.return_value = self.user_data

        rc = update_user(data, self.email, self.token, UNSUBSCRIBE, True)
        self.assertEqual(UU_ALREADY_CONFIRMED, rc)
        # We should have looked up the user's data
        self.assertTrue(get_user_data.called)
        # We should only mention TITLE_UNKNOWN, not TITLE2_UNKNOWN
        sfmc_mock.upsert_row.assert_called_with(ANY, {
            'EMAIL_FORMAT_': 'H',
            'EMAIL_ADDRESS_': 'dude@example.com',
            'LANGUAGE_ISO2': 'en',
            u'TITLE_UNKNOWN_FLG': 'N',
            'TOKEN': ANY,
            'MODIFIED_DATE_': ANY,
            'EMAIL_PERMISSION_STATUS_': 'I',
            u'TITLE_UNKNOWN_DATE': ANY,
            'COUNTRY_': 'US',
        })

    @patch('news.tasks.sfmc')
    @patch('news.tasks.get_user_data')
    def test_update_user_without_format_doesnt_send_format(self, get_user_mock, sfmc_mock):
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
        data = {
            'lang': 'en',
            'country': 'US',
            'newsletters': 'slug',
        }
        update_user(data, self.email, self.token, SUBSCRIBE, True)
        # We'll pass no format to ET
        sfmc_mock.upsert_row.assert_called_with(ANY, {
            'EMAIL_ADDRESS_': 'dude@example.com',
            'LANGUAGE_ISO2': 'en',
            'TITLE_UNKNOWN_FLG': 'Y',
            'TOKEN': ANY,
            'MODIFIED_DATE_': ANY,
            'EMAIL_PERMISSION_STATUS_': 'I',
            'TITLE_UNKNOWN_DATE': ANY,
            'COUNTRY_': 'US'
        })
        # We'll send their welcome in T format because that is the
        # user's preference in ET
        sfmc_mock.send_mail.assert_called_with('en_39_T', 'dude@example.com', ANY, 'T')

    @patch('news.tasks.sfmc')
    @patch('news.tasks.get_user_data')
    def test_update_user_wo_format_or_pref(self, get_user_mock, sfmc_mock):
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
        data = {
            'lang': 'en',
            'country': 'US',
            'newsletters': 'slug',
        }
        update_user(data, self.email, self.token, SUBSCRIBE, True)
        # We'll pass no format to ET
        sfmc_mock.upsert_row.assert_called_with(ANY, {
            'COUNTRY_': 'US',
            'EMAIL_ADDRESS_': 'dude@example.com',
            'EMAIL_PERMISSION_STATUS_': 'I',
            'LANGUAGE_ISO2': 'en',
            'MODIFIED_DATE_': ANY,
            'TITLE_UNKNOWN_DATE': ANY,
            'TITLE_UNKNOWN_FLG': 'Y',
            'TOKEN': ANY
        })
        # We'll send their welcome in H format because that is the
        # default when we have no other preference known.
        sfmc_mock.send_mail.assert_called_with('en_39', 'dude@example.com', ANY, 'H')

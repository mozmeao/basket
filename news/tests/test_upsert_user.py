from django.test import TestCase

from mock import patch, ANY

from news import models
from news.tasks import upsert_user
from news.utils import SET, SUBSCRIBE, UNSUBSCRIBE, generate_token


class UpsertUserTests(TestCase):
    def setUp(self):
        self.token = generate_token()
        self.email = 'dude@example.com'
        # User data in format that get_user_data() returns it
        self.get_user_data = {
            'email': self.email,
            'token': self.token,
            'format': 'H',
            'country': 'us',
            'lang': 'en',
            'newsletters': ['slug'],
            'status': 'ok',
        }

    @patch('news.tasks.sfdc')
    @patch('news.tasks.send_message')
    @patch('news.tasks.get_user_data')
    def test_update_first_last_names(self, get_user_data, send_message, sfdc_mock):
        """sending name fields should result in names being passed to SF"""
        get_user_data.return_value = None  # Does not exist yet
        models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=True,
            languages='en,fr',
            vendor_id='VENDOR1',
            requires_double_optin=True,
        )
        data = {
            'country': 'US',
            'lang': 'en',
            'format': 'H',
            'newsletters': 'slug',
            'first_name': 'The',
            'last_name': 'Dude',
            'email': self.email,
        }
        upsert_user(SUBSCRIBE, data)
        sfdc_data = data.copy()
        sfdc_data['newsletters'] = {'slug': True}
        sfdc_data['token'] = ANY
        sfdc_mock.add.assert_called_with(sfdc_data)

    @patch('news.tasks.sfdc')
    @patch('news.tasks.get_user_data')
    def test_update_user_set_works_if_no_newsletters(self, get_user_data, sfdc_mock):
        """
        A blank `newsletters` field when the update type is SET indicates
        that the person wishes to unsubscribe from all newsletters. This has
        caused exceptions because '' is not a valid newsletter name.
        """
        models.Newsletter.objects.create(
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
            'email': self.email,
            'token': self.token,
        }
        sfdc_data = data.copy()
        sfdc_data['newsletters'] = {'slug': False}

        get_user_data.return_value = self.get_user_data

        upsert_user(SET, data)
        # We should have looked up the user's data
        get_user_data.assert_called()
        # We'll specifically unsubscribe each newsletter the user is
        # subscribed to.
        sfdc_mock.update.assert_called_with(self.get_user_data, sfdc_data)

    @patch('news.tasks.get_user_data')
    @patch('news.tasks.sfdc')
    def test_resubscribe_doesnt_update_newsletter(self, sfdc_mock, get_user_data):
        """
        When subscribing to things the user is already subscribed to, we
        do not pass that newsletter to SF because we don't want that newsletter
        to be updated for no reason as that could cause another welcome to be sent.
        """
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
            'email': self.email,
        }
        sfdc_data = data.copy()
        sfdc_data['newsletters'] = {}

        get_user_data.return_value = self.get_user_data

        upsert_user(SUBSCRIBE, data)
        # We should have looked up the user's data
        get_user_data.assert_called()
        # We should not have mentioned this newsletter in our call to ET
        sfdc_mock.update.assert_called_with(self.get_user_data, sfdc_data)

    @patch('news.tasks.get_user_data')
    @patch('news.tasks.sfdc')
    def test_set_doesnt_update_newsletter(self, sfdc_mock, get_user_data):
        """
        When setting the newsletters to ones the user is already subscribed
        to, we do not pass that newsletter to SF because we
        don't want that newsletter to send a new welcome.
        """
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
            'email': self.email,
            'token': self.token,
        }
        sfdc_data = data.copy()
        sfdc_data['newsletters'] = {}

        # Mock user data - we want our user subbed to our newsletter to start
        get_user_data.return_value = self.get_user_data

        upsert_user(SET, data)
        # We should have looked up the user's data
        self.assertTrue(get_user_data.called)
        # We should not have mentioned this newsletter in our call to SF
        sfdc_mock.update.assert_called_with(self.get_user_data, sfdc_data)

    @patch('news.tasks.get_user_data')
    @patch('news.tasks.sfdc')
    def test_unsub_is_careful(self, sfdc_mock, get_user_data):
        """
        When unsubscribing, we only unsubscribe things the user is
        currently subscribed to.
        """
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
            'token': self.token
        }
        sfdc_data = data.copy()
        # We should only mention slug, not slug2
        sfdc_data['newsletters'] = {'slug': False}
        get_user_data.return_value = self.get_user_data

        upsert_user(UNSUBSCRIBE, data)
        # We should have looked up the user's data
        self.assertTrue(get_user_data.called)
        sfdc_mock.update.assert_called_with(self.get_user_data, sfdc_data)

    @patch('news.tasks.sfdc')
    @patch('news.tasks.get_user_data')
    def test_update_user_without_format_doesnt_send_format(self, get_user_mock, sfdc_mock):
        """
        SF format not changed if update_user call doesn't specify.

        If update_user call doesn't specify a format (e.g. if bedrock
        doesn't get a changed value on a form submission), then Basket
        doesn't send any format to SF.

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
            'email': 'dude@example.com',
            'token': 'foo-token',
            'newsletters': ['other-one'],
            'optin': True,
        }
        data = {
            'lang': 'en',
            'country': 'US',
            'newsletters': 'slug',
            'email': 'dude@example.com',
        }
        sfdc_data = data.copy()
        # We should only mention slug, not slug2
        sfdc_data['newsletters'] = {'slug': True}
        upsert_user(SUBSCRIBE, data)
        sfdc_mock.update.assert_called_with(get_user_mock.return_value, sfdc_data)

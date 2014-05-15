from uuid import uuid4

from django.conf import settings
from django.test import TestCase

from mock import patch, Mock

from news import models
from news.backends.common import NewsletterException
from news.models import Newsletter
from news.tasks import SUBSCRIBE, UU_ALREADY_CONFIRMED, UU_EXEMPT_NEW, \
    UU_EXEMPT_PENDING, UU_MUST_CONFIRM_NEW, UU_MUST_CONFIRM_PENDING, \
    BasketError, confirm_user, update_user


class TestConfirmationLogic(TestCase):
    def check_confirmation(self, user_in_basket, user_in_master,
                           user_in_optin, user_in_confirmed,
                           newsletter_with_required_confirmation,
                           newsletter_without_required_confirmation,
                           is_english, type, expected_result, is_optin=False):
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
                                         is_optin)
        self.assertEqual(expected_result, rc)

    #
    # Tests for brand new users
    #

    def test_new_english_non_required(self):
        self.check_confirmation(user_in_basket=False,
                                user_in_master=False,
                                user_in_optin=False,
                                user_in_confirmed=False,
                                newsletter_with_required_confirmation=False,
                                newsletter_without_required_confirmation=True,
                                is_english=True,
                                type=SUBSCRIBE,
                                expected_result=UU_EXEMPT_NEW)

    def test_new_non_english_non_required(self):
        self.check_confirmation(user_in_basket=False,
                                user_in_master=False,
                                user_in_optin=False,
                                user_in_confirmed=False,
                                newsletter_with_required_confirmation=False,
                                newsletter_without_required_confirmation=True,
                                is_english=False,
                                type=SUBSCRIBE,
                                expected_result=UU_EXEMPT_NEW)

    def test_new_english_required_and_not(self):
        self.check_confirmation(user_in_basket=False,
                                user_in_master=False,
                                user_in_optin=False,
                                user_in_confirmed=False,
                                newsletter_with_required_confirmation=True,
                                newsletter_without_required_confirmation=True,
                                is_english=True,
                                type=SUBSCRIBE,
                                expected_result=UU_EXEMPT_NEW)

    def test_new_non_english_required_and_not(self):
        self.check_confirmation(user_in_basket=False,
                                user_in_master=False,
                                user_in_optin=False,
                                user_in_confirmed=False,
                                newsletter_with_required_confirmation=True,
                                newsletter_without_required_confirmation=True,
                                is_english=False,
                                type=SUBSCRIBE,
                                expected_result=UU_EXEMPT_NEW)

    def test_new_non_english_required(self):
        self.check_confirmation(user_in_basket=False,
                                user_in_master=False,
                                user_in_optin=False,
                                user_in_confirmed=False,
                                newsletter_with_required_confirmation=True,
                                newsletter_without_required_confirmation=False,
                                is_english=False,
                                type=SUBSCRIBE,
                                expected_result=UU_MUST_CONFIRM_NEW)

    def test_new_english_optin(self):
        self.check_confirmation(user_in_basket=False,
                                user_in_master=False,
                                user_in_optin=False,
                                user_in_confirmed=False,
                                newsletter_with_required_confirmation=True,
                                newsletter_without_required_confirmation=False,
                                is_english=True,
                                is_optin=True,
                                type=SUBSCRIBE,
                                expected_result=UU_EXEMPT_NEW)

    #
    # Tests for users already pending confirmation
    #

    def test_pending_english_required(self):
        # Should NOT exempt them and confirm them
        self.check_confirmation(user_in_basket=False,
                                user_in_master=False,
                                user_in_optin=True,
                                user_in_confirmed=False,
                                newsletter_with_required_confirmation=True,
                                newsletter_without_required_confirmation=False,
                                is_english=True,
                                type=SUBSCRIBE,
                                expected_result=UU_MUST_CONFIRM_PENDING)

    def test_pending_english_not_required(self):
        # Should exempt them and confirm them
        self.check_confirmation(user_in_basket=False,
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
        self.check_confirmation(user_in_basket=False,
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
        self.check_confirmation(user_in_basket=False,
                                user_in_master=False,
                                user_in_optin=True,
                                user_in_confirmed=False,
                                newsletter_with_required_confirmation=True,
                                newsletter_without_required_confirmation=True,
                                is_english=False,
                                type=SUBSCRIBE,
                                expected_result=UU_EXEMPT_PENDING)

    def test_pending_english_optin(self):
        self.check_confirmation(user_in_basket=False,
                                user_in_master=False,
                                user_in_optin=True,
                                user_in_confirmed=False,
                                newsletter_with_required_confirmation=True,
                                newsletter_without_required_confirmation=False,
                                is_english=True,
                                is_optin=True,
                                type=SUBSCRIBE,
                                expected_result=UU_EXEMPT_PENDING)

    #
    # Tests for users who have confirmed but not yet been moved to master
    #

    def test_confirmed_english_required(self):
        self.check_confirmation(user_in_basket=False,
                                user_in_master=False,
                                user_in_optin=True,
                                user_in_confirmed=True,
                                newsletter_with_required_confirmation=True,
                                newsletter_without_required_confirmation=False,
                                is_english=True,
                                type=SUBSCRIBE,
                                expected_result=UU_ALREADY_CONFIRMED)

    def test_confirmed_non_english_required(self):
        self.check_confirmation(user_in_basket=False,
                                user_in_master=False,
                                user_in_optin=True,
                                user_in_confirmed=True,
                                newsletter_with_required_confirmation=True,
                                newsletter_without_required_confirmation=False,
                                is_english=False,
                                type=SUBSCRIBE,
                                expected_result=UU_ALREADY_CONFIRMED)

    def test_confirmed_english_not_required(self):
        self.check_confirmation(user_in_basket=False,
                                user_in_master=False,
                                user_in_optin=True,
                                user_in_confirmed=True,
                                newsletter_with_required_confirmation=False,
                                newsletter_without_required_confirmation=True,
                                is_english=True,
                                type=SUBSCRIBE,
                                expected_result=UU_ALREADY_CONFIRMED)

    def test_confirmed_non_english_not_required(self):
        self.check_confirmation(user_in_basket=False,
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
        self.check_confirmation(user_in_basket=False,
                                user_in_master=True,
                                user_in_optin=False,
                                user_in_confirmed=True,
                                newsletter_with_required_confirmation=True,
                                newsletter_without_required_confirmation=False,
                                is_english=True,
                                type=SUBSCRIBE,
                                expected_result=UU_ALREADY_CONFIRMED)

    def test_master_non_english_required(self):
        self.check_confirmation(user_in_basket=False,
                                user_in_master=True,
                                user_in_optin=False,
                                user_in_confirmed=True,
                                newsletter_with_required_confirmation=True,
                                newsletter_without_required_confirmation=False,
                                is_english=False,
                                type=SUBSCRIBE,
                                expected_result=UU_ALREADY_CONFIRMED)

    def test_master_english_not_required(self):
        self.check_confirmation(user_in_basket=False,
                                user_in_master=True,
                                user_in_optin=False,
                                user_in_confirmed=True,
                                newsletter_with_required_confirmation=False,
                                newsletter_without_required_confirmation=True,
                                is_english=True,
                                type=SUBSCRIBE,
                                expected_result=UU_ALREADY_CONFIRMED)

    def test_master_non_english_not_required(self):
        self.check_confirmation(user_in_basket=False,
                                user_in_master=True,
                                user_in_optin=False,
                                user_in_confirmed=True,
                                newsletter_with_required_confirmation=False,
                                newsletter_without_required_confirmation=True,
                                is_english=False,
                                type=SUBSCRIBE,
                                expected_result=UU_ALREADY_CONFIRMED)


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
        with self.assertRaises(NewsletterException):
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
            'email': 'dude@example.com',
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
        """If we can't find the user, raise exception"""
        # Can't patch get_user_data because confirm_user imports it
        # internally. But we can patch look_for_user, which get_user_data
        # will call
        with patch('news.views.look_for_user') as look_for_user:
            look_for_user.return_value = None
            user_data = None
            token = "TOKEN"
            with self.assertRaises(BasketError):
                confirm_user(token, user_data)
        self.assertFalse(apply_updates.called)
        self.assertFalse(send_welcomes.called)


class TestSendWelcomes(TestCase):

    @patch('news.tasks.send_message')
    @patch('news.tasks.apply_updates')
    def test_text_welcome(self, apply_updates, send_message):
        """Test sending the right welcome message"""
        welcome = u'welcome'
        Newsletter.objects.create(
            slug='slug',
            vendor_id='VENDOR',
            welcome=welcome,
            languages='en,ru',
        )
        token = "TOKEN"
        email = 'dude@example.com'
        lang = 'ru'
        format = 'T'
        # User who prefers Russian Text messages
        user_data = {
            'status': 'ok',
            'confirmed': False,
            'newsletters': ['slug'],
            'format': format,
            'lang': lang,
            'token': token,
            'email': email,
        }
        confirm_user(token, user_data)
        expected_welcome = "%s_%s_%s" % (lang, welcome, format)
        send_message.assert_called_with(expected_welcome, email, token, format)

    @patch('news.tasks.send_message')
    @patch('news.tasks.apply_updates')
    def test_html_welcome(self, apply_updates, send_message):
        """Test sending the right welcome message"""
        welcome = u'welcome'
        Newsletter.objects.create(
            slug='slug',
            vendor_id='VENDOR',
            welcome=welcome,
            languages='en,ru',
        )
        token = "TOKEN"
        email = 'dude@example.com'
        lang = 'RU'  # This guy had an uppercase lang code for some reason
        format = 'H'
        # User who prefers Russian HTML messages
        user_data = {
            'status': 'ok',
            'confirmed': False,
            'newsletters': ['slug'],
            'format': format,
            'lang': lang,
            'token': token,
            'email': email,
        }
        confirm_user(token, user_data)
        # Lang code is lowercased. And we don't append anything for HTML.
        expected_welcome = "%s_%s" % (lang.lower(), welcome)
        send_message.assert_called_with(expected_welcome, email, token, format)

    @patch('news.tasks.send_message')
    @patch('news.tasks.apply_updates')
    def test_bad_lang_welcome(self, apply_updates, send_message):
        """Test sending welcome in english if user wants a lang that
        our newsletter doesn't support"""
        welcome = u'welcome'
        Newsletter.objects.create(
            slug='slug',
            vendor_id='VENDOR',
            welcome=welcome,
            languages='en,ru',
        )
        token = "TOKEN"
        email = 'dude@example.com'
        lang = 'fr'
        format = 'H'
        # User who prefers French HTML messages
        user_data = {
            'status': 'ok',
            'confirmed': False,
            'newsletters': ['slug'],
            'format': format,
            'lang': lang,
            'token': token,
            'email': email,
        }
        confirm_user(token, user_data)
        # They're getting English. And we don't append anything for HTML.
        expected_welcome = "en_%s" % welcome
        send_message.assert_called_with(expected_welcome, email, token, format)

    @patch('news.tasks.send_message')
    @patch('news.tasks.apply_updates')
    def test_long_lang_welcome(self, apply_updates, send_message):
        """Test sending welcome in pt if the user wants pt and the newsletter
        supports pt-Br"""
        welcome = u'welcome'
        Newsletter.objects.create(
            slug='slug',
            vendor_id='VENDOR',
            welcome=welcome,
            languages='en,ru,pt-Br',
        )
        token = "TOKEN"
        email = 'dude@example.com'
        lang = 'pt'
        format = 'H'
        user_data = {
            'status': 'ok',
            'confirmed': False,
            'newsletters': ['slug'],
            'format': format,
            'lang': lang,
            'token': token,
            'email': email,
        }
        confirm_user(token, user_data)
        # They're getting pt. And we don't append anything for HTML.
        expected_welcome = "pt_%s" % welcome
        send_message.assert_called_with(expected_welcome, email, token, format)

    @patch('news.tasks.send_message')
    @patch('news.tasks.apply_updates')
    def test_other_long_lang_welcome(self, apply_updates, send_message):
        """Test sending welcome in pt if the user wants pt-Br and the
        newsletter supports pt"""
        welcome = u'welcome'
        Newsletter.objects.create(
            slug='slug',
            vendor_id='VENDOR',
            welcome=welcome,
            languages='en,ru,pt',
        )
        token = "TOKEN"
        email = 'dude@example.com'
        lang = 'pt-Br'
        format = 'H'
        user_data = {
            'status': 'ok',
            'confirmed': False,
            'newsletters': ['slug'],
            'format': format,
            'lang': lang,
            'token': token,
            'email': email,
        }
        confirm_user(token, user_data)
        # They're getting pt. And we don't append anything for HTML.
        expected_welcome = "pt_%s" % welcome
        send_message.assert_called_with(expected_welcome, email, token, format)

    @patch('news.tasks.send_message')
    @patch('news.tasks.apply_updates')
    def test_one_lang_welcome(self, apply_updates, send_message):
        """If a newsletter only has one language, the welcome message
        still gets a language prefix"""
        welcome = u'welcome'
        Newsletter.objects.create(
            slug='slug',
            vendor_id='VENDOR',
            welcome=welcome,
            languages='en',
        )
        token = "TOKEN"
        email = 'dude@example.com'
        lang = 'pt-Br'
        format = 'H'
        user_data = {
            'status': 'ok',
            'confirmed': False,
            'newsletters': ['slug'],
            'format': format,
            'lang': lang,
            'token': token,
            'email': email,
        }
        confirm_user(token, user_data)
        expected_welcome = 'en_' + welcome
        send_message.assert_called_with(expected_welcome, email, token, format)

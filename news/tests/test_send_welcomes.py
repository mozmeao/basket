from django.test import TestCase

from mock import patch

from news.backends.common import NewsletterException
from news.models import Newsletter
from news.tasks import confirm_user, mogrify_message_id, send_message


class TestSendMessage(TestCase):
    @patch('news.tasks.sfmc')
    def test_caching_bad_message_ids(self, mock_sfmc):
        """Bad message IDs are cached so we don't try to send to them again"""
        exc = NewsletterException()
        exc.message = 'Invalid Customer Key'
        mock_sfmc.send_mail.side_effect = exc

        message_id = "MESSAGE_ID"
        for i in range(10):
            send_message(message_id, 'email', 'token', 'format')

        mock_sfmc.send_mail.assert_called_once_with(message_id, 'email', 'token', 'format')


class TestSendWelcomes(TestCase):

    def test_mogrify_message_id_text(self):
        """Test adding lang and text format to message ID"""
        result = mogrify_message_id("MESSAGE", "en", "T")
        expect = "en_MESSAGE_T"
        self.assertEqual(expect, result)

    def test_mogrify_message_id_html(self):
        """Test adding lang and html format to message ID"""
        result = mogrify_message_id("MESSAGE", "en", "H")
        expect = "en_MESSAGE"
        self.assertEqual(expect, result)

    def test_mogrify_message_id_no_lang(self):
        """Test adding no lang and format to message ID"""
        result = mogrify_message_id("MESSAGE", None, "T")
        expect = "MESSAGE_T"
        self.assertEqual(expect, result)

    def test_mogrify_message_id_long_lang(self):
        """Test adding long lang and format to message ID"""
        result = mogrify_message_id("MESSAGE", "en-US", "T")
        expect = "en_MESSAGE_T"
        self.assertEqual(expect, result)

    def test_mogrify_message_id_upcase_lang(self):
        """Test adding uppercase lang and format to message ID"""
        result = mogrify_message_id("MESSAGE", "FR", "T")
        expect = "fr_MESSAGE_T"
        self.assertEqual(expect, result)

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
        send_message.delay.assert_called_with(expected_welcome, email, token, format)

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
        send_message.delay.assert_called_with(expected_welcome, email, token, format)

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
        send_message.delay.assert_called_with(expected_welcome, email, token, format)

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
        send_message.delay.assert_called_with(expected_welcome, email, token, format)

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
        send_message.delay.assert_called_with(expected_welcome, email, token, format)

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
        send_message.delay.assert_called_with(expected_welcome, email, token, format)

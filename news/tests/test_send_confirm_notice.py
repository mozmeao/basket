from django.test import TestCase

from mock import patch

from news.models import Newsletter
from news.tasks import CONFIRMATION_MESSAGE, BasketError, mogrify_message_id, send_confirm_notice


@patch('news.tasks.send_message', autospec=True)
class TestSendConfirmNotice(TestCase):
    """Test send_confirm_notice method"""

    def setUp(self):
        self.email = "user@example.com"
        self.token = "LKDFJLKSDJFLSKDFJ"
        self.newsletter1 = Newsletter.objects.create(
            slug='slug1',
            vendor_id='VENDOR1',
            confirm_message='confirm1',
            languages='en,es,rr-QQ'   # rr is a made-up language
        )
        self.newsletter2 = Newsletter.objects.create(
            slug='slug2',
            vendor_id='VENDOR2',
        )

    # default confirmation notice (no custom notice for newsletter)
    ## known short lang

    def test_default_confirm_notice_H(self, send_message):
        """Test newsletter that has no explicit confirm"""
        send_confirm_notice(self.email, self.token, "en", "H", ['slug2'])
        expected_message = mogrify_message_id(CONFIRMATION_MESSAGE, 'en', 'H')
        send_message.assert_called_with(expected_message,
                                        self.email,
                                        self.token,
                                        'H')

    def test_default_confirm_notice_T(self, send_message):
        """Test newsletter that has no explicit confirm"""
        send_confirm_notice(self.email, self.token, "es", "T", ['slug2'])
        expected_message = mogrify_message_id(CONFIRMATION_MESSAGE, 'es', 'T')
        send_message.assert_called_with(expected_message,
                                        self.email,
                                        self.token,
                                        'T')

    def test_default_confirm_notice_short_for_long(self, send_message):
        """Test using short form of lang that's in the newsletter list as a long lang"""
        send_confirm_notice(self.email, self.token, "rr", "H", ['slug2'])
        expected_message = mogrify_message_id(CONFIRMATION_MESSAGE, 'rr', 'H')
        send_message.assert_called_with(expected_message,
                                        self.email,
                                        self.token,
                                        'H')

    ### known long lang

    def test_default_confirm_notice_long_lang_H(self, send_message):
        """Test newsletter that has no explicit confirm with long lang code"""
        send_confirm_notice(self.email, self.token, "es-ES", "H", ['slug2'])
        expected_message = mogrify_message_id(CONFIRMATION_MESSAGE, 'es', 'H')
        send_message.assert_called_with(expected_message,
                                        self.email,
                                        self.token,
                                        'H')

    def test_default_confirm_notice_long_lang_T(self, send_message):
        """Test newsletter that has no explicit confirm with long lang code"""
        send_confirm_notice(self.email, self.token, "es-ES", "T", ['slug2'])
        expected_message = mogrify_message_id(CONFIRMATION_MESSAGE, 'es', 'T')
        send_message.assert_called_with(expected_message,
                                        self.email,
                                        self.token,
                                        'T')

    ### bad lang

    def test_default_confirm_notice_bad_lang_H(self, send_message):
        """Test when there's no default confirm notice for a language"""
        with self.assertRaises(BasketError):
            send_confirm_notice(self.email, self.token, "fr", "H", ['slug2'])
        with self.assertRaises(BasketError):
            send_confirm_notice(self.email, self.token, "zz-Z", "H", ['slug2'])

    def test_default_confirm_notice_bad_lang_T(self, send_message):
        """Test when newsletter uses default notice and the lang is unknown"""
        with self.assertRaises(BasketError):
            send_confirm_notice(self.email, self.token, "fr", "T", ['slug2'])
        with self.assertRaises(BasketError):
            send_confirm_notice(self.email, self.token, "zz-Z", "T", ['slug2'])

    # explicit (custom) confirmation notice for newsletter
    ### known short lang

    def test_explicit_confirm_notice_H(self, send_message):
        """Test newsletter that has explicit confirm message"""
        send_confirm_notice(self.email, self.token, "en", "H", ['slug1'])
        expected_message = 'en_confirm1'
        send_message.assert_called_with(expected_message,
                                        self.email,
                                        self.token,
                                        'H')

    def test_explicit_confirm_notice_T(self, send_message):
        """Test newsletter that has explicit confirm message"""
        send_confirm_notice(self.email, self.token, "en", "T", ['slug1'])
        expected_message = 'en_confirm1_T'
        send_message.assert_called_with(expected_message,
                                        self.email,
                                        self.token,
                                        'T')

    ### known long lang

    def test_explicit_confirm_notice_long_lang_H(self, send_message):
        """Test newsletter that has explicit confirm message with long lang"""
        send_confirm_notice(self.email, self.token, "en-US", "H", ['slug1'])
        expected_message = 'en_confirm1'
        send_message.assert_called_with(expected_message,
                                        self.email,
                                        self.token,
                                        'H')

    def test_explicit_confirm_notice_long_lang_T(self, send_message):
        """Test newsletter that has explicit confirm message with long lang"""
        send_confirm_notice(self.email, self.token, "en-US", "T", ['slug1'])
        expected_message = 'en_confirm1_T'
        send_message.assert_called_with(expected_message,
                                        self.email,
                                        self.token,
                                        'T')

    ### bad lang

    def test_explicit_confirm_notice_bad_lang_H(self, send_message):
        """Test when newsletter uses explicit notice and the lang is unknown"""
        with self.assertRaises(BasketError):
            send_confirm_notice(self.email, self.token, "zz", "H", ['slug1'])
        with self.assertRaises(BasketError):
            send_confirm_notice(self.email, self.token, "zz-Z", "H", ['slug1'])

    def test_explicit_confirm_notice_bad_lang_T(self, send_message):
        """Test when newsletter uses explicit notice and the lang is unknown"""
        with self.assertRaises(BasketError):
            send_confirm_notice(self.email, self.token, "zz", "T", ['slug1'])
        with self.assertRaises(BasketError):
            send_confirm_notice(self.email, self.token, "zz-Z", "T", ['slug1'])

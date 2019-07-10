from django.test import TestCase

from mock import patch

from basket.news.backends.common import NewsletterException
from basket.news.tasks import mogrify_message_id, send_message


class TestSendMessage(TestCase):
    @patch('basket.news.tasks.sfmc')
    def test_caching_bad_message_ids(self, mock_sfmc):
        """Bad message IDs are cached so we don't try to send to them again"""
        exc = NewsletterException('Invalid Customer Key')
        mock_sfmc.send_mail.side_effect = exc

        message_id = "MESSAGE_ID"
        for i in range(10):
            send_message(message_id, 'email', 'sub-key', 'token')

        mock_sfmc.send_mail.assert_called_once_with(message_id, 'email', 'sub-key', 'token')


class TestMogrifyMessageID(TestCase):
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

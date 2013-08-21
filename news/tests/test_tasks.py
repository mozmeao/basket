from mock import patch

from django.test import TestCase

from news.models import Subscriber
from news.tasks import RECOVERY_MESSAGE_ID, mogrify_message_id, \
    send_recovery_message_task


@patch('news.tasks.send_message', autospec=True)
@patch('news.views.look_for_user', autospec=True)
class RecoveryMessageTask(TestCase):
    def setUp(self):
        self.email = "dude@example.com"

    def test_unknown_email(self, mock_look_for_user, mock_send):
        """Email not in basket or ET"""
        # Should log error and return
        mock_look_for_user.return_value = None
        send_recovery_message_task(self.email)
        self.assertFalse(mock_send.called)

    def test_email_only_in_et(self, mock_look_for_user, mock_send):
        """Email not in basket but in ET"""
        # Should create new subscriber with ET data, then trigger message
        # We can follow the user's format and lang pref
        format = 'T'
        lang = 'fr'
        mock_look_for_user.return_value = {
            'status': 'ok',
            'email': self.email,
            'format': format,
            'country': '',
            'lang': lang,
            'token': 'USERTOKEN',
            'newsletters': [],
        }
        send_recovery_message_task(self.email)
        subscriber = Subscriber.objects.get(email=self.email)
        self.assertEqual('USERTOKEN', subscriber.token)
        message_id = mogrify_message_id(RECOVERY_MESSAGE_ID, lang, format)
        mock_send.assert_called_with(message_id, self.email,
                                     subscriber.token, format)

    def test_email_only_in_basket(self, mock_look_for_user, mock_send):
        """Email known in basket, not in ET"""
        # Should log error and return
        Subscriber.objects.create(email=self.email)
        mock_look_for_user.return_value = None
        send_recovery_message_task(self.email)
        self.assertFalse(mock_send.called)

    def test_email_in_both(self, mock_look_for_user, mock_send):
        """Email known in both basket and ET"""
        # We can follow the user's format and lang pref
        subscriber = Subscriber.objects.create(email=self.email)
        format = 'T'
        lang = 'fr'
        mock_look_for_user.return_value = {
            'status': 'ok',
            'email': self.email,
            'format': format,
            'country': '',
            'lang': lang,
            'token': subscriber.token,
            'newsletters': [],
        }
        send_recovery_message_task(self.email)
        message_id = mogrify_message_id(RECOVERY_MESSAGE_ID, lang, format)
        mock_send.assert_called_with(message_id, self.email,
                                     subscriber.token, format)

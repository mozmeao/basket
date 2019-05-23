from django.test import TestCase

from celery.exceptions import Retry
from mock import patch, Mock

from basket.news.backends.common import NewsletterException
from basket.news.tasks import confirm_user


@patch('basket.news.tasks.sfdc')
@patch('basket.news.tasks.get_user_data')
class TestConfirmTask(TestCase):
    def test_error(self, get_user_data, sfdc_mock):
        """
        If user_data shows an error talking to ET, the task raises
        an exception so our task logic will retry
        """
        get_user_data.side_effect = NewsletterException('Stuffs broke yo.')
        with self.assertRaises(Retry):
            confirm_user('token')
        self.assertFalse(sfdc_mock.update.called)

    def test_normal(self, get_user_data, sfdc_mock):
        """If user_data is okay, and not yet confirmed, the task calls
         the right stuff"""
        token = "TOKEN"
        user_data = {'status': 'ok', 'optin': False, 'newsletters': Mock(), 'format': 'ZZ',
                     'email': 'dude@example.com', 'token': token}
        get_user_data.return_value = user_data
        confirm_user(token)
        sfdc_mock.update.assert_called_with(user_data, {'optin': True})

    def test_already_confirmed(self, get_user_data, sfdc_mock):
        """If user_data already confirmed, task does nothing"""
        user_data = {
            'status': 'ok',
            'optin': True,
            'newsletters': Mock(),
            'format': 'ZZ',
        }
        get_user_data.return_value = user_data
        token = "TOKEN"
        confirm_user(token)
        self.assertFalse(sfdc_mock.update.called)

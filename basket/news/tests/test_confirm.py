from unittest.mock import Mock, patch

from django.test import TestCase

from basket.news.tasks import confirm_user


@patch("basket.news.tasks.ctms")
@patch("basket.news.tasks.get_user_data")
class TestConfirmTask(TestCase):
    def test_normal(self, get_user_data, ctms_mock):
        """If user_data is okay, and not yet confirmed, the task calls
        the right stuff"""
        token = "TOKEN"
        user_data = {
            "status": "ok",
            "optin": False,
            "newsletters": Mock(),
            "email": "dude@example.com",
            "token": token,
            "email_id": "some-email-id",
        }
        get_user_data.return_value = user_data
        confirm_user(token)
        ctms_mock.update.assert_called_with(user_data, {"optin": True})

    def test_already_confirmed(self, get_user_data, ctms_mock):
        """If user_data already confirmed, task does nothing"""
        user_data = {
            "status": "ok",
            "optin": True,
            "newsletters": Mock(),
        }
        get_user_data.return_value = user_data
        token = "TOKEN"
        confirm_user(token)
        self.assertFalse(ctms_mock.update.called)

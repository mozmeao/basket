from django.test import TestCase

import celery
from mock import Mock, patch

from news.models import FailedTask, Subscriber
from news.tasks import (RECOVERY_MESSAGE_ID, mogrify_message_id,
    send_recovery_message_task, SUBSCRIBE, update_phonebook, update_user)


class FailedTaskTest(TestCase):
    """Test that failed tasks are logged in our FailedTask table"""

    @patch('news.tasks.ExactTarget', autospec=True)
    def test_failed_task_logging(self, mock_exact_target):
        """Failed task is logged in FailedTask table"""
        mock_exact_target.side_effect = Exception("Test exception")
        self.assertEqual(0, FailedTask.objects.count())
        args = [{'arg1': 1, 'arg2': 2}, "foo@example.com"]
        kwargs = {'token': 3}
        result = update_phonebook.apply(args=args, kwargs=kwargs)
        fail = FailedTask.objects.get()
        self.assertEqual('news.tasks.update_phonebook', fail.name)
        self.assertEqual(result.task_id, fail.task_id)
        self.assertEqual(args, fail.args)
        self.assertEqual(kwargs, fail.kwargs)
        self.assertEqual(u"Exception('Test exception',)", fail.exc)
        self.assertIn("Exception: Test exception", fail.einfo)


class RetryTaskTest(TestCase):
    """Test that we can retry a task"""
    @patch('django.contrib.messages.info', autospec=True)
    def test_retry_task(self, info):
        TASK_NAME = 'news.tasks.update_phonebook'
        failed_task = FailedTask(name=TASK_NAME,
                                 task_id=4,
                                 args=[1, 2],
                                 kwargs={'token': 3},
                                 exc='',
                                 einfo='')
        # Failed task is deleted after queuing, but that only works on records
        # that have been saved, so just mock that and check later that it was
        # called.
        failed_task.delete = Mock(spec=failed_task.delete)
        # Mock the actual task (already registered with celery):
        mock_update_phonebook = Mock(spec=update_phonebook)
        with patch.dict(celery.registry.tasks, {TASK_NAME: mock_update_phonebook}):
            # Let's retry.
            failed_task.retry()
        # Task was submitted again
        mock_update_phonebook.apply_async.assert_called_with((1, 2), {'token': 3})
        # Previous failed task was deleted
        self.assertTrue(failed_task.delete.called)


@patch('news.tasks.send_message', autospec=True)
@patch('news.utils.look_for_user', autospec=True)
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


class UpdateUserTests(TestCase):
    def _patch_tasks(self, attr, **kwargs):
        patcher = patch('news.tasks.' + attr, **kwargs)
        setattr(self, attr, patcher.start())
        self.addCleanup(patcher.stop)

    def setUp(self):
        self._patch_tasks('lookup_subscriber')
        self._patch_tasks('get_user_data')
        self._patch_tasks('parse_newsletters', return_value=([], []))
        self._patch_tasks('apply_updates')
        self._patch_tasks('confirm_user')
        self._patch_tasks('send_welcomes')
        self._patch_tasks('send_confirm_notice')

    def self_test_success_no_token_create_user(self):
        """
        If no token is provided, use lookup_subscriber to find (and
        possibly create) a user with a matching email.
        """
        subscriber = Mock(email='a@example.com', token='mytoken')
        self.lookup_subscriber.return_value = subscriber, None, False
        self.get_user_data.return_value = None

        update_user({}, 'a@example.com', None, SUBSCRIBE, True)
        self.get_user_data.assert_called_with(token='mytoken')

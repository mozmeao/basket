from django.core import mail
from django.test import TestCase

from mock import patch

from news import models


class SubscriberTest(TestCase):
    def test_get_and_sync_creates(self):
        """
        Subscriber.objects.get_and_sync() should create if email doesn't exist.
        """
        with self.assertRaises(models.Subscriber.DoesNotExist):
            models.Subscriber.objects.get(email='dude@example.com')

        models.Subscriber.objects.get_and_sync('dude@example.com', 'asdfjkl')
        sub = models.Subscriber.objects.get(email='dude@example.com')
        self.assertEqual(sub.token, 'asdfjkl')

    def test_get_and_sync_updates(self):
        """
        Subscriber.objects.get_and_sync() should update token if it doesn't
        match.
        """
        models.Subscriber.objects.create(email='dude@example.com',
                                         token='asdf')

        models.Subscriber.objects.get_and_sync('dude@example.com', 'asdfjkl')
        sub = models.Subscriber.objects.get(email='dude@example.com')
        self.assertEqual(sub.token, 'asdfjkl')


class FailedTaskTest(TestCase):
    good_task_args = [{'case_type': 'ringer', 'email': 'dude@example.com'}, 'walter']

    def test_retry_with_dict(self):
        """When given args with a simple dict, subtask should get matching arguments."""
        task_name = 'make_a_caucasian'
        task = models.FailedTask.objects.create(task_id='el-dudarino',
                                                name=task_name,
                                                args=self.good_task_args)
        with patch.object(models, 'subtask') as sub_mock:
            task.retry()

        sub_mock.assert_called_with(task_name, args=self.good_task_args, kwargs={})

    def test_retry_with_querydict(self):
        """When given args with a QueryDict, subtask should get a dict."""
        task_name = 'make_a_caucasian'
        task_args = [{'case_type': ['ringer'], 'email': ['dude@example.com']}, 'walter']
        task = models.FailedTask.objects.create(task_id='el-dudarino',
                                                name=task_name,
                                                args=task_args)
        with patch.object(models, 'subtask') as sub_mock:
            task.retry()

        sub_mock.assert_called_with(task_name, args=self.good_task_args, kwargs={})

    def test_retry_with_querydict_not_first(self):
        """When given args with a QueryDict in any position, subtask should get a dict."""
        task_name = 'make_a_caucasian'
        task_args = ['donny', {'case_type': ['ringer'], 'email': ['dude@example.com']}, 'walter']
        task = models.FailedTask.objects.create(task_id='el-dudarino',
                                                name=task_name,
                                                args=task_args)
        with patch.object(models, 'subtask') as sub_mock:
            task.retry()

        sub_mock.assert_called_with(task_name, args=['donny'] + self.good_task_args, kwargs={})

    def test_retry_with_almost_querydict(self):
        """When given args with a dict with a list, subtask should get a same args."""
        task_name = 'make_a_caucasian'
        task_args = [{'case_type': 'ringer', 'email': ['dude@example.com']}, 'walter']
        task = models.FailedTask.objects.create(task_id='el-dudarino',
                                                name=task_name,
                                                args=task_args)
        with patch.object(models, 'subtask') as sub_mock:
            task.retry()

        sub_mock.assert_called_with(task_name, args=task_args, kwargs={})


class InterestTests(TestCase):
    def test_notify_stewards(self):
        interest = models.Interest(title='mytest',
                                   steward_emails=['bob@example.com', 'bill@example.com'])
        interest.notify_stewards('interested@example.com', 'en-US', 'BYE')

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertTrue('mytest' in email.subject)
        self.assertEqual(email.to, ['bob@example.com', 'bill@example.com'])

from django.core import mail
from django.test import TestCase

from mock import patch

from basket.news import models


class FailedTaskTest(TestCase):
    good_task_args = [{'case_type': 'ringer', 'email': 'dude@example.com'}, 'walter']

    def test_retry_with_dict(self):
        """When given args with a simple dict, subtask should get matching arguments."""
        task_name = 'make_a_caucasian'
        task = models.FailedTask.objects.create(task_id='el-dudarino',
                                                name=task_name,
                                                args=self.good_task_args)
        with patch.object(models.celery_app, 'send_task') as sub_mock:
            task.retry()

        sub_mock.assert_called_with(task_name, args=self.good_task_args, kwargs={})

    def test_retry_with_querydict(self):
        """When given args with a QueryDict, subtask should get a dict."""
        task_name = 'make_a_caucasian'
        task_args = [{'case_type': ['ringer'], 'email': ['dude@example.com']}, 'walter']
        task = models.FailedTask.objects.create(task_id='el-dudarino',
                                                name=task_name,
                                                args=task_args)
        with patch.object(models.celery_app, 'send_task') as sub_mock:
            task.retry()

        sub_mock.assert_called_with(task_name, args=self.good_task_args, kwargs={})

    def test_retry_with_querydict_not_first(self):
        """When given args with a QueryDict in any position, subtask should get a dict."""
        task_name = 'make_a_caucasian'
        task_args = ['donny', {'case_type': ['ringer'], 'email': ['dude@example.com']}, 'walter']
        task = models.FailedTask.objects.create(task_id='el-dudarino',
                                                name=task_name,
                                                args=task_args)
        with patch.object(models.celery_app, 'send_task') as sub_mock:
            task.retry()

        sub_mock.assert_called_with(task_name, args=['donny'] + self.good_task_args, kwargs={})

    def test_retry_with_almost_querydict(self):
        """When given args with a dict with a list, subtask should get a same args."""
        task_name = 'make_a_caucasian'
        task_args = [{'case_type': 'ringer', 'email': ['dude@example.com']}, 'walter']
        task = models.FailedTask.objects.create(task_id='el-dudarino',
                                                name=task_name,
                                                args=task_args)
        with patch.object(models.celery_app, 'send_task') as sub_mock:
            task.retry()

        sub_mock.assert_called_with(task_name, args=task_args, kwargs={})


class InterestTests(TestCase):
    def test_notify_default_stewards(self):
        """
        If there are no locale-specific stewards for the given language,
        notify the default stewards.
        """
        interest = models.Interest(title='mytest',
                                   default_steward_emails='bob@example.com,bill@example.com')
        interest.notify_stewards('Steve', 'interested@example.com', 'en-US', 'BYE')

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertTrue('mytest' in email.subject)
        self.assertEqual(email.to, ['bob@example.com', 'bill@example.com'])

    def test_notify_locale_stewards(self):
        """
        If there are locale-specific stewards for the given language,
        notify them instead of the default stewards.
        """
        interest = models.Interest.objects.create(
            title='mytest',
            default_steward_emails='bob@example.com,bill@example.com')
        models.LocaleStewards.objects.create(
            interest=interest,
            locale='ach',
            emails='ach@example.com')
        interest.notify_stewards('Steve', 'interested@example.com', 'ach', 'BYE')

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertTrue('mytest' in email.subject)
        self.assertEqual(email.to, ['ach@example.com'])

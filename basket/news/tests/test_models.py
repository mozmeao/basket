from unittest.mock import patch

from django.core import mail
from django.test import TestCase
from django.test.utils import override_settings

from basket.news import models


class AcousticTxEmailTests(TestCase):
    def setUp(self):
        self.message1 = models.AcousticTxEmailMessage.objects.create(
            message_id="the-dude",
            vendor_id="12345",
            language="en-US",
        )
        self.message2 = models.AcousticTxEmailMessage.objects.create(
            message_id="the-dude",
            vendor_id="22345",
            language="es-ES",
        )
        self.message3 = models.AcousticTxEmailMessage.objects.create(
            message_id="the-dude",
            vendor_id="32345",
            language="fr",
        )

    def test_get_vendor_id(self):
        # default language is en-US
        assert "12345" == models.AcousticTxEmailMessage.objects.get_vendor_id(
            "the-dude",
            "de",
        )
        # get best match
        assert "22345" == models.AcousticTxEmailMessage.objects.get_vendor_id(
            "the-dude",
            "es-AR",
        )
        assert "32345" == models.AcousticTxEmailMessage.objects.get_vendor_id(
            "the-dude",
            "fr-FR",
        )
        assert "12345" == models.AcousticTxEmailMessage.objects.get_vendor_id(
            "the-dude",
            "en",
        )


class BrazeTxEmailTests(TestCase):
    def setUp(self):
        self.message1, self.message2, self.message3 = models.BrazeTxEmailMessage.objects.bulk_create(
            [
                models.BrazeTxEmailMessage(
                    message_id="the-dude",
                    campaign_id="12345",
                    language="en-US",
                ),
                models.BrazeTxEmailMessage(
                    message_id="the-dude",
                    campaign_id="22345",
                    language="es-ES",
                ),
                models.BrazeTxEmailMessage(
                    message_id="the-dude",
                    campaign_id="32345",
                    language="fr",
                ),
            ]
        )

    def test_get_campaign_id(self):
        # default language is en-US
        assert "12345" == models.BrazeTxEmailMessage.objects.get_campaign_id(
            "the-dude",
            "de",
        )
        # get best match
        assert "22345" == models.BrazeTxEmailMessage.objects.get_campaign_id(
            "the-dude",
            "es-AR",
        )
        assert "32345" == models.BrazeTxEmailMessage.objects.get_campaign_id(
            "the-dude",
            "fr-FR",
        )
        assert "12345" == models.BrazeTxEmailMessage.objects.get_campaign_id(
            "the-dude",
            "en",
        )


class FailedTaskTest(TestCase):
    args = [{"case_type": "ringer", "email": "dude@example.com"}, "walter"]
    kwargs = {"foo": "bar"}

    @override_settings(RQ_MAX_RETRIES=2)
    @patch("basket.base.rq.random")
    @patch("basket.base.rq.Queue.enqueue")
    def test_retry(self, mock_enqueue, mock_random):
        """Test args and kwargs are passed to enqueue."""
        mock_random.randrange.side_effect = [60, 90]
        task_name = "make_a_caucasian"
        task = models.FailedTask.objects.create(
            task_id="el-dudarino",
            name=task_name,
            args=self.args,
            kwargs=self.kwargs,
        )
        task.retry()

        mock_enqueue.assert_called_once()
        assert mock_enqueue.call_args.args[0] == task_name
        assert mock_enqueue.call_args.kwargs["args"] == self.args
        assert mock_enqueue.call_args.kwargs["kwargs"] == self.kwargs
        assert mock_enqueue.call_args.kwargs["retry"].intervals == [60, 90]


class InterestTests(TestCase):
    def test_notify_default_stewards(self):
        """
        If there are no locale-specific stewards for the given language,
        notify the default stewards.
        """
        interest = models.Interest(
            pk=1,
            title="mytest",
            default_steward_emails="bob@example.com,bill@example.com",
        )
        interest.notify_stewards("Steve", "interested@example.com", "en-US", "BYE")

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertTrue("mytest" in email.subject)
        self.assertEqual(email.to, ["bob@example.com", "bill@example.com"])

    def test_notify_locale_stewards(self):
        """
        If there are locale-specific stewards for the given language,
        notify them instead of the default stewards.
        """
        interest = models.Interest.objects.create(
            title="mytest",
            default_steward_emails="bob@example.com,bill@example.com",
        )
        models.LocaleStewards.objects.create(
            interest=interest,
            locale="ach",
            emails="ach@example.com",
        )
        interest.notify_stewards("Steve", "interested@example.com", "ach", "BYE")

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertTrue("mytest" in email.subject)
        self.assertEqual(email.to, ["ach@example.com"])

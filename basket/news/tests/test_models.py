from unittest.mock import patch

from django.test import TestCase
from django.test.utils import override_settings

from basket.news import models


class BrazeTxEmailTests(TestCase):
    def setUp(self):
        self.message1, self.message2, self.message3 = models.BrazeTxEmailMessage.objects.bulk_create(
            [
                models.BrazeTxEmailMessage(
                    message_id="the-dude",
                    language="en-US",
                ),
                models.BrazeTxEmailMessage(
                    message_id="the-dude",
                    language="es-ES",
                ),
                models.BrazeTxEmailMessage(
                    message_id="the-dude",
                    language="fr",
                ),
            ]
        )

    def test_get_message(self):
        # default language is en-US
        assert self.message1 == models.BrazeTxEmailMessage.objects.get_message(
            "the-dude",
            "de",
        )
        # get best match
        assert self.message2 == models.BrazeTxEmailMessage.objects.get_message(
            "the-dude",
            "es-AR",
        )
        assert self.message3 == models.BrazeTxEmailMessage.objects.get_message(
            "the-dude",
            "fr-FR",
        )
        assert self.message1 == models.BrazeTxEmailMessage.objects.get_message(
            "the-dude",
            "en",
        )

    @override_settings(BRAZE_MESSAGE_ID_MAP={})
    def test_get_tx_message_ids(self):
        assert ["the-dude"] == models.BrazeTxEmailMessage.objects.get_tx_message_ids()

    @override_settings(BRAZE_MESSAGE_ID_MAP={"jeff-dowd": "the-dude"})
    def test_get_tx_message_ids_with_map(self):
        assert sorted(["the-dude", "jeff-dowd"]) == sorted(models.BrazeTxEmailMessage.objects.get_tx_message_ids())


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

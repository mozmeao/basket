from unittest.mock import patch

from django.test.utils import override_settings

import pytest

from basket.base.rq import get_worker
from basket.base.tests.tasks import empty_job
from basket.news.models import QueuedTask


@pytest.mark.django_db
class TestDecorator:
    @override_settings(RQ_RESULT_TTL=0)
    @override_settings(RQ_MAX_RETRIES=0)
    @patch("basket.base.rq.Callback")
    @patch("basket.base.rq.get_queue")
    @patch("basket.base.rq.Queue")
    @patch("basket.base.rq.time")
    def test_rq_task(
        self,
        mock_time,
        mock_get_queue,
        mock_queue,
        mock_callback,
    ):
        """
        Test that the decorator passes the correct arguments to the RQ job.
        """
        mock_time.return_value = 123456789
        mock_get_queue.return_value = mock_queue

        empty_job.delay("arg1")

        mock_queue.enqueue_call.assert_called_once_with(
            empty_job,
            args=("arg1",),
            kwargs={},
            meta={
                "task_name": f"{empty_job.__module__}.{empty_job.__qualname__}",
                "start_time": 123456789,
            },
            retry=None,  # Retry logic is tested above, so no need to test it here.
            result_ttl=0,
            on_failure=mock_callback(),
            on_success=mock_callback(),
        )

    @override_settings(MAINTENANCE_MODE=True)
    def test_maintenance_mode_no_readonly(self, metrics_mock):
        """
        Test that the decorator doesn't run the task if maintenance mode is on.
        """
        assert QueuedTask.objects.count() == 0

        empty_job.delay("arg1")

        metrics_mock.assert_incr_once("basket.base.tests.tasks.empty_job.queued")
        assert QueuedTask.objects.count() == 1

    def test_job_success(self, metrics_mock):
        """
        Test that the decorator marks the job as successful if the task runs
        successfully.
        """
        empty_job.delay("arg1")

        worker = get_worker()
        worker.work(burst=True)  # Burst = worker will quit after all jobs consumed.

        assert len(metrics_mock.filter_records("incr")) == 2
        metrics_mock.assert_incr_once("basket.base.tests.tasks.empty_job.success")
        metrics_mock.assert_incr_once("news.tasks.success_total")
        assert len(metrics_mock.filter_records("timing")) == 2
        metrics_mock.assert_timing_once("basket.base.tests.tasks.empty_job.duration")
        metrics_mock.assert_timing_once("news.tasks.duration_total")

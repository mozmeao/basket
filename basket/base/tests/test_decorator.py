from datetime import timedelta
from unittest.mock import patch

from django.test.utils import override_settings

import pytest
from freezegun import freeze_time

from basket.base.rq import get_worker
from basket.base.tests.tasks import empty_job
from basket.news.models import QueuedTask


@pytest.mark.django_db
@freeze_time("2023-01-02 12:34:56.123456")
class TestDecorator:
    @override_settings(RQ_RESULT_TTL=0)
    @override_settings(RQ_MAX_RETRIES=0)
    @patch("basket.base.rq.Callback")
    @patch("basket.base.rq.get_queue")
    @patch("basket.base.rq.Queue")
    def test_rq_task(
        self,
        mock_get_queue,
        mock_queue,
        mock_callback,
    ):
        """
        Test that the decorator passes the correct arguments to the RQ job.
        """
        mock_get_queue.return_value = mock_queue

        empty_job.delay("arg1")

        mock_queue.enqueue_call.assert_called_once_with(
            empty_job,
            args=("arg1",),
            kwargs={},
            meta={
                "task_name": f"{empty_job.__module__}.{empty_job.__qualname__}",
                "start_time": 1672662896.123456,
            },
            retry=None,  # Retry logic is tested above, so no need to test it here.
            result_ttl=0,
            on_failure=mock_callback(),
            on_success=mock_callback(),
        )

    @override_settings(RQ_RESULT_TTL=0)
    @override_settings(RQ_MAX_RETRIES=0)
    @patch("basket.base.rq.Callback")
    @patch("basket.base.rq.get_queue")
    @patch("basket.base.rq.Queue")
    def test_rq_delayed_task(
        self,
        mock_get_queue,
        mock_queue,
        mock_callback,
    ):
        """
        Test that the decorator uses queue.enqueue_in if an enqueue_in kwarg was passed.
        It should pop `enqueue_in` from kwargs so it isn't passed to the function.
        """
        mock_get_queue.return_value = mock_queue

        enqueue_in = timedelta(minutes=5)
        empty_job.delay("arg1", enqueue_in=enqueue_in)

        mock_queue.enqueue_in.assert_called_once_with(
            enqueue_in,
            empty_job,
            args=("arg1",),
            kwargs={},
            meta={
                "task_name": f"{empty_job.__module__}.{empty_job.__qualname__}",
                "start_time": 1672662896.123456,
            },
            retry=None,  # Retry logic is tested above, so no need to test it here.
            result_ttl=0,
            on_failure=mock_callback(),
            on_success=mock_callback(),
        )

    @override_settings(MAINTENANCE_MODE=True)
    def test_maintenance_mode_no_readonly(self, metricsmock):
        """
        Test that the decorator doesn't run the task if maintenance mode is on.
        """
        assert QueuedTask.objects.count() == 0

        empty_job.delay("arg1")

        metricsmock.assert_incr_once("basket.base.tests.tasks.empty_job.queued")
        assert QueuedTask.objects.count() == 1

    def test_job_success(self, metricsmock):
        """
        Test that the decorator marks the job as successful if the task runs
        successfully.
        """
        empty_job.delay("arg1")

        worker = get_worker()
        worker.work(burst=True)  # Burst = worker will quit after all jobs consumed.

        metricsmock.assert_timing_once("task.timings", tags=["task:basket.base.tests.tasks.empty_job", "status:success"])

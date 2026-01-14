from datetime import datetime
from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import TestCase

from rq.job import JobStatus


class RQExplorerCommandTest(TestCase):
    """Test the rq_explorer management command"""

    def setUp(self):
        """Set up mocks for RQ infrastructure"""
        patcher = patch("basket.news.management.commands.rq_explorer.rq_helpers.get_redis_connection")
        self.mock_get_redis = patcher.start()
        self.addCleanup(patcher.stop)

        patcher = patch("basket.news.management.commands.rq_explorer.Queue")
        self.mock_queue_class = patcher.start()
        self.addCleanup(patcher.stop)

        patcher = patch("basket.news.management.commands.rq_explorer.Job")
        self.mock_job_class = patcher.start()
        self.addCleanup(patcher.stop)

        self.mock_conn = Mock()
        self.mock_get_redis.return_value = self.mock_conn
        self.mock_queue = Mock()
        self.mock_queue_class.return_value = self.mock_queue

    def _create_mock_job(self, job_id, description, enqueued_at=None, status=JobStatus.QUEUED):
        """Helper to create a mock RQ Job"""
        mock_job = Mock()
        mock_job.id = job_id
        mock_job.description = description
        mock_job.enqueued_at = enqueued_at
        mock_job.get_status.return_value = status
        return mock_job

    def test_summary_mode(self):
        """Test summary mode shows task type counts"""
        self.mock_queue.job_ids = ["job1", "job2", "job3"]
        self.mock_job_class.fetch_many.return_value = [
            self._create_mock_job("job1", "basket.news.tasks.update_user(123)"),
            self._create_mock_job("job2", "basket.news.tasks.update_user(456)"),
            self._create_mock_job("job3", "basket.news.tasks.send_email(789)"),
        ]

        out = StringIO()
        call_command("rq_explorer", stdout=out)
        output = out.getvalue()

        self.assertIn("Task types:", output)
        self.assertIn("basket.news.tasks.update_user", output)
        self.assertIn("basket.news.tasks.send_email", output)
        self.assertIn("Total: 3 jobs", output)

    def test_filter_mode_with_matches(self):
        """Test filter mode when matching jobs are found"""
        self.mock_queue.job_ids = ["job1", "job2", "job3"]
        self.mock_job_class.fetch_many.return_value = [
            self._create_mock_job("job1", "basket.news.tasks.fxa_email_changed(123)", enqueued_at=datetime(2025, 1, 1, 10, 0, 0)),
            self._create_mock_job("job2", "basket.news.tasks.update_user(456)", enqueued_at=datetime(2025, 1, 1, 11, 0, 0)),
            self._create_mock_job("job3", "basket.news.tasks.fxa_email_changed(789)", enqueued_at=datetime(2025, 1, 1, 12, 0, 0)),
        ]

        out = StringIO()
        call_command("rq_explorer", task_name="fxa_email_changed", stdout=out)
        output = out.getvalue()

        self.assertIn("Count: 2", output)
        self.assertIn("Longest running task:", output)
        self.assertIn("Job ID: job1", output)

    def test_filter_mode_no_matches(self):
        """Test filter mode when no matching jobs are found"""
        self.mock_queue.job_ids = ["job1"]
        self.mock_job_class.fetch_many.return_value = [
            self._create_mock_job("job1", "basket.news.tasks.update_user(123)"),
        ]

        out = StringIO()
        call_command("rq_explorer", task_name="nonexistent_task", stdout=out)

        self.assertIn("No jobs found matching 'nonexistent_task'", out.getvalue())

    def test_max_jobs_limit(self):
        """Test that max_jobs limit is respected"""
        self.mock_queue.job_ids = [f"job{i}" for i in range(15000)]
        self.mock_job_class.fetch_many.return_value = [self._create_mock_job(f"job{i}", f"basket.news.tasks.task{i}()") for i in range(100)]

        out = StringIO()
        call_command("rq_explorer", max_jobs=100, stdout=out)

        self.assertIn("Inspecting first 100 of 15,000 jobs", out.getvalue())
        # Verify fetch_many was called with exactly 100 job IDs
        call_args = self.mock_job_class.fetch_many.call_args
        self.assertEqual(len(call_args[0][0]), 100)

    def test_handles_missing_jobs(self):
        """Test that missing jobs (None from fetch_many) are handled gracefully"""
        self.mock_queue.job_ids = ["job1", "job2"]
        # fetch_many returns None for jobs that no longer exist
        self.mock_job_class.fetch_many.return_value = [
            self._create_mock_job("job1", "basket.news.tasks.task(job1)"),
            None,
        ]

        out = StringIO()
        call_command("rq_explorer", stdout=out)

        self.assertIn("<missing job payload>", out.getvalue())

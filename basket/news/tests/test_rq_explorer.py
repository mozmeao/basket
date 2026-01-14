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
        # Mock new Redis methods
        self.mock_conn.llen.return_value = 3
        self.mock_conn.lrange.return_value = [b"job1", b"job2", b"job3"]
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
        self.assertIn("Inspected: 3 jobs", output)
        self.assertIn("Total in queue: 3 jobs", output)

    def test_filter_mode_with_matches(self):
        """Test filter mode when matching jobs are found"""
        # Mock new Redis methods
        self.mock_conn.llen.return_value = 3
        self.mock_conn.lrange.return_value = [b"job1", b"job2", b"job3"]

        # Mock pipeline for description fetching
        mock_pipeline = Mock()
        self.mock_conn.pipeline.return_value = mock_pipeline
        mock_pipeline.execute.return_value = [
            b"basket.news.tasks.fxa_email_changed(123)",
            b"basket.news.tasks.update_user(456)",
            b"basket.news.tasks.fxa_email_changed(789)",
        ]

        # Mock Job.key_for
        self.mock_job_class.key_for = lambda job_id: f"rq:job:{job_id}"

        # Only matching jobs should be fetched
        self.mock_job_class.fetch_many.return_value = [
            self._create_mock_job("job1", "basket.news.tasks.fxa_email_changed(123)", enqueued_at=datetime(2025, 1, 1, 10, 0, 0)),
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
        # Mock new Redis methods
        self.mock_conn.llen.return_value = 1
        self.mock_conn.lrange.return_value = [b"job1"]

        # Mock pipeline for description fetching
        mock_pipeline = Mock()
        self.mock_conn.pipeline.return_value = mock_pipeline
        mock_pipeline.execute.return_value = [b"basket.news.tasks.update_user(123)"]

        # Mock Job.key_for
        self.mock_job_class.key_for = lambda job_id: f"rq:job:{job_id}"

        out = StringIO()
        call_command("rq_explorer", task_name="nonexistent_task", stdout=out)

        self.assertIn("No jobs found matching 'nonexistent_task'", out.getvalue())

    def test_max_jobs_limit(self):
        """Test that max_jobs limit is respected"""
        # Mock new Redis methods
        self.mock_conn.llen.return_value = 15000
        self.mock_conn.lrange.return_value = [f"job{i}".encode() for i in range(100)]
        self.mock_job_class.fetch_many.return_value = [self._create_mock_job(f"job{i}", f"basket.news.tasks.task{i}()") for i in range(100)]

        out = StringIO()
        call_command("rq_explorer", max_jobs=100, stdout=out)

        self.assertIn("Inspecting first 100 of 15,000 jobs", out.getvalue())
        # Verify lrange was called with correct bounds
        self.mock_conn.lrange.assert_called_once()
        call_args = self.mock_conn.lrange.call_args[0]
        self.assertEqual(call_args[1], 0)  # Start at 0
        self.assertEqual(call_args[2], 99)  # End at max_jobs-1
        # Verify total queue count is displayed
        self.assertIn("Inspected: 100 jobs", out.getvalue())
        self.assertIn("Total in queue: 15,000 jobs", out.getvalue())

    def test_handles_missing_jobs(self):
        """Test that missing jobs (None from fetch_many) are handled gracefully"""
        # Mock new Redis methods
        self.mock_conn.llen.return_value = 2
        self.mock_conn.lrange.return_value = [b"job1", b"job2"]
        # fetch_many returns None for jobs that no longer exist
        self.mock_job_class.fetch_many.return_value = [
            self._create_mock_job("job1", "basket.news.tasks.task(job1)"),
            None,
        ]

        out = StringIO()
        call_command("rq_explorer", stdout=out)

        self.assertIn("<missing job payload>", out.getvalue())

    def test_large_queue_only_fetches_needed_ids(self):
        """Test that we only fetch max_jobs IDs, not all IDs"""
        # Simulate 500k jobs in queue
        self.mock_conn.llen.return_value = 500000
        self.mock_conn.lrange.return_value = [f"job{i}".encode() for i in range(100)]
        self.mock_job_class.fetch_many.return_value = [self._create_mock_job(f"job{i}", f"task{i}()") for i in range(100)]

        out = StringIO()
        call_command("rq_explorer", max_jobs=100, stdout=out)

        # Verify llen was called to get total count
        self.mock_conn.llen.assert_called_once()

        # Verify lrange was called with correct bounds (only first 100)
        self.mock_conn.lrange.assert_called_once()
        call_args = self.mock_conn.lrange.call_args[0]
        self.assertEqual(call_args[1], 0)  # Start at 0
        self.assertEqual(call_args[2], 99)  # End at max_jobs-1

        # Verify warning about large queue
        self.assertIn("Inspecting first 100 of 500,000 jobs", out.getvalue())
        # Verify total queue count is displayed
        self.assertIn("Inspected: 100 jobs", out.getvalue())
        self.assertIn("Total in queue: 500,000 jobs", out.getvalue())

    def test_filter_mode_uses_pipeline(self):
        """Test that filter mode uses pipeline to check descriptions first"""
        self.mock_conn.llen.return_value = 1000
        self.mock_conn.lrange.return_value = [f"job{i}".encode() for i in range(1000)]

        # Mock pipeline
        mock_pipeline = Mock()
        self.mock_conn.pipeline.return_value = mock_pipeline

        # Simulate 1000 jobs but only 2 match the filter
        descriptions = [b"other_task()" for _ in range(998)]
        descriptions.insert(0, b"basket.news.tasks.fxa_email_changed(123)")
        descriptions.insert(500, b"basket.news.tasks.fxa_email_changed(456)")
        mock_pipeline.execute.return_value = descriptions

        # Mock Job.key_for
        self.mock_job_class.key_for = lambda job_id: f"rq:job:{job_id}"

        # Only the 2 matching jobs should be fully fetched
        self.mock_job_class.fetch_many.return_value = [
            self._create_mock_job("job0", "basket.news.tasks.fxa_email_changed(123)", enqueued_at=datetime(2025, 1, 1, 10, 0, 0)),
            self._create_mock_job("job500", "basket.news.tasks.fxa_email_changed(456)", enqueued_at=datetime(2025, 1, 1, 11, 0, 0)),
        ]

        out = StringIO()
        call_command("rq_explorer", task_name="fxa_email_changed", stdout=out)

        # Verify pipeline was used
        self.mock_conn.pipeline.assert_called_once()
        self.assertEqual(mock_pipeline.hget.call_count, 1000)

        # Verify fetch_many was called with only matching IDs
        fetch_call_args = self.mock_job_class.fetch_many.call_args[0][0]
        self.assertEqual(len(fetch_call_args), 2)
        self.assertIn("job0", fetch_call_args)
        self.assertIn("job500", fetch_call_args)

        # Verify output shows correct count
        self.assertIn("Count: 2", out.getvalue())

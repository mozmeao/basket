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
        self.mock_job_class.key_for = lambda job_id: f"rq:job:{job_id}"

    def _create_mock_job(self, job_id, description, enqueued_at=None, created_at=None, status=JobStatus.QUEUED):
        """Helper to create a mock RQ Job"""
        mock_job = Mock()
        mock_job.id = job_id
        mock_job.description = description
        mock_job.enqueued_at = enqueued_at
        mock_job.created_at = created_at or datetime.now()
        mock_job.get_status.return_value = status
        return mock_job

    def _setup_queue(self, total_jobs, job_ids):
        """Helper to setup basic queue mocks"""
        self.mock_conn.llen.return_value = total_jobs
        self.mock_conn.lrange.return_value = job_ids

    def _setup_filter_pipeline(self, descriptions):
        """Helper to setup pipeline for filter mode"""
        mock_pipeline = Mock()
        self.mock_conn.pipeline.return_value = mock_pipeline
        mock_pipeline.execute.return_value = descriptions
        return mock_pipeline

    def _run_command(self, **kwargs):
        """Helper to run command and return output"""
        out = StringIO()
        call_command("rq_explorer", stdout=out, **kwargs)
        return out.getvalue()

    def test_summary_mode(self):
        """Test summary mode shows task type counts"""
        self._setup_queue(3, [b"job1", b"job2", b"job3"])
        self.mock_job_class.fetch_many.return_value = [
            self._create_mock_job("job1", "basket.news.tasks.update_user(123)"),
            self._create_mock_job("job2", "basket.news.tasks.update_user(456)"),
            self._create_mock_job("job3", "basket.news.tasks.send_email(789)"),
        ]

        output = self._run_command()

        self.assertIn("basket.news.tasks.update_user", output)
        self.assertIn("basket.news.tasks.send_email", output)
        self.assertIn("Inspected: 3 jobs", output)

    def test_empty_queue(self):
        """Test empty queue handling"""
        self._setup_queue(0, [])
        self.mock_job_class.fetch_many.return_value = []

        output = self._run_command()

        self.assertIn("Total in queue: 0 jobs", output)
        self.mock_conn.lrange.assert_not_called()

    def test_filter_mode_with_matches(self):
        """Test filter mode when matching jobs are found"""
        self._setup_queue(3, [b"job1", b"job2", b"job3"])
        self._setup_filter_pipeline(
            [
                b"basket.news.tasks.fxa_email_changed(123)",
                b"basket.news.tasks.update_user(456)",
                b"basket.news.tasks.fxa_email_changed(789)",
            ]
        )
        self.mock_job_class.fetch_many.return_value = [
            self._create_mock_job("job1", "basket.news.tasks.fxa_email_changed(123)", enqueued_at=datetime(2025, 1, 1, 10, 0, 0)),
            self._create_mock_job("job3", "basket.news.tasks.fxa_email_changed(789)", enqueued_at=datetime(2025, 1, 1, 12, 0, 0)),
        ]

        output = self._run_command(task_name="fxa_email_changed")

        self.assertIn("Count: 2", output)
        self.assertIn("Job ID: job1", output)

    def test_filter_mode_no_matches(self):
        """Test filter mode when no matching jobs are found"""
        self._setup_queue(1, [b"job1"])
        self._setup_filter_pipeline([b"basket.news.tasks.update_user(123)"])

        output = self._run_command(task_name="nonexistent_task")

        self.assertIn("No jobs found matching 'nonexistent_task'", output)

    def test_created_at_fallback(self):
        """Test fallback to created_at when enqueued_at is None"""
        self._setup_queue(2, [b"job1", b"job2"])
        self._setup_filter_pipeline([b"basket.news.tasks.test(1)", b"basket.news.tasks.test(2)"])
        self.mock_job_class.fetch_many.return_value = [
            self._create_mock_job("job1", "basket.news.tasks.test(1)", enqueued_at=None, created_at=datetime(2025, 1, 1, 10, 0, 0)),
            self._create_mock_job("job2", "basket.news.tasks.test(2)", enqueued_at=None, created_at=datetime(2025, 1, 1, 9, 0, 0)),
        ]

        output = self._run_command(task_name="test")

        self.assertIn("Job ID: job2", output)  # job2 has earlier created_at

    def test_job_statuses(self):
        """Test different job status displays"""
        statuses = [JobStatus.STARTED, JobStatus.FAILED, JobStatus.FINISHED, JobStatus.SCHEDULED, JobStatus.DEFERRED]

        for status in statuses:
            with self.subTest(status=status):
                self._setup_queue(1, [b"job1"])
                self._setup_filter_pipeline([b"basket.news.tasks.test(1)"])
                self.mock_job_class.fetch_many.return_value = [
                    self._create_mock_job("job1", "basket.news.tasks.test(1)", enqueued_at=datetime(2025, 1, 1, 10, 0, 0), status=status)
                ]

                output = self._run_command(task_name="test")

                self.assertIn(f"Status: {status.name.lower()}", output)

    def test_race_condition_all_jobs_none(self):
        """Test race condition where jobs are deleted between pipeline check and fetch"""
        self._setup_queue(2, [b"job1", b"job2"])
        self._setup_filter_pipeline([b"basket.news.tasks.test(1)", b"basket.news.tasks.test(2)"])
        self.mock_job_class.fetch_many.return_value = [None, None]

        output = self._run_command(task_name="test")

        self.assertIn("No jobs found matching 'test'", output)

    def test_max_jobs_limit(self):
        """Test that max_jobs limit is respected"""
        self._setup_queue(15000, [f"job{i}".encode() for i in range(100)])
        self.mock_job_class.fetch_many.return_value = [self._create_mock_job(f"job{i}", f"task{i}()") for i in range(100)]

        output = self._run_command(max_jobs=100)

        self.assertIn("Inspecting first 100 of 15,000 jobs", output)
        self.assertEqual(self.mock_conn.lrange.call_args[0][2], 99)  # End at max_jobs-1

    def test_default_max_jobs(self):
        """Test default max_jobs value is used"""
        self._setup_queue(5000, [f"job{i}".encode() for i in range(5000)])
        self.mock_job_class.fetch_many.return_value = [self._create_mock_job(f"job{i}", f"task{i}()") for i in range(5000)]

        output = self._run_command()

        self.assertIn("Inspected: 5,000 jobs", output)
        self.assertNotIn("Inspecting first", output)  # No warning since under default limit

    def test_missing_jobs(self):
        """Test that missing jobs (None from fetch_many) are handled gracefully"""
        self._setup_queue(2, [b"job1", b"job2"])
        self.mock_job_class.fetch_many.return_value = [
            self._create_mock_job("job1", "basket.news.tasks.task(1)"),
            None,
        ]

        output = self._run_command()

        self.assertIn("<missing job payload>", output)

    def test_none_and_empty_descriptions(self):
        """Test handling of None and empty string descriptions"""
        self._setup_queue(3, [b"job1", b"job2", b"job3"])
        self.mock_job_class.fetch_many.return_value = [
            self._create_mock_job("job1", None),
            self._create_mock_job("job2", ""),
            self._create_mock_job("job3", "basket.news.tasks.valid()"),
        ]

        output = self._run_command()

        self.assertIn("<no description>", output)

    def test_non_bytes_job_ids(self):
        """Test handling of non-bytes job_ids from Redis"""
        self._setup_queue(3, ["job1", b"job2", "job3"])  # Mix of str and bytes
        self.mock_job_class.fetch_many.return_value = [
            self._create_mock_job("job1", "task1()"),
            self._create_mock_job("job2", "task2()"),
            self._create_mock_job("job3", "task3()"),
        ]

        output = self._run_command()

        self.assertIn("Inspected: 3 jobs", output)

    def test_non_bytes_descriptions(self):
        """Test handling of non-bytes descriptions from pipeline"""
        self._setup_queue(3, [b"job1", b"job2", b"job3"])
        self._setup_filter_pipeline(
            [
                "basket.news.tasks.test(1)",  # String instead of bytes
                b"basket.news.tasks.test(2)",  # Bytes
                "basket.news.tasks.other(3)",
            ]
        )
        self.mock_job_class.fetch_many.return_value = [
            self._create_mock_job("job0", "basket.news.tasks.test(1)", enqueued_at=datetime(2025, 1, 1, 10, 0, 0)),
            self._create_mock_job("job1", "basket.news.tasks.test(2)", enqueued_at=datetime(2025, 1, 1, 11, 0, 0)),
        ]

        output = self._run_command(task_name="test")

        self.assertIn("Count: 2", output)

    def test_same_timestamp_edge_case(self):
        """Test handling of multiple jobs with identical timestamps"""
        same_time = datetime(2025, 1, 1, 10, 0, 0)
        self._setup_queue(3, [b"job1", b"job2", b"job3"])
        self._setup_filter_pipeline([b"basket.news.tasks.test(1)", b"basket.news.tasks.test(2)", b"basket.news.tasks.test(3)"])
        self.mock_job_class.fetch_many.return_value = [
            self._create_mock_job("job1", "basket.news.tasks.test(1)", enqueued_at=same_time),
            self._create_mock_job("job2", "basket.news.tasks.test(2)", enqueued_at=same_time),
            self._create_mock_job("job3", "basket.news.tasks.test(3)", enqueued_at=same_time),
        ]

        output = self._run_command(task_name="test")

        self.assertIn("Longest running task:", output)
        self.assertIn("2025-01-01", output)

    def test_filter_with_max_jobs(self):
        """Test filter mode respects max_jobs limit"""
        self._setup_queue(20000, [f"job{i}".encode() for i in range(100)])
        pipeline = self._setup_filter_pipeline([b"other()" for _ in range(100)])
        pipeline.execute.return_value[0] = b"basket.news.tasks.test(1)"
        pipeline.execute.return_value[50] = b"basket.news.tasks.test(2)"
        self.mock_job_class.fetch_many.return_value = [
            self._create_mock_job("job0", "basket.news.tasks.test(1)", enqueued_at=datetime(2025, 1, 1, 10, 0, 0)),
            self._create_mock_job("job50", "basket.news.tasks.test(2)", enqueued_at=datetime(2025, 1, 1, 11, 0, 0)),
        ]

        output = self._run_command(task_name="test", max_jobs=100)

        self.assertIn("Inspecting first 100 of 20,000 jobs", output)
        self.assertIn("Count: 2", output)

    def test_large_queue_optimization(self):
        """Test that large queues only fetch needed IDs"""
        self._setup_queue(500000, [f"job{i}".encode() for i in range(100)])
        self.mock_job_class.fetch_many.return_value = [self._create_mock_job(f"job{i}", f"task{i}()") for i in range(100)]

        output = self._run_command(max_jobs=100)

        self.mock_conn.llen.assert_called_once()
        self.assertEqual(self.mock_conn.lrange.call_args[0][2], 99)  # Only fetched 100
        self.assertIn("Inspecting first 100 of 500,000 jobs", output)

    def test_filter_mode_uses_pipeline(self):
        """Test that filter mode uses pipeline efficiently"""
        self._setup_queue(1000, [f"job{i}".encode() for i in range(1000)])
        descriptions = [b"other_task()" for _ in range(998)]
        descriptions.insert(0, b"basket.news.tasks.target(1)")
        descriptions.insert(500, b"basket.news.tasks.target(2)")
        pipeline = self._setup_filter_pipeline(descriptions)
        self.mock_job_class.fetch_many.return_value = [
            self._create_mock_job("job0", "basket.news.tasks.target(1)", enqueued_at=datetime(2025, 1, 1, 10, 0, 0)),
            self._create_mock_job("job500", "basket.news.tasks.target(2)", enqueued_at=datetime(2025, 1, 1, 11, 0, 0)),
        ]

        output = self._run_command(task_name="target")

        self.mock_conn.pipeline.assert_called_once()
        self.assertEqual(pipeline.hget.call_count, 1000)
        self.assertEqual(len(self.mock_job_class.fetch_many.call_args[0][0]), 2)  # Only fetched 2 matching jobs
        self.assertIn("Count: 2", output)

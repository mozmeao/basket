from collections import Counter

from django.core.management.base import BaseCommand

from rq import Queue
from rq.job import Job

from basket.base import rq as rq_helpers


class Command(BaseCommand):
    help = "Explore RQ jobs/tasks"

    def add_arguments(self, parser):
        parser.add_argument(
            "--task-name",
            type=str,
            help="Filter jobs by task name (e.g., basket.news.tasks.fxa_email_changed)",
        )
        parser.add_argument(
            "--max-jobs",
            type=int,
            default=10000,
            help="Maximum number of jobs to inspect (default: 10000)",
        )

    def handle(self, **options):
        task_name_filter = options.get("task_name")
        max_jobs = options["max_jobs"]

        def task_type(desc):
            if not desc:
                return "<no description>"
            return desc.split("(", 1)[0]

        conn = rq_helpers.get_redis_connection()
        q = Queue(connection=conn)

        # Get job_ids once to avoid multiple Redis calls
        job_ids = q.job_ids
        total_jobs = len(job_ids)
        job_ids = job_ids[:max_jobs]

        if total_jobs > max_jobs:
            self.stdout.write(self.style.WARNING(f"Inspecting first {max_jobs:,} of {total_jobs:,} jobs"))

        # Batch fetch all jobs in one Redis call (much faster than individual fetches)
        jobs = Job.fetch_many(job_ids, connection=conn)

        if task_name_filter:
            matching_jobs = [job for job in jobs if job is not None and job.description and task_name_filter in job.description]

            if not matching_jobs:
                self.stdout.write(self.style.WARNING(f"No jobs found matching '{task_name_filter}'"))
                return

            self.stdout.write(f"Count: {len(matching_jobs)}\n")

            oldest_job = min(matching_jobs, key=lambda j: j.enqueued_at or j.created_at)
            self.stdout.write("Longest running task:")
            self.stdout.write(f"  Job ID: {oldest_job.id}")
            self.stdout.write(f"  Description: {oldest_job.description}")
            self.stdout.write(f"  Enqueued: {oldest_job.enqueued_at or oldest_job.created_at}")
            self.stdout.write(f"  Status: {oldest_job.get_status().name.lower()}")
            return

        # Summary mode: show task type counts
        counts = Counter()
        for job in jobs:
            if job is None:
                counts["<missing job payload>"] += 1
            else:
                counts[task_type(job.description)] += 1

        self.stdout.write("\nTask types:\n")
        for task, n in counts.most_common():
            self.stdout.write(f"{n:6}  {task}")

        self.stdout.write(f"\nTotal: {sum(counts.values())} jobs")

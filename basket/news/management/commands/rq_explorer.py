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

        total_jobs = conn.llen(q.key)

        # Only fetch the job IDs we'll actually inspect
        if total_jobs > 0:
            job_ids = conn.lrange(q.key, 0, min(max_jobs, total_jobs) - 1)
            job_ids = [job_id.decode("utf-8") if isinstance(job_id, bytes) else job_id for job_id in job_ids]
        else:
            job_ids = []

        if total_jobs > max_jobs:
            self.stdout.write(self.style.WARNING(f"Inspecting first {max_jobs:,} of {total_jobs:,} jobs"))

        # For filter mode, fetch descriptions first, then full jobs
        if task_name_filter:
            pipeline = conn.pipeline()
            for job_id in job_ids:
                pipeline.hget(Job.key_for(job_id), "description")
            descriptions = pipeline.execute()
            matching_ids = []
            for job_id, desc in zip(job_ids, descriptions, strict=False):
                if desc:
                    desc_str = desc.decode("utf-8") if isinstance(desc, bytes) else desc
                    if task_name_filter in desc_str:
                        matching_ids.append(job_id)

            if not matching_ids:
                self.stdout.write(self.style.WARNING(f"No jobs found matching '{task_name_filter}'"))
                return

            self.stdout.write(f"Count: {len(matching_ids)}\n")

            matching_jobs = Job.fetch_many(matching_ids, connection=conn)
            matching_jobs = [job for job in matching_jobs if job is not None]

            if not matching_jobs:
                self.stdout.write(self.style.WARNING(f"No jobs found matching '{task_name_filter}'"))
                return

            oldest_job = min(matching_jobs, key=lambda j: j.enqueued_at or j.created_at)
            self.stdout.write("Longest running task:")
            self.stdout.write(f"  Job ID: {oldest_job.id}")
            self.stdout.write(f"  Description: {oldest_job.description}")
            self.stdout.write(f"  Enqueued: {oldest_job.enqueued_at or oldest_job.created_at}")
            self.stdout.write(f"  Status: {oldest_job.get_status().name.lower()}")
            return

        jobs = Job.fetch_many(job_ids, connection=conn)
        counts = Counter()
        for job in jobs:
            if job is None:
                counts["<missing job payload>"] += 1
            else:
                counts[task_type(job.description)] += 1

        self.stdout.write("\nTask types:\n")
        for task, n in counts.most_common():
            self.stdout.write(f"{n:6}  {task}")

        inspected_count = sum(counts.values())
        self.stdout.write(f"\nInspected: {inspected_count:,} jobs")
        self.stdout.write(f"Total in queue: {total_jobs:,} jobs")

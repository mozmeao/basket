import functools
from time import time

from django.conf import settings

from django_statsd.clients import statsd
from rq.decorators import job

from basket.base.rq import enqueue_kwargs, get_queue


class rq_job(job):
    def __call__(self, f):
        @functools.wraps(f)
        def delay(*args, **kwargs):
            if isinstance(self.queue, str):
                queue = self.queue_class(name=self.queue, connection=self.connection)
            else:
                queue = self.queue

            depends_on = kwargs.pop("depends_on", None)
            job_id = kwargs.pop("job_id", None)
            at_front = kwargs.pop("at_front", False)

            if not depends_on:
                depends_on = self.depends_on

            if not at_front:
                at_front = self.at_front

            # Note: This line is the only addition to the parent class.
            # Copied from rq/decorators.py in v1.15.1.
            self.meta.update(start_time=time())

            return queue.enqueue_call(
                f,
                args=args,
                kwargs=kwargs,
                timeout=self.timeout,
                result_ttl=self.result_ttl,
                ttl=self.ttl,
                depends_on=depends_on,
                job_id=job_id,
                at_front=at_front,
                meta=self.meta,
                description=self.description,
                failure_ttl=self.failure_ttl,
                retry=self.retry,
                on_failure=self.on_failure,
                on_success=self.on_success,
                on_stopped=self.on_stopped,
            )

        f.delay = delay
        return f


def rq_task(func):
    """
    Decorator to standardize RQ tasks.

    Uses RQ's job decorator, but:
    - uses our default queue and connection
    - adds retry logic with exponential backoff
    - adds success/failure/retry callbacks
    - adds statsd metrics for job success/failure/retry
    - adds Sentry error reporting for failed jobs

    """
    task_name = f"{func.__module__}.{func.__qualname__}"

    queue = get_queue()
    connection = queue.connection

    kwargs = enqueue_kwargs(func)

    @rq_job(
        queue,
        connection=connection,
        **kwargs,
    )
    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        # If in maintenance mode, queue the task for later.
        if settings.MAINTENANCE_MODE:
            if settings.READ_ONLY_MODE:
                statsd.incr(f"{task_name}.not_queued")
            else:
                from basket.news.models import QueuedTask

                QueuedTask.objects.create(
                    name=task_name,
                    args=args,
                    kwargs=kwargs,
                )
                statsd.incr(f"{task_name}.queued")
            return

        # NOTE: Exceptions are handled with the RQ_EXCEPTION_HANDLERS
        return func(*args, **kwargs)

    return wrapped

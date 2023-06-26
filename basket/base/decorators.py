import functools

from django.conf import settings

from django_statsd.clients import statsd
from rq.decorators import job as rq_job

from basket.base.rq import enqueue_kwargs, get_queue


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

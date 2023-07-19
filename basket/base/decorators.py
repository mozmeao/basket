import functools

from django.conf import settings

from django_statsd.clients import statsd

from basket.base.rq import get_enqueue_kwargs, get_queue


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

    @functools.wraps(func)
    def delay(*args, **kwargs):
        # If in maintenance mode, `delay(...)` will not run the task, but will
        # instead queue it for later.
        if settings.MAINTENANCE_MODE:
            from basket.news.models import QueuedTask

            QueuedTask.objects.create(
                name=task_name,
                args=args,
                kwargs=kwargs,
            )
            statsd.incr(f"{task_name}.queued")

        else:
            queue = get_queue()
            enqueue_kwargs = get_enqueue_kwargs(func)

            return queue.enqueue_call(
                func,
                args=args,
                kwargs=kwargs,
                **enqueue_kwargs,
            )

    func.delay = delay
    return func

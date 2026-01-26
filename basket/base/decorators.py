import functools

from django.conf import settings
from django.db import close_old_connections

from basket import metrics
from basket.base.rq import get_enqueue_kwargs, get_queue


def rq_task(func):
    """
    Decorator to standardize RQ tasks.

    Similar to RQ's job decorator, but:
    - uses our default queue and connection
    - adds retry logic with exponential backoff
    - adds success/failure/retry callbacks
    - adds statsd metrics for job success/failure/retry
    - adds Sentry error reporting for failed jobs
    - closes stale database connections before task execution

    """
    task_name = f"{func.__module__}.{func.__qualname__}"

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        """
        Wrapper that closes stale database connections before executing the task.
        This prevents MySQL 'Server has gone away' errors in long-running RQ workers seen in stage Sentry errors.
        """
        close_old_connections()

        return func(*args, **kwargs)

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
            metrics.incr(f"{task_name}.queued")

        else:
            queue = get_queue()
            # Pass the wrapper (with connection management) instead of raw func
            enqueue_kwargs = get_enqueue_kwargs(wrapper)
            enqueue_in = kwargs.pop("enqueue_in", None)

            if enqueue_in:
                return queue.enqueue_in(
                    enqueue_in,
                    wrapper,
                    args=args,
                    kwargs=kwargs,
                    **enqueue_kwargs,
                )
            else:
                return queue.enqueue_call(
                    wrapper,
                    args=args,
                    kwargs=kwargs,
                    **enqueue_kwargs,
                )

    # Attach delay method to the wrapper, not the original func
    wrapper.delay = delay
    return wrapper

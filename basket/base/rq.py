import random
import re
import traceback
from time import time

from django.conf import settings

import redis
import requests
import sentry_sdk
from rq import Callback, Retry, SimpleWorker
from rq.job import JobStatus
from rq.queue import Queue
from rq.serializers import JSONSerializer
from silverpop.api import SilverpopResponseException

from basket import metrics
from basket.base.exceptions import RetryTask
from basket.news.backends.common import NewsletterException

# don't propagate and don't retry if these are the error messages
IGNORE_ERROR_MSGS = [
    "INVALID_EMAIL_ADDRESS",
    "InvalidEmailAddress",
    "An invalid phone number was provided",
    "No valid subscribers were provided",
    "There are no valid subscribers",
    "email address is suppressed",
    "invalid email address",
]
# don't propagate and don't retry if these regex match the error messages
IGNORE_ERROR_MSGS_RE = [re.compile(r"campaignId \d+ not found")]
# Exceptions we allow to retry, all others will abort retries.
EXCEPTIONS_ALLOW_RETRY = [
    IOError,
    NewsletterException,
    requests.RequestException,
    RetryTask,
    SilverpopResponseException,
]


# Our cached Redis connection.
_REDIS_CONN = None


def get_redis_connection(url=None, force=False):
    """
    Get a Redis connection.

    Expects a URL including the db, or defaults to `settings.RQ_URL`.

    Call example:
        get_redis_connection("redis://localhost:6379/0")

    """
    global _REDIS_CONN

    if force or _REDIS_CONN is None:
        if url is None:
            if settings.RQ_URL is None:
                # Note: RQ_URL is derived from REDIS_URL.
                raise ValueError("No `settings.REDIS_URL` specified")
            url = settings.RQ_URL
        _REDIS_CONN = redis.Redis.from_url(url)

    return _REDIS_CONN


def get_queue(queue="default"):
    """
    Get an RQ queue with our chosen parameters.

    """
    return Queue(
        queue,
        connection=get_redis_connection(),
        is_async=settings.RQ_IS_ASYNC,
        serializer=JSONSerializer,
    )


def get_worker(queues=None):
    """
    Get an RQ worker with our chosen parameters.

    """
    if queues is None:
        queues = ["default"]

    return SimpleWorker(
        queues,
        connection=get_redis_connection(),
        disable_default_exception_handler=True,
        exception_handlers=[store_task_exception_handler],
        serializer=JSONSerializer,
    )


def get_enqueue_kwargs(func):
    if isinstance(func, str):
        task_name = func
    else:
        task_name = f"{func.__module__}.{func.__qualname__}"

    # Start time is used to calculate the total time taken by the task, which includes queue time plus execution time of the task itself.
    meta = {
        "task_name": task_name,
        "start_time": time(),
    }

    if settings.RQ_MAX_RETRIES == 0:
        retry = None
    else:
        retry = Retry(settings.RQ_MAX_RETRIES, rq_exponential_backoff())

    return {
        "meta": meta,
        "retry": retry,
        "result_ttl": settings.RQ_RESULT_TTL,
        "on_success": Callback(rq_on_success),
        "on_failure": Callback(rq_on_failure),
    }


def rq_exponential_backoff():
    """
    Return an array of retry delays for RQ using an exponential back-off, using
    jitter to even out the spikes, waiting at least 1 minute between retries.
    """
    if settings.DEBUG:
        # While debugging locally, enable faster retries.
        return [5 for n in range(settings.RQ_MAX_RETRIES)]
    else:
        return [max(60, random.randrange(min(settings.RQ_MAX_RETRY_DELAY, 120 * (2**n)))) for n in range(settings.RQ_MAX_RETRIES)]


def record_metrics_timing(job, status):
    task_name = job.meta["task_name"]
    start_time = job.meta.get("start_time")
    if start_time and not settings.MAINTENANCE_MODE and not task_name.endswith("snitch"):
        total_time = int((time() - start_time) * 1000)
        metrics.timing("task.timings", total_time, tags=[f"task:{task_name}", f"status:{status}"])


def rq_on_success(job, connection, result, *args, **kwargs):
    record_metrics_timing(job, "success")


def rq_on_failure(job, connection, *exc_info, **kwargs):
    record_metrics_timing(job, "failure")


def ignore_error(exc, to_ignore=None, to_ignore_re=None):
    to_ignore = to_ignore or IGNORE_ERROR_MSGS
    to_ignore_re = to_ignore_re or IGNORE_ERROR_MSGS_RE
    msg = str(exc)
    for ignore_msg in to_ignore:
        if ignore_msg in msg:
            return True

    for ignore_re in to_ignore_re:
        if ignore_re.search(msg):
            return True

    return False


def store_task_exception_handler(job, *exc_info):
    """
    Handler to store task failures in the database.
    """
    task_name = job.meta["task_name"]

    if task_name.endswith("snitch"):
        return

    # NOTE: We are deliberately not using `job.is_scheduled` or `job.is_failed` properties because
    # they trigger a `get_status` call, which refreshes the status from Redis by default. Since the code
    # is modifying the `job._status` property directly, Redis does not accurately reflect the job's
    # status until processing completes. This custom exception handler is triggered in the middle of
    # that process, so we must access the `_status` property directly to get the current state.

    # A job will retry if it has failed but has not yet reached the maximum number of retries.
    # A job is scheduled for retry when its status is `SCHEDULED`; otherwise, its status is set to `FAILED`.

    if job._status == JobStatus.SCHEDULED:
        # Job failed but is scheduled for a retry.
        metrics.incr("base.tasks.retried", tags=[f"task:{task_name}"])

        if exc_info[1] not in EXCEPTIONS_ALLOW_RETRY:
            # Force retries to abort.
            # Since there's no way to abort retries at the moment in RQ, we can set the job `retries_left` to zero.
            # This will retry one more time but no further retries will be performed.
            job.retries_left = 0

        # Don't log to sentry if we explicitly raise `RetryTask`.
        if not isinstance(exc_info[1], RetryTask):
            with sentry_sdk.isolation_scope() as scope:
                scope.set_tag("action", "retried")
                sentry_sdk.capture_exception()

    elif job._status == JobStatus.FAILED:
        # Job failed but no retries left.
        metrics.incr("base.tasks.failed", tags=[f"task:{task_name}"])

        # Here to avoid a circular import.
        from basket.news.models import FailedTask

        FailedTask.objects.create(
            task_id=job.id,
            name=job.meta["task_name"],
            args=job.args,
            kwargs=job.kwargs,
            exc=exc_info[1].__repr__(),
            einfo="".join(traceback.format_exception(*exc_info)),
        )

        if ignore_error(exc_info[1]):
            with sentry_sdk.isolation_scope() as scope:
                scope.set_tag("action", "ignored")
                sentry_sdk.capture_exception()
            return

        # Don't log to sentry if we explicitly raise `RetryTask`.
        if not isinstance(exc_info[1], RetryTask):
            with sentry_sdk.isolation_scope() as scope:
                scope.set_tag("action", "failed")
                sentry_sdk.capture_exception()

    # Returning `False`` prevents any subsequent exception handlers from running.
    return False

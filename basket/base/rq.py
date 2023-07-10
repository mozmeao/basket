import random
import re
import traceback
from time import time

from django.conf import settings

import redis
import requests
import sentry_sdk
from django_statsd.clients import statsd
from rq import Callback, Retry, SimpleWorker
from rq.queue import Queue
from rq.serializers import JSONSerializer
from silverpop.api import SilverpopResponseException

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


def log_timing(job):
    if start_time := job.meta.get("start_time"):
        total_time = int((time() - start_time) * 1000)
        statsd.timing(f"{job.meta['task_name']}.duration", total_time)
        statsd.timing("news.tasks.duration_total", total_time)


def rq_on_success(job, connection, result, *args, **kwargs):
    # Don't fire statsd metrics in maintenance mode.
    if not settings.MAINTENANCE_MODE:
        log_timing(job)
        task_name = job.meta["task_name"]
        statsd.incr(f"{task_name}.success")
        if not task_name.endswith("snitch"):
            statsd.incr("news.tasks.success_total")


def rq_on_failure(job, connection, *exc_info, **kwargs):
    # Don't fire statsd metrics in maintenance mode.
    if not settings.MAINTENANCE_MODE:
        log_timing(job)
        task_name = job.meta["task_name"]
        statsd.incr(f"{task_name}.failure")
        if not task_name.endswith("snitch"):
            statsd.incr("news.tasks.failure_total")


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

    # A job will retry if it's failed but not yet reached the max retries.
    # We know when a job is going to be retried if the status is `is_scheduled`, otherwise the
    # status is set to `is_failed`.

    if job.is_scheduled:
        # Job failed but is scheduled for a retry.
        statsd.incr(f"{task_name}.retry")
        statsd.incr(f"{task_name}.retries_left.{job.retries_left + 1}")
        statsd.incr("news.tasks.retry_total")

        if exc_info[1] not in EXCEPTIONS_ALLOW_RETRY:
            # Force retries to abort.
            # Since there's no way to abort retries at the moment in RQ, we can set the job `retries_left` to zero.
            # This will retry one more time but no further retries will be performed.
            job.retries_left = 0

        # Don't log to sentry if we explicitly raise `RetryTask`.
        if not isinstance(exc_info[1], RetryTask):
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("action", "retried")
                sentry_sdk.capture_exception()

    elif job.is_failed:
        statsd.incr(f"{task_name}.retry_max")
        statsd.incr("news.tasks.retry_max_total")

        # Job failed but no retries left.
        if settings.STORE_TASK_FAILURES:
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
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("action", "ignored")
                sentry_sdk.capture_exception()
            return

        # Don't log to sentry if we explicitly raise `RetryTask`.
        if not isinstance(exc_info[1], RetryTask):
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("action", "failed")
                sentry_sdk.capture_exception()

from basket.base.decorators import rq_task
from basket.news.utils import NewsletterException


@rq_task
def failing_job(arg1, **kwargs):
    raise ValueError("An exception to trigger the failure handler.")


@rq_task
def retryable_job(arg1, **kwargs):
    raise NewsletterException("An exception to trigger the failure handler.")


@rq_task
def empty_job(arg1, **kwargs):
    pass

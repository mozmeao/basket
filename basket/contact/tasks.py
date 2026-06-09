from basket.base.decorators import rq_task

from .backends import get_contact_sink


@rq_task
def submit_contact(data):
    sink = get_contact_sink()
    sink.submit(data)

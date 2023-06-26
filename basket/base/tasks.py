from time import time

from django.conf import settings

import requests

from basket.base.decorators import rq_task


@rq_task
def snitch(start_time):
    duration = int((time() - start_time) * 1000)
    if settings.SNITCH_ID:
        requests.post(f"https://nosnch.in/{settings.SNITCH_ID}", data={"m": duration})
    else:
        print(f"Snitch: {duration}ms")

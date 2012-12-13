from uuid import uuid4

from django.db import models


class Subscriber(models.Model):
    email = models.EmailField(primary_key=True)
    token = models.CharField(max_length=1024, default=lambda: str(uuid4()))

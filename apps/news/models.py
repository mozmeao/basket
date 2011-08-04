from django.db import models

class Subscriber(models.Model):
    email = models.EmailField()
    token = models.CharField(max_length=1024)

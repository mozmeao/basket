from django.db import models


class Var(models.Model):
    """Persistent app variables."""
    name = models.CharField(max_length=255, primary_key=True)
    value = models.CharField(max_length=255)

from .models import Var


def get(name, default=False):
    try:
        return Var.objects.get(name=name).value
    except Var.DoesNotExist:
        return default

def set(name, value):
    Var(name=name, value=value).save()

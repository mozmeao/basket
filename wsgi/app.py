import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")

from django.core.wsgi import get_wsgi_application

from whitenoise.django import DjangoWhiteNoise

try:
    import newrelic.agent
except ImportError:
    newrelic = False


if newrelic:
    newrelic_ini = os.getenv('NEWRELIC_INI_FILE', False)
    if newrelic_ini:
        newrelic.agent.initialize(newrelic_ini)
    else:
        newrelic = False

application = get_wsgi_application()
application = DjangoWhiteNoise(application)

if newrelic:
    application = newrelic.agent.WSGIApplicationWrapper(application)

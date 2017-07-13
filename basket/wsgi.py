import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "basket.settings")

from django.core.handlers.wsgi import WSGIRequest
from django.core.wsgi import get_wsgi_application

from raven.contrib.django.raven_compat.middleware.wsgi import Sentry
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

IS_HTTPS = os.environ.get('HTTPS', '').strip() == 'on'


class WSGIHTTPSRequest(WSGIRequest):
    def _get_scheme(self):
        if IS_HTTPS:
            return 'https'

        return super(WSGIHTTPSRequest, self)._get_scheme()


application = get_wsgi_application()
application.request_class = WSGIHTTPSRequest
application = DjangoWhiteNoise(application)
application = Sentry(application)

if newrelic:
    application = newrelic.agent.WSGIApplicationWrapper(application)

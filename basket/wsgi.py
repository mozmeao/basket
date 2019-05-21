# flake8: noqa
# newrelic import & initialization must come first
# https://docs.newrelic.com/docs/agents/python-agent/installation/python-agent-advanced-integration#manual-integration
try:
    import newrelic.agent
except ImportError:
    newrelic = False
else:
    newrelic.agent.initialize('newrelic.ini')

import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "basket.settings")

from django.core.handlers.wsgi import WSGIRequest
from django.core.wsgi import get_wsgi_application

from raven.contrib.django.raven_compat.middleware.wsgi import Sentry


IS_HTTPS = os.environ.get('HTTPS', '').strip() == 'on'


class WSGIHTTPSRequest(WSGIRequest):
    def _get_scheme(self):
        if IS_HTTPS:
            return 'https'

        return super(WSGIHTTPSRequest, self)._get_scheme()


application = get_wsgi_application()
application.request_class = WSGIHTTPSRequest
application = Sentry(application)

if newrelic:
    application = newrelic.agent.WSGIApplicationWrapper(application)

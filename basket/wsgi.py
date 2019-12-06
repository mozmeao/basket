# flake8: noqa
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

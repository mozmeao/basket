from django.conf import settings

from django_statsd.clients import statsd
from django_statsd.middleware import GraphiteRequestTimingMiddleware


class GraphiteViewHitCountMiddleware(GraphiteRequestTimingMiddleware):
    """add hit counting to statsd's request timer."""

    def process_view(self, request, view_func, view_args, view_kwargs):
        super(GraphiteViewHitCountMiddleware, self).process_view(
            request, view_func, view_args, view_kwargs)
        if hasattr(request, '_view_name'):
            data = dict(module=request._view_module, name=request._view_name,
                        method=request.method)
            statsd.incr('view.count.{module}.{name}.{method}'.format(**data))
            statsd.incr('view.count.{module}.{method}'.format(**data))
            statsd.incr('view.count.{method}'.format(**data))


class HostnameMiddleware(object):
    def __init__(self):
        values = [getattr(settings, x) for x in ['HOSTNAME', 'DEIS_APP',
                                                 'DEIS_RELEASE', 'DEIS_DOMAIN']]
        self.backend_server = '.'.join(x for x in values if x)

    def process_response(self, request, response):
        response['X-Backend-Server'] = self.backend_server
        return response

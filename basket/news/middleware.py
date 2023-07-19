from django.conf import settings

from django_statsd.clients import statsd
from django_statsd.middleware import GraphiteRequestTimingMiddleware


class GraphiteViewHitCountMiddleware(GraphiteRequestTimingMiddleware):
    """add hit counting to statsd's request timer."""

    def process_view(self, request, view_func, view_args, view_kwargs):
        super(GraphiteViewHitCountMiddleware, self).process_view(
            request,
            view_func,
            view_args,
            view_kwargs,
        )
        if hasattr(request, "_view_name"):
            vmodule = request._view_module
            if vmodule.startswith("basket."):
                vmodule = vmodule[7:]
            data = dict(module=vmodule, name=request._view_name, method=request.method)
            statsd.incr("view.count.{module}.{name}.{method}".format(**data))
            statsd.incr("view.count.{module}.{method}".format(**data))
            statsd.incr("view.count.{method}".format(**data))


class HostnameMiddleware(object):
    def __init__(self, get_response):
        values = [getattr(settings, x) for x in ["CLUSTER_NAME", "K8S_NAMESPACE", "K8S_POD_NAME"]]
        self.backend_server = "/".join(x for x in values if x)
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["X-Backend-Server"] = self.backend_server
        return response

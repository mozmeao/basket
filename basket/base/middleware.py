import contextlib
import inspect
import time

from django.conf import settings
from django.http import Http404
from django.utils.deprecation import MiddlewareMixin

from basket import metrics


class HostnameMiddleware(object):
    def __init__(self, get_response):
        values = [getattr(settings, x) for x in ["CLUSTER_NAME", "K8S_NAMESPACE", "K8S_POD_NAME"]]
        self.backend_server = "/".join(x for x in values if x)
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["X-Backend-Server"] = self.backend_server
        return response


class MetricsStatusMiddleware(MiddlewareMixin):
    """Send status code counts to statsd"""

    def process_response(self, request, response):
        metrics.incr(f"response.{response.status_code}")
        return response

    def process_exception(self, request, exception):
        if not isinstance(exception, Http404):
            metrics.incr("response.500")


class MetricsRequestTimingMiddleware(MiddlewareMixin):
    """Send request timing to statsd"""

    def process_view(self, request, view_func, view_args, view_kwargs):
        if inspect.isfunction(view_func):
            view = view_func
        else:
            view = view.__class__

        with contextlib.suppress(AttributeError):
            request._start_time = time.time()
            request._view_module = view.__module__
            request._view_name = view.__name__

    def _record_timing(self, request):
        if hasattr(request, "_start_time"):
            view_time = int((time.time() - request._start_time) * 1000)
            metrics.timing(f"view.{request._view_module}.{request._view_name}.{request.method}", view_time)
            metrics.timing(f"view.{request._view_module}.{request.method}", view_time)
            metrics.timing(f"view.{request.method}", view_time)

    def process_response(self, request, response):
        self._record_timing(request)
        return response

    def process_exception(self, request, exception):
        self._record_timing(request)

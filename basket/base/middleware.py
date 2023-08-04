import inspect
import time

from django.conf import settings
from django.http import Http404
from django.utils.deprecation import MiddlewareMixin

from basket import metrics


class HostnameMiddleware(MiddlewareMixin):
    """Add header with k8s cluster / pod details for debugging."""

    def process_response(self, request, response):
        response["X-Backend-Server"] = "/".join(filter(None, [getattr(settings, x) for x in ["CLUSTER_NAME", "K8S_NAMESPACE", "K8S_POD_NAME"]]))
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
            view = view_func.__class__

        request._start_time = time.time()
        request._view_module = getattr(view, "__module__", "none")
        request._view_name = getattr(view, "__name__", "none")

    def _record_timing(self, request, status_code):
        if hasattr(request, "_start_time") and hasattr(request, "_view_module") and hasattr(request, "_view_name"):
            view_time = int((time.time() - request._start_time) * 1000)
            metrics.timing(f"view.{request._view_module}.{request._view_name}.{request.method}", view_time, tags=[f"status_code:{status_code}"])
            metrics.timing(f"view.{request._view_module}.{request.method}", view_time, tags=[f"status_code:{status_code}"])
            metrics.timing(f"view.{request.method}", view_time, tags=[f"status_code:{status_code}"])

    def process_response(self, request, response):
        self._record_timing(request, response.status_code)
        return response

    def process_exception(self, request, exception):
        if not isinstance(exception, Http404):
            self._record_timing(request, 500)

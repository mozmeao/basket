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


class MetricsViewTimingMiddleware(MiddlewareMixin):
    """Send request timing to statsd"""

    def process_view(self, request, view_func, view_args, view_kwargs):
        api_name = None

        if inspect.isfunction(view_func):
            view = view_func
        else:
            try:
                # Get the API `url_name` since the API views are class based and they would all come
                # back as `builtins.method` otherwise.
                api_name = view_func.__self__.url_name
            except AttributeError:
                view = view_func.__class__

        request._start_time = time.time()
        if api_name:
            request._view_module = "api"
            request._view_name = api_name
        else:
            request._view_module = getattr(view, "__module__", "none")
            request._view_name = getattr(view, "__name__", "none")

    def _record_timing(self, request, status_code):
        if hasattr(request, "_start_time") and hasattr(request, "_view_module") and hasattr(request, "_view_name"):
            # View times.
            view_time = int((time.time() - request._start_time) * 1000)
            metrics.timing(
                "view.timings",
                view_time,
                tags=[
                    f"view_path:{request._view_module}.{request._view_name}.{request.method}",
                    f"module:{request._view_module}.{request.method}",
                    f"method:{request.method}",
                    f"status_code:{status_code}",
                ],
            )

    def process_response(self, request, response):
        self._record_timing(request, response.status_code)
        return response

    def process_exception(self, request, exception):
        if not isinstance(exception, Http404):
            self._record_timing(request, 500)

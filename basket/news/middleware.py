import re

from django.conf import settings
from django.core.exceptions import MiddlewareNotUsed
from django.http import HttpResponsePermanentRedirect
from django.http.request import split_domain_port

from django_statsd.clients import statsd
from django_statsd.middleware import GraphiteRequestTimingMiddleware
from mozilla_django_oidc.middleware import SessionRefresh


IP_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")


class OIDCSessionRefreshMiddleware(SessionRefresh):
    def is_refreshable_url(self, request):
        # only do OIDC session checking in admin URLs
        if not request.path.startswith("/admin/"):
            return False

        return super().is_refreshable_url(request)


class GraphiteViewHitCountMiddleware(GraphiteRequestTimingMiddleware):
    """add hit counting to statsd's request timer."""

    def process_view(self, request, view_func, view_args, view_kwargs):
        super(GraphiteViewHitCountMiddleware, self).process_view(
            request, view_func, view_args, view_kwargs,
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
        values = [
            getattr(settings, x)
            for x in ["CLUSTER_NAME", "K8S_NAMESPACE", "K8S_POD_NAME"]
        ]
        self.backend_server = "/".join(x for x in values if x)
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["X-Backend-Server"] = self.backend_server
        return response


def is_ip_address(hostname):
    return bool(IP_RE.match(hostname))


class EnforceHostnameMiddleware(object):
    """
    Enforce the hostname per the ENFORCE_HOSTNAME setting in the project's settings

    The ENFORCE_HOSTNAME can either be a single host or a list of acceptable hosts

    via http://www.michaelvdw.nl/code/force-hostname-with-django-middleware-for-heroku/
    """

    def __init__(self, get_response):
        self.allowed_hosts = settings.ENFORCE_HOSTNAME
        self.get_response = get_response
        if settings.DEBUG or not self.allowed_hosts:
            raise MiddlewareNotUsed

    def __call__(self, request):
        """Enforce the host name"""
        host = request.get_host()
        domain, port = split_domain_port(host)
        if domain in self.allowed_hosts or is_ip_address(domain):
            return self.get_response(request)

        # redirect to the proper host name\
        new_url = "%s://%s%s" % (
            "https" if request.is_secure() else "http",
            self.allowed_hosts[0],
            request.get_full_path(),
        )

        return HttpResponsePermanentRedirect(new_url)

from django.conf import settings
from django.core.exceptions import MiddlewareNotUsed
from django.http import HttpResponsePermanentRedirect

from django_statsd.clients import statsd
from django_statsd.middleware import GraphiteRequestTimingMiddleware


class GraphiteViewHitCountMiddleware(GraphiteRequestTimingMiddleware):
    """add hit counting to statsd's request timer."""

    def process_view(self, request, view_func, view_args, view_kwargs):
        super(GraphiteViewHitCountMiddleware, self).process_view(
            request, view_func, view_args, view_kwargs)
        if hasattr(request, '_view_name'):
            vmodule = request._view_module
            if vmodule.startswith('basket.'):
                vmodule = vmodule[7:]
            data = dict(module=vmodule,
                        name=request._view_name,
                        method=request.method)
            statsd.incr('view.count.{module}.{name}.{method}'.format(**data))
            statsd.incr('view.count.{module}.{method}'.format(**data))
            statsd.incr('view.count.{method}'.format(**data))


class HostnameMiddleware(object):
    def __init__(self, get_response):
        values = [getattr(settings, x) for x in ['HOSTNAME', 'DEIS_APP',
                                                 'DEIS_RELEASE', 'DEIS_DOMAIN']]
        self.backend_server = '.'.join(x for x in values if x)
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response['X-Backend-Server'] = self.backend_server
        return response


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
        if host in self.allowed_hosts:
            return self.get_response(request)

        # redirect to the proper host name\
        new_url = "%s://%s%s" % (
            'https' if request.is_secure() else 'http',
            self.allowed_hosts[0], request.get_full_path())

        return HttpResponsePermanentRedirect(new_url)

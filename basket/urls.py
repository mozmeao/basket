from django.conf import settings
from django.conf.urls import include, url
from django.contrib import admin
from django.views.generic import RedirectView

from watchman import views as watchman_views

from basket.news.views import subscribe_main, subscribe_json


home_redirect = '/admin/' if settings.ADMIN_ONLY_MODE else 'https://www.mozilla.org/'

urlpatterns = [
    url(r'^$', RedirectView.as_view(url=home_redirect, permanent=True)),
    url(r'^watchman/$', watchman_views.dashboard, name="watchman.dashboard"),
    url(r'^healthz/$', watchman_views.ping, name="watchman.ping"),
    url(r'^readiness/$', watchman_views.status, name="watchman.status"),
]

if not settings.ADMIN_ONLY_MODE:
    urlpatterns.append(url(r'^news/', include('basket.news.urls')))
    urlpatterns.append(url(r'^subscribe/?$', subscribe_main))
    urlpatterns.append(url(r'^subscribe\.json$', subscribe_json))

if settings.DISABLE_ADMIN:
    urlpatterns.append(
        url(r'^admin/', RedirectView.as_view(url=settings.ADMIN_REDIRECT_URL, permanent=True))
    )
else:
    if settings.OIDC_ENABLE:
        urlpatterns.append(url(r'^oidc/', include('mozilla_django_oidc.urls')))

    admin.autodiscover()
    urlpatterns.extend([
        url(r'^admin/doc/', include('django.contrib.admindocs.urls')),
        url(r'^admin/', include(admin.site.urls)),
    ])

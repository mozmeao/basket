from django.conf import settings
from django.urls import include, path
from django.contrib import admin
from django.views.generic import RedirectView, TemplateView

from watchman import views as watchman_views

from basket.news.views import subscribe_main, subscribe_json, fxa_start, fxa_callback, subhub_post


urlpatterns = [
    path('', TemplateView.as_view(template_name='home.html')),
    path('watchman/', watchman_views.dashboard, name="watchman.dashboard"),
    path('healthz/', watchman_views.ping, name="watchman.ping"),
    path('readiness/', watchman_views.status, name="watchman.status"),
]

if not settings.ADMIN_ONLY_MODE:
    urlpatterns.extend([
        path('news/', include('basket.news.urls')),
        path('subscribe/', subscribe_main),
        path('subscribe.json', subscribe_json),
        path('fxa/', fxa_start),
        path('fxa/callback/', fxa_callback),
        path('subhub/', subhub_post),
    ])

if settings.DISABLE_ADMIN:
    urlpatterns.append(
        path('admin/', RedirectView.as_view(url=settings.ADMIN_REDIRECT_URL, permanent=True))
    )
else:
    if settings.OIDC_ENABLE:
        urlpatterns.append(path('oidc/', include('mozilla_django_oidc.urls')))

    admin.autodiscover()
    urlpatterns.extend([
        path('admin/doc/', include('django.contrib.admindocs.urls')),
        path('admin/', admin.site.urls),
    ])

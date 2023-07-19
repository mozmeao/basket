from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from watchman import views as watchman_views

from basket.news.views import fxa_callback, fxa_start, subscribe_json, subscribe_main

# NOTE: When adding any new URLs be sure to update `settings.OIDC_EXEMPT_URLS` if needed.

urlpatterns = [
    path("", TemplateView.as_view(template_name="home.html")),
    path("watchman/", watchman_views.dashboard, name="watchman.dashboard"),
    path("healthz/", watchman_views.ping, name="watchman.ping"),
    path("readiness/", watchman_views.status, name="watchman.status"),
    path("news/", include("basket.news.urls")),
    path("subscribe/", subscribe_main),
    path("subscribe.json", subscribe_json),
    path("fxa/", fxa_start),
    path("fxa/callback/", fxa_callback),
]

if settings.OIDC_ENABLE:
    urlpatterns.append(path("oidc/", include("mozilla_django_oidc.urls")))

admin.autodiscover()
urlpatterns.extend(
    [
        path("admin/doc/", include("django.contrib.admindocs.urls")),
        path("admin/", admin.site.urls),
    ],
)

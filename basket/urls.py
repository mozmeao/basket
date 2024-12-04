import json

from django.conf import settings
from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path
from django.views.generic import TemplateView

from ninja import NinjaAPI
from ninja.errors import ValidationError
from watchman import views as watchman_views

from basket import errors
from basket.news.views import fxa_callback, fxa_start

# NOTE: When adding any new URLs be sure to update `settings.OIDC_EXEMPT_URLS` if needed.

api = NinjaAPI(
    docs_url="/api/docs",
    title="Basket API",
    urls_namespace="api.v1",
    version="v1",
)
api.add_router("api/v1/news/", "basket.news.api.news_router")
api.add_router("api/v1/users/", "basket.news.api.user_router")

urlpatterns = [
    path("", TemplateView.as_view(template_name="home.html")),
    path("watchman/", watchman_views.dashboard, name="watchman.dashboard"),
    path("healthz/", watchman_views.ping, name="watchman.ping"),
    path("readiness/", watchman_views.status, name="watchman.status"),
    path("", api.urls),
    path("news/", include("basket.news.urls")),
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

if settings.UNITTEST:
    # Added to help test the 500 statsd metrics in unit tests.
    from django.views import defaults

    urlpatterns.extend(
        [
            path("500/", defaults.server_error),
        ]
    )


# So django-ninja returns a pydantic validation error in a consistent JSON shape.
@api.exception_handler(ValidationError)
def validation_errors(request, exc):
    error = exc.errors[0]
    return HttpResponse(
        json.dumps(
            {
                "status": "error",
                "desc": error.get("msg"),
                "code": errors.BASKET_USAGE_ERROR,
            }
        ),
        status=422,
        content_type="application/json",
    )

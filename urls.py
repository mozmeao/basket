from django.conf import settings
from django.conf.urls import include, url
from django.contrib import admin
from django.views.generic import RedirectView


home_redirect = '/admin/' if settings.ADMIN_ONLY_MODE else 'https://www.mozilla.org/'

urlpatterns = [
    url(r'^$', RedirectView.as_view(url=home_redirect))
]

if not settings.ADMIN_ONLY_MODE:
    urlpatterns.append(url(r'^news/', include('news.urls')))

if settings.DISABLE_ADMIN:
    urlpatterns.append(
        url(r'^admin/', RedirectView.as_view(url=settings.ADMIN_REDIRECT_URL))
    )
else:
    if settings.SAML_ENABLE:
        urlpatterns += (
            url(r'^saml2/', include('saml.urls')),
            )

    admin.autodiscover()
    urlpatterns.extend([
        url(r'^admin/doc/', include('django.contrib.admindocs.urls')),
        url(r'^admin/', include(admin.site.urls)),
    ])

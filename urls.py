from django.conf import settings
from django.conf.urls import include, url
from django.contrib import admin


urlpatterns = (
    url(r'^news/', include('news.urls')),
)

if not settings.DISABLE_ADMIN:
    admin.autodiscover()
    urlpatterns += (
        url(r'^admin/doc/', include('django.contrib.admindocs.urls')),
        url(r'^admin/', include(admin.site.urls)),
    )

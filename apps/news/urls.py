from django.conf.urls.defaults import *
from views import subscribe

urlpatterns = patterns('',
    url('^subscribe/$', subscribe),
)

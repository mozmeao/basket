from django.conf.urls.defaults import *
import views

urlpatterns = patterns('',
    url('^unsub$', views.unsub, name='nagios.unsub'),
    url('^$', views.index, name='nagios.index'),
)

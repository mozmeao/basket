from django.conf.urls.defaults import *
import views

urlpatterns = patterns('',
    url('^$', views.index, name='nagios.index'),
)

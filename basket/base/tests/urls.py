# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.http import Http404, HttpResponse
from django.urls import path


def returns_200(request):
    return HttpResponse("test")


def returns_404(request):
    return HttpResponse("404", status=404)


def raises_404(request):
    raise Http404


def returns_500(request):
    return HttpResponse("500", status=500)


urlpatterns = [
    path("returns_200/", returns_200, name="returns_200"),
    path("raises_404/", raises_404, name="raises_404"),
    path("returns_404/", returns_404, name="returns_404"),
    path("returns_500/", returns_500, name="returns_500"),
]

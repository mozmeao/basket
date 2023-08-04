from django.test import Client
from django.test.utils import override_settings
from django.urls import reverse


class TestHostnameMiddleware:
    @override_settings(CLUSTER_NAME="us-west", K8S_NAMESPACE="prod", K8S_POD_NAME="pod1")
    def test_header(self):
        resp = Client().get(reverse("watchman.ping"))
        assert resp.headers.get("X-Backend-Server") == "us-west/prod/pod1"

    @override_settings(CLUSTER_NAME="us-west", K8S_NAMESPACE="prod", K8S_POD_NAME=None)
    def test_header_missing_settings(self):
        resp = Client().get(reverse("watchman.ping"))
        assert resp.headers.get("X-Backend-Server") == "us-west/prod"


class TestMetricsMiddleware:
    def test_200(self, metrics_mock):
        resp = Client().get(reverse("watchman.ping"))
        assert resp.status_code == 200
        metrics_mock.assert_incr_once("response.200")
        metrics_mock.assert_timing_once("view.watchman.views.ping.GET", tags=["status_code:200"])
        metrics_mock.assert_timing_once("view.watchman.views.GET", tags=["status_code:200"])
        metrics_mock.assert_timing_once("view.GET", tags=["status_code:200"])
        metrics_mock.assert_incr_once("view.count.watchman.views.ping.GET")
        metrics_mock.assert_incr_once("view.count.watchman.views.GET")
        metrics_mock.assert_incr_once("view.count.GET")

    def test_404(self, metrics_mock):
        resp = Client().get("/404/")
        assert resp.status_code == 404
        metrics_mock.assert_incr_once("response.404")
        # We don't time 404 responses.
        assert not metrics_mock.filter_records("timing")

    def test_500(self, metrics_mock):
        resp = Client().get("/500/")
        assert resp.status_code == 500
        metrics_mock.assert_incr_once("response.500")
        metrics_mock.assert_timing_once("view.django.views.defaults.server_error.GET", tags=["status_code:500"])
        metrics_mock.assert_timing_once("view.django.views.defaults.GET", tags=["status_code:500"])
        metrics_mock.assert_timing_once("view.GET", tags=["status_code:500"])
        metrics_mock.assert_incr_once("view.count.django.views.defaults.server_error.GET")
        metrics_mock.assert_incr_once("view.count.django.views.defaults.GET")
        metrics_mock.assert_incr_once("view.count.GET")

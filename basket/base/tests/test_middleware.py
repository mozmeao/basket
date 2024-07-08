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
    def test_200(self, metricsmock):
        resp = Client().get(reverse("watchman.ping"))
        assert resp.status_code == 200
        metricsmock.assert_timing_once(
            "view.timings", tags=["view_path:watchman.views.ping.GET", "module:watchman.views.GET", "method:GET", "status_code:200"]
        )

    def test_404(self, metricsmock):
        resp = Client().get("/404/")
        assert resp.status_code == 404
        # We don't time 404 responses.
        assert not metricsmock.filter_records("timing")

    def test_500(self, metricsmock):
        resp = Client().get("/500/")
        assert resp.status_code == 500
        metricsmock.assert_timing_once(
            "view.timings",
            tags=["view_path:django.views.defaults.server_error.GET", "module:django.views.defaults.GET", "method:GET", "status_code:500"],
        )

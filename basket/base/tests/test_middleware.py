from django.test import Client
from django.test.utils import override_settings
from django.urls import reverse

import pytest


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
    @pytest.mark.urls("basket.base.tests.urls")
    def test_200(self, metrics_mock):
        resp = Client().get("/returns_200/")
        assert resp.status_code == 200
        metrics_mock.assert_timing_once(
            "view.timings",
            tags=["view_path:basket.base.tests.urls.returns_200.GET", "module:basket.base.tests.urls.GET", "method:GET", "status_code:200"],
        )

    @pytest.mark.urls("basket.base.tests.urls")
    def test_404(self, metrics_mock):
        resp = Client().get("/raises_404/")
        assert resp.status_code == 404
        metrics_mock.assert_timing_once(
            "view.timings",
            tags=["view_path:basket.base.tests.urls.raises_404.GET", "module:basket.base.tests.urls.GET", "method:GET", "status_code:404"],
        )

    @pytest.mark.urls("basket.base.tests.urls")
    def test_500(self, metrics_mock):
        resp = Client().get("/returns_500/")
        assert resp.status_code == 500
        metrics_mock.assert_timing_once(
            "view.timings",
            tags=["view_path:basket.base.tests.urls.returns_500.GET", "module:basket.base.tests.urls.GET", "method:GET", "status_code:500"],
        )

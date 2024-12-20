from unittest.mock import patch

from django.core.cache import cache
from django.test import Client
from django.urls import reverse

import pytest

from basket.news import models
from basket.news.schemas import NewslettersSchema


@pytest.mark.django_db
class TestNewslettersAPI:
    def setup_method(self, method):
        # These tests don't need the CTMS tests found in the `_TestAPIBase`,
        # so we just set up a standard Django test client.
        self.client = Client()
        self.url = reverse("api.v1:news.newsletters")
        self.n1 = self._add_newsletter("test-1", show=True, order=1)
        self.n2 = self._add_newsletter("test-2", order=2)
        cache.clear()

    def teardown_method(self, method):
        cache.clear()

    def valid_request(self):
        return self.client.get(self.url)

    def _add_newsletter(self, slug, **kwargs):
        return models.Newsletter.objects.create(
            slug=slug,
            title=slug,
            languages="en",
            **kwargs,
        )

    def test_preflight(self):
        resp = self.client.options(
            self.url,
            content_type="application/json",
            HTTP_ORIGIN="https://example.com",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
        )
        assert resp.status_code == 200
        assert resp["Access-Control-Allow-Origin"] == "*"
        assert "GET" in resp["Access-Control-Allow-Methods"]
        assert "content-type" in resp["Access-Control-Allow-Headers"]

    def test_newsletters(self):
        resp = self.client.get(self.url)
        data = resp.json()
        assert resp.status_code == 200
        assert data["status"] == "ok"
        NewslettersSchema.model_validate(data)
        newsletters = data["newsletters"]
        assert len(newsletters) == 2
        n1_data = newsletters[self.n1.slug]
        assert n1_data["slug"] == self.n1.slug
        assert n1_data["title"] == "test-1"
        assert n1_data["languages"] == ["en"]
        assert n1_data["order"] == 1
        # Defaults
        assert n1_data["show"] is True
        assert n1_data["active"] is True
        assert n1_data["private"] is False
        assert n1_data["indent"] is False
        assert n1_data["requires_double_optin"] is False
        assert n1_data["firefox_confirm"] is False
        assert n1_data["is_mofo"] is False
        assert n1_data["is_waitlist"] is False

    def test_newsletters_caches_when_called(self):
        with patch("django.core.cache.cache.set") as mock_cache_set:
            resp = self.client.get(self.url)
            assert resp.status_code == 200
            mock_cache_set.assert_called()

    def test_newsletters_returns_cached_content(self):
        resp1 = self.client.get(self.url)
        with patch("basket.news.api.list_newsletters") as mock_view:
            resp2 = self.client.get(self.url)
            assert resp1.json() == resp2.json()
            mock_view.assert_not_called()

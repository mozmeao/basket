from unittest.mock import patch

from django.core.cache import cache
from django.urls import reverse

import pytest

from basket.news import models
from basket.news.schemas import NewslettersSchema


@pytest.mark.django_db
class TestNewslettersAPI:
    def setup_method(self, method):
        self.url = reverse("api.v1:news.newsletters")
        self.n1 = self._add_newsletter("test-1", show=True, order=1)
        self.n2 = self._add_newsletter("test-2", order=2)

    def teardown_method(self, method):
        cache.clear()

    def _add_newsletter(self, slug, **kwargs):
        return models.Newsletter.objects.create(
            slug=slug,
            title=slug,
            languages="en",
            **kwargs,
        )

    def test_newsletters(self, client):
        resp = client.get(self.url)
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

    def test_newsletters_caches_when_called(self, client):
        with patch("django.core.cache.cache.set") as mock_cache_set:
            resp = client.get(self.url)
            assert resp.status_code == 200
            mock_cache_set.assert_called()

    def test_newsletters_returns_cached_content(self, client):
        resp1 = client.get(self.url)
        with patch("basket.news.api.list_newsletters") as mock_view:
            resp2 = client.get(self.url)
            assert resp1.json() == resp2.json()
            mock_view.assert_not_called()

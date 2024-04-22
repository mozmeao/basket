from unittest import mock

from django.utils import timezone

import pytest
import requests_mock
from freezegun import freeze_time

from basket.news.backends import braze


@pytest.fixture
def braze_client():
    return braze.BrazeClient("http://test.com", "test_api_key")


def test_braze_client_no_api_key():
    with pytest.warns(UserWarning, match="Braze API key is not configured"):
        braze_client = braze.BrazeClient("http://test.com", "")
    assert braze_client.active is False
    assert braze_client.track_user("test@test.com") is None


def test_braze_client_no_base_url():
    with pytest.raises(ValueError):
        braze.BrazeClient("", "test_api_key")


def test_braze_client_invalid_base_url():
    with pytest.raises(ValueError):
        braze.BrazeClient("test.com", "test_api_key")


def test_braze_client_headers(braze_client):
    with requests_mock.mock() as m:
        m.register_uri("POST", "http://test.com/users/track", json={})
        braze_client.track_user("test@test.com")
        assert m.last_request.headers["Content-Type"] == "application/json"
        assert m.last_request.headers["Authorization"] == "Bearer test_api_key"


def test_braze_track_user(braze_client):
    email = "test@test.com"
    expected = {
        "attributes": [
            {
                "_update_existing_only": False,
                "user_alias": {"alias_name": email, "alias_label": "email"},
                "email": email,
            }
        ],
    }
    with requests_mock.mock() as m:
        m.register_uri("POST", "http://test.com/users/track", json={})
        braze_client.track_user(email)
        assert m.last_request.json() == expected


def test_braze_track_user_with_event(braze_client):
    dt = timezone.now()
    email = "test@test.com"
    expected = {
        "attributes": [
            {
                "_update_existing_only": False,
                "user_alias": {"alias_name": email, "alias_label": "email"},
                "email": email,
            },
        ],
        "events": [
            {
                "user_alias": {"alias_name": email, "alias_label": "email"},
                "name": "test_event",
                "time": dt.isoformat(),
            }
        ],
    }
    with requests_mock.mock() as m:
        m.register_uri("POST", "http://test.com/users/track", json={})
        with freeze_time(dt):
            braze_client.track_user(email, "test_event")
        assert m.last_request.json() == expected


def test_braze_track_user_with_event_and_token(braze_client):
    dt = timezone.now()
    email = "test@test.com"
    expected = {
        "attributes": [
            {
                "_update_existing_only": False,
                "user_alias": {"alias_name": email, "alias_label": "email"},
                "email": email,
                "basket_token": "abc123",
            },
        ],
        "events": [
            {
                "user_alias": {"alias_name": email, "alias_label": "email"},
                "name": "test_event",
                "time": dt.isoformat(),
            }
        ],
    }
    with requests_mock.mock() as m:
        m.register_uri("POST", "http://test.com/users/track", json={})
        with freeze_time(dt):
            braze_client.track_user(email, "test_event", user_data={"basket_token": "abc123"})
        assert m.last_request.json() == expected


def test_braze_track_user_with_event_and_token_and_email_id(braze_client):
    dt = timezone.now()
    email = "test@test.com"
    email_id = "fed654"
    expected = {
        "attributes": [
            {
                "external_id": "fed654",
                "email": email,
                "basket_token": "abc123",
            },
        ],
        "events": [
            {
                "external_id": "fed654",
                "name": "test_event",
                "time": dt.isoformat(),
            }
        ],
    }
    with requests_mock.mock() as m:
        m.register_uri("POST", "http://test.com/users/track", json={})
        with freeze_time(dt):
            braze_client.track_user(email, "test_event", user_data={"basket_token": "abc123", "email_id": email_id})
        assert m.last_request.json() == expected


def test_braze_export_users(braze_client):
    email = "test@test.com"
    expected = {
        "user_aliases": [{"alias_name": email, "alias_label": "email"}],
        "email_address": email,
    }
    with requests_mock.mock() as m:
        m.register_uri("POST", "http://test.com/users/export/ids", json={})
        braze_client.export_users(email)
        assert m.last_request.json() == expected


def test_braze_send_campaign(braze_client):
    email = "test@test.com"
    campaign_id = "test_campaign_id"
    expected = {
        "campaign_id": campaign_id,
        "broadcast": False,
        "recipients": [
            {
                "user_alias": {
                    "alias_label": "email",
                    "alias_name": email,
                }
            },
        ],
    }
    with requests_mock.mock() as m:
        m.register_uri("POST", "http://test.com/campaigns/trigger/send", json={})
        braze_client.send_campaign(email, campaign_id)
        assert m.last_request.json() == expected


def test_braze_exception_400(braze_client):
    with requests_mock.mock() as m:
        m.register_uri("POST", "http://test.com/users/track", status_code=400, json={})
        with pytest.raises(braze.BrazeBadRequestError):
            braze_client.track_user("test@test.com")


def test_braze_exception_401(braze_client):
    with requests_mock.mock() as m:
        m.register_uri("POST", "http://test.com/users/track", status_code=401, json={})
        with pytest.raises(braze.BrazeUnauthorizedError):
            braze_client.track_user("test@test.com")


def test_braze_exception_403(braze_client):
    with requests_mock.mock() as m:
        m.register_uri("POST", "http://test.com/users/track", status_code=403, json={})
        with pytest.raises(braze.BrazeForbiddenError):
            braze_client.track_user("test@test.com")


def test_braze_exception_404(braze_client):
    mock.patch("basket.news.backends.braze.BrazeEndpoint.USERS_TRACK", "/does/not/exist")
    with requests_mock.mock() as m:
        m.register_uri("POST", "http://test.com/users/track", status_code=404, json={})
        with pytest.raises(braze.BrazeNotFoundError):
            braze_client.track_user("test@test.com")


def test_braze_exception_429(braze_client):
    with requests_mock.mock() as m:
        m.register_uri("POST", "http://test.com/users/track", status_code=429, json={})
        with pytest.raises(braze.BrazeRateLimitError):
            braze_client.track_user("test@test.com")


def test_braze_exception_418(braze_client):
    # We aren't catching 418 teapot errors, so this should raise a generic BrazeClientError.
    with requests_mock.mock() as m:
        m.register_uri("POST", "http://test.com/users/track", status_code=418, json={})
        with pytest.raises(braze.BrazeClientError):
            braze_client.track_user("test@test.com")


def test_braze_exception_500(braze_client):
    with requests_mock.mock() as m:
        m.register_uri("POST", "http://test.com/users/track", status_code=500, json={})
        with pytest.raises(braze.BrazeInternalServerError):
            braze_client.track_user("test@test.com")

import json
import warnings
from enum import Enum
from urllib.parse import urljoin, urlparse, urlunparse

from django.conf import settings

import requests


# Braze errors: https://www.braze.com/docs/api/errors/
class BrazeBadRequestError(Exception):
    pass  # 400 error (invalid request)


class BrazeUnauthorizedError(Exception):
    pass  # 401 error (invalid API key)


class BrazeForbiddenError(Exception):
    pass  # 403 error (invalid permissions)


class BrazeNotFoundError(Exception):
    pass  # 404 error (invalid endpoint)


class BrazeRateLimitError(Exception):
    pass  # 429 error (rate limit exceeded)


class BrazeInternalServerError(Exception):
    pass  # 500 error (Braze server error)


class BrazeClientError(Exception):
    pass  # any other error


class BrazeEndpoint(Enum):
    CAMPAIGNS_TRIGGER_SEND = "/campaigns/trigger/send"
    USERS_EXPORT_IDS = "/users/export/ids"
    USERS_TRACK = "/users/track"


class BrazeClient:
    def __init__(self, base_url, api_key):
        urlbits = urlparse(base_url)
        if not urlbits.scheme or not urlbits.netloc:
            raise ValueError("Invalid base_url")
        self.api_url = urlunparse((urlbits.scheme, urlbits.netloc, "", "", "", ""))

        self.api_key = api_key
        if not self.api_key:
            warnings.warn("Braze API key is not configured", stacklevel=2)

        self.active = bool(self.api_key)

    def _request(self, endpoint, data=None):
        """
        Make a request to the Braze API.

        @param endpoint: The Braze endpoint to call, from the BrazeEndpoint enum.
        @param data: The data to send to the endpoint, as a dict.
        @return: The response from the Braze API, as a dict.
        @raises: BrazeBadRequestError: 400 error (invalid request)
        @raises: BrazeUnauthorizedError: 401 error (invalid API key)
        @raises: BrazeForbiddenError: 403 error (invalid permissions)
        @raises: BrazeNotFoundError: 404 error (invalid endpoint)
        @raises: BrazeRateLimitError: 429 error (rate limit exceeded)
        @raises: BrazeInternalServerError: 500 error (Braze server error)
        @raises: BrazeClientError: any other error

        """
        if not self.active:
            return

        url = urljoin(self.api_url, endpoint.value)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(data))
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code

            if status_code == 400:
                raise BrazeBadRequestError from exc

            if status_code == 401:
                raise BrazeUnauthorizedError from exc

            if status_code == 403:
                raise BrazeForbiddenError from exc

            if status_code == 404:
                raise BrazeNotFoundError from exc

            if status_code == 429:
                raise BrazeRateLimitError from exc

            if status_code >= 500 and status_code <= 599:
                raise BrazeInternalServerError from exc

            raise BrazeClientError from exc

    def track_user(self, email):
        """
        Track a user in Braze.

        In this case, we are creating an alias-only user to send a transactional-like email.

        You can use the /users/track endpoint to create a new alias-only user by setting the
        _update_existing_only key with a value of false in the body of the request.

        https://www.braze.com/docs/api/endpoints/user_data/post_user_track/

        Note: `email_subscribed` values are:
          - “opted_in” - explicitly registered to receive email messages
          - “unsubscribed” - explicitly opted out of email messages
          - “subscribed” - neither opted in nor out

        """
        data = {
            "attributes": [
                {
                    "_update_existing_only": False,
                    "user_alias": {"alias_name": email, "alias_label": "email"},
                    "email": email,
                    "email_subscribe": "subscribed",
                }
            ],
        }

        return self._request(BrazeEndpoint.USERS_TRACK, data)

    def export_users(self, email):
        """
        Export user profile by identifier.

        https://www.braze.com/docs/api/endpoints/export/user_data/post_users_identifier/

        If alias is not found, returns empty "users" list.

        """
        data = {
            "user_aliases": [{"alias_name": email, "alias_label": "email"}],
            "email_address": email,
        }

        return self._request(BrazeEndpoint.USERS_EXPORT_IDS, data)

    def send_campaign(self, email, campaign_id):
        """
        Send campaign messages via API-triggered delivery.

        https://www.braze.com/docs/api/endpoints/messaging/send_messages/post_send_triggered_campaigns/

        """
        data = {
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

        return self._request(BrazeEndpoint.CAMPAIGNS_TRIGGER_SEND, data)


braze = BrazeClient(settings.BRAZE_BASE_API_URL, settings.BRAZE_API_KEY)

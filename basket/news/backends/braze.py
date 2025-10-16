import json
import warnings
from enum import Enum
from urllib.parse import urljoin, urlparse, urlunparse

from django.conf import settings
from django.utils import timezone

import requests

from basket.news.newsletters import vendor_id_to_slug


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
    USERS_DELETE = "/users/delete"


class BrazeInterface:
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
            if settings.DEBUG:
                print(f"POST {url}")  # noqa: T201
                print(f"Headers: {headers}")  # noqa: T201
                print(json.dumps(data, indent=2))  # noqa: T201
            response = requests.post(url, headers=headers, data=json.dumps(data))
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code
            message = exc.response.text

            if status_code == 400:
                raise BrazeBadRequestError(message) from exc

            if status_code == 401:
                raise BrazeUnauthorizedError(message) from exc

            if status_code == 403:
                raise BrazeForbiddenError(message) from exc

            if status_code == 404:
                raise BrazeNotFoundError(message) from exc

            if status_code == 429:
                raise BrazeRateLimitError(message) from exc

            if status_code >= 500 and status_code <= 599:
                raise BrazeInternalServerError(message) from exc

            raise BrazeClientError(message) from exc

    def track_user(self, email, event=None, user_data=None):
        """
        Track a user in Braze.

        In this case, we are creating an alias-only user to send a transactional-like email.

        You can use the /users/track endpoint to create a new alias-only user by setting the
        _update_existing_only key with a value of false in the body of the request.

        https://www.braze.com/docs/api/endpoints/user_data/post_user_track/

        """
        email_id = user_data and user_data.pop("email_id", None)
        basket_token = user_data and user_data.pop("basket_token", None)

        if email_id:
            # If we have an `email_id`, we can submit this without a user alias.
            attributes = {
                "email": email,
                "external_id": email_id,
                "basket_token": basket_token,
            }
        else:
            # If we don't have an `email_id`, we need to submit the user alias.
            attributes = {
                "email": email,
                "_update_existing_only": False,
                "user_alias": {"alias_name": email, "alias_label": "email"},
            }
            if basket_token:
                attributes["basket_token"] = basket_token

        data = {
            "attributes": [attributes],
        }
        # Events. Event names are based off of the message ID and trigger email sends in Braze.
        if event:
            events = {
                "name": event,
                "time": timezone.now().isoformat(),
            }
            if email_id:
                events["external_id"] = email_id
            else:
                events["user_alias"] = {"alias_name": email, "alias_label": "email"}
            data["events"] = [events]

        return self._request(BrazeEndpoint.USERS_TRACK, data)

    def export_users(self, email, fields_to_export=None):
        """
        Export user profile by identifier.

        https://www.braze.com/docs/api/endpoints/export/user_data/post_users_identifier/

        If alias is not found, returns empty "users" list.

        """
        data = {
            "user_aliases": [{"alias_name": email, "alias_label": "email"}],
            "email_address": email,
        }

        if fields_to_export:
            data["fields_to_export"] = fields_to_export

        return self._request(BrazeEndpoint.USERS_EXPORT_IDS, data)

    def delete_users(self, braze_ids):
        """
        Delete user profile by braze ids.

        https://www.braze.com/docs/api/endpoints/user_data/post_user_delete/

        """

        data = {"braze_ids": braze_ids}

        return self._request(BrazeEndpoint.USERS_DELETE, data)

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


class Braze:
    """Basket interface to Braze"""

    def __init__(self, interface):
        self.interface = interface

    def get(
        self,
        email_id=None,
        token=None,
        email=None,
        fxa_id=None,
    ):
        raise NotImplementedError

    def add(self, data):
        raise NotImplementedError

    def update(self, existing_data, update_data):
        raise NotImplementedError

    def update_by_fxa_id(self, fxa_id, update_data):
        raise NotImplementedError

    def update_by_token(self, token, update_data):
        raise NotImplementedError

    def delete(self, email):
        raise NotImplementedError

    def from_vendor(self, braze_user_data, subscription_groups):
        """
        Converts Braze-formatted data to Basket-formatted data
        """
        custom_attributes = braze_user_data.get("custom_attributes", {})

        user_attributes = custom_attributes.get("user_attributes_v1", [{}])[0]
        newsletters_v1 = custom_attributes.get("newsletters_v1", [])
        waitlists_v1 = custom_attributes.get("waitlists_v1", [])

        braze_subscription_ids = [
            subscription["subscription_group_id"] for subscription in subscription_groups if subscription["subscription_status"] == "subscribed"
        ]
        newsletters = [vendor_id_to_slug(vendor_id) for vendor_id in braze_subscription_ids]

        basket_user_data = {
            "email": braze_user_data["email"],
            "email_id": braze_user_data["external_id"],
            "id": braze_user_data["braze_id"],
            "first_name": braze_user_data.get("first_name"),
            "last_name": braze_user_data.get("last_name"),
            "country": braze_user_data.get("country") or user_attributes.get("mailing_country"),
            "lang": braze_user_data.get("language") or user_attributes.get("email_lang", "en"),
            "newsletters": newsletters,
            "newsletters_v1": newsletters_v1,  # We need to record newsletters_v1 here so we can continue to update it in Braze after CTMS is removed
            "created_date": user_attributes.get("created_at"),
            "last_modified_date": user_attributes.get("updated_at"),
            "optin": braze_user_data.get("email_subscribe") == "opted_in",
            "optout": braze_user_data.get("email_subscribe") == "unsubscribed",
            "token": user_attributes.get("basket_token") or braze_user_data["external_id"],
            # missing fxa fields: fxa_deleted, fxa_id, fxa_lang, fxa_primary_email, fxa_service
        }

        if user_attributes.get(["has_fxa"]) == "true" and user_attributes.get(["fxa_created_at"]):
            basket_user_data["fxa_create_date"] = user_attributes["fxa_created_at"]

        if waitlists_v1:
            for waitlist in waitlists_v1:
                # Legacy waitlist format. For backward compatibility.
                # This logic was ported over from the CTMS from_vendor method.
                name = waitlist.get(["waitlist_name"])
                if name == "guardian-vpn-waitlist":
                    basket_user_data["fpn_country"] = waitlist.get(["waitlist_geo"])
                    basket_user_data["fpn_platform"] = waitlist.get["waitlist_platform"]
                if name.startswith("relay") and name.endswith("-waitlist"):
                    basket_user_data["relay_country"] = waitlist.get(["waitlist_geo"])

        return basket_user_data

    def to_vendor(self):
        raise NotImplementedError


braze = Braze(BrazeInterface(settings.BRAZE_BASE_API_URL, settings.BRAZE_API_KEY))

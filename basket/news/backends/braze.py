import json
import logging
import warnings
from datetime import timedelta
from enum import Enum
from urllib.parse import urljoin, urlparse, urlunparse

from django.conf import settings
from django.utils import timezone

import requests

from basket.base.decorators import rq_task
from basket.base.utils import is_valid_uuid
from basket.news.backends.ctms import ctms, process_country, process_lang
from basket.news.newsletters import slug_to_vendor_id, vendor_id_to_slug

log = logging.getLogger(__name__)

# We need to wait 5 minutes after creating a user to rename its external_id or add
# an alias.
# See: https://www.braze.com/docs/api/api_limits/#optimal-delay-between-endpoints
BRAZE_OPTIMAL_DELAY = timedelta(minutes=5)


# These tasks cannot be placed in basket/news/tasks.py because it would
# create a circular dependency.
@rq_task
def migrate_external_id_task(current_external_id, new_external_id):
    braze.interface.migrate_external_id(
        [
            {
                "current_external_id": current_external_id,
                "new_external_id": new_external_id,
            }
        ]
    )


@rq_task
def add_fxa_id_alias_task(external_id, fxa_id):
    braze.interface.add_fxa_id_alias(external_id, fxa_id)


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


class BrazeUserNotFoundByEmailError(Exception):
    pass


class BrazeUserNotFoundByFxaIdError(Exception):
    pass


class BrazeUserNotFoundByTokenError(Exception):
    pass


class BrazeClientError(Exception):
    pass  # any other error


class BrazeEndpoint(Enum):
    CAMPAIGNS_TRIGGER_SEND = "/campaigns/trigger/send"
    USERS_EXPORT_IDS = "/users/export/ids"
    USERS_TRACK = "/users/track"
    USERS_DELETE = "/users/delete"
    SUBSCRIPTION_USER_STATUS = "/subscription/user/status"
    USERS_MIGRATE_EXTERNAL_ID = "/users/external_ids/rename"
    USERS_ADD_ALIAS = "/users/alias/new"


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

    def _request(self, endpoint, data=None, method="POST", params=None):
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
                print(f"{method} {url}")  # noqa: T201
                print(f"Headers: {headers}")  # noqa: T201
                print(f"Params: {params}")  # noqa: T201
                print(json.dumps(data, indent=2))  # noqa: T201
            if method == "GET":
                response = requests.get(url, headers=headers, params=params, data=json.dumps(data))
            else:
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

    def export_users(self, email, fields_to_export=None, external_id=None, fxa_id=None):
        """
        Export user profile by identifier.

        https://www.braze.com/docs/api/endpoints/export/user_data/post_users_identifier/

        If alias is not found, returns empty "users" list.

        """
        data = {"email_address": email, "user_aliases": []}

        if external_id:
            data["external_ids"] = [external_id]

        if fields_to_export:
            data["fields_to_export"] = fields_to_export

        if fxa_id:
            data["user_aliases"].append({"alias_name": fxa_id, "alias_label": "fxa_id"})

        return self._request(BrazeEndpoint.USERS_EXPORT_IDS, data)

    def delete_user(self, email):
        """
        Delete user profile by email.

        https://www.braze.com/docs/api/endpoints/user_data/post_user_delete/

        """

        data = {
            "email_addresses": [
                {
                    "email": email,
                    "prioritization": ["most_recently_updated"],
                },
            ]
        }

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

    def get_user_subscriptions(self, external_id, email):
        """
        Get user's subscription groups and their status.


        https://www.braze.com/docs/api/endpoints/subscription_groups/get_list_user_subscription_groups/

        """
        params = {"external_id": external_id, "email": email}

        return self._request(BrazeEndpoint.SUBSCRIPTION_USER_STATUS, None, "GET", params)

    def save_user(self, braze_user_data):
        """
        Creates a new user or updates attributes for an existing user in Braze.
        https://www.braze.com/docs/api/endpoints/user_data/post_user_track/
        """
        return self._request(BrazeEndpoint.USERS_TRACK, braze_user_data)

    def add_fxa_id_alias(self, external_id, fxa_id):
        """
        Adds the fxa_id user alias to an existing user in Braze.
        https://www.braze.com/docs/api/endpoints/user_data/post_user_alias
        """
        data = {"user_aliases": [{"alias_name": fxa_id, "alias_label": "fxa_id", "external_id": external_id}]}
        return self._request(BrazeEndpoint.USERS_ADD_ALIAS, data)

    def add_aliases(self, alias_operations):
        """
        @param alias_operations: List of user alias objects (schema below)

        {
            "external_id" : (optional, string),
            "alias_name" : (required, string),
            "alias_label" : (required, string)
        }

        Add up to 50 user aliases in Braze.
        https://www.braze.com/docs/api/endpoints/user_data/post_user_alias
        """
        data = {"user_aliases": alias_operations}
        return self._request(BrazeEndpoint.USERS_ADD_ALIAS, data)

    def migrate_external_id(self, migrations):
        """
        Migrate a user's external_id to a new value. 50 rename objects per request is the hard Braze limit.

        If the migrations list has more than 50 objects, method will send multiple requests, each with <=50 objects.

        https://www.braze.com/docs/api/endpoints/user_data/external_id_migration/post_external_ids_rename/#prerequisites

        """

        if not (isinstance(migrations, list) and all(isinstance(item, dict) for item in migrations)):
            raise BrazeClientError("migrations must be a list of dictionaries")

        results = []
        errors = []

        for i in range(0, len(migrations), 50):
            chunk = migrations[i : i + 50]
            rename_request = {"external_id_renames": chunk}
            rename_response = self._request(BrazeEndpoint.USERS_MIGRATE_EXTERNAL_ID, rename_request)

            external_ids = rename_response.get("external_ids", [])
            rename_errors = rename_response.get("rename_errors", [])

            results.extend(external_ids)
            errors.extend(rename_errors)

        return {
            "braze_collected_response": {
                "external_ids": results,
                "rename_errors": errors,
            }
        }


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
        """
        Get a user using the first ID provided.

        @param email_id: external ID from Braze
        @param token: basket_token
        @param email: email address
        @param fxa_id: external ID from FxA
        @return: dict, or None if not found
        """

        # If we only have a token or fxa_id and the Braze migrations for them haven't been
        # completed we won't be able to look up the user. We add a temporary shim here which
        # will fetch the email from CTMS. This shim can be disabled/removed after the migrations
        # are complete.
        if not email and settings.BRAZE_CTMS_SHIM_ENABLE:
            try:
                ctms_response = ctms.get(token=token, fxa_id=fxa_id)
                if ctms_response:
                    email = ctms_response.get("email")
            except Exception:
                log.warn("Unable to fetch email from CTMS in braze.get shim")

        user_response = self.interface.export_users(
            email,
            [
                "braze_id",
                "country",
                "created_at",
                "custom_attributes",
                "email",
                "email_subscribe",
                "external_id",
                "first_name",
                "language",
                "last_name",
                "user_aliases",
            ],
            token,
            fxa_id,
        )

        if user_response["users"]:
            user_data = user_response["users"][0]
            user_email = email or user_data.get("email")
            is_opted_out = user_data.get("email_subscribe") == "unsubscribed"
            subscriptions = []

            if user_data.get("external_id") and user_email and not is_opted_out:
                subscription_response = self.interface.get_user_subscriptions(user_data["external_id"], email)
                subscriptions = subscription_response.get("users", [{}])[0].get("subscription_groups", [])

            return self.from_vendor(user_data, subscriptions)

    def add(self, data):
        """
        Create a user record.

        @param data: user data to add as a new user.
        """
        braze_user_data = self.to_vendor(None, data)
        external_id = braze_user_data["attributes"][0]["external_id"]
        self.interface.save_user(braze_user_data)

        if data.get("fxa_id"):
            add_fxa_id_alias_task.delay(
                external_id,
                data["fxa_id"],
                enqueue_in=BRAZE_OPTIMAL_DELAY,
            )

        token = data.get("token")
        if token and settings.BRAZE_PARALLEL_WRITE_ENABLE:
            migrate_external_id_task.delay(
                external_id,
                token,
                enqueue_in=BRAZE_OPTIMAL_DELAY,
            )

        return {"email": {"email_id": external_id}}

    def update(self, existing_data, update_data):
        """
        Update data in an existing user record.

        @param existing_data: current user record
        @param update_data: dict of new data
        """
        braze_user_data = self.to_vendor(existing_data, update_data)
        external_id = braze_user_data["attributes"][0]["external_id"]
        self.interface.save_user(braze_user_data)

        if update_data.get("fxa_id") and existing_data.get("fxa_id") != update_data["fxa_id"]:
            add_fxa_id_alias_task.delay(
                external_id,
                update_data["fxa_id"],
                enqueue_in=BRAZE_OPTIMAL_DELAY,
            )

    def update_by_fxa_id(self, fxa_id, update_data):
        """
        Update data in an existing user record by fxa_id.

        @param fxa_id: external ID from FxA
        @param update_data: dict of new data
        @raises BrazeUserNotFoundByFxaIdError: when no record found
        """
        existing_user = self.get(fxa_id=fxa_id)
        if not existing_user:
            raise BrazeUserNotFoundByFxaIdError
        self.update(existing_user, update_data)

    def update_by_token(self, token, update_data):
        """
        Update data in an existing user record by basket_token.

        @param token: basket_token
        @param update_data: dict of new data
        @raises BrazeUserNotFoundByTokenError: when no record found
        """
        existing_user = self.get(token=token)
        if not existing_user:
            raise BrazeUserNotFoundByTokenError
        self.update(existing_user, update_data)

    def delete(self, email):
        """
        Delete the user matching the email

        @param email: The email of the user
        @return: deleted user data if successful
        @raises: BrazeUserNotFoundByEmailError
        """
        data = self.interface.export_users(email=email, fields_to_export=["external_id", "user_aliases"])
        if not data["users"]:
            raise BrazeUserNotFoundByEmailError

        email_id = data["users"][0].get("external_id")
        user_aliases = data["users"][0].get("user_aliases", [])
        fxa_id = next((user_alias["alias_name"] for user_alias in user_aliases if user_alias.get("alias_label") == "fxa_id"), None)

        self.interface.delete_user(email)
        # return in list of {email_id, fxa_id} to match CTMS.delete
        return [{"email_id": email_id, "fxa_id": fxa_id}]

    def from_vendor(self, braze_user_data, subscription_groups):
        """
        Converts Braze-formatted data to Basket-formatted data
        """

        user_attributes = braze_user_data.get("custom_attributes", {}).get("user_attributes_v1", [{}])[0]
        user_aliases = braze_user_data.get("user_aliases", [])
        subscription_ids = [subscription["id"] for subscription in (subscription_groups or []) if subscription["status"] == "Subscribed"]
        newsletter_slugs = list(filter(None, map(vendor_id_to_slug, subscription_ids)))
        fxa_id = next((user_alias["alias_name"] for user_alias in user_aliases if user_alias.get("alias_label") == "fxa_id"), None)

        basket_user_data = {
            "email": braze_user_data["email"],
            "email_id": braze_user_data["external_id"],
            "id": braze_user_data["braze_id"],
            "first_name": braze_user_data.get("first_name"),
            "last_name": braze_user_data.get("last_name"),
            "country": braze_user_data.get("country") or user_attributes.get("mailing_country"),
            "lang": braze_user_data.get("language") or user_attributes.get("email_lang", "en"),
            "newsletters": newsletter_slugs,
            "created_date": user_attributes.get("created_at"),
            "last_modified_date": user_attributes.get("updated_at"),
            "optin": braze_user_data.get("email_subscribe") == "opted_in",
            "optout": braze_user_data.get("email_subscribe") == "unsubscribed",
            "token": user_attributes.get("basket_token"),
            "fxa_service": user_attributes.get("fxa_first_service"),
            "fxa_lang": user_attributes.get("fxa_lang"),
            "fxa_primary_email": user_attributes.get("fxa_primary_email"),
            "fxa_create_date": user_attributes.get("fxa_created_at") if user_attributes.get("has_fxa") else None,
            "has_fxa": user_attributes.get("has_fxa"),
            "fxa_id": fxa_id,
            "fxa_deleted": user_attributes.get("fxa_deleted"),
            "unsub_reason": user_attributes.get("unsub_reason"),
        }

        return basket_user_data

    def to_vendor(self, basket_user_data=None, update_data=None, events=None):
        """
        Converts Basket-formatted data to Braze-formatted data
        """
        existing_user_data = basket_user_data or {}
        updated_user_data = existing_user_data | (update_data or {})

        now = timezone.now().isoformat()
        country = process_country(updated_user_data.get("country") or None)
        language = process_lang(updated_user_data.get("lang") or None)

        external_id = (
            updated_user_data.get("token") if not existing_user_data and settings.BRAZE_ONLY_WRITE_ENABLE else updated_user_data.get("email_id")
        )

        if not external_id:
            raise ValueError("Missing Braze external_id")

        subscription_groups = []
        if update_data and isinstance(update_data.get("newsletters"), dict):
            for slug, is_subscribed in update_data["newsletters"].items():
                vendor_id = slug_to_vendor_id(slug)
                if is_valid_uuid(vendor_id):
                    subscription_groups.append(
                        {
                            "subscription_group_id": vendor_id,
                            "subscription_state": "subscribed" if is_subscribed else "unsubscribed",
                        }
                    )

        user_attributes = {
            "external_id": external_id,
            "email": updated_user_data.get("email"),
            "update_timestamp": now,
            "_update_existing_only": bool(existing_user_data),
            "email_subscribe": "unsubscribed" if updated_user_data.get("optout") else "opted_in" if updated_user_data.get("optin") else "subscribed",
            "subscription_groups": subscription_groups,
            "user_attributes_v1": [
                {
                    "basket_token": updated_user_data.get("token"),
                    "created_at": {"$time": updated_user_data.get("created_date", now)},
                    "email_lang": language,
                    "mailing_country": country,
                    "updated_at": {"$time": now},
                    "has_fxa": bool(updated_user_data.get("fxa_id")) or updated_user_data.get("has_fxa", False),
                    "fxa_created_at": {"$time": fxa_create_date} if (fxa_create_date := updated_user_data.get("fxa_create_date")) else None,
                    "fxa_first_service": updated_user_data.get("fxa_service"),
                    "fxa_lang": updated_user_data.get("fxa_lang"),
                    "fxa_primary_email": updated_user_data.get("fxa_primary_email"),
                    "fxa_deleted": updated_user_data.get("fxa_deleted"),
                    "unsub_reason": updated_user_data.get("unsub_reason"),
                }
            ],
        }

        # Country, language, first and last name are billable data points. Only update them when necessary.
        if country != process_country(existing_user_data.get("country") or None):
            user_attributes["country"] = country
        if not existing_user_data or language != process_lang(existing_user_data.get("language") or None):
            user_attributes["language"] = language
        if (first_name := updated_user_data.get("first_name")) != existing_user_data.get("first_name"):
            user_attributes["first_name"] = first_name
        if (last_name := updated_user_data.get("last_name")) != existing_user_data.get("last_name"):
            user_attributes["last_name"] = last_name

        braze_data = {"attributes": [user_attributes]}

        if events:
            braze_data["events"] = events

        return braze_data


braze_tx = Braze(BrazeInterface(settings.BRAZE_BASE_API_URL, settings.BRAZE_API_KEY))
braze = Braze(BrazeInterface(settings.BRAZE_BASE_API_URL, settings.BRAZE_NEWSLETTER_API_KEY))

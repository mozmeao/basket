"""
API Client Library for Mozilla's Contact Management System (CTMS)
https://github.com/mozilla-it/ctms-api/
"""
import logging
import re
from functools import cached_property, partial, partialmethod
from urllib.parse import urljoin, urlparse, urlunparse

from django.conf import settings
from django.core.cache import cache

import sentry_sdk
from oauthlib.oauth2 import BackendApplicationClient
from requests.adapters import HTTPAdapter
from requests_oauthlib import OAuth2Session
from urllib3.util import Retry

from basket import metrics
from basket.news.backends.common import get_timer_decorator
from basket.news.country_codes import SFDC_COUNTRIES_LIST, convert_country_3_to_2
from basket.news.newsletters import (
    is_supported_newsletter_language,
    newsletter_slugs,
    newsletter_waitlist_slugs,
)

logger = logging.getLogger(__name__)

time_request = get_timer_decorator("news.backends.ctms")


class CTMSError(Exception):
    """Base class for exceptions raised by CTMS functions."""


# Map CTMS group / name pairs to basket flat format names
# Missing basket names from pre-2021 SFDC integration:
#  record_type - Identify MoFo donors with an associated opportunity
#  postal_code - Extra data for MoFo petitions
#  source_url - Set-once source URL, now per-newsletter
#  fsa_* - Firefox Student Ambassadors, deprecated
#  cv_* - Common Voice, moved to MoFo
#  payee_id - Stripe payee ID for MoFo donations
#  fxa_last_login - Imported into Acoustic periodically from FxA
CTMS_TO_BASKET_NAMES = {
    "amo": {
        "add_on_ids": None,
        "display_name": "amo_display_name",
        "email_opt_in": None,
        "language": None,
        "last_login": "amo_last_login",
        "location": "amo_location",
        "profile_url": "amo_homepage",
        "user": "amo_user",
        "user_id": "amo_id",
        "username": None,
        "create_timestamp": None,
        "update_timestamp": None,
    },
    "email": {
        "primary_email": "email",
        "basket_token": "token",
        "double_opt_in": "optin",
        "sfdc_id": "id",
        "first_name": "first_name",
        "last_name": "last_name",
        "mailing_country": "country",
        "email_format": "format",
        "email_lang": "lang",
        "has_opted_out_of_email": "optout",
        "unsubscribe_reason": "reason",
        "email_id": "email_id",
        "create_timestamp": "created_date",
        "update_timestamp": "last_modified_date",
    },
    "fxa": {
        "fxa_id": "fxa_id",
        "primary_email": "fxa_primary_email",
        "created_date": "fxa_create_date",
        "lang": "fxa_lang",
        "first_service": "fxa_service",
        "account_deleted": "fxa_deleted",
    },
    "mofo": {
        # Need more information about the future MoFo integrations
        "mofo_email_id": None,
        "mofo_contact_id": None,
        "mofo_relevant": "mofo_relevant",
    },
}

VPN_NEWSLETTER_SLUG = "guardian-vpn-waitlist"


def from_vendor(contact):
    """Convert CTMS nested data to basket key-value format

    @params contact: CTMS data
    @return: dict in basket format
    """
    data = {
        "newsletters": [],
    }
    for group_name, group in contact.items():
        basket_group = CTMS_TO_BASKET_NAMES.get(group_name)
        if basket_group:
            for ctms_name, basket_name in basket_group.items():
                if basket_name and ctms_name in group:
                    data[basket_name] = group[ctms_name]
        elif group_name == "newsletters":
            # Import newsletter names
            # Unimported per-newsletter data: format, language, source, unsub_reason
            for newsletter in group:
                if newsletter["subscribed"]:
                    data.setdefault("newsletters", []).append(newsletter["name"])
        elif group_name == "waitlists":
            # Unimported per-waitlist data: source, extra fields...
            for waitlist in group:
                wl_name = waitlist["name"]
                # Legacy waitlist format. For backward compatibility.
                # See `to_vendor()`` and `waitlist_fields_for_slug()` for the inverse.
                if wl_name == "vpn":
                    wl_name = VPN_NEWSLETTER_SLUG
                    data["fpn_country"] = waitlist["fields"].get("geo")
                    if platform := waitlist["fields"].get("platform"):
                        data["fpn_platform"] = platform
                else:
                    wl_name += "-waitlist"
                if wl_name.startswith("relay") and wl_name.endswith("-waitlist"):
                    data["relay_country"] = waitlist["fields"].get("geo")
                data.setdefault("newsletters", []).append(wl_name)
        else:
            pass
    return data


BASKET_TO_CTMS_NAMES = {}
for group_name, group in CTMS_TO_BASKET_NAMES.items():
    for key, basket_name in group.items():
        if basket_name is not None:
            BASKET_TO_CTMS_NAMES[basket_name] = (group_name, key)

# Known basket keys to discard, used in pre-2021 SFDC integration
DISCARD_BASKET_NAMES = {
    "_set_subscriber",  # Identify newsletter subscribers in SFDC
    "record_type",  # Identify donors with associated opportunity
    "postal_code",  # Extra data for MoFo petitions
    #
    # fsa_* is Firefox Student Ambassador data, deprecated
    "fsa_school",
    "fsa_grad_year",
    "fsa_major",
    "fsa_city",
    "fsa_current_status",
    "fsa_allow_share",
    #
    # cv_* is Common Voice data, moved to MoFo
    "cv_days_interval",
    "cv_created_at",
    "cv_goal_reached_at",
    "cv_first_contribution_date",
    "cv_two_day_streak",
    "cv_last_active_date",
    #
    "fxa_last_login",  # Imported into Acoustic periodically from FxA
    "api_key",  # Added from authenticated calls
    "api-key",  # Alternate spelling for authenticated calls
    "privacy",  # Common in newsletter forms as privacy policy checkbox
    "trigger_welcome",  # "N" to avoid sending a (deprecated) welcome email.
}


def process_country(raw_country):
    """Convert to 2-letter country, and throw out unknown countries."""
    country = raw_country.strip().lower()
    if len(country) == 3:
        new_country = convert_country_3_to_2(country)
        if new_country:
            country = new_country

    if country not in SFDC_COUNTRIES_LIST:
        raise ValueError(f"{country} not in SFDC_COUNTRIES_LIST")
    return country


def process_lang(raw_lang):
    """Ensure language is supported."""
    lang = raw_lang.strip()
    if lang.lower() in settings.EXTRA_SUPPORTED_LANGS:
        return lang
    elif is_supported_newsletter_language(lang):
        return lang[:2].lower()
    else:
        # Use the default language (English) for unsupported languages
        return "en"


def truncate_string(max_length, raw_string):
    """Truncate the a string to a maximum length, and return None for empty."""
    if raw_string is None:
        raise ValueError("expected string, got None")
    string = raw_string.strip()
    if len(string) > max_length:
        metrics.incr("news.backends.ctms.data_truncated")
        return string[:max_length]
    return string


TO_VENDOR_PROCESSORS = {
    "country": process_country,
    "lang": process_lang,
    "first_name": partial(truncate_string, 255),
    "last_name": partial(truncate_string, 255),
    "reason": partial(truncate_string, 1000),  # CTMS unlimited, but 1k is reasonable
    "fpn_country": partial(truncate_string, 100),
    "fpn_platform": partial(truncate_string, 100),
}


def waitlist_fields_for_slug(data, slug):
    """
    Gather arbitrary fields using the slug as prefix.
    For example, with `slug="super-product"`, the following data::

        super_product_currency=eur
        super_product_country=fr
        other_field=42

    is turned into::

        {
          "country": "fr",
          "currency": "eur",
        }
    """
    # Specific cases for legacy waitlists:
    if slug in ("relay-vpn-bundle", "relay-phone-masking"):
        slug = "relay"
    new_fields = {
        "relay_country": "relay_geo",
        "fpn_country": "vpn_geo",
        "fpn_platform": "vpn_platform",
    }

    prefix = re.sub("[^0-9a-zA-Z]+", "_", slug) + "_"
    consumed_keys = []

    # Turn flat fields into a dict.
    fields = {}
    for name, raw_value in data.items():
        if name in new_fields:
            consumed_key = name
            name = new_fields[name]
        else:
            consumed_key = name
        if not name.startswith(prefix):
            continue
        field_name = name.replace(prefix, "")
        fields[field_name] = raw_value
        consumed_keys.append(consumed_key)
    return fields, consumed_keys


def to_vendor(data, existing_data=None):
    """
    Transform basket key-value data and convert to CTMS nested data

    Differences from SFDC.to_vendor:
    * No equivalent to Subscriber__c, UAT_Test_Data__c
    * Doesn't convert SFDC values Browser_Locale__c, FSA_*, CV_*, MailingCity
    * CTMS API handles boolean conversion
    * Allows setting a value to an empty string or None, if existing is set.

    @params data: data to update, basket format
    @params existing_data: existing user data, basket format
    @return: dict in CTMS format
    """
    ctms_data = {}
    unknown_data = {}
    amo_deleted = False
    newsletters = None
    newsletter_subscription_default = {}
    existing_data = existing_data or {}
    if "lang" in existing_data:
        default_lang = process_lang(existing_data["lang"])
        newsletter_subscription_default["lang"] = default_lang
    if "format" in existing_data:
        newsletter_subscription_default["format"] = existing_data["format"]

    cleaned_data = {}
    for name, raw_value in data.items():
        # Pre-process raw_value, which may remove it.
        processor = TO_VENDOR_PROCESSORS.get(name)
        if processor:
            try:
                value = processor(raw_value)
            except ValueError:
                continue  # Skip invalid values
        else:
            value = raw_value

        # Strip whitespace
        try:
            value = value.strip()
        except AttributeError:
            pass
        # Skip empty values if new record or also unset in existing data
        if (value is None or value == "") and not existing_data.get(name):
            continue

        cleaned_data[name] = value

    for name in cleaned_data.keys():
        value = cleaned_data[name]
        # Place in CTMS contact structure
        if name in BASKET_TO_CTMS_NAMES:
            group_name, key = BASKET_TO_CTMS_NAMES[name]
            ctms_data.setdefault(group_name, {})[key] = value
            if name in {"lang", "format"}:
                newsletter_subscription_default[name] = value
        elif name == "source_url":
            newsletter_subscription_default["source"] = value
        elif name == "newsletters":
            # Process newsletters after gathering all newsletter keys
            newsletters = value
            if not isinstance(newsletters, dict):
                newsletters = {slug: True for slug in newsletters}
        elif name == "amo_deleted":
            amo_deleted = bool(value)
        elif name not in DISCARD_BASKET_NAMES:
            unknown_data[name] = data[name]  # raw value

    # Process the newsletters and waitlists.
    # Waitlist are newsletters with the `is_waitlist` flag, and can carry
    # arbitrary data in `fields`, that will be validated by CTMS.
    if newsletters:
        valid_slugs = newsletter_slugs()
        waitlist_slugs = newsletter_waitlist_slugs()
        output_newsletters = []
        output_waitlists = []
        # Detect unsubscribe all
        optout = data.get("optout", False) or False
        if optout and (not any(newsletters.values())) and (set(valid_slugs) == set(newsletters.keys())):
            # When unsubscribe all is requested, let CTMS unsubscribe from all.
            # Note that since `valid_slugs` is a superset of `waitlist_slugs`, we
            # also unsubscribe from all waitlists.
            output_newsletters = "UNSUBSCRIBE"
            output_waitlists = "UNSUBSCRIBE"
        else:
            # Dictionary of slugs to sub/unsub flags
            for slug, subscribed in newsletters.items():
                if slug not in valid_slugs:
                    continue
                if slug in waitlist_slugs:
                    # Rename legacy VPN waitlist. See `from_vendor()`` for the inverse.
                    if slug == VPN_NEWSLETTER_SLUG:
                        slug = "vpn"
                    # The newsletter is a waitlist. Ignore its conventional suffix.
                    slug = slug.replace("-waitlist", "")
                    if subscribed:
                        fields_mapping, consumed_fields = waitlist_fields_for_slug(cleaned_data, slug)
                        # Remove all consumed waitlist fields from unknown data
                        for field_name in consumed_fields:
                            try:
                                del unknown_data[field_name]
                            except KeyError:
                                # The same field was consumed by several waitlists.
                                pass
                        # Submit the waitlist details, with potential source URL.
                        wl_sub = {
                            "name": slug,
                            "subscribed": True,
                            "source": newsletter_subscription_default.get("source"),
                            "fields": fields_mapping,
                        }
                    else:
                        wl_sub = {"name": slug, "subscribed": False}
                    output_waitlists.append(wl_sub)
                else:
                    # Regular newsletter, which may include extra data from the
                    # email group like `format`, `source`, and `lang`, e.g.
                    if subscribed:
                        nl_sub = newsletter_subscription_default.copy()
                        nl_sub.update({"name": slug, "subscribed": True})
                    else:
                        nl_sub = {"name": slug, "subscribed": False}
                    output_newsletters.append(nl_sub)

        if output_newsletters:
            ctms_data["newsletters"] = output_newsletters
        if output_waitlists:
            ctms_data["waitlists"] = output_waitlists

    # When an AMO account is deleted, reset data to defaults
    if amo_deleted:
        ctms_data["amo"] = "DELETE"

    if unknown_data:
        logger.warning(
            "ctms.to_vendor() could not convert unknown data",
            extra={"unknown_data": unknown_data},
        )
        with sentry_sdk.push_scope() as scope:
            scope.set_extra("unknown_data", unknown_data)
            sentry_sdk.capture_message("ctms.to_vendor() could not convert unknown data")

    return ctms_data


class CTMSSession:
    """Add authentication to requests to the CTMS API"""

    def __init__(
        self,
        api_url,
        client_id,
        client_secret,
        token_cache_key="ctms_token",
    ):
        """Initialize a CTMSSession

        @param api_url: The base API URL (protocol and domain)
        @param client_id: The CTMS client_id for OAuth2
        @param client_secret: The CTMS client_secret for OAuth2
        @param token_cache_key: The cache key to store access tokens
        """
        urlbits = urlparse(api_url)
        if not urlbits.scheme or not urlbits.netloc:
            raise ValueError("Invalid api_url")
        self.api_url = urlunparse((urlbits.scheme, urlbits.netloc, "", "", "", ""))

        if not client_id:
            raise ValueError("client_id is empty")
        self.client_id = client_id

        if not client_secret:
            raise ValueError("client_secret is empty")
        self.client_secret = client_secret

        if not token_cache_key:
            raise ValueError("client_secret is empty")
        self.token_cache_key = token_cache_key

    @property
    def _token(self):
        """Get the current OAuth2 token"""
        return cache.get(self.token_cache_key)

    def save_token(self, token):
        """Set the OAuth2 token"""
        expires_in = int(token.get("expires_in", 60))
        timeout = int(expires_in * 0.95)
        cache.set(self.token_cache_key, token, timeout=timeout)

    @_token.setter
    def _token(self, token):
        self.save_token(token)

    @classmethod
    def check_2xx_response(cls, response):
        """Raise an error for a non-2xx response"""
        response.raise_for_status()
        return response

    @cached_property
    def _session(self):
        """Get an authenticated OAuth2 session"""
        client = BackendApplicationClient(client_id=self.client_id)
        session = OAuth2Session(
            client=client,
            token=self._token,
            auto_refresh_url=urljoin(self.api_url, "/token"),
            auto_refresh_kwargs={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            token_updater=self.save_token,
        )
        session.register_compliance_hook(
            "access_token_response",
            CTMSSession.check_2xx_response,
        )
        session.register_compliance_hook(
            "refresh_token_response",
            CTMSSession.check_2xx_response,
        )
        # Mount an HTTPAdapter to retry requests.
        retries = Retry(
            total=5,
            backoff_factor=0.5,
            allowed_methods={"GET", "POST", "PATCH"},
        )
        session.mount(self.api_url, HTTPAdapter(max_retries=retries))
        if not session.authorized:
            session = self._authorize_session(session)
        return session

    def _authorize_session(self, session):
        """Fetch a client-crendetials token and add to the session."""
        self._token = session.fetch_token(
            token_url=urljoin(self.api_url, "/token"),
            client_id=self.client_id,
            client_secret=self.client_secret,
        )
        return session

    def request(self, method, path, *args, **kwargs):
        """
        Request a CTMS API endpoint, with automatic token refresh.

        CTMS doesn't implement a refresh token endpoint (yet?), so we can't use
        the OAuth2Session auto-refresh features.

        @param method: the HTTP method, like 'GET'
        @param path: the path on the server, starting with a slash
        @param *args: positional args for requests.request
        @param **kwargs: keyword arge for requests.request. Important ones are
            params (for querystring parameters) and json (for the JSON-encoded
            body).
        @return a requests Response
        """
        session = self._session
        url = urljoin(self.api_url, path)
        resp = session.request(method, url, *args, **kwargs)
        metrics.incr("news.backends.ctms.request", tags=[f"method:{method}", f"status_code:{resp.status_code}"])
        if resp.status_code == 401:
            self._session = self._authorize_session(session)
            metrics.incr("news.backends.ctms.session_refresh")
            resp = session.request(method, url, *args, **kwargs)
            metrics.incr("news.backends.ctms.request", tags=[f"method:{method}", f"status_code:{resp.status_code}"])
        return resp

    get = partialmethod(request, "GET")
    patch = partialmethod(request, "PATCH")
    post = partialmethod(request, "POST")


class CTMSNoIdsError(CTMSError):
    """No valid IDs were passed to retrieve CTMS records."""

    def __init__(self, required_ids):
        self.required_ids = required_ids

    def __repr__(self):
        return f"{self.__class__.__name__}({self.required_ids})"

    def __str__(self):
        return f"None of the required identifiers are set: {', '.join(name for name in self.required_ids)}"


class CTMSNotFoundByEmailIDError(CTMSError):
    """
    A CTMS record was not found by the primary email_id.

    This replaces a 404 HTTPError when the email_id is part of the URL.
    """

    def __init__(self, email_id):
        self.email_id = email_id

    def __repr__(self):
        return f"{self.__class__.__name__}({self.email_id!r})"

    def __str__(self):
        return f"Contact not found with email ID {self.email_id!r}"


class CTMSUniqueIDConflictError(CTMSError):
    """
    The update was rejected because it would create a duplicate ID.

    This replaces a 409 HTTPError.
    """

    def __init__(self, detail):
        self.detail = detail

    def __repr__(self):
        return f"{self.__class__.__name__}({self.detail!r})"

    def __str__(self):
        return f"Unique ID conflict: {self.detail!r}"


class CTMSValidationError(CTMSError):
    """
    An invalid parameter was sent in the request.

    This replaces a 422 HTTPError, used by CTMS to report a validation error.
    """

    def __init__(self, detail):
        self.detail = detail

    def __repr__(self):
        return f"{self.__class__.__name__}({self.detail!r})"

    def __str__(self):
        return f"CTMS rejected the invalid request: {self.detail!r}"


class CTMSInterface:
    """Basic Interface to the CTMS API"""

    # Identifiers that uniquely identity a CTMS record
    unique_ids = [
        "email_id",
        "basket_token",
        "primary_email",
        "fxa_id",
        "mofo_email_id",
    ]
    # Identifiers that can be shared by multiple CTMS records
    shared_ids = ["sfdc_id", "mofo_contact_id", "amo_user_id", "fxa_primary_email"]
    all_ids = unique_ids + shared_ids

    def __init__(self, session):
        self.session = session

    @time_request
    def get_by_alternate_id(
        self,
        email_id=None,
        primary_email=None,
        basket_token=None,
        sfdc_id=None,
        fxa_id=None,
        mofo_email_id=None,
        mofo_contact_id=None,
        amo_user_id=None,
        fxa_primary_email=None,
    ):
        """
        Call GET /ctms to get a list of contacts matching all alternate IDs.

        @param email_id: CTMS email ID
        @param primary_email: User's primary email
        @param basket_token: Basket's token
        @param sfdc_id: Legacy SalesForce.com ID
        @param fxa_id: Firefox Accounts ID
        @param mofo_email_id: Mozilla Foundation email ID
        @param mofo_contact_id: Mozilla Foundation contact ID
        @param amo_user_id: User ID from addons.mozilla.org
        @param fxa_primary_email: Primary email in Firefox Accounts
        @return: list of contact dicts
        @raises: CTMSNoIds, on no IDs set
        @raises: request.HTTPError, status_code 400, on bad auth credentials
        @raises: request.HTTPError, status_code 401, on no auth credentials
        @raises: request.HTTPError, status_code 404, on unknown email_id
        """

        ids = {}
        for name, value in locals().items():
            if name in self.all_ids and value is not None:
                ids[name] = value
        if not ids:
            raise CTMSNoIdsError(self.all_ids)
        resp = self.session.get("/ctms", params=ids)
        self._check_response(resp)
        return resp.json()

    @time_request
    def post_to_create(self, data):
        """
        Call POST /ctms to create a contact.

        The email (email.primary_email) is the only required item. If the CTMS
        email_id is not set (email.email_id), the server will generate one. Any
        unspecified value will be set to a default.

        @param data: The contact data, as a nested dictionary
        @return: The created contact data
        """
        resp = self.session.post("/ctms", json=data)
        self._check_response(resp)
        return resp.json()

    @time_request
    def get_by_email_id(self, email_id):
        """
        Call GET /ctms/{email_id} to get contact data by CTMS email_id.

        @param email_id: The CTMS email_id of the contact
        @return: The contact data
        @raises: request.HTTPError, status_code 400, on bad auth credentials
        @raises: request.HTTPError, status_code 401, on no auth credentials
        @raises: request.HTTPError, status_code 404, on unknown email_id
        """
        resp = self.session.get(f"/ctms/{email_id}")
        self._check_response(resp, email_id)
        return resp.json()

    @time_request
    def patch_by_email_id(self, email_id, data):
        """
        Call PATCH /ctms/{email_id} to partially update a CTMS contact by ID

        To update a data element, send the key and the new value:

          {"email": {"primary_email": "new_email.example.com"}}

        To delete a subgroup, resetting to defaults, send the group value as "DELETE":

          {"amo": DELETE}

        To unsubscribe from all newsletters, set to "UNSUBSCRIBE":

          {"newsletters": "UNSUBSCRIBE"}

        @param email_id: The CTMS email_id of the contact
        @param data: The contact data to update
        @return: The updated contact data
        """
        resp = self.session.patch(f"/ctms/{email_id}", json=data)
        self._check_response(resp, email_id)
        return resp.json()

    def _check_response(self, response, email_id=None):
        """
        Check a CTMS response, and raise exceptions as needed.

        @param response: The response from CTMS
        @param email_id: The email_id, implies a 404 is a CTMSNotFoundByEmailIDError
        """
        if response.status_code == 404 and email_id:
            raise CTMSNotFoundByEmailIDError(email_id)
        if response.status_code == 409:
            body = response.json()
            raise CTMSUniqueIDConflictError(body["detail"])
        if response.status_code == 422:
            body = response.json()
            raise CTMSValidationError(body["detail"])

        # Raise HTTPError for other non-2xx status
        response.raise_for_status()


class CTMSMultipleContactsError(CTMSError):
    """Multiple contacts were returned when one was expected."""

    def __init__(self, id_name, id_value, contacts):
        self.id_name = id_name
        self.id_value = id_value
        self.contacts = contacts

    def __repr__(self):
        return f"{self.__class__.__name__}({self.id_name!r}, {self.id_value!r}, {self.contacts!r})"

    def __str__(self):
        try:
            email_ids = repr(
                [contact["email"]["email_id"] for contact in self.contacts],
            )
        except Exception:
            email_ids = "(unable to extract email_ids)"
        return f"{len(self.contacts)} contacts returned for {self.id_name}={self.id_value!r} with email_ids {email_ids}"


class CTMSNotFoundByAltIDError(CTMSError):
    """A CTMS record was not found by an alternate ID."""

    def __init__(self, id_name, id_value):
        self.id_name = id_name
        self.id_value = id_value

    def __repr__(self):
        return f"{self.__class__.__name__}({self.id_name!r}, {self.id_value!r})"

    def __str__(self):
        return f"No contacts returned for {self.id_name}={self.id_value!r}"


class CTMSNotConfigured(CTMSError):
    """CTMS is not configured."""

    def __str__(self):
        return "CTMS is not configured"


class CTMS:
    """Basket interface to CTMS"""

    def __init__(self, interface, is_primary=False):
        self.interface = interface
        self.is_primary = is_primary

    def get(
        self,
        email_id=None,
        token=None,
        email=None,
        fxa_id=None,
        mofo_email_id=None,
        amo_id=None,
        sfdc_id=None,
    ):
        """
        Get a contact record, using the first ID provided.

        @param email_id: CTMS email ID
        @param token: external ID
        @param email: email address
        @param fxa_id: external ID from FxA
        @param mofo_email_id: external ID from MoFo
        @param amo_id: external ID from AMO
        @param sfdc_id: legacy SFDC ID
        @return: dict, or None if disabled
        @raises CTMSNoIds: no IDs are set
        @raises CTMSMultipleContacts:: multiple contacts returned
        """
        if not self.interface:
            if self.is_primary:
                raise CTMSNotConfigured()
            else:
                return None

        if email_id:
            contact = self.interface.get_by_email_id(email_id)
        else:
            alt_ids = []
            if token:
                alt_ids.append({"basket_token": token})
            if email:
                alt_ids.append({"primary_email": email})
            if fxa_id:
                alt_ids.append({"fxa_id": fxa_id})
            if mofo_email_id:
                alt_ids.append({"mofo_email_id": mofo_email_id})
            if amo_id:
                alt_ids.append({"amo_user_id": amo_id})
            if sfdc_id:
                alt_ids.append({"sfdc_id": sfdc_id})
            if not alt_ids:
                raise CTMSNoIdsError(
                    required_ids=(
                        "email_id",
                        "token",
                        "email",
                        "sfdc_id",
                        "fxa_id",
                        "mofo_email_id",
                        "amo_id",
                    ),
                )

            # Try alternate IDs in order
            first_run = True
            first_contacts = None
            contact = None
            for params in alt_ids:
                contacts = self.interface.get_by_alternate_id(**params)
                if first_run:
                    first_contacts = contacts
                    first_run = False
                if len(contacts) == 1:
                    contact = contacts[0]
                    break

            # Did not find single contact, return result of first ID check
            # If first alt ID returned multiple, raise exception
            # If it returned an empty list, return None below
            if contact is None and first_contacts:
                id_name, id_value = list(alt_ids[0].items())[0]
                raise CTMSMultipleContactsError(id_name, id_value, first_contacts)

        if contact:
            return from_vendor(contact)
        else:
            return None

    def add(self, data):
        """
        Create a contact record.

        @param data: user data to add as a new contact.
        @return: new user data, CTMS format
        """
        if not self.interface:
            if self.is_primary:
                raise CTMSNotConfigured()
            else:
                return None
        return self.interface.post_to_create(to_vendor(data))

    def update(self, existing_data, update_data):
        """
        Update data in an existing contact record

        @param existing_data: current contact record
        @param update_data: dict of new data
        @return: updated user data, CTMS format
        """
        if not self.interface:
            if self.is_primary:
                raise CTMSNotConfigured()
            else:
                return None
        email_id = existing_data.get("email_id")
        if not email_id:
            # TODO: When CTMS is primary, this should be an error
            return None
        ctms_data = to_vendor(update_data, existing_data)
        return self.interface.patch_by_email_id(email_id, ctms_data)

    def update_by_alt_id(self, alt_id_name, alt_id_value, update_data):
        """
        Update data in an existing contact record by an alternate ID

        @param alt_id_name: the alternate ID name, such as 'token'
        @param alt_id_value: the alternate ID value
        @param update_data: dict of new data
        @return: updated user data, CTMS format
        @raises CTMSNotFoundByAltID: when no record found
        """
        if not self.interface:
            if self.is_primary:
                raise CTMSNotConfigured()
            else:
                return None

        contact = self.get(**{alt_id_name: alt_id_value})
        if contact:
            return self.update(contact, update_data)
        else:
            raise CTMSNotFoundByAltIDError(alt_id_name, alt_id_value)


def ctms_session():
    """Return a CTMSSession configured from Django settings."""
    if settings.CTMS_ENABLED:
        return CTMSSession(
            api_url=settings.CTMS_URL,
            client_id=settings.CTMS_CLIENT_ID,
            client_secret=settings.CTMS_CLIENT_SECRET,
        )
    else:
        logger.warning("CTMS not enabled.")
        return None


def ctms_interface():
    """Return a CTMSInterface configured from Django settings."""
    session = ctms_session()
    if session:
        return CTMSInterface(session)
    else:
        return None


ctms = CTMS(ctms_interface(), is_primary=True)

import hashlib
import hmac
import time
from abc import ABC

from django.conf import settings
from django.core.cache import cache

import fxa.errors
import sentry_sdk
from ninja.security import APIKeyHeader, APIKeyQuery, HttpBearer
from ninja.security.base import AuthBase

from basket import metrics
from basket.news.models import APIUser
from basket.news.utils import get_fxa_clients

AUTHORIZED = "authorized"
UNAUTHORIZED = "unauthorized"

# NOTE: In our API we can check `request.auth == AUTHORIZED` to see if the user is authenticated.
# If that is `False` either return a 401 or return a 200 with a different payload.


def parse_signature_header(header_value):
    """Parse `t=<timestamp>,v1=<hex digest>` into (timestamp, signature), or (None, None)."""
    parts = {}
    for chunk in header_value.split(","):
        key, _, value = chunk.partition("=")
        if value:
            parts[key.strip()] = value.strip()

    try:
        return int(parts["t"]), parts["v1"]
    except (KeyError, ValueError):
        return None, None


def verify_signature(request, secret, replay_scope):
    """Check `X-Basket-Signature` on `request`; return None if valid, else a short failure reason."""
    timestamp, signature = parse_signature_header(request.headers.get("X-Basket-Signature", ""))
    if timestamp is None or signature is None:
        return "missing_or_malformed"

    if abs(time.time() - timestamp) > settings.INTAKE_SIGNATURE_TOLERANCE_SECONDS:
        return "stale_timestamp"

    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + request.body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected.encode(), signature.encode()):
        return "mismatch"

    replay_ttl = max(1, int(timestamp + settings.INTAKE_SIGNATURE_TOLERANCE_SECONDS - time.time()) + 1)
    if not cache.add(f"{replay_scope}:sig:{signature}", True, timeout=replay_ttl):
        return "replay"

    return None


class APIUserIsValid:
    def authenticate(self, request, key):
        if APIUser.is_valid(key):
            return AUTHORIZED


class QueryApiKey(APIUserIsValid, APIKeyQuery):
    param_name = "api-key"


class HeaderApiKey(APIUserIsValid, APIKeyHeader):
    param_name = "X-Api-Key"


class WebhookHmacSignature(APIKeyHeader):
    """`X-Api-Key` identifies the APIUser, then `X-Basket-Signature` must verify against that user's `hmac_secret`."""

    param_name = "X-Api-Key"

    def authenticate(self, request, key):
        user = APIUser.get_valid(key)
        if user is None:
            return self._reject("unknown_key")

        if not user.hmac_secret:
            return self._reject("no_secret")

        failure = verify_signature(request, user.hmac_secret, "assign")
        if failure:
            return self._reject(failure)

        metrics.incr("news.auth.webhook_hmac", tags=["result:accepted"])
        return AUTHORIZED

    def _reject(self, reason):
        metrics.incr("news.auth.webhook_hmac", tags=["result:rejected", f"reason:{reason}"])
        return None


class FxaBearerToken(HttpBearer):
    def authenticate(self, request, token):
        email = request.GET.get("email") or request.POST.get("email")
        if not email:
            return None

        oauth, profile = get_fxa_clients()
        # Validate the token with oauth-server and check for appropriate scope.
        # This will raise an exception if things are not as they should be.
        try:
            oauth.verify_token(token, scope=["basket", "profile:email"])
            fxa_email = profile.get_email(token)
        except fxa.errors.Error as e:
            # Unable to validate token or find email.
            sentry_sdk.capture_exception(e)
            return None

        if email == fxa_email:
            return AUTHORIZED


class Unauthorized(AuthBase, ABC):
    """
    This authentication class always sets the user status to "unauthorized".

    It is placed last in the `auth=[...]` list to serve as a fallback when no other authentication
    classes validate the user. The design relies on each auth class returning either `AUTHORIZED`
    or `None`; in django-ninja a non-`None` return value stops further checks in the sequence.

    By placing this class at the end, the system can iterate through all other authentication
    methods first. Only if no other method authenticates the user does this class return an
    `UNAUTHORIZED` status. This allows access to the endpoint without an API key, while the view can
    still verify the user's status by checking if `request.auth == AUTHORIZED`.

    """

    openapi_type = "unauthorized"

    def __call__(self, request):
        return self.authenticate(request)

    def authenticate(self, request):
        return UNAUTHORIZED

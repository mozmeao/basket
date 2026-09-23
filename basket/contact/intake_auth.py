import hashlib
import hmac
import time

from django.conf import settings
from django.core.cache import cache

from ninja.errors import HttpError
from ninja.security import APIKeyHeader

from basket.news.models import APIUser


class IntakeUnauthorized(HttpError):
    """Raised for any auth failure on /api/v1/intake/. Handled in intake_api.py, where
    the rest of /api/v1/intake/'s error responses live."""

    def __init__(self):
        super().__init__(401, "unauthorized")


def _parse_signature_header(header_value):
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


class IntakeAuth(APIKeyHeader):
    """Two mandatory checks in one class, since django-ninja's `auth=[...]` list is
    first-match-wins, not AND: a valid `X-Api-Key` identifies which partner's secret to
    check against, then `X-Basket-Signature` (Stripe-style `t=...,v1=...`) must verify
    against that partner's own `hmac_secret`."""

    param_name = "X-Api-Key"

    def authenticate(self, request, key):
        user = APIUser.get_valid(key)
        if user is None:
            raise IntakeUnauthorized()

        if not user.hmac_secret:
            # blank=True was removed from the model, but existing rows (or anything
            # bypassing form validation) could still have one -- fail closed rather
            # than sign with a publicly-known empty key.
            raise IntakeUnauthorized()

        timestamp, signature = _parse_signature_header(request.headers.get("X-Basket-Signature", ""))
        if timestamp is None or signature is None:
            raise IntakeUnauthorized()

        if abs(time.time() - timestamp) > settings.INTAKE_SIGNATURE_TOLERANCE_SECONDS:
            raise IntakeUnauthorized()

        signed_content = f"{timestamp}.".encode() + request.body
        expected = hmac.new(user.hmac_secret.encode(), signed_content, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise IntakeUnauthorized()

        # Reject replay of a previously-accepted signature within its own freshness
        # window -- the timestamp check above only bounds *how old* a signature can be,
        # it doesn't stop the same valid signature being resubmitted. cache.add is
        # atomic: it stores the key only if absent, so this can't race a concurrent
        # replay attempt.
        replay_ttl = max(1, int(timestamp + settings.INTAKE_SIGNATURE_TOLERANCE_SECONDS - time.time()) + 1)
        if not cache.add(f"intake:sig:{signature}", True, timeout=replay_ttl):
            raise IntakeUnauthorized()

        return user

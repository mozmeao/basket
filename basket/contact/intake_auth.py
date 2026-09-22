import hashlib
import hmac
import time

from django.conf import settings

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
        try:
            user = APIUser.objects.get(api_key=key, enabled=True)
        except APIUser.DoesNotExist:
            raise IntakeUnauthorized() from None

        timestamp, signature = _parse_signature_header(request.headers.get("X-Basket-Signature", ""))
        if timestamp is None or signature is None:
            raise IntakeUnauthorized()

        if abs(time.time() - timestamp) > settings.INTAKE_SIGNATURE_TOLERANCE_SECONDS:
            raise IntakeUnauthorized()

        signed_content = f"{timestamp}.".encode() + request.body
        expected = hmac.new(user.hmac_secret.encode(), signed_content, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise IntakeUnauthorized()

        return user

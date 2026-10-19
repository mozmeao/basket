from ninja.errors import HttpError
from ninja.security import APIKeyHeader

from basket.news.auth import verify_signature
from basket.news.models import APIUser


class IntakeUnauthorized(HttpError):
    """Raised for any auth failure on /api/v1/intake/. Handled in intake_api.py, where
    the rest of /api/v1/intake/'s error responses live."""

    def __init__(self):
        super().__init__(401, "unauthorized")


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

        if verify_signature(request, user.hmac_secret, "intake"):
            raise IntakeUnauthorized()

        return user

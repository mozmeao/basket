from abc import ABC

import fxa.errors
import sentry_sdk
from ninja.security import APIKeyHeader, APIKeyQuery, HttpBearer
from ninja.security.base import AuthBase

from basket.news.models import APIUser
from basket.news.utils import get_fxa_clients

AUTHORIZED = "authorized"
UNAUTHORIZED = "unauthorized"

# NOTE: In our API we can check `request.auth == AUTHORIZED` to see if the user is authenticated.
# If that is `False` either return a 401 or return a 200 with a different payload.


class APIUserIsValid:
    def authenticate(self, request, key):
        if APIUser.is_valid(key):
            return AUTHORIZED


class QueryApiKey(APIUserIsValid, APIKeyQuery):
    param_name = "api-key"


class HeaderApiKey(APIUserIsValid, APIKeyHeader):
    param_name = "X-Api-Key"


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
        except fxa.errors.Error:
            # Unable to validate token or find email.
            sentry_sdk.capture_exception()
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

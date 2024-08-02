from ninja.security import APIKeyHeader, APIKeyQuery

from basket.news.models import APIUser

AUTHORIZED = "authorized"
UNAUTHORIZED = "unauthorized"

# NOTE: We can check `request.auth == AUTHORIZED` to see if the user is authenticated.
# If that is `False` we can either return a 401 or return a 200 with a different payload.


class QueryApiKey(APIKeyQuery):
    param_name = "api-key"

    def authenticate(self, request, key):
        if APIUser.is_valid(key):
            return AUTHORIZED

        return UNAUTHORIZED


class HeaderApiKey(APIKeyHeader):
    param_name = "X-Api-Key"

    def authenticate(self, request, key):
        if APIUser.is_valid(key):
            return AUTHORIZED

        return UNAUTHORIZED


# TODO: FxaBearerToken

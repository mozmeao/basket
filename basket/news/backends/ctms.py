"""
API Client Library for Mozilla's Contact Management System (CTMS)
https://github.com/mozilla-it/ctms-api/
"""

from functools import cached_property, partialmethod
from urllib.parse import urlparse, urlunparse, urljoin

from django.conf import settings
from django.core.cache import cache

from requests_oauthlib import OAuth2Session
from oauthlib.oauth2 import BackendApplicationClient


class CTMSSession:
    """Add authentication to requests to the CTMS API"""

    def __init__(
        self, api_url, client_id, client_secret, token_cache_key="ctms_token",
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

    @_token.setter
    def _token(self, token):
        """Set the OAuth2 token"""
        expires_in = int(token.get("expires_in", 60))
        timeout = int(expires_in * 0.95)
        cache.set(self.token_cache_key, token, timeout=timeout)

    @classmethod
    def check_2xx_response(cls, response):
        """Raise an error for a non-2xx response"""
        response.raise_for_status()
        return response

    @cached_property
    def _session(self):
        """Get an authenticated OAuth2 session"""
        client = BackendApplicationClient(client_id=self.client_id)
        session = OAuth2Session(client=client, token=self._token)
        session.register_compliance_hook(
            "access_token_response", CTMSSession.check_2xx_response
        )
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
        if resp.status_code == 401:
            self._session = self._authorize_session(session)
            resp = session.request(method, url, *args, **kwargs)
        return resp

    get = partialmethod(request, "GET")
    post = partialmethod(request, "POST")
    put = partialmethod(request, "PUT")


def ctms_session():
    """Return a CTMSSession configured from Django settings."""
    if settings.CTMS_ENABLED:
        return CTMSSession(
            api_url=settings.CTMS_URL,
            client_id=settings.CTMS_CLIENT_ID,
            client_secret=settings.CTMS_CLIENT_SECRET,
        )
    else:
        return None

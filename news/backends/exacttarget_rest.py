import json
import time

from django.conf import settings

import requests


class ETRestError(Exception):
    pass


class ExactTargetRest(object):
    """Client for ExactTarget's "Fuel" RESTful API."""
    _access_token = None
    _access_token_expires = None
    _access_token_expire_buffer = 30  # seconds
    _refresh_token = None

    api_urls = {
        'auth': 'https://auth.exacttargetapis.com/v1/requestToken',
        'sms_send': 'https://www.exacttargetapis.com/sms/v1/messageContact/{msg_id}/send',
    }

    def __init__(self, client_id=None, client_secret=None):
        self.client_id = client_id or getattr(settings, 'ET_CLIENT_ID', None)
        self.client_secret = client_secret or getattr(settings, 'ET_CLIENT_SECRET', None)

        if self.client_id is None or self.client_secret is None:
            raise ValueError('You must provide the Client ID and Client Secret from the '
                             'ExactTarget App Center.')

    def _request(self, url_name, data, url_params=None, method='POST', extra_headers=None):
        """Make a request to the ET REST API."""
        headers = {'content-type': 'application/json'}

        if url_name != 'auth':
            headers.update(self.auth_header)

        if extra_headers:
            headers.update(extra_headers)

        url = self.api_urls[url_name]
        if url_params:
            url = url.format(**url_params)

        return requests.request(method, url, data=json.dumps(data), headers=headers)

    def auth_token_expired(self):
        """Returns boolean True if the access token has expired."""
        return (self._access_token_expires - self._access_token_expire_buffer) < time.time()

    @property
    def auth_header(self):
        return {'Authorization': 'Bearer {0}'.format(self.auth_token)}

    @property
    def auth_token(self):
        """
        An auth token for connecting to the API. Requests a new auth
        token on access if necessary.
        """
        if not self._access_token or self.auth_token_expired():
            data = {
                'clientId': self.client_id,
                'clientSecret': self.client_secret,
                'accessType': 'offline',  # so we get a refresh token
            }

            if self._refresh_token:
                data['refreshToken'] = self._refresh_token

            response = self._request('auth', data)
            response_data = response.json()

            if 'errorcode' in response_data:
                raise ETRestError(
                    '{0}: {1}'.format(response_data['errorcode'], response_data['message']))
            elif 'accessToken' in response_data:
                self._access_token = response_data['accessToken']
                self._access_token_expires = time.time() + response_data['expiresIn']
                self._refresh_token = response_data['refreshToken']
            else:
                raise ETRestError('Unknown error during authentication: ' + response.text)

        return self._access_token

    def send_sms(self, phone_numbers, message_id):
        data = {
            'mobileNumbers': phone_numbers,
            'Subscribe': True,
            'Resubscribe': True,
            'keyword': 'FFDROID',  # TODO: Set keyword in arguments.
        }
        response = self._request('sms_send', data, url_params={'msg_id': message_id})
        if response.status_code == 400:
            errors = response.json()['errors']
            raise ETRestError(errors)

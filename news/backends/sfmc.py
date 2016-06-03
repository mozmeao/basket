from functools import wraps
from random import randint
from time import time

from django.conf import settings
from django.core.cache import cache

import requests
from django_statsd.clients import statsd
from FuelSDK import ET_Client, ET_DataExtension_Row, ET_TriggeredSend

from news.backends.common import NewsletterException, NewsletterNoResultsException


HERD_TIMEOUT = 60
AUTH_BUFFER = 300  # 5 min
MAX_BUFFER = HERD_TIMEOUT + AUTH_BUFFER


class ETRefreshClient(ET_Client):
    token_cache_key = 'backends:sfmc:auth:tokens'
    authTokenExpiresIn = None
    token_property_names = [
        'authToken',
        'authTokenExpiration',
        'internalAuthToken',
        'refreshKey',
    ]
    _old_authToken = None

    def token_is_expired(self):
        """Report token is expired between 5 and 6 minutes early

        Having the expiration be random helps prevent multiple basket
        instances simultaneously requesting a new token from SFMC,
        a.k.a. the Thundering Herd problem.
        """
        if self.authTokenExpiration is None:
            return True

        time_buffer = randint(1, HERD_TIMEOUT) + AUTH_BUFFER
        return time() + time_buffer > self.authTokenExpiration

    def refresh_auth_tokens_from_cache(self):
        """Refresh the auth token and other values from cache"""
        if self.authToken is not None and time() + MAX_BUFFER < self.authTokenExpiration:
            # no need to refresh if the current tokens are still good
            return

        tokens = cache.get(self.token_cache_key)
        if tokens:
            for prop, value in tokens.items():
                if prop in self.token_property_names:
                    setattr(self, prop, value)

            # set the value so we can detect if it changed later
            self._old_authToken = self.authToken
            self.build_soap_client()

    def cache_auth_tokens(self):
        if self.authToken is not None and self.authToken != self._old_authToken:
            new_tokens = {prop: getattr(self, prop) for prop in self.token_property_names}
            # 10 min longer than expiration so that refreshKey can be used
            cache.set(self.token_cache_key, new_tokens, self.authTokenExpiresIn + 600)

    def request_token(self, payload):
        r = requests.post(self.auth_url, json=payload)
        token_response = r.json()

        if 'accessToken' in token_response:
            return token_response

        # try again without refreshToken
        if 'refreshToken' in payload:
            # not strictly required, makes testing easier
            payload = payload.copy()
            del payload['refreshToken']
            return self.request_token(payload)

        raise NewsletterException('Unable to validate auth keys: ' + repr(token_response),
                                  status_code=r.status_code)

    def refresh_token(self, force_refresh=False):
        """
        Called from many different places right before executing a SOAP call
        """
        # If we don't already have a token or the token expires within 5 min(300 seconds), get one
        self.refresh_auth_tokens_from_cache()
        if force_refresh or self.authToken is None or self.token_is_expired():
            payload = {
                'clientId': self.client_id,
                'clientSecret': self.client_secret,
                'accessType': 'offline',
            }
            if self.refreshKey:
                payload['refreshToken'] = self.refreshKey

            token_response = self.request_token(payload)
            statsd.incr('news.backends.sfmc.auth_token_refresh')
            self.authToken = token_response['accessToken']
            self.authTokenExpiresIn = token_response['expiresIn']
            self.authTokenExpiration = time() + self.authTokenExpiresIn
            self.internalAuthToken = token_response['legacyToken']
            if 'refreshToken' in token_response:
                self.refreshKey = token_response['refreshToken']

            self.build_soap_client()
            self.cache_auth_tokens()


def assert_response(resp):
    if not resp.status:
        raise NewsletterException(str(resp.results))


def assert_results(resp):
    assert_response(resp)
    if not resp.results:
        raise NewsletterNoResultsException()


def build_attributes(data):
    return [{'Name': key, 'Value': value} for key, value in data.items()]


def time_request(f):
    """
    Decorator for timing and counting requests to the API
    """
    @wraps(f)
    def wrapped(*args, **kwargs):
        starttime = time()
        e = None
        try:
            resp = f(*args, **kwargs)
        except NewsletterException as e:
            pass
        except Exception:
            raise

        totaltime = int((time() - starttime) * 1000)
        statsd.timing('news.backends.sfmc.timing', totaltime)
        statsd.timing('news.backends.sfmc.{}.timing'.format(f.__name__), totaltime)
        statsd.incr('news.backends.sfmc.count')
        statsd.incr('news.backends.sfmc.{}.count'.format(f.__name__))
        if e:
            raise
        else:
            return resp

    return wrapped


class SFMC(object):
    client = None
    sms_api_url = 'https://www.exacttargetapis.com/sms/v1/messageContact/{}/send'

    def __init__(self):
        if 'clientid' in settings.SFMC_SETTINGS:
            self.client = ETRefreshClient(False, settings.SFMC_DEBUG, settings.SFMC_SETTINGS)

    @property
    def auth_header(self):
        self.client.refresh_token()
        return {'Authorization': 'Bearer {0}'.format(self.client.authToken)}

    def _get_row_obj(self, de_name, props):
        row = ET_DataExtension_Row()
        row.auth_stub = self.client
        row.CustomerKey = row.Name = de_name
        row.props = props
        return row

    @time_request
    def get_row(self, de_name, fields, token=None, email=None):
        """
        Get the values of `fields` from a data extension. Either token or email is required.

        @param de_name: name of the data extension
        @param fields: list of column names
        @param token: the user's token
        @param email: the user's email address
        @return: dict of user data
        """
        assert token or email, 'token or email required'
        row = self._get_row_obj(de_name, fields)
        if token:
            row.search_filter = {
                'Property': 'TOKEN',
                'SimpleOperator': 'equals',
                'Value': token,
            }
        elif email:
            row.search_filter = {
                'Property': 'EMAIL_ADDRESS_',
                'SimpleOperator': 'equals',
                'Value': email,
            }

        resp = row.get()
        assert_results(resp)
        # TODO do something if more than 1 result is returned
        return dict((p.Name, p.Value)
                    for p in resp.results[0].Properties.Property)

    @time_request
    def add_row(self, de_name, values):
        """
        Add a row to a data extension.

        @param de_name: name of the data extension
        @param values: dict containing the COLUMN: VALUE pairs
        @return: None
        """
        row = self._get_row_obj(de_name, values)
        resp = row.post()
        assert_response(resp)

    @time_request
    def update_row(self, de_name, values):
        """
        Update a row in a data extension.

        @param de_name: name of the data extension
        @param values: dict containing the COLUMN: VALUE pairs.
            Must contain TOKEN or EMAIL_ADDRESS_.
        @return: None
        """
        row = self._get_row_obj(de_name, values)
        resp = row.patch()
        assert_response(resp)

    @time_request
    def upsert_row(self, de_name, values):
        """
        Add or update a row in a data extension.

        @param de_name: name of the data extension
        @param values: dict containing the COLUMN: VALUE pairs.
            Must contain TOKEN or EMAIL_ADDRESS_.
        @return: None
        """
        row = self._get_row_obj(de_name, values)
        resp = row.patch(True)
        assert_response(resp)

    @time_request
    def delete_row(self, de_name, token=None, email=None):
        """
        Delete a row from a data extension. Either token or email are required.

        @param de_name: name of the data extension
        @param token: user's token
        @param email: user's email address
        @return: None
        """
        assert token or email, 'token or email required'
        if token:
            values = {'TOKEN': token}
        else:
            values = {'EMAIL_ADDRESS_': email}

        row = self._get_row_obj(de_name, values)
        resp = row.delete()
        assert_response(resp)

    @time_request
    def send_mail(self, ts_name, email, token, format):
        """
        Send an email message to a user (Triggered Send).

        @param ts_name: the name of the message to send
        @param email: the email address of the user
        @return: None
        """
        ts = ET_TriggeredSend()
        ts.auth_stub = self.client
        ts.props = {'CustomerKey': ts_name}
        ts.attributes = build_attributes({
            'TOKEN': token,
            'EMAIL_FORMAT_': format,
        })
        ts.subscribers = [{
            'EmailAddress': email,
            'SubscriberKey': token,
            'EmailTypePreference': 'HTML' if format == 'H' else 'Text',
            'Attributes': ts.attributes,
        }]
        resp = ts.send()
        assert_response(resp)

    @time_request
    def send_sms(self, phone_numbers, message_id):
        data = {
            'mobileNumbers': phone_numbers,
            'Subscribe': True,
            'Resubscribe': True,
            'keyword': 'FFDROID',  # TODO: Set keyword in arguments.
        }
        url = self.sms_api_url.format(message_id)
        response = requests.post(url, json=data, headers=self.auth_header)
        if response.status_code >= 400:
            errors = response.json()['errors']
            raise NewsletterException(errors, status_code=response.status_code)


sfmc = SFMC()

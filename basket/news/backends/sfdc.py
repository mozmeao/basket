"""
API Client Library for Salesforce.com (SFDC)
"""
from random import randint
from time import time

import requests
from django.conf import settings
from django.core.cache import cache

import simple_salesforce as sfapi
from django_statsd.clients import statsd
from simple_salesforce.api import DEFAULT_API_VERSION

from basket.base.utils import email_is_testing
from basket.news.backends.common import get_timer_decorator
from basket.news.country_codes import SFDC_COUNTRIES_LIST, convert_country_3_to_2
from basket.news.newsletters import newsletter_map, newsletter_inv_map, is_supported_newsletter_language


_BOOLEANS = {'1': True, 'y': True, 'yes': True, 'true': True, 'on': True,
             '0': False, 'n': False, 'no': False, 'false': False, 'off': False}


def cast_boolean(value):
    # mostly borrowed from python-decouple
    value = str(value).lower()
    if value not in _BOOLEANS:
        raise ValueError('Not a boolean: %s' % value)

    return _BOOLEANS[value]


def cast_lower(value):
    return value.lower()


time_request = get_timer_decorator('news.backends.sfdc')
LAST_NAME_DEFAULT_VALUE = '_'
SFDC_SESSION_CACHE_KEY = 'backends:sfdc:auth:sessionid'
AUTH_BUFFER = 300  # 5 min
HERD_TIMEOUT = 60
FIELD_MAP = {
    'id': 'Id',
    'record_type': 'RecordTypeId',
    'email': 'Email',
    'first_name': 'FirstName',
    'last_name': 'LastName',
    'format': 'Email_Format__c',
    'country': 'MailingCountryCode',
    'postal_code': 'MailingPostalCode',
    'lang': 'Email_Language__c',
    'token': 'Token__c',
    'optin': 'Double_Opt_In__c',
    'optout': 'HasOptedOutOfEmail',
    'source_url': 'Signup_Source_URL__c',
    'created_date': 'CreatedDate',
    'last_modified_date': 'LastModifiedDate',
    'reason': 'Unsubscribe_Reason__c',
    'fsa_school': 'FSA_School__c',
    'fsa_grad_year': 'FSA_Grad_Year__c',
    'fsa_major': 'FSA_Major__c',
    'fsa_city': 'MailingCity',
    'fsa_current_status': 'FSA_Current_Status__c',
    'fsa_allow_share': 'FSA_Allow_Info_Shared__c',
    'cv_days_interval': 'cv_days_interval__c',
    'cv_created_at': 'cv_created_at__c',
    'cv_goal_reached_at': 'cv_goal_reached_at__c',
    'cv_first_contribution_date': 'cv_first_contr_dt__c',
    'cv_two_day_streak': 'cv_two_day_streak__c',
    'cv_last_active_date': 'cv_last_active_dt__c',
    'amo_id': 'AMO_User_ID__c',
    'amo_user': 'AMO_User__c',
    'amo_display_name': 'AMO_Display_Name__c',
    'amo_last_login': 'AMO_Last_Login__c',
    'amo_location': 'AMO_Location__c',
    'amo_homepage': 'AMO_Homepage_URL__c',
    'amo_deleted': 'AMO_Account_Deleted__c',
    'payee_id': 'PMT_Cust_Id__c',
    'fxa_id': 'FxA_Id__c',
    'fxa_deleted': 'FxA_Account_Deleted__c',
    'fxa_lang': 'FxA_Language__c',
    'fxa_service': 'FirstService__c',
    'fxa_create_date': 'FxA_Created_Date__c',
    'fpn_country': 'FPN_Waitlist_Geo__c',
    'fpn_platform': 'FPN_Waitlist_Platform__c',
}
INV_FIELD_MAP = {v: k for k, v in FIELD_MAP.items()}
FIELD_DEFAULTS = {
    'format': 'H',
    'country': '',
    'lang': '',
}
PROCESSORS_TO_VENDOR = {
    'optin': cast_boolean,
    'optout': cast_boolean,
    'fsa_allow_share': cast_boolean,
}
PROCESSORS_FROM_VENDOR = {
    'country': cast_lower,
    'lang': cast_lower,
}
FIELD_MAX_LENGTHS = {
    'FirstName': 40,
    'LastName': 80,
    'Browser_Locale__c': 10,
    'Signup_Source_URL__c': 255,
    'Unsubscribe_Reason__c': 1000,
    'FSA_School__c': 100,
    'FSA_Grad_Year__c': 4,
    'FSA_Major__c': 100,
    'MailingCity': 100,
    'FPN_Waitlist_Geo__c': 120,
    'FPN_Waitlist_Platform__c': 120,
}


def to_vendor(data):
    """
    Take data received by basket and convert it to be sent to SFDC

    @param data: dict data received
    @return:
    """
    data = data.copy()
    contact = {}
    if data.pop('_set_subscriber', True):
        contact['Subscriber__c'] = True

    if 'email' in data:
        if email_is_testing(data['email']):
            contact['UAT_Test_Data__c'] = True

    if 'country' in data:
        data['country'] = data['country'].lower()
        if len(data['country']) == 3:
            new_country = convert_country_3_to_2(data['country'])
            if new_country:
                data['country'] = new_country

        if data['country'] not in SFDC_COUNTRIES_LIST:
            # just don't set the country
            del data['country']

    lang = data.get('lang')
    if lang:
        if lang.lower() in settings.EXTRA_SUPPORTED_LANGS:
            pass
        elif is_supported_newsletter_language(lang):
            data['lang'] = lang[:2].lower()
        else:
            # use our default language (English) if we don't support the language
            data['lang'] = 'en'

    for k, v in data.items():
        if v is not None and v != '' and k in FIELD_MAP:
            if k in PROCESSORS_TO_VENDOR:
                v = PROCESSORS_TO_VENDOR[k](v)

            contact[FIELD_MAP[k]] = v

    news_map = newsletter_map()
    newsletters = data.get('newsletters', None)
    if newsletters:
        if isinstance(newsletters, dict):
            # we got newsletter slugs with boolean values
            for k, v in newsletters.items():
                try:
                    contact[news_map[k]] = v
                except KeyError:
                    pass
        else:
            # we got a list of slugs for subscriptions
            for nl in newsletters:
                try:
                    contact[news_map[nl]] = True
                except KeyError:
                    pass

    # truncate long data
    for field, length in FIELD_MAX_LENGTHS.items():
        if field in contact and len(contact[field]) > length:
            statsd.incr('news.backends.sfdc.data_truncated')
            contact[field] = contact[field][:length]

    return contact


def from_vendor(contact):
    """
    Take contact data retrieved from SFDC and convert it for ease of use

    @param contact: contact data from SFDC
    @return:
    """
    news_map = newsletter_inv_map()
    data = {}
    newsletters = []
    for fn, fv in contact.items():
        if fn in INV_FIELD_MAP:
            data_name = INV_FIELD_MAP[fn]
            if data_name in FIELD_DEFAULTS:
                fv = fv or FIELD_DEFAULTS[data_name]
            if data_name in PROCESSORS_FROM_VENDOR:
                fv = PROCESSORS_FROM_VENDOR[data_name](fv)

            data[data_name] = fv
        elif fn in news_map and fv:
            newsletters.append(news_map[fn])

    data['newsletters'] = newsletters
    return data


def get_sf_session(force=False):
    if force:
        session_info = None
    else:
        session_info = cache.get(SFDC_SESSION_CACHE_KEY)

    if session_info is None:
        statsd.incr('news.backends.sfdc.session_refresh')
        session_id, sf_instance = sfapi.SalesforceLogin(**settings.SFDC_SETTINGS)
        session_info = {
            'id': session_id,
            'instance': sf_instance,
            'expires': time() + settings.SFDC_SESSION_TIMEOUT,
        }
        cache.set(SFDC_SESSION_CACHE_KEY, session_info, settings.SFDC_SESSION_TIMEOUT)

    return session_info


class RefreshingSFType(sfapi.SFType):
    session_id = None
    session_expires = None
    sf_instance = None

    def __init__(self, name='Contact'):
        self.sf_version = DEFAULT_API_VERSION
        self.name = name
        self.request = requests.Session()
        self.refresh_session()

    def _base_url(self):
        return ('https://{instance}/services/data/'
                'v{version}/sobjects/{name}/').format(instance=self.sf_instance,
                                                       name=self.name,
                                                       version=self.sf_version)

    def refresh_session(self):
        sf_session = get_sf_session()
        if sf_session['id'] == self.session_id:
            # no other instance has set a new one yet
            sf_session = get_sf_session(force=True)

        self.session_id = sf_session['id']
        self.session_expires = sf_session['expires']
        self.sf_instance = sf_session['instance']
        self.base_url = self._base_url()

    def session_is_expired(self):
        """Report session as expired between 5 and 6 minutes early

        Having the expiration be random helps prevent multiple basket
        instances simultaneously requesting a new token from SFMC,
        a.k.a. the Thundering Herd problem.
        """
        time_buffer = randint(1, HERD_TIMEOUT) + AUTH_BUFFER
        return time() + time_buffer > self.session_expires

    def _call_salesforce(self, method, url, **kwargs):
        if self.session_is_expired():
            self.refresh_session()

        kwargs['timeout'] = settings.SFDC_REQUEST_TIMEOUT
        try:
            statsd.incr('news.backends.sfdc.call_salesforce')
            resp = super(RefreshingSFType, self)._call_salesforce(method, url, **kwargs)
        except sfapi.SalesforceExpiredSession:
            statsd.incr('news.backends.sfdc.call_salesforce')
            statsd.incr('news.backends.sfdc.session_expired')
            self.refresh_session()
            resp = super(RefreshingSFType, self)._call_salesforce(method, url, **kwargs)

        limit_info = resp.headers.get('sforce-limit-info')
        if limit_info:
            usages = sfapi.Salesforce.parse_api_usage(limit_info)
            usage = usages.get('api-usage')
            if usage:
                statsd.gauge('news.backends.sfdc.daily_api_used', int(usage.used), rate=0.5)
                statsd.gauge('news.backends.sfdc.daily_api_limit', int(usage.total), rate=0.5)
                percentage = float(usage.used) / float(usage.total) * 100
                statsd.gauge('news.backends.sfdc.percent_daily_api_used', percentage, rate=0.5)

        return resp


class SFDC(object):
    _contact = None
    _opportunity = None
    _campaign_member = None
    _addon = None
    _dev_addon = None

    @property
    def contact(self):
        if self._contact is None and settings.SFDC_SETTINGS.get('username'):
            self._contact = RefreshingSFType()

        return self._contact

    @property
    def opportunity(self):
        if self._opportunity is None and settings.SFDC_SETTINGS.get('username'):
            self._opportunity = RefreshingSFType('Opportunity')

        return self._opportunity

    @property
    def campaign_member(self):
        if self._campaign_member is None and settings.SFDC_SETTINGS.get('username'):
            self._campaign_member = RefreshingSFType('CampaignMember')

        return self._campaign_member

    @property
    def addon(self):
        if self._addon is None and settings.SFDC_SETTINGS.get('username'):
            self._addon = RefreshingSFType('Add_On__c')

        return self._addon

    @property
    def dev_addon(self):
        if self._dev_addon is None and settings.SFDC_SETTINGS.get('username'):
            self._dev_addon = RefreshingSFType('DevAddOn__c')

        return self._dev_addon

    @time_request
    def get(self, token=None, email=None, payee_id=None, amo_id=None, fxa_id=None):
        """
        Get a contact record. One of the arguments is required.

        @param token: external ID
        @param email: email address
        @param payee_id: external ID from Stripe/payment processor
        @param amo_id: external ID from AMO
        @param fxa_id: external ID from FxA
        @return: dict
        """
        arg_values = locals()
        args = ('token', 'email', 'payee_id', 'amo_id', 'fxa_id')
        field = None
        value = None
        for arg in args:
            if arg_values[arg] is not None:
                field = arg
                value = arg_values[arg]
                break

        if field is None:
            raise RuntimeError('One of the arguments is required: ' + ', '.join(args))

        id_field = FIELD_MAP[field]
        contact = self.contact.get_by_custom_id(id_field, value)
        return from_vendor(contact)

    @time_request
    def add(self, data):
        """
        Create a contact record.

        @param data: user data to add as a new contact.
        @return: None
        """
        if not data.get('last_name', '').strip():
            data['last_name'] = LAST_NAME_DEFAULT_VALUE

        return self.contact.create(to_vendor(data))

    @time_request
    def update(self, record, data):
        """
        Update data in an existing contact record.

        @param record: current contact record
        @param data: dict of user data
        @return: None
        """
        # need a copy because we'll modify it
        data = data.copy()
        if 'id' in record:
            contact_id = record['id']
        elif 'token' in record or 'email' in record:
            fn = 'token' if 'token' in record else 'email'
            contact_id = '{}/{}'.format(FIELD_MAP[fn], record[fn])
            # can't send the ID field in the data
            data.pop(fn, None)
        else:
            raise KeyError('id, token, or email required')

        # source_url should only be added if user doesn't already have one
        if record.get('source_url') and 'source_url' in data:
            del data['source_url']

        # first_name should only be updated if user doesn't already have one
        if record.get('first_name') and 'first_name' in data:
            del data['first_name']

        # last_name should only be updated if it is currently the default value
        if record.get('last_name') != LAST_NAME_DEFAULT_VALUE and 'last_name' in data:
            del data['last_name']

        return self.contact.update(contact_id, to_vendor(data))

    @time_request
    def delete(self, record):
        """
        Delete a contact record.

        @param record: current contact record
        @return: None
        """
        self.contact.delete(record['id'])


sfdc = SFDC()

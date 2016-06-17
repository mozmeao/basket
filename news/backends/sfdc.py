"""
API Client Library for Salesforce.com (SFDC)
"""
from django.conf import settings

import simple_salesforce as sfapi
from django_statsd.clients import statsd
from simple_salesforce.api import DEFAULT_API_VERSION

from news.backends.common import get_timer_decorator
from news.newsletters import newsletter_map, newsletter_inv_map


time_request = get_timer_decorator('news.backends.sfdc')
LAST_NAME_DEFAULT_VALUE = ','
FIELD_MAP = {
    'id': 'Id',
    'email': 'Email',
    'first_name': 'FirstName',
    'last_name': 'LastName',
    'format': 'Email_Format__c',
    'country': 'MailingCountryCode',
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
}
INV_FIELD_MAP = {v: k for k, v in FIELD_MAP.items()}
FIELD_DEFAULTS = {
    'format': 'H',
    'country': '',
    'lang': '',
}
FIELD_PROCESSORS = {
    'country': lambda x: x.lower(),
    'lang': lambda x: x.lower(),
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
}


def to_vendor(data):
    """
    Take data received by basket and convert it to be sent to SFDC

    @param data: dict data received
    @return:
    """
    contact = {
        # True for every contact moving through basket
        'Subscriber__c': True,
    }
    for k, v in data.iteritems():
        if k in FIELD_MAP:
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
    for fn, fv in contact.iteritems():
        if fn in INV_FIELD_MAP:
            data_name = INV_FIELD_MAP[fn]
            if data_name in FIELD_DEFAULTS:
                fv = fv or FIELD_DEFAULTS[data_name]
            if data_name in FIELD_PROCESSORS:
                data[data_name] = FIELD_PROCESSORS[data_name](fv)
            else:
                data[data_name] = fv
        elif fn in news_map and fv:
            newsletters.append(news_map[fn])

    data['newsletters'] = newsletters
    return data


def get_sf_session():
    return sfapi.SalesforceLogin(**settings.SFDC_SETTINGS)


class RefreshingSFType(sfapi.SFType):
    def _call_salesforce(self, method, url, **kwargs):
        try:
            resp = super(RefreshingSFType, self)._call_salesforce(method, url, **kwargs)
        except sfapi.SalesforceExpiredSession:
            self.session_id, _ = get_sf_session()
            resp = super(RefreshingSFType, self)._call_salesforce(method, url, **kwargs)
            statsd.incr('news.backends.sfdc.session_expired')

        if 'sforce-limit-info' in resp.headers:
            try:
                usage, limit = resp.headers['sforce-limit-info'].split('=')[1].split('/')
            except Exception:
                usage = limit = None

            if usage:
                percentage = float(usage) / float(limit) * 100
                statsd.gauge('news.backends.sfdc.percent_daily_api_used', percentage, rate=0.5)

        return resp


class SFDC(object):
    contact = None

    def __init__(self):
        if not settings.SFDC_SETTINGS.get('username'):
            return

        session_id, sf_instance = get_sf_session()
        self.contact = RefreshingSFType('Contact', session_id, sf_instance,
                                        DEFAULT_API_VERSION)

    @time_request
    def get(self, token=None, email=None):
        """
        Get a contact record.

        @param token: external ID
        @param email: email address
        @return: dict
        """
        assert token or email, 'token or email is required'
        id_field = FIELD_MAP['token' if token else 'email']
        contact = self.contact.get_by_custom_id(id_field, token or email)
        return from_vendor(contact)

    @time_request
    def add(self, data):
        """
        Create a contact record.

        @param data: user data to add as a new contact.
        @return: None
        """
        data.setdefault('last_name', LAST_NAME_DEFAULT_VALUE)
        self.contact.create(to_vendor(data))

    @time_request
    def update(self, record, data):
        """
        Update data in an existing record.

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

        self.contact.update(contact_id, to_vendor(data))

    @time_request
    def delete(self, record):
        """
        Delete a contact record.

        @param record: current contact record
        @return: None
        """
        self.contact.delete(record['id'])


sfdc = SFDC()

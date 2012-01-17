"""
This library provides a Python interface for working with
ExactTarget's SOAP API.

To watch the SOAP requests:        
import logging
logging.getLogger('suds.client').addHandler(logging.StreamHandler(sys.__stdout__))
logging.getLogger('suds.client').setLevel(logging.DEBUG)
"""

from functools import wraps
import sys

from suds import WebFault
from suds.client import Client
from suds.wsse import *

from common import *

def assert_status(obj):
    """Make sure the returned status is OK"""
    if obj.OverallStatus != 'OK':
        raise NewsletterException(obj.OverallStatus)


def assert_result(obj):
    """Make sure the returned object has a result"""
    if not hasattr(obj, 'Results') or len(obj.Results) == 0:
        raise NewsletterException('No results returns')


def handle_fault(e):
    """Handle an exception thrown by suds, and throw the appropriate
    type of error"""

    if hasattr(e, 'fault') and hasattr(e.fault, 'faultstring'):
        # We have no fault code for a login failure, so check the
        # string
        if e.fault.faultstring.lower() == 'login failed':
            raise UnauthorizedException(str(e))
    raise NewsletterException(str(e))


def logged_in(f):
    """ Decorator to ensure the request will be authenticated """

    @wraps(f)
    def wrapper(inst, *args, **kwargs):
        if not inst.client:
            inst.client = Client(inst.__class__.WSDL_URL)
            
            security = Security()
            token = UsernameToken(inst.user, inst.pass_)
            security.tokens.append(token)
            inst.client.set_options(wsse=security)
        return f(inst, *args, **kwargs)
    return wrapper

    
class ExactTarget(object):
    WSDL_URL = 'https://webservice.s4.exacttarget.com/etframework.wsdl'

    def __init__(self, user, pass_):
        self.client = None
        self.user = user
        self.pass_ = pass_
    
    def create(self, name):
        return self.client.factory.create(name)

    @logged_in
    def add_subscriber(self, list_ids, fields, records):
        list_ids = [list_ids] if isinstance(list_ids, int) else list_ids
        records = [records] if isinstance(records[0], basestring) else records

        subscribers = []

        for record in records:
            subscriber = self.create('Subscriber')

            # Remove properties so that suds doesn't create them as
            # empty fields in the SOAP request which will fail.
            # You will see this throughout all this code.
            del subscriber.EmailTypePreference
            del subscriber.Status
            del subscriber.PrimarySMSPublicationStatus

            for i, v in enumerate(record):
                if fields[i] == 'email':
                    subscriber.EmailAddress = v
                    subscriber.SubscriberKey = v
                elif fields[i] == 'format':
                    subscriber.EmailTypePreference = v
                else:
                    attr = self.create('Attribute')
                    attr.Name = fields[i]
                    attr.Value = v
                    subscriber.Attributes.append(attr)

            subscribers.append(subscriber)

        lsts = []
        for list_id in list_ids:
            lst = self.create('SubscriberList')
            lst.ID = list_id
            del lst.Status
            lsts.append(lst)
        
        subscriber.Lists = lsts

        opt = self.create('SaveOption')
        opt.PropertyName = '*'
        opt.SaveAction = 'UpdateAdd'

        opts = self.create('UpdateOptions')
        opts.SaveOptions.SaveOption = [opt]
        del opts.RequestType
        del opts.QueuePriority

        try:
            obj = self.client.service.Update(opts, [subscriber])
            assert_status(obj)
        except WebFault, e:
            handle_fault(e)
        
    @logged_in
    def get_subscriber(self, email, list_id, fields):
        req = self.create('RetrieveRequest')
        req.ObjectType = 'Subscriber'
        req.Properties = ['ID', 'EmailAddress', 'EmailTypePreference']

        filter_ = self.create('SimpleFilterPart')
        filter_.Value = email
        filter_.SimpleOperator = 'equals'
        filter_.Property = 'EmailAddress'

        req.Filter = filter_
        del req.Options

        try:
            obj = self.client.service.Retrieve(req)
            assert_status(obj)
            assert_result(obj)
        except WebFault, e:
            handle_fault(e)

        record = obj.Results[0]
        res = {}

        for field in fields:
            if field == 'email':
                res['email'] = record.EmailAddress
            else:
                for attr in record.Attributes:
                    if attr.Name == field:
                        res[field] = attr.Value

        return res
        
    @logged_in
    def get_lists_for_subscriber(self, emails):
        emails = [emails] if isinstance(emails, basestring) else emails

        req = self.create('RetrieveRequest')
        req.ObjectType = 'ListSubscriber'
        req.Properties = ['ListID']

        filter_ = self.create('SimpleFilterPart')
        filter_.Value = emails[0]
        filter_.SimpleOperator = 'equals'
        filter_.Property = 'SubscriberKey'
        req.Filter = filter_

        del req.Options

        try:
            obj = self.client.service.Retrieve(req)
            assert_status(obj)
            assert_result(obj)
        except WebFault, e:
            handle_fault(e)

        lists = []
        for res in obj.Results:
            lists.append(res.ListID)

        return lists

    @logged_in
    def add_record(self, data_ids, fields, records):
        data_ids = [data_ids] if isinstance(data_ids, basestring) else data_ids

        objs = []
        for id in data_ids:
            obj = self.create('DataExtensionObject')
            props = []

            for i, v in enumerate(records):
                prop = self.create('APIProperty')
                prop.Name = fields[i]
                prop.Value = v

                props.append(prop)

            obj.Properties.Property = props
            obj.CustomerKey = id
            objs.append(obj)

        # This does not update appropriately yet, it creates new
        # records
        opt = self.create('SaveOption')
        opt.PropertyName = '*'
        opt.SaveAction = 'UpdateAdd'

        opts = self.create('UpdateOptions')
        opts.SaveOptions.SaveOption = [opt]
        del opts.RequestType
        del opts.QueuePriority

        try:
            obj = self.client.service.Update(opts, objs)
            assert_status(obj)
        except WebFault, e:
            handle_fault(e)

    @logged_in
    def get_record(self, email, fields):
        req = self.create('RetrieveRequest')
        req.ObjectType = 'DataExtensionObject[who]'
        req.Properties = fields

        filter_ = self.create('SimpleFilterPart')
        filter_.Value = email
        filter_.SimpleOperator = 'equals'
        filter_.Property = 'email'
        req.Filter = filter_

        del req.Options

        try:
            obj = self.client.service.Retrieve(req)
            assert_status(obj)
            assert_result(obj)        
        except WebFault, e:
            handle_fault(e)
            
        return dict((p.Name, p.Value)
                    for p in obj.Results[0].Properties.Property)

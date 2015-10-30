"""
This library provides a Python interface for working with
ExactTarget's SOAP API.

To watch the SOAP requests:
import logging
logger = getLogger('suds.client')
logger.addHandler(logging.StreamHandler(sys.__stdout__))
logger.setLevel(logging.DEBUG)

Some test code:
et = ExactTarget('<user>', '<pass>')
et.data_ext().add_record('Master_Subscribers',
   ['TOKEN', 'EMAIL_ADDRESS_', 'CREATED_DATE_', 'MODIFIED_DATE_'],
   ['hello', 'jlong@mozilla.com', '2011-01-01', '2011-01-01'])
et.trigger_send('WelcomeEmail', 'jlong@mozilla.com', 'hello', 'H')
"""

import os
from functools import wraps

from django.conf import settings
from django.core.cache import cache

from suds import WebFault
from suds.cache import Cache
from suds.client import Client
from suds.transport.https import HttpAuthenticated
from suds.wsse import Security, UsernameToken

from .common import NewsletterException, NewsletterNoResultsException, \
    UnauthorizedException


ET_TIMEOUT = getattr(settings, 'EXACTTARGET_TIMEOUT', 20)


class SudsDjangoCache(Cache):
    """
    Implement the suds cache interface using Django caching.
    """
    def __init__(self, days=None, *args, **kwargs):
        if days:
            self.timeout = 24 * 60 * 60 * days
        else:
            self.timeout = None

    def _cache_key(self, id):
        return "suds-%s" % id

    def get(self, id):
        return cache.get(self._cache_key(id))

    def put(self, id, value):
        cache.set(self._cache_key(id), value, self.timeout)

    def purge(self, id):
        cache.delete(self._cache_key(id))


def assert_status(obj):
    """Make sure the returned status is OK"""
    if obj.OverallStatus != 'OK':
        if hasattr(obj, 'Results') and len(obj.Results) > 0:
            res = obj.Results[0]

            if hasattr(res, 'ErrorMessage') and res.ErrorMessage:
                raise NewsletterException(res.ErrorMessage)
            elif hasattr(res, 'ValueErrors') and res.ValueErrors:
                # For some reason, the value errors array is inside an array
                val_errs = res.ValueErrors[0]
                if len(val_errs) > 0:
                    raise NewsletterException(val_errs[0].ErrorMessage)
            elif hasattr(res, 'StatusCode') and res.StatusCode == 'Error':
                raise NewsletterException(res.StatusMessage)
        raise NewsletterException(obj.OverallStatus)


def assert_result(obj):
    """Make sure the returned object has a result"""
    if not hasattr(obj, 'Results') or len(obj.Results) == 0:
        raise NewsletterNoResultsException('No results returned')


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
            # Try to re-use existing client instance.
            inst.client = getattr(logged_in, 'cached_client', None)
        if not inst.client:
            # Monkey-patch suds because it always initializes an ObjectCache
            # before looking at the cache you told it to use, and that tries
            # to use the same subdir under /tmp even if it already exists
            # and is owned by another user.
            # While we're at it, use Django caching instead of temp files.
            import suds.client
            suds.client.ObjectCache = SudsDjangoCache

            wsdl_file_name = ('et-sandbox-wsdl.txt' if settings.EXACTTARGET_USE_SANDBOX
                              else 'et-wsdl.txt')

            # This is just a cached version. The real URL is:
            # https://webservice.s4.exacttarget.com/etframework.wsdl
            #
            # The cached version has been stripped down to make suds run 1000x
            # faster. I deleted most of the fields in the TriggeredSendDefinition
            # and TriggeredSend objects that we don't use.
            wsdl_url = 'file://{0}/{1}'.format(os.path.dirname(os.path.abspath(__file__)),
                                               wsdl_file_name)

            security = Security()
            token = UsernameToken(inst.user, inst.pass_)
            security.tokens.append(token)
            inst.client = Client(wsdl_url, wsse=security,
                                 transport=HttpAuthenticated(timeout=ET_TIMEOUT))

            # Save client instance and just re-use it next time.
            setattr(logged_in, 'cached_client', inst.client)
        return f(inst, *args, **kwargs)
    return wrapper


class ExactTargetObject(object):

    def __init__(self, user, pass_, client=None):
        self.client = client
        self.user = user
        self.pass_ = pass_

    def create(self, name, **kwargs):
        obj = self.client.factory.create(name)
        for key in kwargs:
            setattr(obj, key, kwargs[key])
        return obj


class ExactTargetList(ExactTargetObject):

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


class ExactTargetDataExt(ExactTargetObject):

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

        opt = self.create('SaveOption')
        opt.PropertyName = '*'
        opt.SaveAction = 'UpdateAdd'

        self.create('RequestType')
        opts = self.create('UpdateOptions')
        opts.SaveOptions.SaveOption = [opt]

        try:
            obj = self.client.service.Update(opts, objs)
            assert_status(obj)
        except WebFault, e:
            handle_fault(e)

    @logged_in
    def get_record(self, data_id, token, fields, field='TOKEN'):
        req = self.create('RetrieveRequest')
        req.ObjectType = 'DataExtensionObject[%s]' % data_id
        req.Properties = fields

        filter_ = self.create('SimpleFilterPart')
        filter_.Value = token
        filter_.SimpleOperator = 'equals'
        filter_.Property = field
        req.Filter = filter_

        del req.Options

        try:
            obj = self.client.service.Retrieve(req)
            assert_status(obj)
            assert_result(obj)
        except WebFault, e:
            handle_fault(e)

        # FIXME: Exact Target could have returned multiple results, but we
        # only return the first one here. This is a place we could try to
        # fix data duplication.

        return dict((p.Name, p.Value)
                    for p in obj.Results[0].Properties.Property)

    @logged_in
    def delete_record(self, data_id, token):
        """
        Delete record with token ``token`` from data extension ``data_id``
        """

        # See:
        #  Delete method: http://help.exacttarget.com/en/technical_library/web_service_guide/methods/delete/
        #  Data Extension Object: http://help.exacttarget.com/en/technical_library/web_service_guide/objects/dataextensionobject/
        #  Example: http://help.exacttarget.com/en/technical_library/web_service_guide/technical_articles/deleting_a_row_from_a_data_extension_via_the_web_service_api/

        # We need an array of APIObject objects.
        # DataExtensionObject is a subclass of APIObject.
        # CustomerKey is the external Key of the Data Extension from the UI.
        deo = self.create('DataExtensionObject',
                          CustomerKey=data_id,
                          )
        # Which record is it
        key = self.create('APIProperty',
                          Name='TOKEN',
                          Value=token)
        # Yes, "Keys" is a scalar with a "Key" that is a sequence of keys.
        # Only in SOAP.
        deo.Keys.Key = [key]

        # A DeleteOptions object is required, but need not have anything in it.
        opts = self.create("DeleteOptions")

        try:
            obj = self.client.service.Delete(opts, [deo])
            assert_status(obj)
            assert_result(obj)
        except WebFault, e:
            handle_fault(e)


class ExactTarget(ExactTargetObject):

    @logged_in
    def list(self):
        return ExactTargetList(self.user, self.pass_, self.client)

    @logged_in
    def data_ext(self):
        return ExactTargetDataExt(self.user, self.pass_, self.client)

    @logged_in
    def trigger_send(self, send_name, fields):
        send = self.create('TriggeredSend')
        defn = send.TriggeredSendDefinition

        status = self.create('TriggeredSendStatusEnum')
        defn.Name = send_name
        defn.CustomerKey = send_name
        defn.TriggeredSendStatus = status.Active

        sub = self.create('Subscriber')
        sub.EmailAddress = fields.pop('EMAIL_ADDRESS_')
        sub.SubscriberKey = fields['TOKEN']
        sub.EmailTypePreference = ('HTML'
                                   if fields['EMAIL_FORMAT_'] == 'H'
                                   else 'Text')
        del sub.Status

        for k, v in fields.items():
            attr = self.create('Attribute')
            attr.Name = k
            attr.Value = v
            sub.Attributes.append(attr)

        send.Subscribers = [sub]

        self.create('RequestType')
        opts = self.create('CreateOptions')

        try:
            obj = self.client.service.Create(opts, [send])
            assert_status(obj)
            assert_result(obj)
        except WebFault, e:
            handle_fault(e)

    @logged_in
    def trigger_send_sms(self, send_name, mobile_number):
        send = self.create('SMSTriggeredSend')
        send.Number = mobile_number
        defn = send.SMSTriggeredSendDefinition
        defn.Name = send_name
        defn.CustomerKey = send_name

        sub = self.create('Subscriber')
        sub.SubscriberKey = mobile_number
        sub.EmailTypePreference = 'Text'

        del sub.Status

        send.Subscriber = sub

        self.create('RequestType')
        opts = self.create('CreateOptions')

        try:
            obj = self.client.service.Create(opts, [send])
            assert_status(obj)
            assert_result(obj)
        except WebFault, e:
            handle_fault(e)

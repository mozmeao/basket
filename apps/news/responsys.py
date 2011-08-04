from functools import wraps

from suds import WebFault
from suds.client import Client


class UnauthorizedException(Exception):
    """Failure to log into Responsys."""
    pass


class NewsletterException(Exception):
    """Error when trying to talk to Responsys"""
    pass


def logged_in(f):
    """ Decorator to ensure an authenticated session with Responsys
    before calling a function """

    @wraps(f)
    def wrapper(inst, *args, **kwargs):
        if not inst.session:
            raise UnauthorizedException("Not logged in to Responsys, "
                                        "must call login()")
        return f(inst, *args, **kwargs)
    return wrapper


def fault_msg(fault):
    if hasattr(fault.detail, 'ListFault'):
        return fault.detail.ListFault.exceptionMessage
    return str(fault.detail)


class Responsys(object):
    WSDL_URL = 'https://ws2.responsys.net/webservices/wsdl/ResponsysWS_Level1.wsdl'

    def __init__(self):
        self.client = None
        self.session = None

    def login(self, user, pass_):
        """ Login and create a Responsys session, returns False on
        failure """

        if not self.client:
            self.client = Client(self.__class__.WSDL_URL)
        elif self.session:
            self.logout()

        try:
            res = self.client.service.login(user, pass_)
        except WebFault, e:
            return False

        self.session = res['sessionId']

        # Set auth token for all requests
        header = self.client.factory.create('SessionHeader')
        header.sessionId = self.session
        self.client.set_options(soapheaders=header)

    @logged_in
    def logout(self):
        """ Logout and expire the current Responsys session """

        self.client.service.logout()
        self.session = None

    @logged_in
    def merge_list_members(self, folder, list_, fields, records):
        """
        Add data to the list located at <folder>/<list_> in
        Responsys.

        <fields> is an array of field names
        <records> is a single record or an array of records to insert
        (record = array). If the email already exists, its data will
        be updated
        """

        client = self.client
        records = [records] if isinstance(records[0], basestring) else records

        def make_record(record):
            data = client.factory.create('Record')
            data.fieldValues = record
            return data

        target = client.factory.create('InteractObject')
        target.folderName = folder
        target.objectName = list_

        data = client.factory.create('RecordData')
        data.fieldNames = fields
        data.records = [make_record(r) for r in records]

        # Configure the action to update the data when it matches on
        # the email address field, otherwise insert a new entry, and
        # default opt in
        rule = client.factory.create('ListMergeRule')
        rule.insertOnNoMatch = True
        rule.updateOnMatch = 'REPLACE_ALL'
        rule.matchColumnName1 = 'EMAIL_ADDRESS_'
        rule.matchOperator = 'NONE'
        rule.optinValue = 'I'
        rule.optoutValue = 'O'
        rule.htmlValue = 'H'
        rule.textValue = 'T'
        rule.rejectRecordIfChannelEmpty = 'E'
        rule.defaultPermissionStatus = 'OPTIN'
        
        try:
            client.service.mergeListMembers(target, data, rule)
        except WebFault, e:
            raise NewsletterException(fault_msg(e.fault))
    
    @logged_in
    def retrieve_list_members(self, emails, folder, list_, fields):
        emails = [emails] if isinstance(emails, basestring) else emails
        client = self.client

        target = client.factory.create('InteractObject')
        target.folderName = folder
        target.objectName = list_

        try:
            user = client.service.retrieveListMembers(target,
                                                      'EMAIL_ADDRESS',
                                                      fields,
                                                      emails)
        except WebFault, e:
            raise NewsletterException(fault_msg(e.fault))

        values = user.recordData.records[0].fieldValues
        return dict(zip(fields, values))

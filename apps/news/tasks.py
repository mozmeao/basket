import uuid
from email.utils import formatdate
import datetime
from time import mktime
from datetime import date

from django.conf import settings
from celery.task import task

from backends.exacttarget import (ExactTarget, ExactTargetDataExt,
                                  NewsletterException, UnauthorizedException)
from models import Subscriber
from newsletters import *


# A few constants to indicate the type of action to take
# on a user with a list of newsletters
SUBSCRIBE = 1
UNSUBSCRIBE = 2
SET = 3


# Double optin-in languages
CONFIRM_SENDS = {
    'es': 'es_confirmation_email',
    'es-ES': 'es_confirmation_email',
    'de': 'de_confirmation_email',
    'fr': 'fr_confirmation_email',
    'id': 'id_confirmation_email',
    'pt': 'pt_br_confirmation_email',
    'pt-BR': 'pt_br_confirmation_email',
    'ru': 'ru_confirmation_email_2',
}
SMS_MESSAGES = (
    'SMS_Android',
)


def gmttime():
    d = datetime.datetime.now() + datetime.timedelta(minutes=10)
    stamp = mktime(d.timetuple())
    return formatdate(timeval=stamp, localtime=False, usegmt=True)


def parse_newsletters(record, type, newsletters):
    """Utility function to take a list of newsletters and according
    the type of action (subscribe, unsubscribe, and set) set the
    appropriate flags in `record` which is a dict of parameters that
    will be sent to the email provider."""

    newsletters = [x.strip() for x in newsletters.split(',')]

    if type == SUBSCRIBE or type == SET:
        # Subscribe the user to these newsletters
        for nl in newsletters:
            name = newsletter_field(nl)
            if name:
                record['%s_FLG' % name] = 'Y'
                record['%s_DATE' % name] = date.today().strftime('%Y-%m-%d')

    if type == UNSUBSCRIBE or type == SET:
        # Unsubscribe the user to these newsletters
        unsubs = newsletters

        if type == SET:
            # Unsubscribe to the inversion of these newsletters
            subs = set(newsletters)
            all = set(newsletter_names())
            unsubs = all.difference(subs)

        for nl in unsubs:
            name = newsletter_field(nl)
            if name:
                record['%s_FLG' % name] = 'N'
                record['%s_DATE' % name] = date.today().strftime('%Y-%m-%d')


@task(default_retry_delay=60)  # retry in 1 minute on failure
def update_user(data, email, token, created, type, optin):
    """Task for updating user's preferences and newsletters.

    ``authed_email`` is the email for the user pulled from the database
    with their token, if exists."""

    log = update_user.get_logger()

    # Parse the parameters
    record = {
        'EMAIL_ADDRESS_': email,
        'TOKEN': token,
        'EMAIL_PERMISSION_STATUS_': 'I',
        'MODIFIED_DATE_': gmttime(),
    }
    if created:
        record['CREATED_DATE_'] = gmttime()

    extra_fields = {
        'country': 'COUNTRY_',
        'lang': 'LANGUAGE_ISO2',
        'source_url': 'SOURCE_URL',
    }

    # Optionally add more fields
    for field in extra_fields:
        if field in data:
            record[extra_fields[field]] = data[field]

    fmt = data.get('format', 'H').lower()
    if fmt == 'text':
        fmt = 'T'
    elif fmt == 'html':
        fmt = 'H'

    record['EMAIL_FORMAT_'] = fmt.upper()

    # Set the newsletter flags in the record
    parse_newsletters(record, type, data.get('newsletters', ''))

    # Submit the final data to the service
    et = ExactTarget(settings.EXACTTARGET_USER, settings.EXACTTARGET_PASS)
    lang = record.get('LANGUAGE_ISO2', None)

    target_et = settings.EXACTTARGET_DATA
    welcome = None

    if lang in CONFIRM_SENDS and type == SUBSCRIBE:
        # This lang requires double opt-in and a different welcome
        # email
        target_et = settings.EXACTTARGET_OPTIN_STAGE
        welcome = CONFIRM_SENDS[lang]
        record['SubscriberKey'] = record['TOKEN']
        record['EmailAddress'] = record['EMAIL_ADDRESS_']
    elif data.get('trigger_welcome', 'Y') == 'Y' and type == SUBSCRIBE:
        # Otherwise, send this welcome email unless its suppressed
        # This is the CustomerKey of the en-US welcome email
        welcome = '39'

    try:
        et.data_ext().add_record(target_et, record.keys(), record.values())
    except (NewsletterException, UnauthorizedException), e:
        return handle_exception_and_fix(target_et, record, update_user, e)

    # This is a separate try because the above one might recover, and
    # we still need to send the welcome email
    try:
        if welcome:
            et.trigger_send(welcome, {
                'EMAIL_ADDRESS_': record['EMAIL_ADDRESS_'],
                'TOKEN': record['TOKEN'],
                'EMAIL_FORMAT_': record.get('EMAIL_FORMAT_', 'H'),
            })
    except (NewsletterException, UnauthorizedException), e:
        return handle_exception(update_user, e)


@task(default_retry_delay=60)
def confirm_user(token):
    try:
        ext = ExactTargetDataExt(settings.EXACTTARGET_USER,
                                 settings.EXACTTARGET_PASS)
        ext.add_record('Confirmation', ['TOKEN'], [token])
    except (NewsletterException, UnauthorizedException), e:
        handle_exception(confirm_user, e)


@task(default_retry_delay=60)
def update_student_reps(data):
    data.pop('privacy')
    fmt = data.pop('format', 'H')
    country = data.pop('country')
    email = data.pop('email')

    fmt = fmt.lower()
    if fmt == 'text':
        fmt = 'T'
    elif fmt == 'html':
        fmt = 'H'

    # Get the user or create them
    (sub, created) = Subscriber.objects.get_or_create(email=email)

    # Create a token if it's a new user
    if created:
        sub.token = str(uuid.uuid4())
        data['TOKEN'] = sub.token
        sub.save()
    else:
        data['TOKEN'] = sub.token

    data['STUDENT_REPS_FLG'] = data.get('STUDENT_REPS_FLG', 'N')
    data['STUDENT_REPS_DATE'] = gmttime()
    data['STUDENT_REPS_MEMBER_FLG'] = 'Y'
    data['STUDENT_REPS_MEMBER_DATE'] = gmttime()
    data['EMAIL_FORMAT_'] = fmt
    data['EMAIL_ADDRESS'] = email

    try:
        et = ExactTarget(settings.EXACTTARGET_USER, settings.EXACTTARGET_PASS)
        ext = et.data_ext()
        ext.add_record('Student_Reps',
                       data.keys(),
                       data.values())
        et.trigger_send(893, {
            'EMAIL_ADDRESS_': email,
            'TOKEN': data['TOKEN'],
            'EMAIL_FORMAT_': fmt,
            'STUDENT_REPS_FLG': data['STUDENT_REPS_FLG'],
            'STUDENT_REPS_MEMBER_FLG': data['STUDENT_REPS_MEMBER_FLG'],
            'FIRST_NAME': data['FIRST_NAME'],
        })
    except (NewsletterException, UnauthorizedException), e:
        return handle_exception(update_student_reps, e)

    # Need to add the user to the Master_Subscriber table now
    record = {
        'EMAIL_ADDRESS_': email,
        'TOKEN': data['TOKEN'],
        'STUDENT_REPS_FLG': data.get('STUDENT_REPS_FLG', 'N'),
        'STUDENT_REPS_DATE': data['STUDENT_REPS_DATE'],
        'MODIFIED_DATE_': gmttime(),
    }

    if created:
        record['CREATED_DATE_'] = gmttime()

    try:
        ext.add_record('Master_Subscribers',
                       record.keys(),
                       record.values())
    except (NewsletterException, UnauthorizedException), e:
        return handle_exception_and_fix('Master_Subscribers',
                                        record,
                                        update_student_reps,
                                        e)


@task(default_retry_delay=60)
def add_sms_user(send_name, mobile_number, optin):
    if send_name not in SMS_MESSAGES:
        return
    et = ExactTarget(settings.EXACTTARGET_USER, settings.EXACTTARGET_PASS)
    try:
        et.trigger_send_sms(send_name, mobile_number)
        if optin:
            record = {'Phone': mobile_number, 'SubscriberKey': mobile_number}
            et.data_ext().add_record('Mobile_Subscribers',
                                     record.keys(),
                                     record.values())
    except (NewsletterException, UnauthorizedException), e:
        handle_exception(add_sms_user, e)


def handle_exception_and_fix(ext_name, record, task, e):
    # Sometimes a user is in basket's database but not in
    # ExactTarget because the API failed or something. If that's
    # the case, any future API call will error because basket
    # won't add the required CREATED_DATE field. Try to add them
    # with it here.
    if e.message.find('CREATED_DATE_') != -1:
        record['CREATED_DATE_'] = gmttime()
        ext = ExactTargetDataExt(settings.EXACTTARGET_USER,
                                 settings.EXACTTARGET_PASS)
        ext.add_record(ext_name, record.keys(), record.values())
    else:
        return handle_exception(task, e)


def handle_exception(task, e):
    # When celery is turn on, hande these exceptions here. Since
    # celery isn't turned on yet, let them propagate.
    #
    # if isinstance(e, URLError):
    #     # URL timeout, try again
    #     task.retry(exc=e)
    # elif isinstance(e, NewsletterException):
    #     log.error('NewsletterException: %s' % e.message)
    # elif isinstance(e, UnauthorizedException):
    #     log.error('Email service provider auth failure')
    raise e

from functools import wraps
import json
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email as dj_validate_email
from django.http import HttpResponse
from django.utils.encoding import force_unicode
from django.utils.translation.trans_real import parse_accept_lang_header

# Get error codes from basket-client so users see the same definitions
from basket import errors

from news.backends.common import NewsletterNoResultsException
from news.backends.exacttarget import (ExactTargetDataExt, NewsletterException,
                                       UnauthorizedException)
from news.models import APIUser, Subscriber
from news.newsletters import (newsletter_fields, newsletter_languages, newsletter_slugs,
                              slug_to_vendor_id)


## Error messages
MSG_TOKEN_REQUIRED = 'Must have valid token for this request'
MSG_EMAIL_OR_TOKEN_REQUIRED = 'Must have valid token OR email for this request'
MSG_USER_NOT_FOUND = 'User not found'


class HttpResponseJSON(HttpResponse):
    def __init__(self, data, status=None):
        super(HttpResponseJSON, self).__init__(content=json.dumps(data),
                                               content_type='application/json',
                                               status=status)


class EmailValidationError(ValidationError):
    def __init__(self, message, suggestion=None):
        super(EmailValidationError, self).__init__(message)
        self.suggestion = suggestion


def has_valid_api_key(request):
    # The API key could be the query parameter 'api-key' or the
    # request header 'X-api-key'.

    api_key = request.REQUEST.get('api-key', None) or\
        request.META.get('HTTP_X_API_KEY', None)
    return APIUser.is_valid(api_key)


def lookup_subscriber(token=None, email=None):
    """
    Find or create Subscriber object for given token and/or email.

    If we don't already have a Basket Subscriber record, we check
    in ET to see if we know about this user there.  If they exist in
    ET, we create a new Basket Subscriber record with the information
    from ET. If they don't exist in ET, and we were given an email,
    we create a new Subscriber record with the given email and make
    up a new token for them.

    # FIXME: when we create a new token for a new email, maybe we
    should put that in ET right away. Though we couldn't put that in
    any of our three existing tables, so we either need a
    fourth one for users who are neither confirmed nor pending, or
    to come up with another solution.

    If we are only given a token, and cannot find any user with that
    token in Basket or ET, then the returned subscriber is None.

    Returns (Subscriber, user_data, created).

    The user_data is only provided if we had to ask ET about this
    email/token (and found it there); otherwise, it's None.
    """
    if not (token or email):
        raise Exception(MSG_EMAIL_OR_TOKEN_REQUIRED)
    kwargs = {}
    if token:
        kwargs['token'] = token
    if email:
        kwargs['email'] = email
    user_data = None
    try:
        subscriber = Subscriber.objects.get(**kwargs)
    except Subscriber.DoesNotExist:
        # Note: If both token and email were passed in, it would be possible
        # that subscribers exist that match one or the other but not both.
        # But currently no callers pass both, so luckily we don't have to
        # figure out what we would do in that case.
        created = True
        # Check with ET to see if our DB is just out of sync
        user_data = get_user_data(sync_data=True, **kwargs)
        if user_data and user_data['status'] == 'ok':
            # Found them in ET and updated subscriber db locally
            subscriber = Subscriber.objects.get(**kwargs)
        else:
            # Not in ET. If we have an email, create a new basket
            # record for them
            if email:
                # It's barely possible the subscriber has been created
                # since we checked, so play it safe and get_or_create.
                # (Yes, this has been seen.)
                subscriber, created = Subscriber.objects.\
                    get_or_create(email=email)
            else:
                # No email?  Just token? Token not known in basket or ET?
                # That's an error.
                subscriber = None
    else:
        created = False
    return subscriber, user_data, created


def newsletter_exception_response(exc):
    """Convert a NewsletterException into a JSON HTTP response."""
    return HttpResponseJSON({
        'status': 'error',
        'code': exc.error_code or errors.BASKET_UNKNOWN_ERROR,
        'desc': str(exc),
    }, exc.status_code or 400)


def logged_in(f):
    """Decorator to check if the user has permission to view these
    pages"""

    @wraps(f)
    def wrapper(request, token, *args, **kwargs):
        try:
            subscriber, subscriber_data, created = lookup_subscriber(token=token)
        except NewsletterException as e:
            return newsletter_exception_response(e)

        if not subscriber:
            return HttpResponseJSON({
                'status': 'error',
                'desc': MSG_TOKEN_REQUIRED,
                'code': errors.BASKET_USAGE_ERROR,
            }, 403)

        request.subscriber_data = subscriber_data
        request.subscriber = subscriber
        return f(request, token, *args, **kwargs)
    return wrapper


LANG_RE = re.compile(r'^[a-z]{2,3}(?:-[a-z]{2})?$', re.IGNORECASE)


def language_code_is_valid(code):
    """Return True if ``code`` looks like a language code.

    So it must be either 2 (or 3) alpha characters, or 2 pairs of 2
    characters separated by a dash. It will also
    accept the empty string.

    Raises TypeError if anything but a string is passed in.
    """
    if not isinstance(code, basestring):
        raise TypeError("Language code must be a string")

    if code == '':
        return True
    else:
        return bool(LANG_RE.match(code))


def update_user_task(request, api_call_type, data=None, optin=True, sync=False):
    """Call the update_user task async with the right parameters.

    If sync==True, be sure to do the update synchronously and include the token
    in the response.  Otherwise, basket has the option to do it all later
    in the background.
    """
    from news.tasks import update_user

    sub = getattr(request, 'subscriber', None)
    data = data or request.POST.dict()

    newsletters = data.get('newsletters', None)
    if newsletters:
        all_newsletters = newsletter_slugs()
        for nl in [x.strip() for x in newsletters.split(',')]:
            if nl not in all_newsletters:
                return HttpResponseJSON({
                    'status': 'error',
                    'desc': 'invalid newsletter',
                    'code': errors.BASKET_INVALID_NEWSLETTER,
                }, 400)

    if 'lang' in data and not language_code_is_valid(data['lang']):
        return HttpResponseJSON({
            'status': 'error',
            'desc': 'invalid language',
            'code': errors.BASKET_INVALID_LANGUAGE,
        }, 400)

    email = data.get('email', sub.email if sub else None)
    if not email:
        return HttpResponseJSON({
            'status': 'error',
            'desc': MSG_EMAIL_OR_TOKEN_REQUIRED,
            'code': errors.BASKET_USAGE_ERROR,
        }, 400)

    if sync:
        if sub:
            created = False
        else:
            # We need a token for this user. If we don't have a Subscriber
            # object for them already, we'll need to find or make one,
            # checking ET first if need be.
            sub, user_data, created = lookup_subscriber(email=email)

        update_user.delay(data, sub.email, sub.token, api_call_type, optin)
        return HttpResponseJSON({
            'status': 'ok',
            'token': sub.token,
            'created': created,
        })
    else:
        update_user.delay(data, email, None, api_call_type, optin)
        return HttpResponseJSON({
            'status': 'ok',
        })


def look_for_user(database, email, token, fields):
    """Try to get the user's data from the specified ET database.
    If found and the database is not the 'Confirmed' database,
    return it (a dictionary, see get_user_data).
    If found and it's the 'Confirmed' database, just return True.
    If not found, return None.
    Any other exception just propagates and needs to be handled
    by the caller.
    """
    ext = ExactTargetDataExt(settings.EXACTTARGET_USER,
                             settings.EXACTTARGET_PASS)
    try:
        user = ext.get_record(database,
                              email or token,
                              fields,
                              'EMAIL_ADDRESS_' if email else 'TOKEN')
    except NewsletterNoResultsException:
        return None
    if database == settings.EXACTTARGET_CONFIRMATION:
        return True
    newsletters = []
    for slug in newsletter_slugs():
        vendor_id = slug_to_vendor_id(slug)
        flag = "%s_FLG" % vendor_id
        if user.get(flag, 'N') == 'Y':
            newsletters.append(slug)
    user_data = {
        'status': 'ok',
        'email': user['EMAIL_ADDRESS_'],
        'format': user['EMAIL_FORMAT_'] or 'H',
        'country': user['COUNTRY_'] or '',
        'lang': user['LANGUAGE_ISO2'] or '',  # Never None
        'token': user['TOKEN'],
        'created-date': user['CREATED_DATE_'],
        'newsletters': newsletters,
    }
    return user_data


def get_user_data(token=None, email=None, sync_data=False):
    """Return a dictionary of the user's data from Exact Target.
    Look them up by their email if given, otherwise by the token.

    If sync_data is set, create or update our local basket record
    if needed so we have a record of this email and the token that
    goes with it.

    Look first for the user in the master subscribers database, then in the
    optin database.

    If they're not in the master subscribers database but are in the
    optin database, then check the confirmation database too.  If we
    find them in either the master subscribers or confirmation database,
    add 'confirmed': True to their data; otherwise, 'confirmed': False.
    Also, ['pending'] is True if they are in the double-opt-in database
    and not in the confirmed or master databases.

    If the user was not found, return None instead of a dictionary.

    If there was an error, result['status'] == 'error'
    and result['desc'] has more info;
    otherwise, result['status'] == 'ok'

    Review of results:

    None = user completely unknown, no errors talking to ET.

    otherwise, return value is::

    {
        'status':  'ok',      # no errors talking to ET
        'status':  'error',   # errors talking to ET, see next field
        'desc':  'error message'   # details if status is error
        'email': 'email@address',
        'format': 'T'|'H',
        'country': country code,
        'lang': language code,
        'token': UUID,
        'created-date': date created,
        'newsletters': list of slugs of newsletters subscribed to,
        'confirmed': True if user has confirmed subscription (or was excepted),
        'pending': True if we're waiting for user to confirm subscription
        'master': True if we found them in the master subscribers table
    }


    """
    newsletters = newsletter_fields()

    fields = [
        'EMAIL_ADDRESS_',
        'EMAIL_FORMAT_',
        'COUNTRY_',
        'LANGUAGE_ISO2',
        'TOKEN',
        'CREATED_DATE_',
    ]

    for nl in newsletters:
        fields.append('%s_FLG' % nl)

    confirmed = True
    pending = False
    master = True
    try:
        # Look first in the master subscribers database for the user
        user_data = look_for_user(settings.EXACTTARGET_DATA,
                                  email, token, fields)
        # If we get back a user, then they have already confirmed.

        # If not, look for them in the database of unconfirmed users.
        if user_data is None:
            master = False
            confirmed = False
            user_data = look_for_user(settings.EXACTTARGET_OPTIN_STAGE,
                                      email, token, fields)
            if user_data is None:
                # No such user, as far as we can tell - if they're in
                # neither the master subscribers nor optin database,
                # we don't know them.
                return None

            # We found them in the optin database. But actually, they
            # might have confirmed but the batch job hasn't
            # yet run to move their data to the master subscribers
            # database; catch that case here by looking for them in the
            # Confirmed database.  Do it simply; the confirmed database
            # doesn't have most of the user's data, just their token.
            if look_for_user(settings.EXACTTARGET_CONFIRMATION,
                             email, token, ['Token']):
                # Ah-ha, they're in the Confirmed DB so they did confirm
                confirmed = True

        user_data['confirmed'] = confirmed
        user_data['pending'] = pending
        user_data['master'] = master
    except NewsletterException as e:
        raise NewsletterException(str(e),
                                  error_code=errors.BASKET_NETWORK_FAILURE,
                                  status_code=400)
    except UnauthorizedException:
        raise NewsletterException('Email service provider auth failure',
                                  error_code=errors.BASKET_EMAIL_PROVIDER_AUTH_FAILURE,
                                  status_code=500)

    # We did find a user
    if sync_data:
        # if user not in our db create it, if token mismatch fix it.
        Subscriber.objects.get_and_sync(user_data['email'], user_data['token'])

    return user_data


def get_user(token=None, email=None, sync_data=False):
    try:
        user_data = get_user_data(token, email, sync_data)
        status_code = 200
    except NewsletterException as e:
        return newsletter_exception_response(e)

    if user_data is None:
        user_data = {
            'status': 'error',
            'code': errors.BASKET_UNKNOWN_EMAIL if email else errors.BASKET_UNKNOWN_TOKEN,
            'desc': 'Unable to find user.'
        }
        status_code = 400
    return HttpResponseJSON(user_data, status_code)


def get_accept_languages(header_value):
    """
    Parse the user's Accept-Language HTTP header and return a list of languages
    """
    # adapted from bedrock: http://j.mp/1o3pWo5
    languages = []
    pattern = re.compile(r'^([A-Za-z]{2,3})(?:-([A-Za-z]{2})(?:-[A-Za-z0-9]+)?)?$')

    try:
        parsed = parse_accept_lang_header(header_value)
    except ValueError:  # see https://code.djangoproject.com/ticket/21078
        return languages

    for lang, priority in parsed:
        m = pattern.match(lang)

        if not m:
            continue

        lang = m.group(1).lower()

        # Check if the shorter code is supported. This covers obsolete long
        # codes like fr-FR (should match fr) or ja-JP (should match ja)
        if m.group(2) and lang not in newsletter_languages():
            lang += '-' + m.group(2).upper()

        if lang not in languages:
            languages.append(lang)

    return languages


def get_best_language(languages):
    """
    Return the best language for use with our newsletters. If none match, return first in list.

    @param languages: list of language codes.
    @return: a single language code
    """
    if not languages:
        return None

    supported_langs = newsletter_languages()
    for lang in languages:
        if lang in supported_langs:
            return lang

    return languages[0]


def validate_email(email):
    """Validates that the email is valid.

    Returns None on success and raises a ValidationError if
    invalid. The exception will have a 'suggestion' parameter
    that will contain the suggested email address or None.

    @param email: unicode string, email address hopefully
    @return: None if email address in the 'email' key is valid
    @raise: EmailValidationError if 'email' key is invalid
    """
    # disabling this for now and falling back to dumb regex validation.
    # Bug 1066762.
    # TODO: Find a more robust solution
    #       Possibly ET's email validation API.
    try:
        dj_validate_email(force_unicode(email))
    except ValidationError:
        raise EmailValidationError('Invalid email address')

    return None

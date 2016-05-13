import json
import re
from datetime import date
from itertools import chain
from uuid import uuid4

from django.conf import settings
from django.core.cache import get_cache
from django.core.exceptions import ValidationError
from django.core.validators import validate_email as dj_validate_email
from django.http import HttpResponse
from django.utils.encoding import force_unicode
from django.utils.translation.trans_real import parse_accept_lang_header


# Get error codes from basket-client so users see the same definitions
from basket import errors

from news.backends.common import (
    NewsletterException,
    NewsletterNoResultsException,
    UnauthorizedException,
)
from news.backends.sfmc import sfmc
from news.models import APIUser, BlockedEmail
from news.newsletters import (
    newsletter_field,
    newsletter_fields,
    newsletter_group_newsletter_slugs,
    newsletter_languages,
    newsletter_slugs,
    slug_to_vendor_id,
)


# Error messages
MSG_TOKEN_REQUIRED = 'Must have valid token for this request'
MSG_EMAIL_OR_TOKEN_REQUIRED = 'Must have valid token OR email for this request'
MSG_USER_NOT_FOUND = 'User not found'

# A few constants to indicate the type of action to take
# on a user with a list of newsletters
# (Use strings so when we log function args, they make sense.)
SUBSCRIBE = 'SUBSCRIBE'
UNSUBSCRIBE = 'UNSUBSCRIBE'
SET = 'SET'

email_block_list_cache = get_cache('email_block_list')


def generate_token():
    return str(uuid4())


class HttpResponseJSON(HttpResponse):
    def __init__(self, data, status=None):
        super(HttpResponseJSON, self).__init__(content=json.dumps(data),
                                               content_type='application/json',
                                               status=status)


class EmailValidationError(ValidationError):
    def __init__(self, message, suggestion=None):
        super(EmailValidationError, self).__init__(message)
        self.suggestion = suggestion


def get_email_block_list():
    """Return a list of blocked email domains."""
    cache_key = 'email_block_list'
    block_list = email_block_list_cache.get(cache_key)
    if block_list is None:
        block_list = list(BlockedEmail.objects.values_list('email_domain', flat=True))
        email_block_list_cache.set(cache_key, block_list)

    return block_list


def email_is_blocked(email):
    """Check an email and return True if blocked."""
    for blocked in get_email_block_list():
        if email.endswith(blocked):
            return True

    return False


def has_valid_api_key(request):
    # The API key could be the query parameter 'api-key' or the
    # request header 'X-api-key'.

    api_key = (request.REQUEST.get('api-key', None) or
               request.REQUEST.get('api_key', None) or
               request.META.get('HTTP_X_API_KEY', None))
    return APIUser.is_valid(api_key)


def get_or_create_user_data(token=None, email=None):
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
    token in Basket or ET, then the returned user_data is None.

    Returns (user_data, created).
    """
    kwargs = {}
    if token:
        kwargs['token'] = token
    elif email:
        kwargs['email'] = email
    else:
        raise Exception(MSG_EMAIL_OR_TOKEN_REQUIRED)

    # Note: If both token and email were passed in we use the token as it is the most explicit.

    # NewsletterException uncaught here on purpose
    user_data = get_user_data(**kwargs)
    if user_data and user_data['status'] == 'ok':
        # Found them in ET and updated subscriber db locally
        created = False

    # Not in ET. If we have an email, generate a token.
    elif email:
        user_data = {
            'email': email,
            'token': generate_token(),
            'master': False,
            'pending': False,
            'confirmed': False,
            'lang': '',
            'status': 'ok',
        }
        created = True
    else:
        # No email?  Just token? Token not known in basket or ET?
        # That's an error.
        user_data = created = None

    return user_data, created


def newsletter_exception_response(exc):
    """Convert a NewsletterException into a JSON HTTP response."""
    return HttpResponseJSON({
        'status': 'error',
        'code': exc.error_code or errors.BASKET_UNKNOWN_ERROR,
        'desc': str(exc),
    }, exc.status_code or 400)


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


def look_for_user(database, email, token, fields):
    """Try to get the user's data from the specified ET database.
    If found and the database is not the 'Confirmed' database,
    return it (a dictionary, see get_user_data).
    If found and it's the 'Confirmed' database, just return True.
    If not found, return None.
    Any other exception just propagates and needs to be handled
    by the caller.
    """
    try:
        user = sfmc.get_row(database, fields, token, email)
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


def get_user_data(token=None, email=None):
    """Return a dictionary of the user's data from Exact Target.
    Look them up by their email if given, otherwise by the token.

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
                             None, user_data['token'], ['Token']):
                # Ah-ha, they're in the Confirmed DB so they did confirm
                confirmed = True
            else:
                # They're in the optin db, but not confirmed, so we wait
                pending = True

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

    return user_data


def get_user(token=None, email=None):
    try:
        user_data = get_user_data(token, email)
        status_code = 200
    except NewsletterException as e:
        return newsletter_exception_response(e)

    if user_data is None:
        user_data = {
            'status': 'error',
            'code': errors.BASKET_UNKNOWN_EMAIL if email else errors.BASKET_UNKNOWN_TOKEN,
            'desc': MSG_USER_NOT_FOUND,
        }
        status_code = 404
    return HttpResponseJSON(user_data, status_code)


def get_accept_languages(header_value):
    """
    Parse the user's Accept-Language HTTP header and return a list of languages
    """
    # adapted from bedrock: http://j.mp/1o3pWo5
    languages = []
    pattern = re.compile(r'^([A-Za-z]{2,3})(?:-([A-Za-z]{2})(?:-[A-Za-z0-9]+)?)?$')

    # bug 1102652
    header_value = header_value.replace('_', '-')

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

    # try again with 2 letter languages
    languages_2l = [lang[:2] for lang in languages]
    supported_langs = newsletter_languages()

    for lang in chain(languages, languages_2l):
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


def parse_newsletters(record, api_call_type, newsletters, cur_newsletters):
    """Utility function to take a list of newsletters and according
    the type of action (subscribe, unsubscribe, and set) set the
    appropriate flags in `record` which is a dict of parameters that
    will be sent to the email provider.

    Parameters are only set for the newsletters whose subscription
    status needs to change, so that we don't unnecessarily update the
    last modification timestamp of newsletters.

    :param dict record: Parameters that will be sent to ET
    :param integer api_call_type: SUBSCRIBE means add these newsletters to the
        user's subscriptions if not already there, UNSUBSCRIBE means remove
        these newsletters from the user's subscriptions if there, and SET
        means change the user's subscriptions to exactly this set of
        newsletters.
    :param list newsletters: List of the slugs of the newsletters to be
        subscribed, unsubscribed, or set.
    :param set cur_newsletters: Set of the slugs of the newsletters that
        the user is currently subscribed to. None if there was an error.
    :returns: (to_subscribe, to_unsubscribe) - lists of slugs of the
        newsletters that we will request new subscriptions to, or request
        unsubscription from, respectively.
    """

    to_subscribe = []
    to_unsubscribe = []

    if api_call_type == SUBSCRIBE:
        grouped_newsletters = set()
        for nl in newsletters:
            group_nl = newsletter_group_newsletter_slugs(nl)
            if group_nl:
                grouped_newsletters.update(group_nl)
            else:
                grouped_newsletters.add(nl)

        newsletters = list(grouped_newsletters)

    if api_call_type == SUBSCRIBE or api_call_type == SET:
        # Subscribe the user to these newsletters if not already
        for nl in newsletters:
            name = newsletter_field(nl)
            if name and (cur_newsletters is None or
                                 nl not in cur_newsletters):
                record['%s_FLG' % name] = 'Y'
                record['%s_DATE' % name] = date.today().strftime('%Y-%m-%d')
                to_subscribe.append(nl)

    if api_call_type == UNSUBSCRIBE or api_call_type == SET:
        # Unsubscribe the user to these newsletters

        if api_call_type == SET:
            # Unsubscribe from the newsletters currently subscribed to
            # but not in the new list
            if cur_newsletters is not None:
                unsubs = cur_newsletters - set(newsletters)
            else:
                subs = set(newsletters)
                all = set(newsletter_slugs())
                unsubs = all - subs
        else:  # type == UNSUBSCRIBE
            # unsubscribe from the specified newsletters
            unsubs = newsletters

        for nl in unsubs:
            # Unsubscribe from any unsubs that the user is currently subbed to
            name = newsletter_field(nl)
            if name and (cur_newsletters is None or nl in cur_newsletters):
                record['%s_FLG' % name] = 'N'
                record['%s_DATE' % name] = date.today().strftime('%Y-%m-%d')
                to_unsubscribe.append(nl)
    return to_subscribe, to_unsubscribe

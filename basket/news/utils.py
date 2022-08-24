import json
import re
from datetime import date, datetime
from itertools import chain
from uuid import uuid4

from django.conf import settings
from django.core.cache import caches
from django.http import HttpResponse
from django.utils.encoding import force_str
from django.utils.translation.trans_real import parse_accept_lang_header

import fxa.constants
import fxa.errors
import fxa.oauth
import fxa.profile
import phonenumbers
import requests
import sentry_sdk

# Get error codes from basket-client so users see the same definitions
from basket import errors
from django_statsd.clients import statsd
from email_validator import validate_email, EmailNotValidError

from basket.news.backends.common import NewsletterException
from basket.news.backends.ctms import (
    ctms,
    CTMSError,
    CTMSNotConfigured,
    CTMSNotFoundByAltIDError,
)
from basket.news.models import APIUser, BlockedEmail
from basket.news.newsletters import (
    newsletter_group_newsletter_slugs,
    newsletter_inactive_slugs,
    newsletter_languages,
)


# Error messages
MSG_TOKEN_REQUIRED = "Must have valid token for this request"
MSG_EMAIL_OR_TOKEN_REQUIRED = "Must have valid token OR email for this request"
MSG_USER_NOT_FOUND = "User not found"

# A few constants to indicate the type of action to take
# on a user with a list of newsletters
# (Use strings so when we log function args, they make sense.)
SUBSCRIBE = "SUBSCRIBE"
UNSUBSCRIBE = "UNSUBSCRIBE"
SET = "SET"

email_block_list_cache = caches["email_block_list"]


def iso_format_unix_timestamp(timestamp, date_only=False):
    """
    Convert a unix timestamp in seconds since epoc
    to an ISO formatted date string
    """
    if timestamp:
        if date_only:
            dto = date.fromtimestamp(float(timestamp))
        else:
            dto = datetime.utcfromtimestamp(float(timestamp))

        return dto.isoformat()


def generate_token():
    return str(uuid4())


class HttpResponseJSON(HttpResponse):
    def __init__(self, data, status=None):
        super(HttpResponseJSON, self).__init__(
            content=json.dumps(data),
            content_type="application/json",
            status=status,
        )


def parse_phone_number(pnum, country="us"):
    """Parse and validate phone number input and return an E164 formatted number or None if invalid."""
    region_code = country.upper()
    try:
        pn = phonenumbers.parse(pnum, region_code)
    except phonenumbers.NumberParseException:
        return None

    if phonenumbers.is_valid_number_for_region(pn, region_code):
        return phonenumbers.format_number(pn, phonenumbers.PhoneNumberFormat.E164)

    return None


def get_email_block_list():
    """Return a list of blocked email domains."""
    cache_key = "email_block_list"
    block_list = email_block_list_cache.get(cache_key)
    if block_list is None:
        block_list = list(BlockedEmail.objects.values_list("email_domain", flat=True))
        email_block_list_cache.set(cache_key, block_list)

    return block_list


def email_is_blocked(email):
    """Check an email and return True if blocked."""
    for blocked in get_email_block_list():
        if email.endswith(blocked):
            statsd.incr("basket.news.utils.email_blocked." + blocked)
            return True

    return False


def is_authorized(request, email=None):
    if has_valid_api_key(request):
        return True

    if email and has_valid_fxa_oauth(request, email):
        return True

    return False


def has_valid_api_key(request):
    # The API key could be the query parameter 'api-key' or the
    # request header 'X-api-key'.
    api_key = (
        request.POST.get("api-key", None)
        or request.POST.get("api_key", None)
        or request.GET.get("api-key", None)
        or request.GET.get("api_key", None)
        or request.headers.get("X-Api-Key", None)
    )
    if api_key:
        return APIUser.is_valid(api_key)

    return False


FXA_CLIENTS = {
    "oauth": None,
    "profile": None,
}


def get_fxa_clients():
    """Return and/or create FxA OAuth client instances"""
    if FXA_CLIENTS["oauth"] is None:
        server_urls = fxa.constants.ENVIRONMENT_URLS.get(settings.FXA_OAUTH_SERVER_ENV)
        FXA_CLIENTS["oauth"] = fxa.oauth.Client(
            server_url=server_urls["oauth"],
            client_id=settings.FXA_CLIENT_ID,
            client_secret=settings.FXA_CLIENT_SECRET,
        )
        FXA_CLIENTS["profile"] = fxa.profile.Client(server_url=server_urls["profile"])

    return FXA_CLIENTS["oauth"], FXA_CLIENTS["profile"]


def has_valid_fxa_oauth(request, email):
    if not email:
        return False

    # Grab the token out of the Authorization header
    authorization = request.headers.get("Authorization")
    if not authorization:
        return False

    authorization = authorization.split(None, 1)
    if authorization[0].lower() != "bearer" or len(authorization) != 2:
        return False

    token = authorization[1].strip()
    oauth, profile = get_fxa_clients()
    # Validate the token with oauth-server and check for appropriate scope.
    # This will raise an exception if things are not as they should be.
    try:
        oauth.verify_token(token, scope=["basket", "profile:email"])
    except fxa.errors.Error:
        # security failure or server problem. can't validate. return invalid
        sentry_sdk.capture_exception()
        return False

    try:
        fxa_email = profile.get_email(token)
    except fxa.errors.Error:
        # security failure or server problem. can't validate. return invalid
        sentry_sdk.capture_exception()
        return False

    return email == fxa_email


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
        kwargs["token"] = token
    elif email:
        kwargs["email"] = email
    else:
        raise Exception(MSG_EMAIL_OR_TOKEN_REQUIRED)

    # Note: If both token and email were passed in we use the token as it is the most explicit.

    # NewsletterException uncaught here on purpose
    user_data = get_user_data(**kwargs)
    if user_data and user_data["status"] == "ok":
        # Found them in ET and updated subscriber db locally
        created = False

    # Not in ET. If we have an email, generate a token.
    elif email:
        user_data = {
            "email": email,
            "token": generate_token(),
            "master": False,
            "pending": False,
            "confirmed": False,
            "lang": "",
            "status": "ok",
        }
        created = True
    else:
        # No email?  Just token? Token not known in basket or ET?
        # That's an error.
        user_data = created = None

    return user_data, created


def newsletter_exception_response(exc):
    """Convert a NewsletterException into a JSON HTTP response."""
    return HttpResponseJSON(
        {
            "status": "error",
            "code": exc.error_code or errors.BASKET_UNKNOWN_ERROR,
            "desc": str(exc),
        },
        exc.status_code or 400,
    )


LANG_RE = re.compile(r"^[a-z]{2,3}(?:-[a-z]{2})?$", re.IGNORECASE)


def language_code_is_valid(code):
    """Return True if ``code`` looks like a language code.

    So it must be either 2 (or 3) alpha characters, or 2 pairs of 2
    characters separated by a dash. It will also
    accept the empty string.

    Raises TypeError if anything but a string is passed in.
    """
    if not isinstance(code, str):
        raise TypeError("Language code must be a string")

    if code == "":
        return True
    else:
        return bool(LANG_RE.match(code))


IGNORE_USER_FIELDS = [
    "id",
    "reason",
    "fsa_school",
    "fsa_grad_year",
    "fsa_major",
    "fsa_city",
    "fsa_current_status",
    "fsa_allow_share",
    "cv_days_interval",
    "cv_created_at",
    "cv_goal_reached_at",
    "cv_first_contribution_date",
    "cv_two_day_streak",
    "cv_last_active_date",
    "amo_id",
    "amo_user",
    "amo_display_name",
    "amo_last_login",
    "amo_location",
    "amo_homepage",
    "payee_id",
    "fxa_id",
]


def get_user_data(
    token=None,
    email=None,
    payee_id=None,
    amo_id=None,
    fxa_id=None,
    extra_fields=None,
    get_fxa=False,
):
    """
    Return a dictionary of the user's data.

    Use CTMS (Mozilla's Contact Management System) as the primary source.
    Lookups are by token, email, AMO ID, and FxA ID.

    If the user was not found, return None instead of a dictionary.

    Some data fields are not returned by default. Those fields are listed
    in the IGNORE_USER_FIELDS list. If you need one of those fields then
    call this function with said field name in a list passed in
    the `extra_fields` argument.

    If `get_fxa` is True then a boolean field will be including indicating whether they are
    an account holder or not.

    Review of results:

    None = user completely unknown, no errors talking to CTMS.

    otherwise, return value is::

    {
        'status':  'ok',      # no errors talking to ET
        'status':  'error',   # errors talking to ET, see next field
        'desc':  'error message'   # details if status is error
        'email': 'email@address',
        'email_id': CTMS UUID,
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
    user = {}

    if not user.get("email_id"):
        ctms_user = None
        try:
            ctms_user = ctms.get(
                token=token,
                email=email,
                sfdc_id=user.get("id"),
                amo_id=amo_id,
                fxa_id=fxa_id,
            )
        except CTMSNotFoundByAltIDError:
            return None
        except requests.exceptions.HTTPError as error:
            if error.response.status_code == 401:
                raise NewsletterException(
                    "Email service provider auth failure",
                    error_code=errors.BASKET_EMAIL_PROVIDER_AUTH_FAILURE,
                    status_code=500,
                )
            else:
                raise NewsletterException(
                    str(error),
                    error_code=errors.BASKET_NETWORK_FAILURE,
                    status_code=400,
                )
        except CTMSNotConfigured:
            raise NewsletterException(
                "Email service provider auth failure",
                error_code=errors.BASKET_EMAIL_PROVIDER_AUTH_FAILURE,
                status_code=500,
            )
        except CTMSError as e:
            raise NewsletterException(
                str(e),
                error_code=errors.BASKET_NETWORK_FAILURE,
                status_code=400,
            )
        if ctms_user:
            user = ctms_user
        else:
            return None

    # don't send some of the returned data
    for fn in IGNORE_USER_FIELDS:
        if extra_fields and fn not in extra_fields:
            user.pop(fn, None)

    if get_fxa:
        user["has_fxa"] = bool(user.get("fxa_id"))

    user["status"] = "ok"
    return user


def get_user(token=None, email=None, get_fxa=False):
    if settings.MAINTENANCE_MODE and not settings.MAINTENANCE_READ_ONLY:
        # can't return user data during maintenance
        return HttpResponseJSON(
            {
                "status": "error",
                "desc": "user data is not available in maintenance mode",
                "code": errors.BASKET_NETWORK_FAILURE,
            },
            400,
        )

    try:
        user_data = get_user_data(token, email, get_fxa=get_fxa)
        status_code = 200
    except NewsletterException as e:
        return newsletter_exception_response(e)

    if user_data is None:
        user_data = {
            "status": "error",
            "code": errors.BASKET_UNKNOWN_EMAIL
            if email
            else errors.BASKET_UNKNOWN_TOKEN,
            "desc": MSG_USER_NOT_FOUND,
        }
        status_code = 404
    return HttpResponseJSON(user_data, status_code)


def get_accept_languages(header_value):
    """
    Parse the user's Accept-Language HTTP header and return a list of languages
    """
    # adapted from bedrock: http://j.mp/1o3pWo5
    if not header_value:
        return []
    languages = []
    pattern = re.compile(r"^([A-Za-z]{2,3})(?:-([A-Za-z]{2})(?:-[A-Za-z0-9]+)?)?$")

    # bug 1102652
    header_value = header_value.replace("_", "-")

    try:
        parsed = parse_accept_lang_header(header_value)
    except ValueError:  # see https://code.djangoproject.com/ticket/21078
        return languages

    for lang, _priority in parsed:
        m = pattern.match(lang)

        if not m:
            continue

        lang = m.group(1).lower()

        # Check if the shorter code is supported. This covers obsolete long
        # codes like fr-FR (should match fr) or ja-JP (should match ja)
        if m.group(2) and lang not in newsletter_languages():
            lang += "-" + m.group(2).upper()

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


def get_best_request_lang(request):
    accept_lang = request.headers.get("Accept-Language")
    if accept_lang:
        lang = get_best_language(get_accept_languages(accept_lang))
        if lang:
            return lang

    return None


def _fix_supported_lang(code):
    """
    If there's a dash in the locale the second half should be upper case.
    """
    if "-" in code:
        codebits = code.split("-")
        code = "{}-{}".format(codebits[0], codebits[1].upper())

    return code


def get_best_supported_lang(code):
    """
    Take whatever language code we get from the user and return the best one
    we support for newsletters.
    """
    code = str(code).lower()
    all_langs = [lang.lower() for lang in newsletter_languages()]
    if code in all_langs:
        return _fix_supported_lang(code)

    all_langs_2char = {c[:2]: c for c in all_langs}
    code2 = code[:2]
    if code2 in all_langs_2char:
        return _fix_supported_lang(all_langs_2char[code2])

    return "en"


def process_email(email):
    """Validates that the email is valid.

    Return email ascii encoded if valid, None if not.
    """
    if not email:
        return None

    email = force_str(email)
    try:
        # NOTE SFDC doesn't support SMPTUTF8, so we cannot enable support
        #      here until they do or we switch providers
        info = validate_email(email, allow_smtputf8=False, check_deliverability=False)
    except EmailNotValidError:
        return None

    return info.ascii_email


def parse_newsletters_csv(newsletters):
    """Return a list of newsletter names from a comma separated string"""
    if isinstance(newsletters, (list, tuple)):
        return newsletters

    if not isinstance(newsletters, str):
        return []

    return [x.strip() for x in newsletters.split(",") if x.strip()]


def parse_newsletters(api_call_type, newsletters, cur_newsletters):
    """Utility function to take a list of newsletters and according
    the type of action (subscribe, unsubscribe, and set) set the
    appropriate flags in `record` which is a dict of parameters that
    will be sent to the email provider.

    Parameters are only set for the newsletters whose subscription
    status needs to change, so that we don't unnecessarily update the
    last modification timestamp of newsletters.

    :param integer api_call_type: SUBSCRIBE means add these newsletters to the
        user's subscriptions if not already there, UNSUBSCRIBE means remove
        these newsletters from the user's subscriptions if there, and SET
        means change the user's subscriptions to exactly this set of
        newsletters.
    :param list newsletters: List of the slugs of the newsletters to be
        subscribed, unsubscribed, or set.
    :param list cur_newsletters: List of the slugs of the newsletters that
        the user is currently subscribed to. None if there was an error.
    :returns: dict of slugs of the newsletters with boolean values: True for subscriptions,
        and False for unsubscription.
    """
    newsletter_map = {}
    newsletters = set(newsletters)
    if cur_newsletters is None:
        cur_newsletters = set()
    else:
        cur_newsletters = set(cur_newsletters)
        if api_call_type == SET:
            # don't mess with inactive newsletters on a full update
            cur_newsletters -= set(newsletter_inactive_slugs())

    if api_call_type == SUBSCRIBE:
        grouped_newsletters = set()
        for nl in newsletters:
            group_nl = newsletter_group_newsletter_slugs(nl)
            if group_nl:
                grouped_newsletters.update(group_nl)
            else:
                grouped_newsletters.add(nl)

        newsletters = grouped_newsletters

    if api_call_type == SUBSCRIBE or api_call_type == SET:
        # Subscribe the user to these newsletters if not already
        subs = newsletters - cur_newsletters
        for nl in subs:
            newsletter_map[nl] = True

    if api_call_type == UNSUBSCRIBE or api_call_type == SET:
        # Unsubscribe the user to these newsletters

        if api_call_type == SET:
            # Unsubscribe from the newsletters currently subscribed to
            # but not in the new list
            if cur_newsletters:
                unsubs = cur_newsletters - newsletters
            else:
                unsubs = []
        else:  # type == UNSUBSCRIBE
            # unsubscribe from the specified newsletters
            if cur_newsletters:
                unsubs = newsletters & cur_newsletters
            else:
                # we might not be subscribed to anything,
                # or just didn't get user data. default to everything.
                unsubs = newsletters

        for nl in unsubs:
            newsletter_map[nl] = False

    return newsletter_map


def split_name(name):
    """
    Takes a full name as a string and attempts to make it conform to the narrow
    "first/last" system Salesforce requires.

    Drops any "jr" or "sr" suffix.
    """

    # remove leading/trailing whitespace and periods
    # also accounts for a string of spaces being provided
    name = name.strip(" .")

    # if the name is an empty string, we're done
    if not name:
        return "", ""

    # try to make the final bit after the last space the last name
    names = name.rsplit(None, 1)

    if len(names) == 2:
        first, last = names

        # if last name is 'jr' or 'sr' and first name has a space in it, do
        # more splitting
        if " " in first and last.lower() in ["jr", "sr"]:
            first, last = first.rsplit(None, 1)
    else:
        first, last = "", names[0]

    return first, last


def cents_to_dollars(cents):
    try:
        dollars = int(cents) / float(100)
    except ValueError:
        dollars = 0

    return dollars

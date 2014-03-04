import logging

from flanker.addresslib import address, validate


log = logging.getLogger(__name__)


def get_valid_email(email):
    """Return (valid email address or None, True if email is a suggestion).

    It uses flanker to correct commonly misspelled domains (e.g. gmil.com)
    and to check to make sure MX records exist for the domain.
    """
    if not email:
        return None, None
    # returns None if it has no alternate or if the email is invalid
    good_email = validate.suggest_alternate(email) or email
    suggestion = False
    if email != good_email:
        log.info('Using suggested alternate email')
        suggestion = True

    good_email = address.validate_address(good_email)
    if isinstance(good_email, address.EmailAddress):
        good_email = good_email.address

    # returns None if the email is invalid, or the email if all's well
    return good_email, suggestion

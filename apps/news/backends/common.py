
class UnauthorizedException(Exception):
    """Failure to log into the email server."""
    pass


class NewsletterException(Exception):
    """Error when trying to talk to the the email server."""
    pass

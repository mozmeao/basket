
class UnauthorizedException(Exception):
    """Failure to log into the email server."""
    pass


class NewsletterException(Exception):
    """Error when trying to talk to the the email server."""
    pass


class NewsletterNoResultsException(NewsletterException):
    """
    No results were returned from the mail server (but the request
    didn't report any errors)
    """
    pass

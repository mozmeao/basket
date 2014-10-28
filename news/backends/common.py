
class UnauthorizedException(Exception):
    """Failure to log into the email server."""
    pass


class NewsletterException(Exception):
    """Error when trying to talk to the the email server."""

    def __init__(self, msg=None, error_code=None, status_code=None):
        self.error_code = error_code
        self.status_code = status_code
        super(NewsletterException, self).__init__(msg)


class NewsletterNoResultsException(NewsletterException):
    """
    No results were returned from the mail server (but the request
    didn't report any errors)
    """
    pass

from functools import wraps
from time import time

from basket import metrics


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


def get_timer_decorator(prefix):
    """
    Decorator for timing and counting requests to the API
    """

    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            starttime = time()

            def record_timing():
                totaltime = int((time() - starttime) * 1000)
                metrics.timing(f"{prefix}.timing", totaltime, tags=[f"fn:{f.__name__}"])

            try:
                resp = f(*args, **kwargs)
            except NewsletterException:
                record_timing()
                raise

            record_timing()
            return resp

        return wrapped

    return decorator

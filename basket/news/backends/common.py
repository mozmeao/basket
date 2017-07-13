from functools import wraps
from time import time

from django_statsd.clients import statsd


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
            e = None
            try:
                resp = f(*args, **kwargs)
            except NewsletterException as e:
                pass
            except Exception:
                raise

            totaltime = int((time() - starttime) * 1000)
            statsd.timing(prefix + '.timing', totaltime)
            statsd.timing(prefix + '.{}.timing'.format(f.__name__), totaltime)
            statsd.incr(prefix + '.count')
            statsd.incr(prefix + '.{}.count'.format(f.__name__))
            if e:
                raise
            else:
                return resp

        return wrapped

    return decorator

class BasketError(Exception):
    """
    Tasks can raise this when an error happens that we should not retry.

    E.g. if the error indicates we're passing bad parameters, as opposed to an
    error where we'd typically raise `NewsletterException`.
    """

    pass


class RetryTask(Exception):
    """An exception to raise within a task if you just want to retry."""

    pass

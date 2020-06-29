from django.conf import settings


def email_is_testing(email):
    """Return true if email address is at a known testing domain"""
    if not settings.USE_SANDBOX_BACKEND:
        for domain in settings.TESTING_EMAIL_DOMAINS:
            if email.endswith("@{}".format(domain)):
                return True

    return False

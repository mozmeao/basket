import uuid

from django.conf import settings


def email_is_testing(email):
    # Return true if email address is at a known testing domain
    if not settings.USE_SANDBOX_BACKEND:
        for domain in settings.TESTING_EMAIL_DOMAINS:
            if email.endswith(f"@{domain}"):
                return True

    return False


def is_valid_uuid(value, version=None):
    try:
        uuid_obj = uuid.UUID(value)
        if uuid_obj.version != 4:
            return False
        return True
    except ValueError:
        return False


def generate_token():
    return str(uuid.uuid4())

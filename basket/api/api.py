import uuid

from ninja import NinjaAPI

from basket import errors, metrics
from basket.api.auth import AUTHORIZED, HeaderApiKey, QueryApiKey
from basket.api.schemas import ErrorSchema, NewsletterSchema, NewslettersSchema, UserSchema
from basket.news.models import Newsletter
from basket.news.utils import (
    MSG_EMAIL_OR_TOKEN_REQUIRED,
    MSG_USER_NOT_FOUND,
    NewsletterException,
    get_user_data,
    process_email,
)

api = NinjaAPI(title="Basket API")


@api.get("/newsletters/", response={200: NewslettersSchema})
def newsletters(request):
    # Get the newsletters as a dictionary of dictionaries that are
    # easily jsonified
    result = {}
    for newsletter in Newsletter.objects.all():
        newsletter.languages = newsletter.languages.split(",")
        result[newsletter.slug] = NewsletterSchema.from_orm(newsletter).dict()

    return {"status": "ok", "newsletters": result}


@api.get("/lookup-user/", auth=[QueryApiKey(), HeaderApiKey()], response={200: UserSchema, 400: ErrorSchema, 401: ErrorSchema, 404: ErrorSchema})
def lookup_user(request, email: str | None = None, token: uuid.UUID | None = None, fxa: bool = False):
    # TODO: Add maintenance mode check.

    # Both email and token, and neither, is an error.
    if not (email or token) or (email and token):
        return _usage_error()

    authorized = request.auth == AUTHORIZED
    masked = not authorized

    if email and not authorized:
        return _auth_error()

    if email:
        email = process_email(email)
        if not email:
            return _invalid_email()

    try:
        user_data = get_user_data(email=email, token=token, get_fxa=fxa, masked=masked)
    except NewsletterException as exc:
        return _unknown_error(exc)

    if not user_data:
        if token:
            return _unknown_token()
        return _unknown_email()

    return user_data


## Validation errors


def _invalid_email():
    metrics.incr("news.views.invalid_email_response")
    return 400, {
        "status": "error",
        "desc": "Invalid email address",
        "code": errors.BASKET_INVALID_EMAIL,
    }


def _invalid_token():
    metrics.incr("news.views.invalid_token_response")
    return 400, {
        "status": "error",
        "desc": "Invalid basket token",
        "code": errors.BASKET_INVALID_TOKEN,
    }


def _auth_error():
    return 401, {
        "status": "error",
        "desc": "Using lookup_user with `email`, you need to pass a valid `api-key` or FxA OAuth Authorization header.",
        "code": errors.BASKET_AUTH_ERROR,
    }


def _usage_error():
    return 400, {
        "status": "error",
        "desc": MSG_EMAIL_OR_TOKEN_REQUIRED,
        "code": errors.BASKET_USAGE_ERROR,
    }


def _unknown_error(exc):
    return exc.status_code or 400, {
        "status": "error",
        "desc": str(exc),
        "code": exc.error_code or errors.BASKET_UNKNOWN_ERROR,
    }


def _unknown_token():
    return 404, {
        "status": "error",
        "desc": MSG_USER_NOT_FOUND,
        "code": errors.BASKET_UNKNOWN_TOKEN,
    }


def _unknown_email():
    return 404, {
        "status": "error",
        "desc": MSG_USER_NOT_FOUND,
        "code": errors.BASKET_UNKNOWN_EMAIL,
    }

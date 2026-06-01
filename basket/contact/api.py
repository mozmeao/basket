from django.conf import settings

from django_ratelimit.core import is_ratelimited
from ninja import Router
from pydantic import ValidationError

from basket import metrics

from .schemas import ContactEnterpriseSchema

### /api/v1/contact URLS
contact_router = Router()

@contact_router.post(
    "/enterprise/",
    url_name="contact.enterprise",
    description="Submit enterprise contact form",
    response={200: dict, 429: dict},
)
def contact_enterprise(request, payload: ContactEnterpriseSchema):
    try:
        if is_ratelimited(
            request,
            group="basket.contact.enterprise.ip",
            key="ip",
            rate=settings.CONTACT_ENTERPRISE_RATE_LIMIT,
            increment=True,
        ):
            metrics.incr("contact.enterprise.ratelimited", tags=["reason:ip"])
            return 429, {"status": "error"}

        if is_ratelimited(
            request,
            group="basket.contact.enterprise.email",
            key=lambda *_: payload.email.lower(),
            rate=settings.CONTACT_ENTERPRISE_RATE_LIMIT,
            increment=True,
        ):
            metrics.incr("contact.enterprise.ratelimited", tags=["reason:email"])
            return 429, {"status": "error"}

        if payload.website:
            metrics.incr("contact.enterprise.honeypot")
            return {"status": "ok"}
        return {"status": "ok"}

    except ValidationError as e:
        metrics.incr("contact.enterprise.spam_rejected", tags=["reason:spam"])
        return {"status": "error"}


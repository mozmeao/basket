from django.conf import settings

from django_ratelimit.core import is_ratelimited
from ninja import Router

from basket import metrics

from . import tasks
from .schemas import ContactBasicSchema, ContactEnterpriseSchema

### /api/v1/contact URLS
contact_router = Router()


def submit_contact(request, payload, form: str):
    """Rate limit, drop bots, then queue the contact. Shared by every contact form."""
    for reason, key in (("ip", "ip"), ("email", lambda *_: payload.business_email.lower())):
        if is_ratelimited(request, group=f"basket.contact.{form}.{reason}", key=key, rate=settings.CONTACT_ENTERPRISE_RATE_LIMIT, increment=True):
            metrics.incr(f"contact.{form}.ratelimited", tags=[f"reason:{reason}"])
            return 429, {"status": "error"}

    if payload.office_fax:
        metrics.incr(f"contact.{form}.honeypot")
        return {"status": "ok"}

    tasks.submit_contact.delay(payload.model_dump(exclude={"office_fax"}))
    return {"status": "ok"}


@contact_router.post(
    "enterprise/",
    url_name="contact.enterprise",
    description="Submit enterprise contact form",
    response={200: dict, 429: dict},
)
def contact_enterprise(request, payload: ContactEnterpriseSchema):
    return submit_contact(request, payload, "enterprise")


@contact_router.post(
    "basic/",
    url_name="contact.basic",
    description="Submit basic contact form",
    response={200: dict, 429: dict},
)
def contact_basic(request, payload: ContactBasicSchema):
    return submit_contact(request, payload, "basic")

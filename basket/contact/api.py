from ninja import Router

from .schemas import ContactEnterpriseSchema

### /api/v1/contact URLS
contact_router = Router()

@contact_router.post(
    "/enterprise/",
    url_name="contact.enterprise",
    description="Submit enterprise contact form",
    response={200: dict},
)
def contact_enterprise(request, payload: ContactEnterpriseSchema):
    return {"status": "ok"}

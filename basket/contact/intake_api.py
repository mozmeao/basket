import json

from django.conf import settings
from django.http import HttpResponse

from ninja import Router

from basket import errors
from basket.base.throttling import ApiKeyThrottle
from basket.news.api import api

from .intake_auth import IntakeAuth, IntakeUnauthorized
from .intake_tasks import deliver_to_gsheet
from .models import FormDelivery, FormRoute, FormSubmission
from .schemas import IntakeSchema

### /api/v1/intake URLS
intake_router = Router()


@api.exception_handler(IntakeUnauthorized)
def intake_unauthorized(request, exc):
    return HttpResponse(
        json.dumps({"status": "error", "detail": "unauthorized", "code": errors.BASKET_AUTH_ERROR}),
        status=401,
        content_type="application/json",
    )


@intake_router.post(
    "/",
    url_name="intake.submit",
    description="Receive a form submission and route it to configured destinations",
    auth=[IntakeAuth()],
    throttle=[ApiKeyThrottle(settings.INTAKE_RATE_LIMIT)],
    response={200: dict, 403: dict, 404: dict},
)
def submit_intake(request, payload: IntakeSchema):
    api_user = request.auth

    allowed_form_ids = api_user.allowed_form_ids
    if not isinstance(allowed_form_ids, list) or (allowed_form_ids and payload.form_id not in allowed_form_ids):
        return 403, {"status": "error", "detail": "form_id not permitted for this api user"}

    try:
        route = FormRoute.objects.get(form_id=payload.form_id, active=True)
    except FormRoute.DoesNotExist:
        return 404, {"status": "error", "detail": "unknown or inactive form_id"}

    submission = FormSubmission.objects.create(
        route=route,
        payload=payload.model_dump(),
        source_url=payload.source_url,
    )

    for destination in route.destinations.filter(active=True):
        if destination.dest_type == "gsheet":
            # Up front, so the rollup stays "queued" until every destination reports.
            FormDelivery.objects.create(submission=submission, destination=destination)
            deliver_to_gsheet.delay(submission.id, destination.id)

    return {"status": "queued"}

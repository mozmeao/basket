import uuid

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect

from basket.petition.forms import PetitionForm


# Doing this here to not affect the rest of basket.
def _add_cors(response):
    response["Access-Control-Allow-Origin"] = settings.PETITION_CORS_URL
    response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    return response


def sign_petition(request):
    if request.method == "OPTIONS":
        return _add_cors(JsonResponse({"status": "none"}))

    if request.method == "GET":
        return redirect(settings.PETITION_REDIRECT_URL)

    if request.method == "POST":
        form = PetitionForm(request.POST)
        if not form.is_valid():
            return _add_cors(JsonResponse({"status": "error", "errors": form.errors}))

        petition = form.save(commit=False)
        petition.ip = request.META.get("REMOTE_ADDR", "")
        petition.user_agent = request.META.get("HTTP_USER_AGENT", "")
        petition.referrer = request.META.get("HTTP_REFERER", "")
        petition.token = uuid.uuid4()
        petition.save()

        return _add_cors(JsonResponse({"status": "success"}))

        # TODO: Send confirmation email to user's email.

import uuid

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils.http import urlsafe_base64_decode
from django.views.decorators.cache import cache_page

from basket.petition.forms import PetitionForm
from basket.petition.models import Petition


# Doing this here to not affect the rest of basket.
def _add_cors(response):
    response["Access-Control-Allow-Origin"] = settings.PETITION_CORS_URL
    response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response["Access-Control-Allow-Headers"] = "*"
    return response


def sign_petition(request):
    if request.method == "OPTIONS":
        return _add_cors(JsonResponse({"status": "none"}))

    if request.method == "GET":
        return redirect(settings.PETITION_LETTER_URL)

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

        # Send email confirmation.
        petition.send_email_confirmation()

        return _add_cors(JsonResponse({"status": "success"}))


@cache_page(60 * 15)
def signatures_json(request):
    petitions = Petition.objects.filter(approved=True).order_by("created").values("name", "title", "affiliation")
    data = {"signatures": list(petitions)}
    return JsonResponse(data)


def confirm_token(request, pidb64, token):
    petition_id = urlsafe_base64_decode(pidb64).decode()
    try:
        petition = Petition.objects.get(id=petition_id, token=token, email_confirmed=False)
    except Petition.DoesNotExist:
        return redirect(settings.PETITION_LETTER_URL)

    petition.email_confirmed = True
    petition.save()

    return redirect(settings.PETITION_THANKS_URL)

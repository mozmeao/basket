import uuid

from django.conf import settings
from django.core.mail import send_mail
from django.http import JsonResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.cache import cache_page

from basket.petition.forms import PetitionForm
from basket.petition.models import Petition


# Doing this here to not affect the rest of basket.
def _add_cors(response):
    response["Access-Control-Allow-Origin"] = settings.PETITION_CORS_URL
    response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    return response


def _send_confirmation(request, petition):
    pidb64 = urlsafe_base64_encode(str(petition.pk).encode())
    confirm_link = request.build_absolute_uri(reverse("confirm-token", args=[pidb64, petition.token]))

    email_subject = "Verify your email: Joint Statement on AI Safety and Openness"
    email_body = render_to_string(
        "petition/confirmation_email.txt",
        {
            "name": petition.name,
            "confirm_link": confirm_link,
        },
    )
    email_from = "noreply@mozilla.com"
    email_to = [f"{petition.name} <{petition.email}>"]

    send_mail(email_subject, email_body, email_from, email_to)


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

        # Send email confirmation.
        _send_confirmation(request, petition)

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
        return redirect(settings.PETITION_REDIRECT_URL)

    petition.email_confirmed = True
    petition.save()

    return redirect(settings.PETITION_REDIRECT_URL)

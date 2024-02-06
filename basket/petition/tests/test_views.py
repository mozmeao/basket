import uuid

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from django.utils.http import urlsafe_base64_encode

import pytest

from basket.petition.models import Petition


def test_petition_get(client):
    # Get should just redirect to petition page.
    url = reverse("sign-petition")
    response = client.get(url)
    assert response.status_code == 302
    assert response.url == settings.PETITION_LETTER_URL


@pytest.mark.django_db
def test_petition_post_success(client, mocker, settings):
    mock_send_mail = mocker.patch("basket.petition.models.send_email_confirmation")
    settings.SITE_URL = "http://testserver"
    url = reverse("sign-petition")
    data = {
        "name": "The Dude",
        "email": "thedude@example.com",
        "title": "Dude",
        "affiliation": "The Knudsens",
    }
    response = client.post(url, data=data)
    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    assert Petition.objects.count() == 1
    petition = Petition.objects.first()
    assert petition.name == "The Dude"
    assert petition.email == "thedude@example.com"
    assert petition.title == "Dude"
    assert petition.affiliation == "The Knudsens"
    assert petition.token is not None
    assert petition.email_confirmed is False
    assert petition.verified_general is False
    assert petition.verified_linkedin is False
    assert petition.verified_research is False
    assert petition.approved is False
    assert petition.vip is False
    assert petition.created is not None
    assert str(petition) == "The Dude, Dude (thedude@example.com)"

    assert mock_send_mail.delay.call_count == 1
    pidb64 = urlsafe_base64_encode(str(petition.pk).encode())
    link = f"http://testserver/petition/confirm/{pidb64}/{petition.token}/"
    assert mock_send_mail.delay.call_args[0] == ("The Dude", "thedude@example.com", link)


@pytest.mark.django_db
def test_petition_post_invalid(client, mocker):
    mock_send_mail = mocker.patch("basket.petition.models.send_email_confirmation")
    url = reverse("sign-petition")
    data = {
        "name": "The Dude",
        "email": "",
        "title": "",
        "affiliation": "The Knudsens",
    }
    response = client.post(url, data=data)
    assert response.status_code == 200
    assert response.json() == {
        "status": "error",
        "errors": {
            "email": ["This field is required."],
            "title": ["This field is required."],
        },
    }
    assert Petition.objects.count() == 0
    assert mock_send_mail.delay.call_count == 0


@pytest.mark.django_db
def test_petition_email_invalid(client, mocker):
    mock_send_mail = mocker.patch("basket.petition.models.send_email_confirmation")
    url = reverse("sign-petition")
    data = {
        "name": "The Dude",
        "email": "invalid",
        "title": "Dude",
        "affiliation": "The Knudsens",
    }
    response = client.post(url, data=data)
    assert response.status_code == 200
    assert response.json() == {
        "status": "error",
        "errors": {
            "email": ["Enter a valid email address."],
        },
    }
    assert Petition.objects.count() == 0
    assert mock_send_mail.delay.call_count == 0


@pytest.mark.django_db
def test_petition_name_invalid(client, mocker):
    mock_send_mail = mocker.patch("basket.petition.models.send_email_confirmation")
    url = reverse("sign-petition")
    data = {
        "name": "The Dude <script>alert('xss');</script>",
        "email": "thedude@example.com",
        "title": "Dude",
        "affiliation": "The Knudsens",
    }
    response = client.post(url, data=data)
    assert response.status_code == 200
    assert response.json() == {
        "status": "error",
        "errors": {
            "name": ["Invalid characters"],
        },
    }
    assert Petition.objects.count() == 0
    assert mock_send_mail.delay.call_count == 0


@pytest.mark.django_db
def test_petition_db_emoji(client, mocker):
    mock_send_mail = mocker.patch("basket.petition.models.send_email_confirmation")
    url = reverse("sign-petition")
    data = {
        "name": "The Dude 😎",
        "email": "thedude@example.com",
        "title": "Dude",
        "affiliation": "The Knudsens",
    }
    response = client.post(url, data=data)
    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
    }
    assert mock_send_mail.delay.call_count == 1


def test_petition_cors(client):
    url = reverse("sign-petition")
    response = client.options(url)
    assert response.status_code == 200
    assert response["Access-Control-Allow-Origin"] == settings.PETITION_CORS_URL
    assert response["Access-Control-Allow-Methods"] == "POST, OPTIONS"
    assert response["Access-Control-Allow-Headers"] == "*"


@pytest.mark.django_db
def test_signatures_json(client, petition):
    url = reverse("signatures-json")

    cache.clear()

    # One approved signature is defined in conftest.py.
    # One not yet approved signature.
    Petition.objects.create(
        name="The Troll",
        email="troll@example.com",
        title="Troll",
        affiliation="Troll Farm",
        approved=False,
        token=uuid.uuid4(),
    )

    response = client.get(url)
    assert response.status_code == 200
    assert response.json() == {
        "signatures": [
            {
                "name": petition.name,
                "title": petition.title,
                "affiliation": petition.affiliation,
            }
        ]
    }

    # No signatures.
    cache.clear()
    petition.delete()

    response = client.get(url)
    assert response.status_code == 200
    assert response.json() == {"signatures": []}

    # Confirm there's caching on the response.
    assert response["Cache-Control"] == "max-age=300"


@pytest.mark.django_db
def test_confirm_token(client, petition):
    assert petition.email_confirmed is False

    pidb64 = urlsafe_base64_encode(str(petition.pk).encode())
    response = client.get(reverse("confirm-token", args=[pidb64, petition.token]))
    assert response.status_code == 302
    assert response.url == settings.PETITION_THANKS_URL

    petition.refresh_from_db()
    assert petition.email_confirmed is True


@pytest.mark.django_db
def test_confirm_token_invalid(client, petition):
    assert petition.email_confirmed is False

    pidb64 = urlsafe_base64_encode(str(petition.pk).encode())
    # Using a different UUID token so it's invalid.
    response = client.get(reverse("confirm-token", args=[pidb64, uuid.uuid4()]))
    assert response.status_code == 302
    assert response.url == settings.PETITION_LETTER_URL

    petition.refresh_from_db()
    assert petition.email_confirmed is False

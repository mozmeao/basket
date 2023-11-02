from django.conf import settings
from django.urls import reverse

import pytest

from basket.petition.models import Petition


def test_petition_get(client):
    # Get should just redirect to petition page.
    url = reverse("sign-petition")
    response = client.get(url)
    assert response.status_code == 302
    assert response.url == settings.PETITION_REDIRECT_URL


@pytest.mark.django_db
def test_petition_post_success(client):
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
    assert petition.created is not None


@pytest.mark.django_db
def test_petition_post_invalid(client):
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


@pytest.mark.django_db
def test_petition_email_invalid(client):
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


def test_petition_cors(client):
    url = reverse("sign-petition")
    response = client.options(url)
    assert response.status_code == 200
    assert response["Access-Control-Allow-Origin"] == settings.PETITION_CORS_URL
    assert response["Access-Control-Allow-Methods"] == "POST, OPTIONS"

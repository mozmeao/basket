from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from basket.petition.views import confirm_token, sign_petition, signatures_json

urlpatterns = (
    path("sign/", csrf_exempt(sign_petition), name="sign-petition"),
    path("signatures.json", signatures_json, name="signatures-json"),
    path("confirm/<pidb64>/<token>/", confirm_token, name="confirm-token"),
)

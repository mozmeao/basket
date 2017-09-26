from mozilla_django_oidc.auth import OIDCAuthenticationBackend
from django.contrib.auth.backends import ModelBackend


class OIDCModelBackend(OIDCAuthenticationBackend, ModelBackend):
    pass

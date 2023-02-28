from django.contrib.auth.backends import ModelBackend

from mozilla_django_oidc.auth import OIDCAuthenticationBackend


class OIDCModelBackend(OIDCAuthenticationBackend, ModelBackend):
    pass

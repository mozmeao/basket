from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import Permission, User
from django.test import Client
from django.urls import reverse

import pytest

from basket.base.forms import EmailListForm
from basket.news.backends.ctms import CTMSNotFoundByEmailError


@pytest.mark.django_db
class TestAdminDSARView:
    def setup_method(self, method):
        self.client = Client()
        self.url = reverse("admin.dsar")

    def _create_admin_user(self, with_perm=True):
        user = User.objects.create_user(username="admin", password="password")
        user.is_staff = True
        if with_perm:
            user.user_permissions.add(Permission.objects.get(codename="dsar_access"))
        user.save()
        return user

    def _login_admin_user(self):
        self.client.login(username="admin", password="password")

    def test_get_requires_login(self):
        self._create_admin_user()
        response = self.client.get(self.url)
        assert response.status_code == 302
        assert response.url.startswith(settings.LOGIN_URL)

    def test_get_requires_perm(self):
        self._create_admin_user(with_perm=False)
        self._login_admin_user()
        response = self.client.get(self.url)
        assert response.status_code == 302
        assert response.url.startswith(settings.LOGIN_URL)

    def test_get(self):
        self._create_admin_user()
        self._login_admin_user()
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert isinstance(response.context["form"], EmailListForm)
        assert response.context["output"] is None

    def test_post_valid_emails(self):
        self._create_admin_user()
        self._login_admin_user()
        with patch("basket.base.views.ctms", spec_set=["delete"]) as mock_ctms:
            mock_ctms.delete.side_effect = [
                [{"email_id": "123", "fxa_id": "", "mofo_contact_id": ""}],
                [{"email_id": "456", "fxa_id": "string", "mofo_contact_id": ""}],
                [{"email_id": "789", "fxa_id": "string", "mofo_contact_id": "string"}],
            ]
            response = self.client.post(self.url, {"emails": "test1@example.com\ntest2@example.com\ntest3@example.com"}, follow=True)

        assert response.status_code == 200
        assert mock_ctms.delete.call_count == 3
        assert "DELETED test1@example.com (ctms id: 123)." in response.context["output"]
        assert "DELETED test2@example.com (ctms id: 456). fxa: YES." in response.context["output"]
        assert "DELETED test3@example.com (ctms id: 789). fxa: YES. mofo: YES." in response.context["output"]

    def test_post_valid_email(self):
        self._create_admin_user()
        self._login_admin_user()
        with patch("basket.base.views.ctms", spec_set=["delete"]) as mock_ctms:
            mock_ctms.delete.return_value = [{"email_id": "123", "fxa_id": "", "mofo_contact_id": ""}]
            response = self.client.post(self.url, {"emails": "test@example.com"}, follow=True)

        assert response.status_code == 200
        assert mock_ctms.delete.called
        assert "DELETED test@example.com (ctms id: 123)." in response.context["output"]

    def test_post_unknown_ctms_user(self, mocker):
        self._create_admin_user()
        self._login_admin_user()
        with patch("basket.base.views.ctms", spec_set=["delete"]) as mock_ctms:
            mock_ctms.delete.side_effect = CTMSNotFoundByEmailError("unknown@example.com")
            response = self.client.post(self.url, {"emails": "unknown@example.com"}, follow=True)

        assert response.status_code == 200
        assert mock_ctms.delete.called
        assert "unknown@example.com not found in CTMS" in response.context["output"]

    def test_post_invalid_email(self, mocker):
        self._create_admin_user()
        self._login_admin_user()
        with patch("basket.base.views.ctms", spec_set=["delete"]) as mock_ctms:
            mock_ctms.delete.side_effect = CTMSNotFoundByEmailError
            response = self.client.post(self.url, {"emails": "invalid@email"}, follow=True)

        assert response.status_code == 200
        assert not mock_ctms.delete.called
        assert response.context["output"] is None
        assert response.context["form"].errors == {"emails": ["Invalid email: invalid@email"]}

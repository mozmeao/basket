import json
from pathlib import Path
from unittest.mock import call, patch

from django.conf import settings
from django.contrib.auth.models import Permission, User
from django.test import Client
from django.urls import reverse

import pytest

from basket.base.forms import EmailForm, EmailListForm
from basket.news.backends.ctms import CTMSNotFoundByEmailError

TEST_DATA_DIR = Path(__file__).resolve().parent.joinpath("data")


class DSARViewTestBase:
    url_name = None

    def setup_method(self, method):
        self.client = Client()
        self.url = reverse(self.url_name)

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


@pytest.mark.django_db
class TestAdminDSARDeleteView(DSARViewTestBase):
    url_name = "admin:dsar.delete"

    def test_get(self):
        self._create_admin_user()
        self._login_admin_user()
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert isinstance(response.context["dsar_form"], EmailListForm)
        assert response.context["dsar_output"] is None

    def test_post_valid_emails(self):
        self._create_admin_user()
        self._login_admin_user()
        with patch("basket.admin.ctms", spec_set=["delete"]) as mock_ctms:
            mock_ctms.delete.side_effect = [
                [{"email_id": "123", "fxa_id": "", "mofo_contact_id": ""}],
                [{"email_id": "456", "fxa_id": "string", "mofo_contact_id": ""}],
                [{"email_id": "789", "fxa_id": "string", "mofo_contact_id": "string"}],
            ]
            response = self.client.post(self.url, {"emails": "test1@example.com\ntest2@example.com\ntest3@example.com"}, follow=True)

        assert response.status_code == 200
        assert mock_ctms.delete.call_count == 3
        assert "DELETED test1@example.com (ctms id: 123)." in response.context["dsar_output"]
        assert "DELETED test2@example.com (ctms id: 456). fxa: YES." in response.context["dsar_output"]
        assert "DELETED test3@example.com (ctms id: 789). fxa: YES. mofo: YES." in response.context["dsar_output"]

    def test_post_valid_email(self):
        self._create_admin_user()
        self._login_admin_user()
        with patch("basket.admin.ctms", spec_set=["delete"]) as mock_ctms:
            mock_ctms.delete.return_value = [{"email_id": "123", "fxa_id": "", "mofo_contact_id": ""}]
            response = self.client.post(self.url, {"emails": "test@example.com"}, follow=True)

        assert response.status_code == 200
        assert mock_ctms.delete.called
        assert "DELETED test@example.com (ctms id: 123)." in response.context["dsar_output"]

    def test_post_unknown_ctms_user(self, mocker):
        self._create_admin_user()
        self._login_admin_user()
        with patch("basket.admin.ctms", spec_set=["delete"]) as mock_ctms:
            mock_ctms.delete.side_effect = CTMSNotFoundByEmailError("unknown@example.com")
            response = self.client.post(self.url, {"emails": "unknown@example.com"}, follow=True)

        assert response.status_code == 200
        assert mock_ctms.delete.called
        assert "unknown@example.com not found in CTMS" in response.context["dsar_output"]

    def test_post_invalid_email(self, mocker):
        self._create_admin_user()
        self._login_admin_user()
        with patch("basket.admin.ctms", spec_set=["delete"]) as mock_ctms:
            mock_ctms.delete.side_effect = CTMSNotFoundByEmailError
            response = self.client.post(self.url, {"emails": "invalid@email"}, follow=True)

        assert response.status_code == 200
        assert not mock_ctms.delete.called
        assert response.context["dsar_output"] is None
        assert response.context["dsar_form"].errors == {"emails": ["Invalid email: invalid@email"]}


@pytest.mark.django_db
class TestAdminDSARInfoView(DSARViewTestBase):
    url_name = "admin:dsar.info"
    user_data_file = "example_ctms_user_data.json"

    def _get_test_data(self):
        with TEST_DATA_DIR.joinpath(self.user_data_file).open() as fp:
            data = json.load(fp)

        return data

    def test_get(self):
        self._create_admin_user()
        self._login_admin_user()
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert isinstance(response.context["dsar_form"], EmailForm)
        assert "dsar_contact" not in response.context

    def test_post_valid_email(self):
        self._create_admin_user()
        self._login_admin_user()
        user_data = self._get_test_data()
        with patch("basket.admin.ctms", spec_set=["interface"]) as mock_ctms:
            mock_ctms.interface.get_by_alternate_id.return_value = user_data
            response = self.client.post(self.url, {"email": "test@example.com"}, follow=True)

        assert response.status_code == 200
        mock_ctms.interface.get_by_alternate_id.assert_called_with(primary_email="test@example.com")
        assert response.context["dsar_contact"]["email"]["basket_token"] == "0723e863-cff2-4f74-b492-82b861732d19"

    def test_post_unknown_ctms_user(self, mocker):
        self._create_admin_user()
        self._login_admin_user()
        with patch("basket.admin.ctms", spec_set=["interface"]) as mock_ctms:
            mock_ctms.interface.get_by_alternate_id.side_effect = CTMSNotFoundByEmailError("unknown@example.com")
            response = self.client.post(self.url, {"email": "unknown@example.com"}, follow=True)

        assert response.status_code == 200
        assert mock_ctms.interface.get_by_alternate_id.called
        assert b"User not found in CTMS" in response.content

    def test_post_invalid_email(self, mocker):
        self._create_admin_user()
        self._login_admin_user()
        with patch("basket.admin.ctms", spec_set=["interface"]) as mock_ctms:
            response = self.client.post(self.url, {"email": "invalid@email"}, follow=True)

        assert response.status_code == 200
        assert not mock_ctms.interface.get_by_alternate_id.called
        assert "dsar_contact" not in response.context
        assert response.context["dsar_form"].errors == {"email": ["Enter a valid email address."]}


@pytest.mark.django_db
class TestAdminDSARUnsubView(DSARViewTestBase):
    url_name = "admin:dsar.unsubscribe"
    update_data = {
        "email": {
            "has_opted_out_of_email": True,
            "unsubscribe_reason": "User requested global unsubscribe",
        },
        "newsletters": "UNSUBSCRIBE",
        "waitlists": "UNSUBSCRIBE",
    }

    def test_get(self):
        self._create_admin_user()
        self._login_admin_user()
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert isinstance(response.context["dsar_form"], EmailListForm)
        assert response.context["dsar_output"] is None

    def test_post_valid_emails(self):
        self._create_admin_user()
        self._login_admin_user()
        with patch("basket.admin.ctms", spec_set=["get", "interface"]) as mock_ctms:
            mock_ctms.get.side_effect = [
                {"email_id": "123", "fxa_id": "", "mofo_contact_id": ""},
                {"email_id": "456", "fxa_id": "string", "mofo_contact_id": ""},
                {"email_id": "789", "fxa_id": "string", "mofo_contact_id": "string"},
            ]
            response = self.client.post(self.url, {"emails": "test1@example.com\ntest2@example.com\ntest3@example.com"}, follow=True)

        assert response.status_code == 200
        assert mock_ctms.get.call_count == 3
        mock_ctms.interface.patch_by_email_id.assert_has_calls(
            [
                call("123", self.update_data),
                call("456", self.update_data),
                call("789", self.update_data),
            ]
        )
        assert "UNSUBSCRIBED test1@example.com (ctms id: 123)." in response.context["dsar_output"]
        assert "UNSUBSCRIBED test2@example.com (ctms id: 456)." in response.context["dsar_output"]
        assert "UNSUBSCRIBED test3@example.com (ctms id: 789)." in response.context["dsar_output"]

    def test_post_valid_email(self):
        self._create_admin_user()
        self._login_admin_user()
        with patch("basket.admin.ctms", spec_set=["get", "interface"]) as mock_ctms:
            mock_ctms.get.return_value = {"email_id": "123", "fxa_id": "", "mofo_contact_id": ""}
            response = self.client.post(self.url, {"emails": "test@example.com"}, follow=True)

        assert response.status_code == 200
        assert mock_ctms.get.called
        mock_ctms.interface.patch_by_email_id.assert_called_with("123", self.update_data)
        assert "UNSUBSCRIBED test@example.com (ctms id: 123)." in response.context["dsar_output"]

    def test_post_unknown_ctms_user(self, mocker):
        self._create_admin_user()
        self._login_admin_user()
        with patch("basket.admin.ctms", spec_set=["get", "interface"]) as mock_ctms:
            mock_ctms.get.return_value = None
            response = self.client.post(self.url, {"emails": "unknown@example.com"}, follow=True)

        assert response.status_code == 200
        assert mock_ctms.get.called
        assert not mock_ctms.interface.patch_by_email_id.called
        assert "unknown@example.com not found in CTMS" in response.context["dsar_output"]

    def test_post_invalid_email(self, mocker):
        self._create_admin_user()
        self._login_admin_user()
        with patch("basket.admin.ctms", spec_set=["get", "interface"]) as mock_ctms:
            response = self.client.post(self.url, {"emails": "invalid@email"}, follow=True)

        assert response.status_code == 200
        assert not mock_ctms.get.called
        assert not mock_ctms.interface.patch_by_email_id.called
        assert response.context["dsar_output"] is None
        assert response.context["dsar_form"].errors == {"emails": ["Invalid email: invalid@email"]}

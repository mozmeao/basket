from unittest.mock import patch

from django.contrib.admin.sites import site

import pytest

from basket.contact.admin import FormDeliveryInline, FormRouteAdmin, FormSubmissionAdmin
from basket.contact.models import FormDestination, FormRoute, FormSubmission


def test_form_route_and_submission_are_registered():
    assert FormRoute in site._registry
    assert FormSubmission in site._registry


@pytest.fixture
def route(db):
    return FormRoute.objects.create(form_id="enterprise-contact", name="Enterprise Contact", active=True, created_by="dev@example.com")


@pytest.fixture
def admin_instance():
    return FormRouteAdmin(FormRoute, site)


@pytest.mark.django_db
class TestTestDeliveryAction:
    def test_no_active_destinations_warns(self, admin_instance, route, rf):
        request = rf.get("/admin/")
        with patch.object(admin_instance, "message_user") as message_user:
            admin_instance.test_delivery(request, FormRoute.objects.filter(pk=route.pk))

        message_user.assert_called_once()
        assert "no active destinations" in message_user.call_args.args[1]

    def test_successful_delivery_creates_submission_and_reports_success(self, admin_instance, route, rf):
        FormDestination.objects.create(route=route, dest_type="gsheet", label="Sheet", config={}, field_map={}, active=True)
        request = rf.get("/admin/")

        with (
            patch("basket.contact.admin.deliver_to_gsheet") as mock_deliver,
            patch.object(admin_instance, "message_user") as message_user,
        ):
            admin_instance.test_delivery(request, FormRoute.objects.filter(pk=route.pk))

        mock_deliver.assert_called_once()
        assert FormSubmission.objects.filter(route=route).exists()
        assert "delivered successfully" in message_user.call_args.args[1]

    def test_failed_delivery_reports_error(self, admin_instance, route, rf):
        FormDestination.objects.create(route=route, dest_type="gsheet", label="Sheet", config={}, field_map={}, active=True)
        request = rf.get("/admin/")

        with (
            patch("basket.contact.admin.deliver_to_gsheet", side_effect=Exception("boom")),
            patch.object(admin_instance, "message_user") as message_user,
        ):
            admin_instance.test_delivery(request, FormRoute.objects.filter(pk=route.pk))

        assert "failed" in message_user.call_args.args[1]

    def test_dummy_data_covers_every_mapped_field(self, admin_instance, route, rf):
        # Regression: dummy data used to cover only email/first_name.
        FormDestination.objects.create(
            route=route,
            dest_type="gsheet",
            label="Sheet",
            config={},
            field_map={"email": "Email", "first_name": "First Name", "Deployment Size": "Deployment Size"},
            active=True,
        )
        request = rf.get("/admin/")

        with (
            patch("basket.contact.admin.deliver_to_gsheet") as mock_deliver,
            patch.object(admin_instance, "message_user"),
        ):
            admin_instance.test_delivery(request, FormRoute.objects.filter(pk=route.pk))

        submission = FormSubmission.objects.get(route=route)
        assert "Deployment Size" in submission.payload["data"]
        assert submission.payload["data"]["Deployment Size"].startswith("basket-admin-test_")
        mock_deliver.assert_called_once()

    def test_dummy_data_is_clearly_marked_as_test_data(self, admin_instance, route, rf):
        # This writes to real destinations, so values must be obviously synthetic.
        FormDestination.objects.create(route=route, dest_type="gsheet", label="Sheet", config={}, field_map={"email": "Email"}, active=True)
        request = rf.get("/admin/")

        with (
            patch("basket.contact.admin.deliver_to_gsheet"),
            patch.object(admin_instance, "message_user"),
        ):
            admin_instance.test_delivery(request, FormRoute.objects.filter(pk=route.pk))

        submission = FormSubmission.objects.get(route=route)
        assert submission.payload["data"]["email"].startswith("basket-admin-test_")
        assert submission.payload["data"]["email"].endswith("@example.invalid")

    def test_inactive_destinations_are_skipped(self, admin_instance, route, rf):
        FormDestination.objects.create(route=route, dest_type="gsheet", label="Sheet", config={}, field_map={}, active=False)
        request = rf.get("/admin/")

        with patch.object(admin_instance, "message_user") as message_user:
            admin_instance.test_delivery(request, FormRoute.objects.filter(pk=route.pk))

        assert "no active destinations" in message_user.call_args.args[1]


@pytest.mark.django_db
class TestFormSubmissionAdmin:
    def test_cannot_be_added_changed_or_deleted_via_admin(self):
        admin_instance = FormSubmissionAdmin(FormSubmission, site)
        assert admin_instance.has_add_permission(None) is False
        assert admin_instance.has_change_permission(None) is False
        assert admin_instance.has_delete_permission(None) is False

    def test_shows_per_destination_deliveries_read_only(self):
        inline = FormDeliveryInline(FormSubmission, site)
        assert FormDeliveryInline in FormSubmissionAdmin.inlines
        assert inline.has_add_permission(None) is False
        assert inline.can_delete is False
        assert set(inline.readonly_fields) == {"destination", "status", "row_number"}

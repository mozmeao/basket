from django.core.exceptions import ValidationError
from django.db.models import ProtectedError

import pytest

from basket.contact.models import DEST_TYPES, STATUS, FormDestination, FormRoute, FormSubmission


@pytest.fixture
def route():
    return FormRoute.objects.create(form_id="enterprise-contact", name="Enterprise Contact", created_by="dev@example.com")


@pytest.mark.django_db
class TestFormRoute:
    def test_defaults_to_inactive(self, route):
        assert route.active is False

    def test_form_id_must_be_unique(self, route):
        with pytest.raises(Exception):  # noqa: B017 -- IntegrityError, backend-dependent
            FormRoute.objects.create(form_id="enterprise-contact", name="Duplicate", created_by="dev@example.com")

    def test_str(self, route):
        assert str(route) == "Enterprise Contact (enterprise-contact)"


@pytest.mark.django_db
class TestFormDestination:
    def test_defaults_to_active(self, route):
        dest = FormDestination.objects.create(route=route, dest_type="gsheet", label="Sheet", config={}, field_map={})
        assert dest.active is True

    def test_only_gsheet_is_offered(self):
        # v1 deliberately restricts this -- the fan-out loop has no else branch, so
        # adding a dest_type here without a matching task would silently enqueue nothing.
        assert DEST_TYPES == [("gsheet", "Google Sheet")]

    def test_deleting_route_cascades_to_destinations(self, route):
        dest = FormDestination.objects.create(route=route, dest_type="gsheet", label="Sheet", config={}, field_map={})
        route.delete()
        assert not FormDestination.objects.filter(pk=dest.pk).exists()

    def test_str(self, route):
        dest = FormDestination.objects.create(route=route, dest_type="gsheet", label="Sheet", config={}, field_map={})
        assert str(dest) == "Sheet (gsheet)"

    def test_clean_accepts_header_text(self, route):
        dest = FormDestination(
            route=route, dest_type="gsheet", label="Sheet", config={}, field_map={"email": "Business Email", "first_name": "First Name"}
        )
        dest.clean()  # should not raise

    def test_clean_rejects_empty_string_values(self, route):
        dest = FormDestination(route=route, dest_type="gsheet", label="Sheet", config={}, field_map={"email": "  "})
        with pytest.raises(ValidationError):
            dest.clean()

    def test_clean_rejects_non_string_values(self, route):
        # A common mistake -- e.g. pasting a number or boolean instead of header text.
        dest = FormDestination(route=route, dest_type="gsheet", label="Sheet", config={}, field_map={"email": 1})
        with pytest.raises(ValidationError):
            dest.clean()

    def test_clean_does_not_crash_when_field_map_is_none(self, route):
        # full_clean() still calls clean() even when field_map already failed its own
        # required-field check and is None -- it doesn't stop at the first error.
        dest = FormDestination(route=route, dest_type="gsheet", label="Sheet", config={}, field_map=None)
        dest.clean()  # should not raise AttributeError


@pytest.mark.django_db
class TestFormSubmission:
    def test_defaults_to_queued(self, route):
        submission = FormSubmission.objects.create(route=route, payload={})
        assert submission.status == "queued"

    def test_no_partial_state(self):
        # v1 deliberately dropped "partial" -- each destination's task sets status
        # directly to delivered/failed. See the module-level comment on STATUS.
        assert STATUS == [("queued", "queued"), ("delivered", "delivered"), ("failed", "failed")]

    def test_deleting_route_with_submissions_is_protected(self, route):
        # Submissions are an audit trail -- a route must not be deletable out from
        # under one, unlike destinations which cascade freely.
        FormSubmission.objects.create(route=route, payload={})
        with pytest.raises(ProtectedError):
            route.delete()

    def test_str(self, route):
        submission = FormSubmission.objects.create(route=route, payload={})
        assert str(submission) == f"enterprise-contact @ {submission.received_at:%Y-%m-%d %H:%M}"

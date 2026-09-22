from unittest.mock import patch

import pytest

from basket.contact.intake_tasks import _build_row, _column_to_index, deliver_to_gsheet
from basket.contact.models import FormDestination, FormRoute, FormSubmission


class TestColumnToIndex:
    def test_single_letter(self):
        assert _column_to_index("A") == 0
        assert _column_to_index("B") == 1
        assert _column_to_index("Z") == 25

    def test_double_letter(self):
        assert _column_to_index("AA") == 26
        assert _column_to_index("AB") == 27

    def test_lowercase(self):
        assert _column_to_index("a") == 0


class TestBuildRow:
    def test_empty_field_map(self):
        assert _build_row({"email": "a@b.com"}, {}) == []

    def test_simple_mapping(self):
        row = _build_row({"email": "a@b.com", "first_name": "Jane"}, {"email": "A", "first_name": "B"})
        assert row == ["a@b.com", "Jane"]

    def test_fills_gaps_between_mapped_columns(self):
        row = _build_row({"email": "a@b.com", "country": "US"}, {"email": "A", "country": "C"})
        assert row == ["a@b.com", "", "US"]

    def test_unmapped_data_fields_are_dropped(self):
        row = _build_row({"email": "a@b.com", "secret": "shh"}, {"email": "A"})
        assert row == ["a@b.com"]

    def test_missing_data_field_becomes_empty_string(self):
        row = _build_row({"email": "a@b.com"}, {"email": "A", "first_name": "B"})
        assert row == ["a@b.com", ""]


@pytest.fixture
def route(db):
    return FormRoute.objects.create(form_id="enterprise-contact", name="Enterprise Contact", active=True, created_by="dev@example.com")


@pytest.fixture
def destination(route):
    return FormDestination.objects.create(
        route=route,
        dest_type="gsheet",
        label="Sheet",
        config={"sheet_id": "sheet-id", "tab": "Responses"},
        field_map={"email": "A", "first_name": "B"},
        active=True,
    )


@pytest.fixture
def submission(route):
    return FormSubmission.objects.create(route=route, payload={"data": {"email": "a@b.com", "first_name": "Jane"}})


@pytest.fixture
def sent_rows(settings):
    settings.GOOGLE_SHEETS_CONTACT_CREDENTIALS_JSON = "{}"
    with (
        patch("basket.contact.intake_tasks.Credentials"),
        patch("basket.contact.intake_tasks.AuthorizedSession") as session,
    ):
        yield session.return_value.post


@pytest.mark.django_db
class TestDeliverToGsheet:
    def test_appends_row_and_marks_delivered(self, submission, destination, sent_rows):
        deliver_to_gsheet(submission.id, destination.id)

        assert sent_rows.call_args.kwargs["json"]["values"] == [["a@b.com", "Jane"]]
        assert sent_rows.call_args.args[0].endswith("/sheet-id/values/Responses:append")
        submission.refresh_from_db()
        assert submission.status == "delivered"

    def test_marks_failed_and_reraises_on_error(self, submission, destination, sent_rows):
        sent_rows.return_value.raise_for_status.side_effect = Exception("boom")

        with pytest.raises(Exception, match="boom"):
            deliver_to_gsheet(submission.id, destination.id)

        submission.refresh_from_db()
        assert submission.status == "failed"

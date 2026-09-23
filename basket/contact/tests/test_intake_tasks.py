from unittest.mock import MagicMock, patch

import pytest

from basket.contact.intake_tasks import _build_row, deliver_to_gsheet
from basket.contact.models import FormDeliveryClaim, FormDestination, FormRoute, FormSubmission


class TestBuildRow:
    def test_empty_field_map(self):
        assert _build_row({"email": "a@b.com"}, {}, ["Email"]) == []

    def test_simple_mapping(self):
        row = _build_row({"email": "a@b.com", "first_name": "Jane"}, {"email": "Email", "first_name": "First Name"}, ["Email", "First Name"])
        assert row == ["a@b.com", "Jane"]

    def test_fills_gaps_between_mapped_headers(self):
        row = _build_row({"email": "a@b.com", "country": "US"}, {"email": "Email", "country": "Country"}, ["Email", "Middle", "Country"])
        assert row == ["a@b.com", "", "US"]

    def test_unmapped_data_fields_are_dropped(self):
        row = _build_row({"email": "a@b.com", "secret": "shh"}, {"email": "Email"}, ["Email"])
        assert row == ["a@b.com"]

    def test_missing_data_field_becomes_empty_string(self):
        row = _build_row({"email": "a@b.com"}, {"email": "Email", "first_name": "First Name"}, ["Email", "First Name"])
        assert row == ["a@b.com", ""]

    def test_header_reordering_does_not_misalign_values(self):
        # The whole point of matching by header text: the sheet's columns can be in
        # any order, or have extra columns, and the mapping still lands correctly.
        row = _build_row(
            {"email": "a@b.com", "first_name": "Jane"},
            {"email": "Email", "first_name": "First Name"},
            ["Extra", "First Name", "Email"],
        )
        assert row == ["", "Jane", "a@b.com"]

    def test_header_not_found_raises(self):
        with pytest.raises(ValueError, match="not found"):
            _build_row({"email": "a@b.com"}, {"email": "Business Email"}, ["Email"])


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
        field_map={"email": "Email", "first_name": "First Name"},
        active=True,
        next_row=2,
    )


@pytest.fixture
def submission(route):
    return FormSubmission.objects.create(route=route, payload={"data": {"email": "a@b.com", "first_name": "Jane"}})


@pytest.fixture
def mock_session(settings):
    settings.GOOGLE_SHEETS_CONTACT_CREDENTIALS_JSON = "{}"
    with (
        patch("basket.contact.intake_tasks.Credentials"),
        patch("basket.contact.intake_tasks.AuthorizedSession") as session_cls,
    ):
        session = session_cls.return_value
        get_response = MagicMock()
        get_response.json.return_value = {"values": [["Email", "First Name"]]}
        session.get.return_value = get_response
        yield session


@pytest.mark.django_db
class TestDeliverToGsheet:
    def test_writes_row_and_marks_delivered(self, submission, destination, mock_session):
        deliver_to_gsheet(submission.id, destination.id)

        assert mock_session.get.call_args.args[0].endswith("/sheet-id/values/Responses!1:1")
        assert mock_session.put.call_args.kwargs["json"]["values"] == [["a@b.com", "Jane"]]
        assert mock_session.put.call_args.args[0].endswith("/sheet-id/values/Responses!A2")
        submission.refresh_from_db()
        assert submission.status == "delivered"

    def test_claims_rows_sequentially_across_deliveries(self, route, destination, mock_session):
        # Regression: relying on the Sheets API's `values.append` to auto-detect "the
        # table" proved unreliable with a sparse/discontiguous header row -- it could
        # append dozens of columns out, or even merge a new row's values into an
        # unrelated existing row. Tracking the row number ourselves and incrementing
        # it under a DB lock removes that ambiguity, and lets two deliveries to the
        # same destination land on consecutive rows instead of racing for the same one.
        first = FormSubmission.objects.create(route=route, payload={"data": {"email": "a@b.com", "first_name": "Jane"}})
        second = FormSubmission.objects.create(route=route, payload={"data": {"email": "c@d.com", "first_name": "Bob"}})

        deliver_to_gsheet(first.id, destination.id)
        deliver_to_gsheet(second.id, destination.id)

        first_write, second_write = mock_session.put.call_args_list
        assert first_write.args[0].endswith("!A2")
        assert second_write.args[0].endswith("!A3")
        destination.refresh_from_db()
        assert destination.next_row == 4

    def test_bootstraps_row_counter_from_sheet_when_unset(self, submission, destination, mock_session):
        destination.next_row = None
        destination.save(update_fields=["next_row"])

        def fake_get(url, **kwargs):
            response = MagicMock()
            if url.endswith("!1:1"):
                response.json.return_value = {"values": [["Email", "First Name"]]}
            else:
                response.json.return_value = {"values": [["Email", "First Name"], ["existing@example.com", "Old"]]}
            return response

        mock_session.get.side_effect = fake_get

        deliver_to_gsheet(submission.id, destination.id)

        assert mock_session.put.call_args.args[0].endswith("!A3")
        destination.refresh_from_db()
        assert destination.next_row == 4

    def test_marks_failed_and_reraises_on_error(self, submission, destination, mock_session):
        mock_session.put.return_value.raise_for_status.side_effect = Exception("boom")

        with pytest.raises(Exception, match="boom"):
            deliver_to_gsheet(submission.id, destination.id)

        submission.refresh_from_db()
        assert submission.status == "failed"

    def test_retry_after_write_failure_reuses_the_same_claimed_row(self, submission, destination, mock_session):
        # Regression: RQ retries `deliver_to_gsheet` from scratch on failure. If the
        # sheet write fails after the row was already claimed, a naive retry would
        # claim a fresh row and orphan the first one. The claim must be reused instead.
        mock_session.put.return_value.raise_for_status.side_effect = Exception("boom")
        with pytest.raises(Exception, match="boom"):
            deliver_to_gsheet(submission.id, destination.id)

        mock_session.put.return_value.raise_for_status.side_effect = None
        deliver_to_gsheet(submission.id, destination.id)

        first_attempt, retry = mock_session.put.call_args_list
        assert first_attempt.args[0].endswith("!A2")
        assert retry.args[0].endswith("!A2")
        assert FormDeliveryClaim.objects.filter(submission=submission, destination=destination).count() == 1
        destination.refresh_from_db()
        assert destination.next_row == 3
        submission.refresh_from_db()
        assert submission.status == "delivered"

    def test_marks_failed_when_header_not_found(self, route, mock_session):
        # Regression: a field_map header that doesn't exist in the sheet used to
        # silently misalign or corrupt the row instead of failing clearly.
        destination = FormDestination.objects.create(
            route=route,
            dest_type="gsheet",
            label="Sheet",
            config={"sheet_id": "sheet-id", "tab": "Responses"},
            field_map={"email": "Business Email"},  # not in the mocked header row
            active=True,
        )
        submission = FormSubmission.objects.create(route=route, payload={"data": {"email": "a@b.com"}})

        with pytest.raises(ValueError, match="not found"):
            deliver_to_gsheet(submission.id, destination.id)

        submission.refresh_from_db()
        assert submission.status == "failed"
        mock_session.put.assert_not_called()
        destination.refresh_from_db()
        assert destination.next_row is None  # never claimed a row for a submission that can't be written

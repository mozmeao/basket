from unittest.mock import MagicMock, patch

import pytest

from basket.contact.intake_tasks import _build_row, _claim_row, deliver_to_gsheet
from basket.contact.models import FormDelivery, FormDestination, FormRoute, FormSubmission


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
def second_destination(route):
    return FormDestination.objects.create(
        route=route,
        dest_type="gsheet",
        label="Other Sheet",
        config={"sheet_id": "other-sheet", "tab": "Responses"},
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

        assert mock_session.get.call_args.args[0].endswith("/sheet-id/values/'Responses'!1:1")
        assert mock_session.put.call_args.kwargs["json"]["values"] == [["a@b.com", "Jane"]]
        assert mock_session.put.call_args.args[0].endswith("/sheet-id/values/'Responses'!A2")
        submission.refresh_from_db()
        assert submission.status == "delivered"

    def test_quotes_tab_names_with_spaces_for_a1_notation(self, route, mock_session):
        # "Form Responses 1" is Google Sheets' default tab name.
        destination = FormDestination.objects.create(
            route=route,
            dest_type="gsheet",
            label="Sheet",
            config={"sheet_id": "sheet-id", "tab": "Form Responses 1"},
            field_map={"email": "Email", "first_name": "First Name"},
            active=True,
            next_row=2,
        )
        submission = FormSubmission.objects.create(route=route, payload={"data": {"email": "a@b.com", "first_name": "Jane"}})

        deliver_to_gsheet(submission.id, destination.id)

        assert mock_session.get.call_args.args[0].endswith("/sheet-id/values/'Form Responses 1'!1:1")
        assert mock_session.put.call_args.args[0].endswith("/sheet-id/values/'Form Responses 1'!A2")

    def test_claims_rows_sequentially_across_deliveries(self, route, destination, mock_session):
        # Regression: values:append misplaced rows when the header row had gaps.
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
        # Regression: RQ retries from scratch, which used to claim a fresh row each time.
        mock_session.put.return_value.raise_for_status.side_effect = Exception("boom")
        with pytest.raises(Exception, match="boom"):
            deliver_to_gsheet(submission.id, destination.id)

        mock_session.put.return_value.raise_for_status.side_effect = None
        deliver_to_gsheet(submission.id, destination.id)

        first_attempt, retry = mock_session.put.call_args_list
        assert first_attempt.args[0].endswith("!A2")
        assert retry.args[0].endswith("!A2")
        delivery = FormDelivery.objects.get(submission=submission, destination=destination)
        assert delivery.status == "delivered"
        destination.refresh_from_db()
        assert destination.next_row == 3
        submission.refresh_from_db()
        assert submission.status == "delivered"

    def test_claim_row_reuses_a_row_claimed_while_waiting_for_the_lock(self, submission, destination, mock_session):
        # `stale` was loaded before a concurrent attempt claimed row 2, so next_row must not move.
        stale = FormDelivery.objects.create(submission=submission, destination=destination)
        FormDelivery.objects.filter(pk=stale.pk).update(row_number=2)
        FormDestination.objects.filter(pk=destination.pk).update(next_row=3)

        assert _claim_row(mock_session, stale, "sheet-id", "Responses") == 2

        destination.refresh_from_db()
        assert destination.next_row == 3
        mock_session.get.assert_not_called()

    def test_submission_fails_if_any_destination_fails(self, submission, destination, second_destination, mock_session):
        # Regression: a later success used to overwrite an earlier failure.
        def fake_put(url, **kwargs):
            response = MagicMock()
            if "other-sheet" in url:
                response.raise_for_status.side_effect = Exception("boom")
            return response

        mock_session.put.side_effect = fake_put

        with pytest.raises(Exception, match="boom"):
            deliver_to_gsheet(submission.id, second_destination.id)
        deliver_to_gsheet(submission.id, destination.id)

        submission.refresh_from_db()
        assert submission.status == "failed"
        assert FormDelivery.objects.get(submission=submission, destination=destination).status == "delivered"
        assert FormDelivery.objects.get(submission=submission, destination=second_destination).status == "failed"

    def test_submission_stays_queued_until_every_destination_delivers(self, submission, destination, second_destination, mock_session):
        FormDelivery.objects.create(submission=submission, destination=destination)
        FormDelivery.objects.create(submission=submission, destination=second_destination)

        deliver_to_gsheet(submission.id, destination.id)
        submission.refresh_from_db()
        assert submission.status == "queued"

        deliver_to_gsheet(submission.id, second_destination.id)
        submission.refresh_from_db()
        assert submission.status == "delivered"

    def test_marks_failed_when_header_not_found(self, route, mock_session):
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
        assert destination.next_row is None
        delivery = FormDelivery.objects.get(submission=submission, destination=destination)
        assert delivery.status == "failed"
        assert delivery.row_number is None

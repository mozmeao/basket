import re
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
        # Remembers PUTs so row counts reflect earlier deliveries.
        sheet = {1: ["Email", "First Name"]}

        def fake_get(url, **kwargs):
            response = MagicMock()
            single_row = re.search(r"!(\d+):\1$", url)
            if single_row:
                row = sheet.get(int(single_row.group(1)))
                response.json.return_value = {"values": [row]} if row else {}
            else:
                values = [sheet.get(i, []) for i in range(1, max(sheet) + 1)]
                response.json.return_value = {"values": values}
            return response

        def fake_put(url, **kwargs):
            response = session.put.return_value
            try:
                response.raise_for_status()
            except Exception:
                return response  # a failed write doesn't land in the sheet
            sheet[int(url.rsplit("!A", 1)[1])] = kwargs["json"]["values"][0]
            return response

        session.get.side_effect = fake_get
        session.put.side_effect = fake_put
        session.sheet = sheet
        yield session


@pytest.mark.django_db
class TestDeliverToGsheet:
    def test_writes_row_and_marks_delivered(self, submission, destination, mock_session):
        deliver_to_gsheet(submission.id, destination.id)

        assert any(call.args[0].endswith("/sheet-id/values/'Responses'!1:1") for call in mock_session.get.call_args_list)
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

        assert any(call.args[0].endswith("/sheet-id/values/'Form Responses 1'!1:1") for call in mock_session.get.call_args_list)
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
        mock_session.sheet[2] = ["existing@example.com", "Old"]

        deliver_to_gsheet(submission.id, destination.id)

        assert mock_session.put.call_args.args[0].endswith("!A3")
        destination.refresh_from_db()
        assert destination.next_row == 4

    def test_skips_rows_added_to_the_sheet_after_the_counter_was_set(self, submission, destination, mock_session):
        mock_session.sheet.update({i: ["x@example.com", "X"] for i in range(2, 102)})

        deliver_to_gsheet(submission.id, destination.id)

        assert mock_session.put.call_args.args[0].endswith("!A102")
        destination.refresh_from_db()
        assert destination.next_row == 103

    def test_fills_the_row_freed_by_a_deletion(self, submission, destination, mock_session):
        FormDestination.objects.filter(pk=destination.pk).update(next_row=102)
        mock_session.sheet.update({i: ["x@example.com", "X"] for i in range(2, 101)})

        deliver_to_gsheet(submission.id, destination.id)

        assert mock_session.put.call_args.args[0].endswith("!A101")

    @pytest.mark.parametrize("status", ["queued", "failed"])
    def test_skips_rows_claimed_by_deliveries_not_yet_written(self, route, submission, destination, mock_session, status):
        pending = FormSubmission.objects.create(route=route, payload={"data": {"email": "c@d.com", "first_name": "Bob"}})
        FormDelivery.objects.create(submission=pending, destination=destination, status=status, row_number=5)

        deliver_to_gsheet(submission.id, destination.id)

        assert mock_session.put.call_args.args[0].endswith("!A6")

    def test_ignores_rows_claimed_by_delivered_deliveries(self, route, submission, destination, mock_session):
        done = FormSubmission.objects.create(route=route, payload={"data": {"email": "c@d.com", "first_name": "Bob"}})
        FormDelivery.objects.create(submission=done, destination=destination, status="delivered", row_number=5)

        deliver_to_gsheet(submission.id, destination.id)

        assert mock_session.put.call_args.args[0].endswith("!A2")

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

    def test_retry_claims_a_fresh_row_if_the_claimed_one_was_filled_meanwhile(self, submission, destination, mock_session):
        mock_session.put.return_value.raise_for_status.side_effect = Exception("boom")
        with pytest.raises(Exception, match="boom"):
            deliver_to_gsheet(submission.id, destination.id)

        mock_session.sheet[2] = ["manual@example.com", "Manual"]
        mock_session.put.return_value.raise_for_status.side_effect = None
        deliver_to_gsheet(submission.id, destination.id)

        assert mock_session.put.call_args.args[0].endswith("!A3")
        assert mock_session.sheet[2] == ["manual@example.com", "Manual"]
        delivery = FormDelivery.objects.get(submission=submission, destination=destination)
        assert delivery.row_number == 3
        assert delivery.status == "delivered"

    def test_retry_fills_the_gap_left_by_a_deletion_while_it_waited(self, submission, destination, mock_session):
        mock_session.sheet.update({i: ["x@example.com", "X"] for i in range(2, 102)})
        mock_session.put.return_value.raise_for_status.side_effect = Exception("boom")
        with pytest.raises(Exception, match="boom"):
            deliver_to_gsheet(submission.id, destination.id)
        assert mock_session.put.call_args.args[0].endswith("!A102")

        del mock_session.sheet[101]
        mock_session.put.return_value.raise_for_status.side_effect = None
        deliver_to_gsheet(submission.id, destination.id)

        assert mock_session.put.call_args.args[0].endswith("!A101")
        assert FormDelivery.objects.get(submission=submission, destination=destination).row_number == 101

    def test_retry_rewrites_its_own_row_if_the_earlier_write_landed(self, submission, destination, mock_session):
        mock_session.sheet[2] = ["a@b.com", "Jane"]
        FormDelivery.objects.create(submission=submission, destination=destination, status="failed", row_number=2)

        deliver_to_gsheet(submission.id, destination.id)

        assert mock_session.put.call_args.args[0].endswith("!A2")
        assert max(mock_session.sheet) == 2

    def test_retry_recognizes_its_own_row_when_sheets_dropped_trailing_blanks(self, route, destination, mock_session):
        submission = FormSubmission.objects.create(route=route, payload={"data": {"email": "a@b.com"}})
        mock_session.sheet[2] = ["a@b.com"]
        FormDelivery.objects.create(submission=submission, destination=destination, status="failed", row_number=2)

        deliver_to_gsheet(submission.id, destination.id)

        assert mock_session.put.call_args.args[0].endswith("!A2")
        assert mock_session.put.call_args.kwargs["json"]["values"] == [["a@b.com", ""]]
        assert max(mock_session.sheet) == 2

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

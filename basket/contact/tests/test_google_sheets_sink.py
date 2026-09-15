from unittest.mock import patch

import pytest

from basket.contact.backends.google_sheets_contact_sink import _COLUMNS, GoogleSheetsContactSink


@pytest.fixture
def sent_rows(settings):
    settings.GOOGLE_SHEETS_CONTACT_CREDENTIALS_JSON = "{}"
    settings.GOOGLE_SHEETS_CONTACT_SPREADSHEET_ID = "sheet-id"
    with (
        patch("basket.contact.backends.google_sheets_contact_sink.Credentials"),
        patch("basket.contact.backends.google_sheets_contact_sink.AuthorizedSession") as session,
    ):
        yield session.return_value.post


def test_both_forms_append_aligned_rows_to_one_tab(sent_rows):
    # Basic and enterprise share the sheet, so every row must have the same width
    # and put each value under the same column.
    GoogleSheetsContactSink().submit({"first_name": "Jane", "opt_in": "on", "accepted_terms": "on"})
    GoogleSheetsContactSink().submit({"first_name": "Ann", "opt_in": "on", "message": "hi"})

    basic, enterprise = (call.kwargs["json"]["values"][0] for call in sent_rows.call_args_list)
    assert len(basic) == len(enterprise) == len(_COLUMNS)
    assert basic[_COLUMNS.index("opt_in")] == enterprise[_COLUMNS.index("opt_in")] == "on"
    assert basic[_COLUMNS.index("accepted_terms")] == "on"
    assert enterprise[_COLUMNS.index("accepted_terms")] == ""
    assert basic[_COLUMNS.index("message")] == ""
    assert enterprise[_COLUMNS.index("message")] == "hi"
    assert sent_rows.call_args.args[0].endswith("/values/lead-capture:append")

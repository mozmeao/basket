import json

from django.conf import settings

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials

from basket.base.decorators import rq_task

from .models import FormDestination, FormSubmission

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_APPEND_URL = "https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{range}:append"


def _column_to_index(column: str) -> int:
    """Convert a spreadsheet column letter ("A", "B", ..., "AA", ...) to a 0-based index."""
    index = 0
    for char in column.upper():
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


def _build_row(data: dict, field_map: dict) -> list:
    """Map CMS field values to column positions, filling gaps with "" so the row lines
    up correctly regardless of which columns are actually mapped. Fields in `data` with
    no entry in `field_map` are silently dropped -- v1 always discards unmapped fields."""
    if not field_map:
        return []
    positions = {_column_to_index(column): data.get(field, "") for field, column in field_map.items()}
    width = max(positions) + 1
    return [positions.get(i, "") for i in range(width)]


def _append_row(sheet_id: str, tab: str, row: list) -> None:
    credentials = Credentials.from_service_account_info(
        json.loads(settings.GOOGLE_SHEETS_CONTACT_CREDENTIALS_JSON),
        scopes=_SCOPES,
    )
    session = AuthorizedSession(credentials)
    url = _APPEND_URL.format(spreadsheet_id=sheet_id, range=tab)
    response = session.post(url, params={"valueInputOption": "RAW"}, json={"values": [row]})
    response.raise_for_status()


@rq_task
def deliver_to_gsheet(submission_id, destination_id):
    submission = FormSubmission.objects.get(pk=submission_id)
    destination = FormDestination.objects.get(pk=destination_id)

    try:
        row = _build_row(submission.payload["data"], destination.field_map)
        _append_row(destination.config["sheet_id"], destination.config["tab"], row)
    except Exception:
        submission.status = "failed"
        submission.save(update_fields=["status"])
        raise

    submission.status = "delivered"
    submission.save(update_fields=["status"])

import json

from django.conf import settings
from django.db import transaction

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials

from basket.base.decorators import rq_task

from .models import FormDelivery, FormDestination, FormSubmission

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_VALUES_URL = "https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{range}"
_REQUEST_TIMEOUT_SECONDS = 10


def _get_session() -> AuthorizedSession:
    credentials = Credentials.from_service_account_info(
        json.loads(settings.GOOGLE_SHEETS_CONTACT_CREDENTIALS_JSON),
        scopes=_SCOPES,
    )
    return AuthorizedSession(credentials)


def _quote_tab(tab: str) -> str:
    # A1 notation needs tab names with spaces quoted; embedded quotes are doubled.
    return "'" + tab.replace("'", "''") + "'"


def _fetch_header_row(session: AuthorizedSession, sheet_id: str, tab: str) -> list:
    url = _VALUES_URL.format(spreadsheet_id=sheet_id, range=f"{_quote_tab(tab)}!1:1")
    response = session.get(url, timeout=_REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    rows = response.json().get("values", [])
    return rows[0] if rows else []


def _fetch_row_count(session: AuthorizedSession, sheet_id: str, tab: str) -> int:
    url = _VALUES_URL.format(spreadsheet_id=sheet_id, range=_quote_tab(tab))
    response = session.get(url, timeout=_REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return len(response.json().get("values", []))


def _claim_row(session: AuthorizedSession, delivery: FormDelivery, sheet_id: str, tab: str) -> int:
    if delivery.row_number is not None:
        return delivery.row_number

    # Fetched before locking so a slow Sheets call can't block other deliveries.
    destination = FormDestination.objects.get(pk=delivery.destination_id)
    existing_rows = _fetch_row_count(session, sheet_id, tab) if destination.next_row is None else None

    with transaction.atomic():
        destination = FormDestination.objects.select_for_update().get(pk=delivery.destination_id)
        delivery.refresh_from_db(fields=["row_number"])
        if delivery.row_number is not None:  # claimed by a concurrent attempt while we waited
            return delivery.row_number
        if destination.next_row is None:
            destination.next_row = existing_rows + 1
        delivery.row_number = destination.next_row
        destination.next_row += 1
        destination.save(update_fields=["next_row"])
        delivery.save(update_fields=["row_number"])
    return delivery.row_number


def _build_row(data: dict, field_map: dict, headers: list) -> list:
    if not field_map:
        return []

    positions = {}
    for field, header in field_map.items():
        try:
            index = headers.index(header)
        except ValueError:
            raise ValueError(f"header {header!r} not found in the destination's sheet header row -- check field_map") from None
        positions[index] = data.get(field, "")

    width = max(positions) + 1
    return [positions.get(i, "") for i in range(width)]


def _write_row(session: AuthorizedSession, sheet_id: str, tab: str, row_number: int, row: list) -> None:
    # Explicit row, not values:append, which misplaces rows when the header row has gaps.
    url = _VALUES_URL.format(spreadsheet_id=sheet_id, range=f"{_quote_tab(tab)}!A{row_number}")
    response = session.put(url, params={"valueInputOption": "RAW"}, json={"values": [row]}, timeout=_REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()


def _record_outcome(delivery: FormDelivery, status: str) -> None:
    # Locked so concurrent destination tasks can't race on the rollup.
    with transaction.atomic():
        submission = FormSubmission.objects.select_for_update().get(pk=delivery.submission_id)
        delivery.status = status
        delivery.save(update_fields=["status"])
        statuses = set(submission.deliveries.values_list("status", flat=True))
        if "failed" in statuses:
            submission.status = "failed"
        elif statuses == {"delivered"}:
            submission.status = "delivered"
        else:
            submission.status = "queued"
        submission.save(update_fields=["status"])


@rq_task
def deliver_to_gsheet(submission_id, destination_id):
    submission = FormSubmission.objects.get(pk=submission_id)
    destination = FormDestination.objects.get(pk=destination_id)
    delivery, _created = FormDelivery.objects.get_or_create(submission=submission, destination=destination)

    try:
        session = _get_session()
        sheet_id = destination.config["sheet_id"]
        tab = destination.config["tab"]
        headers = _fetch_header_row(session, sheet_id, tab)
        row = _build_row(submission.payload["data"], destination.field_map, headers)
        row_number = _claim_row(session, delivery, sheet_id, tab)
        _write_row(session, sheet_id, tab, row_number, row)
    except Exception:
        _record_outcome(delivery, "failed")
        raise

    _record_outcome(delivery, "delivered")

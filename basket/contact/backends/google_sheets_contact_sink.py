import json
import logging

from django.conf import settings

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials

from .contact_sink import ContactSink

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_APPEND_URL = "https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{range}:append"


# Column order of the sheet. Every form writes here; fields a form does not collect
# are left blank, so new columns only ever get appended.
_COLUMNS = [
    "first_name",
    "last_name",
    "company",
    "job_title",
    "business_email",
    "business_phone",
    "country",
    "opt_in",
    "lead_source",
    "cta",
    "firefox_use_stage",
    "deployment_size",
    "support_needs",
    "timeline",
    "message",
    "accepted_terms",
]


class GoogleSheetsContactSink(ContactSink):
    def submit(self, contact: dict) -> None:
        credentials = Credentials.from_service_account_info(
            json.loads(settings.GOOGLE_SHEETS_CONTACT_CREDENTIALS_JSON),
            scopes=_SCOPES,
        )
        session = AuthorizedSession(credentials)

        row = [contact.get(column, "") for column in _COLUMNS]

        url = _APPEND_URL.format(
            spreadsheet_id=settings.GOOGLE_SHEETS_CONTACT_SPREADSHEET_ID,
            range="lead-capture",
        )
        response = session.post(
            url,
            params={"valueInputOption": "RAW"},
            json={"values": [row]},
        )
        response.raise_for_status()

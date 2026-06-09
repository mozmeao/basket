import json
import logging

from django.conf import settings

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials

from .ContactSink import ContactSink

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_APPEND_URL = "https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{range}:append"


class GoogleSheetsContactSink(ContactSink):
    def submit(self, contact: dict) -> None:
        credentials = Credentials.from_service_account_info(
            json.loads(settings.GOOGLE_SHEETS_CONTACT_CREDENTIALS_JSON),
            scopes=_SCOPES,
        )
        session = AuthorizedSession(credentials)

        row = [
            contact["first_name"],
            contact["last_name"],
            contact["company"],
            contact["job_title"],
            contact["business_email"],
            contact["business_phone"],
            contact["company_size"],
            contact["country"],
            contact["opt_in"],
            "http://techrider.de",  # lead source
            "Request a Private Briefing",  # cta
        ]

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

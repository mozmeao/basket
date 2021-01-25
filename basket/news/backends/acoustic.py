import logging

from django.conf import settings
from django.template.loader import render_to_string

from silverpop.api import ApiResponse, Silverpop


logger = logging.getLogger(__name__)


class SilverpopTransact(Silverpop):
    api_xt_endpoint = "https://transact-campaign-us-%s.goacoustic.com/XTMail"

    def __init__(self, client_id, client_secret, refresh_token, server_number):
        self.api_xt_endpoint = self.api_xt_endpoint % server_number
        super().__init__(client_id, client_secret, refresh_token, server_number)

    def _call_xt(self, xml):
        logger.debug("Request: %s" % xml)
        response = self.session.post(self.api_xt_endpoint, data={"xml": xml})
        return ApiResponse(response)

    def send_mail(self, to, campaign_id, fields=None):
        ctx = {
            "to": to,
            "campaign_id": campaign_id,
            "fields": fields or {},
        }
        xml = render_to_string("acoustic/tx-email.xml", ctx)
        return self._call_xt(xml)


acoustic = SilverpopTransact(
    client_id=settings.ACOUSTIC_CLIENT_ID,
    client_secret=settings.ACOUSTIC_CLIENT_SECRET,
    refresh_token=settings.ACOUSTIC_REFRESH_TOKEN,
    server_number=settings.ACOUSTIC_SERVER_NUMBER,
)

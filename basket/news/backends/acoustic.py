import logging
from xml.etree import ElementTree

from django.conf import settings

from silverpop.api import Silverpop, SilverpopResponseException


logger = logging.getLogger(__name__)


def process_reponse(resp):
    logger.debug("Response: %s" % resp.text)
    response = ElementTree.fromstring(resp.text.encode("utf-8"))
    failure = response.find(".//FAILURES/FAILURE")
    if failure:
        raise SilverpopResponseException(failure.attrib["description"])

    fault = response.find(".//Fault/FaultString")
    if fault:
        raise SilverpopResponseException(fault.text)

    return response


def process_tx_response(resp):
    logger.debug("Response: %s" % resp.text)
    response = ElementTree.fromstring(resp.text.encode("utf-8"))
    errors = response.findall(".//ERROR_STRING")
    if errors:
        for e in errors:
            if e.text:
                raise SilverpopResponseException(e.text)

    return response


def xml_tag(tag, value=None, **attrs):
    xmlt = ElementTree.Element(tag, attrs)
    if value:
        xmlt.text = value

    return xmlt


def transact_xml(to, campaign_id, fields=None, bcc=None):
    fields = fields or {}
    bcc = bcc or []
    if isinstance(bcc, str):
        bcc = [bcc]

    root = xml_tag("XTMAILING")
    root.append(xml_tag("CAMPAIGN_ID", campaign_id))
    if "transaction_id" in fields:
        root.append(xml_tag("TRANSACTION_ID", fields["transaction_id"]))

    root.append(xml_tag("SEND_AS_BATCH", "false"))
    root.append(xml_tag("NO_RETRY_ON_FAILURE", "false"))
    if fields:
        save_cols_tag = xml_tag("SAVE_COLUMNS")
        root.append(save_cols_tag)
        for name in fields:
            save_cols_tag.append(xml_tag("COLUMN_NAME", name))

    recipient_tag = xml_tag("RECIPIENT")
    root.append(recipient_tag)
    recipient_tag.append(xml_tag("EMAIL", to))
    for addr in bcc:
        recipient_tag.append(xml_tag("BCC", addr))
    recipient_tag.append(xml_tag("BODY_TYPE", "HTML"))
    for name, value in fields.items():
        p_tag = xml_tag("PERSONALIZATION")
        p_tag.append(xml_tag("TAG_NAME", name))
        p_tag.append(xml_tag("VALUE", value))
        recipient_tag.append(p_tag)

    return ElementTree.tostring(root, encoding="unicode")


class Acoustic(Silverpop):
    def _call(self, xml):
        logger.debug("Request: %s" % xml)
        response = self.session.post(self.api_endpoint, data={"xml": xml})
        return process_reponse(response)


class AcousticTransact(Silverpop):
    api_xt_endpoint = "https://transact-campaign-us-%s.goacoustic.com/XTMail"

    def __init__(self, client_id, client_secret, refresh_token, server_number):
        self.api_xt_endpoint = self.api_xt_endpoint % server_number
        super().__init__(client_id, client_secret, refresh_token, server_number)

    def _call_xt(self, xml):
        logger.debug("Request: %s" % xml)
        response = self.session.post(self.api_xt_endpoint, data={"xml": xml})
        return process_tx_response(response)

    def send_mail(self, to, campaign_id, fields=None, bcc=None):
        self._call_xt(transact_xml(to, campaign_id, fields, bcc))


acoustic = Acoustic(
    client_id=settings.ACOUSTIC_CLIENT_ID,
    client_secret=settings.ACOUSTIC_CLIENT_SECRET,
    refresh_token=settings.ACOUSTIC_REFRESH_TOKEN,
    server_number=settings.ACOUSTIC_SERVER_NUMBER,
)
acoustic_tx = AcousticTransact(
    client_id=settings.ACOUSTIC_TX_CLIENT_ID,
    client_secret=settings.ACOUSTIC_TX_CLIENT_SECRET,
    refresh_token=settings.ACOUSTIC_TX_REFRESH_TOKEN,
    server_number=settings.ACOUSTIC_TX_SERVER_NUMBER,
)

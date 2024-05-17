import logging

from django.conf import settings
from django.utils.encoding import force_bytes

from lxml import etree
from requests import ConnectionError
from silverpop.api import Silverpop, SilverpopResponseException

logger = logging.getLogger(__name__)
XML_HEADER = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


def process_response(resp):
    logger.debug(f"Response: {resp.text}")
    response = etree.fromstring(resp.text.encode("utf-8"))
    failure = response.find(".//FAILURES/FAILURE")
    if failure:
        raise SilverpopResponseException(failure.attrib["description"])

    fault = response.find(".//Fault/FaultString")
    if fault:
        raise SilverpopResponseException(fault.text)

    return response


def xml_tag(tag, value=None, cdata=False, **attrs):
    xmlt = etree.Element(tag, attrs)
    if value:
        if cdata:
            xmlt.text = etree.CDATA(value)
        else:
            xmlt.text = value

    return xmlt


def transact_xml(to, campaign_id, fields=None, bcc=None, save_to_db=False):
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
    if fields and save_to_db:
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

    return XML_HEADER + etree.tostring(root, encoding="unicode")


class Acoustic(Silverpop):
    def _call(self, xml):
        logger.debug(f"Request: {xml}")
        try:
            response = self.session.post(
                self.api_endpoint,
                data=force_bytes(xml),
                timeout=10,
                headers={"Content-Type": "text/xml"},
            )
        except ConnectionError:
            # try one more time
            response = self.session.post(
                self.api_endpoint,
                data=force_bytes(xml),
                timeout=10,
                headers={"Content-Type": "text/xml"},
            )

        return process_response(response)


acoustic = Acoustic(
    client_id=settings.ACOUSTIC_CLIENT_ID,
    client_secret=settings.ACOUSTIC_CLIENT_SECRET,
    refresh_token=settings.ACOUSTIC_REFRESH_TOKEN,
    server_number=settings.ACOUSTIC_SERVER_NUMBER,
)

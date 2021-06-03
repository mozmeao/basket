import json
from copy import deepcopy
from datetime import datetime, timedelta
from uuid import uuid4
from urllib.error import URLError

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from django.test.utils import override_settings
from django.utils.timezone import now

import simple_salesforce as sfapi
from celery.exceptions import Retry
from mock import ANY, Mock, call, patch
from requests.exceptions import ConnectionError as RequestsConnectionError

from basket.news.backends.ctms import CTMSNotFoundByAltIDError
from basket.news.backends.sfdc import SFDCDisabled
from basket.news.celery import app as celery_app
from basket.news.models import AcousticTxEmailMessage, FailedTask, CommonVoiceUpdate
from basket.news.tasks import (
    _add_fxa_activity,
    amo_sync_addon,
    amo_sync_user,
    et_task,
    fxa_delete,
    fxa_email_changed,
    fxa_login,
    fxa_verified,
    gmttime,
    PETITION_CONTACT_FIELDS,
    process_common_voice_batch,
    process_donation,
    process_donation_event,
    process_donation_receipt,
    process_petition_signature,
    process_newsletter_subscribe,
    record_common_voice_update,
    send_acoustic_tx_message,
    SUBSCRIBE,
    get_lock,
    RetryTask,
    update_custom_unsub,
    update_user_meta,
    get_fxa_user_data,
)
from basket.news.utils import iso_format_unix_timestamp


@override_settings(TASK_LOCKING_ENABLE=False, SFDC_ENABLED=True)
@patch("basket.news.tasks.upsert_user")
@patch("basket.news.tasks.get_user_data")
@patch("basket.news.tasks.sfdc")
@patch("basket.news.tasks.ctms")
class ProcessPetitionSignatureTests(TestCase):
    def _get_sig_data(self):
        return {
            "form": {
                "campaign_id": "abiding",
                "email": "dude@example.com",
                "first_name": "Jeffery",
                "last_name": "Lebowski",
                "country": "us",
                "postal_code": "90210",
                "source_url": "https://example.com/change",
                "email_subscription": False,
                "comments": "The Dude abides",
                "metadata": {
                    "location": "bowling alley",
                    "donnie": "out of his element",
                },
            },
        }

    def _get_contact_data(self, data):
        data = data["form"]
        contact_data = {"_set_subscriber": False, "mofo_relevant": True}
        contact_data.update({k: data[k] for k in PETITION_CONTACT_FIELDS if k in data})
        return contact_data

    def test_signature_with_comments_metadata(
        self, ctms_mock, sfdc_mock, gud_mock, uu_mock
    ):
        data = self._get_sig_data()
        contact_data = self._get_contact_data(data)
        user_data = {
            "id": "1234",
            "token": "the-token",
        }
        campaign_member = {
            "CampaignId": data["form"]["campaign_id"],
            "ContactId": user_data["id"],
            "Full_URL__c": data["form"]["source_url"],
            "Status": "Signed",
            "Petition_Comments__c": data["form"]["comments"],
            "Petition_Flex__c": json.dumps(data["form"]["metadata"]),
        }
        gud_mock.return_value = user_data
        process_petition_signature(data)
        sfdc_mock.update.assert_called_with(gud_mock(), contact_data)
        del contact_data["_set_subscriber"]
        ctms_mock.update.assert_called_once_with(gud_mock(), contact_data)
        sfdc_mock.add.assert_not_called()
        ctms_mock.add.assert_not_called()
        uu_mock.delay.assert_not_called()
        sfdc_mock.campaign_member.create.assert_called_with(campaign_member)

    def test_signature_with_long_comments_metadata(
        self, ctms_mock, sfdc_mock, gud_mock, uu_mock
    ):
        data = self._get_sig_data()
        data["form"]["comments"] = "DUDER!" * 100
        data["form"]["metadata"]["location"] = "bowling alley" * 100
        contact_data = self._get_contact_data(data)
        user_data = {
            "id": "1234",
            "token": "the-token",
        }
        campaign_member = {
            "CampaignId": data["form"]["campaign_id"],
            "ContactId": user_data["id"],
            "Full_URL__c": data["form"]["source_url"],
            "Status": "Signed",
            "Petition_Comments__c": data["form"]["comments"][:500],
            "Petition_Flex__c": json.dumps(data["form"]["metadata"])[:500],
        }
        assert data["form"]["comments"] != campaign_member["Petition_Comments__c"]
        gud_mock.return_value = user_data
        process_petition_signature(data)
        sfdc_mock.update.assert_called_with(gud_mock(), contact_data)
        del contact_data["_set_subscriber"]
        ctms_mock.update.assert_called_once_with(gud_mock(), contact_data)
        sfdc_mock.add.assert_not_called()
        ctms_mock.add.assert_not_called()
        uu_mock.delay.assert_not_called()
        sfdc_mock.campaign_member.create.assert_called_with(campaign_member)

    def test_signature_without_comments_metadata(
        self, ctms_mock, sfdc_mock, gud_mock, uu_mock
    ):
        data = self._get_sig_data()
        del data["form"]["comments"]
        del data["form"]["metadata"]
        contact_data = self._get_contact_data(data)
        user_data = {
            "id": "1234",
            "token": "the-token",
        }
        campaign_member = {
            "CampaignId": data["form"]["campaign_id"],
            "ContactId": user_data["id"],
            "Full_URL__c": data["form"]["source_url"],
            "Status": "Signed",
        }
        gud_mock.return_value = user_data
        process_petition_signature(data)
        sfdc_mock.update.assert_called_with(gud_mock(), contact_data)
        del contact_data["_set_subscriber"]
        ctms_mock.update.assert_called_once_with(gud_mock(), contact_data)
        sfdc_mock.add.assert_not_called()
        ctms_mock.add.assert_not_called()
        uu_mock.delay.assert_not_called()
        sfdc_mock.campaign_member.create.assert_called_with(campaign_member)

    def test_signature_with_subscription(self, ctms_mock, sfdc_mock, gud_mock, uu_mock):
        data = self._get_sig_data()
        data["form"]["email_subscription"] = True
        del data["form"]["comments"]
        del data["form"]["metadata"]
        contact_data = self._get_contact_data(data)
        user_data = {
            "id": "1234",
            "token": "the-token",
        }
        campaign_member = {
            "CampaignId": data["form"]["campaign_id"],
            "ContactId": user_data["id"],
            "Full_URL__c": data["form"]["source_url"],
            "Status": "Signed",
        }
        gud_mock.return_value = user_data
        process_petition_signature(data)
        sfdc_mock.update.assert_called_with(gud_mock(), contact_data)
        del contact_data["_set_subscriber"]
        ctms_mock.update.assert_called_once_with(gud_mock(), contact_data)
        sfdc_mock.add.assert_not_called()
        ctms_mock.add.assert_not_called()
        uu_mock.delay.assert_called_with(
            SUBSCRIBE,
            {
                "token": user_data["token"],
                "lang": "en-US",
                "newsletters": "mozilla-foundation",
                "source_url": data["form"]["source_url"],
            },
        )
        sfdc_mock.campaign_member.create.assert_called_with(campaign_member)

    @patch("basket.news.tasks.generate_token")
    def test_signature_with_new_user(
        self, gt_mock, ctms_mock, sfdc_mock, gud_mock, uu_mock
    ):
        data = self._get_sig_data()
        del data["form"]["comments"]
        del data["form"]["metadata"]
        contact_data = self._get_contact_data(data)
        contact_data["token"] = gt_mock()
        contact_data["email"] = data["form"]["email"]
        contact_data["record_type"] = settings.DONATE_CONTACT_RECORD_TYPE
        user_data = {
            "id": "1234",
            "token": "the-token",
        }
        campaign_member = {
            "CampaignId": data["form"]["campaign_id"],
            "ContactId": user_data["id"],
            "Full_URL__c": data["form"]["source_url"],
            "Status": "Signed",
        }
        gud_mock.side_effect = [None, user_data]
        email_id = str(uuid4())
        ctms_mock.add.return_value = {"email": {"email_id": email_id}}
        process_petition_signature(data)
        sfdc_mock.update.assert_not_called()
        ctms_mock.update.assert_not_called()
        ctms_data = contact_data.copy()
        del ctms_data["_set_subscriber"]
        del ctms_data["record_type"]
        ctms_mock.add.assert_called_once_with(ctms_data)
        contact_data["email_id"] = email_id
        sfdc_mock.add.assert_called_with(contact_data)
        uu_mock.delay.assert_not_called()
        sfdc_mock.campaign_member.create.assert_called_with(campaign_member)

    @patch("basket.news.tasks.generate_token")
    def test_signature_with_new_user_retry(
        self, gt_mock, ctms_mock, sfdc_mock, gud_mock, uu_mock
    ):
        data = self._get_sig_data()
        del data["form"]["comments"]
        del data["form"]["metadata"]
        contact_data = self._get_contact_data(data)
        contact_data["token"] = gt_mock()
        contact_data["email"] = data["form"]["email"]
        contact_data["record_type"] = settings.DONATE_CONTACT_RECORD_TYPE
        gud_mock.return_value = None
        email_id = str(uuid4())
        ctms_mock.add.return_value = {"email": {"email_id": email_id}}
        with self.assertRaises(Retry):
            process_petition_signature(data)

        sfdc_mock.update.assert_not_called()
        ctms_mock.update.assert_not_called()
        ctms_data = contact_data.copy()
        del ctms_data["_set_subscriber"]
        del ctms_data["record_type"]
        ctms_mock.add.assert_called_once_with(ctms_data)
        contact_data["email_id"] = email_id
        sfdc_mock.add.assert_called_with(contact_data)
        uu_mock.delay.assert_not_called()
        sfdc_mock.campaign_member.create.assert_not_called()

    @override_settings(SFDC_ENABLED=False)
    def test_signature_metadata_sfdc_disabled(
        self, ctms_mock, sfdc_mock, gud_mock, uu_mock
    ):
        data = self._get_sig_data()
        contact_data = self._get_contact_data(data)
        user_data = {
            "id": "1234",
            "token": "the-token",
        }
        gud_mock.return_value = user_data
        process_petition_signature(data)
        sfdc_mock.update.assert_called_with(gud_mock(), contact_data)
        del contact_data["_set_subscriber"]
        ctms_mock.update.assert_called_once_with(gud_mock(), contact_data)
        sfdc_mock.add.assert_not_called()
        ctms_mock.add.assert_not_called()
        uu_mock.delay.assert_not_called()
        sfdc_mock.campaign_member.create.assert_not_called()

    @override_settings(SFDC_ENABLED=False)
    def test_signature_without_comments_metadata_sfdc_disabled(
        self, ctms_mock, sfdc_mock, gud_mock, uu_mock
    ):
        data = self._get_sig_data()
        del data["form"]["comments"]
        del data["form"]["metadata"]
        contact_data = self._get_contact_data(data)
        user_data = {
            "id": "1234",
            "token": "the-token",
        }
        gud_mock.return_value = user_data
        process_petition_signature(data)
        sfdc_mock.update.assert_called_with(gud_mock(), contact_data)
        del contact_data["_set_subscriber"]
        ctms_mock.update.assert_called_once_with(gud_mock(), contact_data)
        sfdc_mock.add.assert_not_called()
        ctms_mock.add.assert_not_called()
        uu_mock.delay.assert_not_called()
        sfdc_mock.campaign_member.create.assert_not_called()

    @override_settings(SFDC_ENABLED=False)
    def test_signature_with_subscription_sfdc_disabled(
        self, ctms_mock, sfdc_mock, gud_mock, uu_mock
    ):
        data = self._get_sig_data()
        data["form"]["email_subscription"] = True
        del data["form"]["comments"]
        del data["form"]["metadata"]
        contact_data = self._get_contact_data(data)
        user_data = {
            "id": "1234",
            "token": "the-token",
        }
        gud_mock.return_value = user_data
        process_petition_signature(data)
        sfdc_mock.update.assert_called_with(gud_mock(), contact_data)
        del contact_data["_set_subscriber"]
        ctms_mock.update.assert_called_once_with(gud_mock(), contact_data)
        sfdc_mock.add.assert_not_called()
        ctms_mock.add.assert_not_called()
        uu_mock.delay.assert_called_with(
            SUBSCRIBE,
            {
                "token": user_data["token"],
                "lang": "en-US",
                "newsletters": "mozilla-foundation",
                "source_url": data["form"]["source_url"],
            },
        )
        sfdc_mock.campaign_member.create.assert_not_called()

    @override_settings(SFDC_ENABLED=False)
    @patch("basket.news.tasks.generate_token")
    def test_signature_with_new_user_sfdc_disabled(
        self, gt_mock, ctms_mock, sfdc_mock, gud_mock, uu_mock
    ):
        data = self._get_sig_data()
        del data["form"]["comments"]
        del data["form"]["metadata"]
        contact_data = self._get_contact_data(data)
        contact_data["token"] = gt_mock()
        contact_data["email"] = data["form"]["email"]
        contact_data["record_type"] = settings.DONATE_CONTACT_RECORD_TYPE
        user_data = {
            "id": "1234",
            "token": "the-token",
        }
        gud_mock.side_effect = [None, user_data]
        email_id = str(uuid4())
        ctms_mock.add.return_value = {"email": {"email_id": email_id}}
        process_petition_signature(data)
        sfdc_mock.update.assert_not_called()
        ctms_mock.update.assert_not_called()
        ctms_data = contact_data.copy()
        del ctms_data["_set_subscriber"]
        del ctms_data["record_type"]
        ctms_mock.add.assert_called_once_with(ctms_data)
        contact_data["email_id"] = email_id
        sfdc_mock.add.assert_called_with(contact_data)
        uu_mock.delay.assert_not_called()
        sfdc_mock.campaign_member.create.assert_not_called()

    @override_settings(SFDC_ENABLED=False)
    @patch("basket.news.tasks.generate_token")
    def test_signature_with_new_user_retry_sfdc_disabled(
        self, gt_mock, ctms_mock, sfdc_mock, gud_mock, uu_mock
    ):
        data = self._get_sig_data()
        del data["form"]["comments"]
        del data["form"]["metadata"]
        contact_data = self._get_contact_data(data)
        contact_data["token"] = gt_mock()
        contact_data["email"] = data["form"]["email"]
        contact_data["record_type"] = settings.DONATE_CONTACT_RECORD_TYPE
        gud_mock.return_value = None
        email_id = str(uuid4())
        ctms_mock.add.return_value = {"email": {"email_id": email_id}}
        with self.assertRaises(Retry):
            process_petition_signature(data)

        sfdc_mock.update.assert_not_called()
        ctms_mock.update.assert_not_called()
        ctms_data = contact_data.copy()
        del ctms_data["_set_subscriber"]
        del ctms_data["record_type"]
        ctms_mock.add.assert_called_once_with(ctms_data)
        contact_data["email_id"] = email_id
        sfdc_mock.add.assert_called_with(contact_data)
        uu_mock.delay.assert_not_called()
        sfdc_mock.campaign_member.create.assert_not_called()


@override_settings(TASK_LOCKING_ENABLE=False)
@patch("basket.news.tasks.sfdc")
class ProcessDonationEventTests(TestCase):
    def test_charge_failed(self, sfdc_mock):
        process_donation_event(
            {
                "event_type": "charge.failed",
                "transaction_id": "el-dudarino",
                "failure_code": "expired_card",
            },
        )
        sfdc_mock.opportunity.update.assert_called_with(
            "PMT_Transaction_ID__c/el-dudarino",
            {
                "PMT_Type_Lost__c": "charge.failed",
                "PMT_Reason_Lost__c": "expired_card",
                "StageName": "Closed Lost",
            },
        )

    def test_charge_refunded_ignored(self, sfdc_mock):
        process_donation_event(
            {
                "event_type": "charge.refunded",
                "transaction_id": "el-dudarino",
                "reason": "requested_by_customer",
                "status": "pending",
            },
        )
        sfdc_mock.opportunity.update.assert_not_called()

    def test_charge_refunded(self, sfdc_mock):
        process_donation_event(
            {
                "event_type": "charge.refunded",
                "transaction_id": "el-dudarino",
                "reason": "requested_by_customer",
                "status": "succeeded",
            },
        )
        sfdc_mock.opportunity.update.assert_called_with(
            "PMT_Transaction_ID__c/el-dudarino",
            {
                "PMT_Type_Lost__c": "charge.refunded",
                "PMT_Reason_Lost__c": "requested_by_customer",
                "StageName": "Closed Lost",
            },
        )

    def test_charge_disputed_ignored(self, sfdc_mock):
        process_donation_event(
            {
                "event_type": "charge.dispute.closed",
                "transaction_id": "el-dudarino",
                "reason": "fraudulent",
                "status": "under_review",
            },
        )
        sfdc_mock.opportunity.update.assert_not_called()

    def test_charge_disputed(self, sfdc_mock):
        process_donation_event(
            {
                "event_type": "charge.dispute.closed",
                "transaction_id": "el-dudarino",
                "reason": "fraudulent",
                "status": "lost",
            },
        )
        sfdc_mock.opportunity.update.assert_called_with(
            "PMT_Transaction_ID__c/el-dudarino",
            {
                "PMT_Type_Lost__c": "charge.dispute.closed",
                "PMT_Reason_Lost__c": "fraudulent",
                "StageName": "Closed Lost",
            },
        )


@override_settings(DONATE_RECEIPTS_BCC=["dude@example.com"])
@patch("basket.news.tasks.acoustic_tx")
class ProcessDonationReceiptTests(TestCase):
    _data = {
        "created": 1479746809.327,
        "locale": "pt-BR",
        "currency": "USD",
        "donation_amount": "75",
        "transaction_fee": 0.42,
        "net_amount": 75.42,
        "conversion_amount": 42.75,
        "last_4": "5309",
        "email": "dude@example.com",
        "first_name": "Jeffery",
        "last_name": "Lebowski",
        "project": "mozillafoundation",
        "source_url": "https://example.com/donate",
        "recurring": True,
        "service": "paypal",
        "transaction_id": "NLEKFRBED3BQ614797468093.25",
        "campaign_id": "were-you-listening-to-the-dudes-story",
    }

    @property
    def donate_data(self):
        return self._data.copy()

    def setUp(self):
        AcousticTxEmailMessage.objects.create(
            message_id="donation-receipt", vendor_id="the-dude", language="en-US",
        )

    def test_receipt(self, acoustic_mock):
        data = self.donate_data
        process_donation_receipt(data)
        acoustic_mock.send_mail.assert_called_with(
            "dude@example.com",
            "the-dude",
            {
                "donation_locale": "pt-BR",
                "currency": "USD",
                "donation_amount": "75.00",
                "cc_last_4_digits": "5309",
                "first_name": "Jeffery",
                "last_name": "Lebowski",
                "project": "mozillafoundation",
                "payment_source": "paypal",
                "transaction_id": "NLEKFRBED3BQ614797468093.25",
                "created": "2016-11-21 08:46",
                "day_of_month": "21",
                "payment_frequency": "Recurring",
                "friendly_from_name": "Mozilla",
            },
            bcc=["dude@example.com"],
            save_to_db=True,
        )

    def test_receipt_one_time(self, acoustic_mock):
        data = self.donate_data
        data["recurring"] = False
        process_donation_receipt(data)
        acoustic_mock.send_mail.assert_called_with(
            "dude@example.com",
            "the-dude",
            {
                "donation_locale": "pt-BR",
                "currency": "USD",
                "donation_amount": "75.00",
                "cc_last_4_digits": "5309",
                "first_name": "Jeffery",
                "last_name": "Lebowski",
                "project": "mozillafoundation",
                "payment_source": "paypal",
                "transaction_id": "NLEKFRBED3BQ614797468093.25",
                "created": "2016-11-21 08:46",
                "day_of_month": "21",
                "payment_frequency": "One-Time",
                "friendly_from_name": "Mozilla",
            },
            bcc=["dude@example.com"],
            save_to_db=True,
        )

    def test_receipt_thunderbird(self, acoustic_mock):
        data = self.donate_data
        data["project"] = "thunderbird"
        process_donation_receipt(data)
        acoustic_mock.send_mail.assert_called_with(
            "dude@example.com",
            "the-dude",
            {
                "donation_locale": "pt-BR",
                "currency": "USD",
                "donation_amount": "75.00",
                "cc_last_4_digits": "5309",
                "first_name": "Jeffery",
                "last_name": "Lebowski",
                "project": "thunderbird",
                "payment_source": "paypal",
                "transaction_id": "NLEKFRBED3BQ614797468093.25",
                "created": "2016-11-21 08:46",
                "day_of_month": "21",
                "payment_frequency": "Recurring",
                "friendly_from_name": "MZLA Thunderbird",
            },
            bcc=["dude@example.com"],
            save_to_db=True,
        )


@override_settings(TASK_LOCKING_ENABLE=False, SFDC_ENABLED=True)
@patch("basket.news.tasks.get_user_data")
@patch("basket.news.tasks.sfdc")
@patch("basket.news.tasks.ctms")
class ProcessDonationTests(TestCase):
    donate_data = {
        "created": 1479746809.327,
        "locale": "pt-BR",
        "currency": "USD",
        "donation_amount": "75.00",
        "transaction_fee": 0.42,
        "net_amount": 75.42,
        "conversion_amount": 42.75,
        "last_4": "5309",
        "email": "dude@example.com",
        "first_name": "Jeffery",
        "last_name": "Lebowski",
        "project": "mozillafoundation",
        "source_url": "https://example.com/donate",
        "recurring": True,
        "service": "paypal",
        "transaction_id": "NLEKFRBED3BQ614797468093.25",
        "campaign_id": "were-you-listening-to-the-dudes-story",
    }

    def test_one_name(self, ctms_mock, sfdc_mock, gud_mock):
        data = self.donate_data.copy()
        gud_mock.return_value = {
            "id": "1234",
            "first_name": "",
            "last_name": "_",
        }
        del data["first_name"]
        data["last_name"] = "Donnie"
        process_donation(data)
        sfdc_mock.update.assert_called_with(
            gud_mock(),
            {"_set_subscriber": False, "mofo_relevant": True, "last_name": "Donnie"},
        )
        ctms_mock.update.assert_called_with(
            gud_mock(), {"last_name": "Donnie", "mofo_relevant": True}
        )

    def test_name_splitting(self, ctms_mock, sfdc_mock, gud_mock):
        data = self.donate_data.copy()
        gud_mock.return_value = None
        email_id = str(uuid4())
        ctms_mock.add.return_value = {"email": {"email_id": email_id}}
        del data["first_name"]
        data["last_name"] = "Theodore Donald Kerabatsos"
        process_donation(data)
        ctms_mock.add.assert_called_with(
            {
                "token": ANY,
                "email": "dude@example.com",
                "first_name": "Theodore Donald",
                "last_name": "Kerabatsos",
                "mofo_relevant": True,
            }
        )
        sfdc_mock.add.assert_called_with(
            {
                "_set_subscriber": False,
                "token": ANY,
                "record_type": ANY,
                "email": "dude@example.com",
                "first_name": "Theodore Donald",
                "last_name": "Kerabatsos",
                "email_id": email_id,
                "mofo_relevant": True,
            }
        )

    def test_name_empty(self, ctms_mock, sfdc_mock, gud_mock):
        """Should be okay if only last_name is provided and is just spaces.

        https://github.com/mozmeao/basket/issues/45
        """
        data = self.donate_data.copy()
        gud_mock.return_value = None
        email_id = str(uuid4())
        ctms_mock.add.return_value = {"email": {"email_id": email_id}}
        del data["first_name"]
        data["last_name"] = "  "
        process_donation(data)
        ctms_mock.add.assert_called_with(
            {"token": ANY, "email": "dude@example.com", "mofo_relevant": True}
        )
        sfdc_mock.add.assert_called_with(
            {
                "_set_subscriber": False,
                "token": ANY,
                "email": "dude@example.com",
                "record_type": ANY,
                "email_id": email_id,
                "mofo_relevant": True,
            }
        )

    def test_name_none(self, ctms_mock, sfdc_mock, gud_mock):
        """Should be okay if only last_name is provided and is None.

        https://sentry.prod.mozaws.net/operations/basket-prod/issues/683973/
        """
        data = self.donate_data.copy()
        gud_mock.return_value = None
        email_id = str(uuid4())
        ctms_mock.add.return_value = {"email": {"email_id": email_id}}
        del data["first_name"]
        data["last_name"] = None
        process_donation(data)
        ctms_mock.add.assert_called_with(
            {"token": ANY, "email": "dude@example.com", "mofo_relevant": True}
        )
        sfdc_mock.add.assert_called_with(
            {
                "_set_subscriber": False,
                "token": ANY,
                "email": "dude@example.com",
                "record_type": ANY,
                "email_id": email_id,
                "mofo_relevant": True,
            }
        )

    def test_ctms_add_fails(self, ctms_mock, sfdc_mock, gud_mock):
        """If ctms.add fails, sfdc.add is still called without an email_id."""
        data = self.donate_data.copy()
        gud_mock.return_value = None
        ctms_mock.add.return_value = None
        process_donation(data)
        ctms_mock.add.assert_called_with(
            {
                "token": ANY,
                "email": "dude@example.com",
                "first_name": "Jeffery",
                "last_name": "Lebowski",
                "mofo_relevant": True,
            }
        )
        sfdc_mock.add.assert_called_with(
            {
                "_set_subscriber": False,
                "token": ANY,
                "email": "dude@example.com",
                "first_name": "Jeffery",
                "last_name": "Lebowski",
                "record_type": ANY,
                "mofo_relevant": True,
            }
        )

    def test_only_update_contact_if_modified(self, ctms_mock, sfdc_mock, gud_mock):
        data = self.donate_data.copy()
        gud_mock.return_value = {
            "id": "1234",
            "first_name": "",
            "last_name": "_",
        }
        process_donation(data)
        sfdc_mock.update.assert_called_with(
            gud_mock(),
            {
                "_set_subscriber": False,
                "first_name": "Jeffery",
                "last_name": "Lebowski",
                "mofo_relevant": True,
            },
        )
        ctms_mock.update.assert_called_with(
            gud_mock(),
            {"first_name": "Jeffery", "last_name": "Lebowski", "mofo_relevant": True},
        )

        sfdc_mock.reset_mock()
        ctms_mock.reset_mock()
        data = self.donate_data.copy()
        gud_mock.return_value = {
            "id": "1234",
            "first_name": "Jeffery",
            "last_name": "Lebowski",
        }
        process_donation(data)
        sfdc_mock.update.assert_not_called()
        ctms_mock.update.assert_not_called()

    def test_donation_data(self, ctms_mock, sfdc_mock, gud_mock):
        data = self.donate_data.copy()
        gud_mock.return_value = {
            "id": "1234",
            "first_name": "Jeffery",
            "last_name": "Lebowski",
        }
        process_donation(data)
        sfdc_mock.opportunity.create.assert_called_with(
            {
                "RecordTypeId": ANY,
                "Name": "Foundation Donation",
                "Donation_Contact__c": "1234",
                "StageName": "Closed Won",
                # calculated from data['created']
                "CloseDate": "2016-11-21T16:46:49.327000",
                "Amount": float(data["donation_amount"]),
                "Currency__c": "USD",
                "Payment_Source__c": "paypal",
                "PMT_Transaction_ID__c": data["transaction_id"],
                "Payment_Type__c": "Recurring",
                "SourceURL__c": data["source_url"],
                "Project__c": data["project"],
                "Donation_Locale__c": data["locale"],
                "Processors_Fee__c": data["transaction_fee"],
                "Net_Amount__c": data["net_amount"],
                "Conversion_Amount__c": data["conversion_amount"],
                "Last_4_Digits__c": data["last_4"],
                "CampaignId": data["campaign_id"],
            },
        )

    def test_donation_data_optional_null(self, ctms_mock, sfdc_mock, gud_mock):
        """Having a `None` in an optional field used to throw a TypeError.

        https://github.com/mozmeao/basket/issues/366
        """
        data = self.donate_data.copy()
        data["subscription_id"] = None
        gud_mock.return_value = {
            "id": "1234",
            "first_name": "Jeffery",
            "last_name": "Lebowski",
        }
        process_donation(data)
        sfdc_mock.opportunity.create.assert_called_with(
            {
                "RecordTypeId": ANY,
                "Name": "Foundation Donation",
                "Donation_Contact__c": "1234",
                "StageName": "Closed Won",
                # calculated from data['created']
                "CloseDate": "2016-11-21T16:46:49.327000",
                "Amount": float(data["donation_amount"]),
                "Currency__c": "USD",
                "Payment_Source__c": "paypal",
                "PMT_Transaction_ID__c": data["transaction_id"],
                "Payment_Type__c": "Recurring",
                "SourceURL__c": data["source_url"],
                "Project__c": data["project"],
                "Donation_Locale__c": data["locale"],
                "Processors_Fee__c": data["transaction_fee"],
                "Net_Amount__c": data["net_amount"],
                "Conversion_Amount__c": data["conversion_amount"],
                "Last_4_Digits__c": data["last_4"],
                "CampaignId": data["campaign_id"],
            },
        )

    def test_donation_silent_failure_on_dupe(self, ctms_mock, sfdc_mock, gud_mock):
        data = self.donate_data.copy()
        gud_mock.return_value = {
            "id": "1234",
            "first_name": "Jeffery",
            "last_name": "Lebowski",
        }
        error_content = [
            {
                "errorCode": "DUPLICATE_VALUE",
                "fields": [],
                "message": "duplicate value found: PMT_Transaction_ID__c "
                "duplicates value on record with id: blah-blah",
            },
        ]
        exc = sfapi.SalesforceMalformedRequest("url", 400, "opportunity", error_content)
        sfdc_mock.opportunity.create.side_effect = exc
        process_donation(data)

    def test_donation_normal_failure_not_dupe(self, ctms_mock, sfdc_mock, gud_mock):
        data = self.donate_data.copy()
        gud_mock.return_value = {
            "id": "1234",
            "first_name": "Jeffery",
            "last_name": "Lebowski",
        }
        error_content = [
            {
                "errorCode": "OTHER_ERROR",
                "fields": [],
                "message": "Some other non-dupe problem",
            },
        ]
        exc = sfapi.SalesforceMalformedRequest("url", 400, "opportunity", error_content)
        sfdc_mock.opportunity.create.side_effect = exc
        with self.assertRaises(Retry):
            process_donation(data)

    @override_settings(SFDC_ENABLED=False)
    def test_donation_data_new_user(self, ctms_mock, sfdc_mock, gud_mock):
        """Donation data is skipped for new user."""
        data = self.donate_data.copy()
        gud_mock.return_value = None
        email_id = str(uuid4())
        ctms_mock.add.return_value = {"email": {"email_id": email_id}}
        del data["first_name"]
        data["last_name"] = "  "
        process_donation(data)
        ctms_mock.add.assert_called_with(
            {"token": ANY, "email": "dude@example.com", "mofo_relevant": True}
        )
        assert not sfdc_mock.add.called
        assert not sfdc_mock.opportunity.create.called

    @override_settings(SFDC_ENABLED=False)
    def test_donation_data_existing_user(self, ctms_mock, sfdc_mock, gud_mock):
        """Donation data is skipped for existing, unchanged user."""
        data = self.donate_data.copy()
        gud_mock.return_value = {
            "id": "1234",
            "first_name": "Jeffery",
            "last_name": "Lebowski",
        }
        process_donation(data)
        assert not ctms_mock.update.called
        assert not sfdc_mock.update.called
        assert not sfdc_mock.opportunity.create.called


@patch("basket.news.tasks.upsert_user")
@patch("basket.news.tasks.get_best_supported_lang")
class ProcessNewsletterSubscribeTests(TestCase):
    def test_process(self, mock_gbsl, mock_upsert):
        """
        process_newsletter_subscribe calls upsert_user

        Note: The input data is a guess and may not reflect real queue items
        """
        data = {
            "form": {
                "email": "test@example.com",
                "newsletters": ["mozilla-foundation"],
                "lang": "fr",
            },
            "other": "stuff",
        }
        mock_gbsl.return_value = "fr"
        process_newsletter_subscribe(data)
        mock_gbsl.assert_called_once_with("fr")
        mock_upsert.assert_called_once_with(
            SUBSCRIBE,
            {
                "email": "test@example.com",
                "newsletters": ["mozilla-foundation"],
                "lang": "fr",
            },
        )


@override_settings(TASK_LOCKING_ENABLE=True)
class TaskDuplicationLockingTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_locks_work(self):
        """Calling get_lock more than once quickly with the same key should be locked"""
        get_lock("dude@example.com")
        with self.assertRaises(RetryTask):
            get_lock("dude@example.com")

    def test_lock_prefix_works(self):
        """Should allow same key to not lock other prefixes"""
        get_lock("dude@example.com", prefix="malibu")
        get_lock("dude@example.com", prefix="in-n-out")
        with self.assertRaises(RetryTask):
            get_lock("dude@example.com", prefix="malibu")

    @patch("basket.news.tasks.cache")
    def test_locks_do_not_leak_info(self, cache_mock):
        """Should not use plaintext key in lock name"""
        email = "donny@example.com"
        cache_mock.add.return_value = True
        get_lock(email)
        key = cache_mock.add.call_args[0][0]
        self.assertNotIn(email, key)


class FailedTaskTest(TestCase):
    """Test that failed tasks are logged in our FailedTask table"""

    @patch("basket.news.tasks.acoustic_tx")
    def test_failed_task_logging(self, mock_acoustic):
        """Failed task is logged in FailedTask table"""
        mock_acoustic.send_mail.side_effect = Exception("Test exception")
        self.assertEqual(0, FailedTask.objects.count())
        args = ["you@example.com", "SFDCID"]
        kwargs = {"fields": {"token": 3}}
        result = send_acoustic_tx_message.apply(args=args, kwargs=kwargs)
        fail = FailedTask.objects.get()
        self.assertEqual("news.tasks.send_acoustic_tx_message", fail.name)
        self.assertEqual(result.task_id, fail.task_id)
        self.assertEqual(args, fail.args)
        self.assertEqual(kwargs, fail.kwargs)
        self.assertEqual("Exception('Test exception')", fail.exc)
        self.assertIn("Exception: Test exception", fail.einfo)


class RetryTaskTest(TestCase):
    """Test that we can retry a task"""

    @patch("django.contrib.messages.info", autospec=True)
    def test_retry_task(self, info):
        TASK_NAME = "news.tasks.update_phonebook"
        failed_task = FailedTask(
            name=TASK_NAME,
            task_id=4,
            args=[1, 2],
            kwargs={"token": 3},
            exc="",
            einfo="",
        )
        # Failed task is deleted after queuing, but that only works on records
        # that have been saved, so just mock that and check later that it was
        # called.
        failed_task.delete = Mock(spec=failed_task.delete)
        with patch.object(celery_app, "send_task") as send_task_mock:
            # Let's retry.
            failed_task.retry()
        # Task was submitted again
        send_task_mock.assert_called_with(TASK_NAME, args=[1, 2], kwargs={"token": 3})
        # Previous failed task was deleted
        self.assertTrue(failed_task.delete.called)


class ETTaskTests(TestCase):
    def _test_retry_increase(self, mock_backoff, error):
        """
        The delay for retrying a task should increase geometrically by a
        power of 2. I really hope I said that correctly.
        """

        @et_task
        def myfunc():
            raise error

        myfunc.push_request(retries=4)
        myfunc.retry = Mock(side_effect=Exception)
        # have to use run() to make sure our request above is used
        with self.assertRaises(Exception):
            myfunc.run()

        mock_backoff.assert_called_with(4)
        myfunc.retry.assert_called_with(countdown=mock_backoff())

    @patch("basket.news.tasks.exponential_backoff")
    def test_urlerror(self, mock_backoff):
        self._test_retry_increase(mock_backoff, URLError(reason=Exception("foo bar!")))

    @patch("basket.news.tasks.exponential_backoff")
    def test_requests_connection_error(self, mock_backoff):
        self._test_retry_increase(
            mock_backoff, RequestsConnectionError("Connection aborted.")
        )


class AddFxaActivityTests(TestCase):
    def _base_test(self, user_agent=False, fxa_id="123", first_device=True):
        if not user_agent:
            user_agent = (
                "Mozilla/5.0 (Windows NT 6.1; rv:10.0) Gecko/20100101 Firefox/10.0"
            )

        data = {
            "fxa_id": fxa_id,
            "first_device": first_device,
            "user_agent": user_agent,
            "service": "sync",
            "ts": 1614301517.225,
        }

        with patch("basket.news.tasks.fxa_activity_acoustic") as apply_updates_mock:
            _add_fxa_activity(data)
        record = apply_updates_mock.delay.call_args[0][0]
        return record

    def test_login_date(self):
        with patch("basket.news.tasks.date") as date_mock:
            date_mock.fromtimestamp().isoformat.return_value = "this is time"
            record = self._base_test()
        self.assertEqual(record["LOGIN_DATE"], "this is time")

    def test_first_device(self):
        record = self._base_test(first_device=True)
        self.assertEqual(record["FIRST_DEVICE"], "y")

        record = self._base_test(first_device=False)
        self.assertEqual(record["FIRST_DEVICE"], "n")

    def test_fxa_id(self):
        record = self._base_test(fxa_id="This is id")
        self.assertEqual(record["FXA_ID"], "This is id")

    def test_windows(self):
        ua = "Mozilla/5.0 (Windows NT 6.1; rv:10.0) Gecko/20100101 Firefox/10.0"
        record = self._base_test(ua)
        self.assertEqual(record["OS_NAME"], "Windows")
        self.assertEqual(record["OS_VERSION"], "7")  # Not sure if we expect '7' here.
        self.assertEqual(record["BROWSER"], "Firefox 10.0")
        self.assertEqual(record["DEVICE_NAME"], "Other")
        self.assertEqual(record["DEVICE_TYPE"], "D")

    def test_mac(self):
        ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.6; rv:10.0) Gecko/20100101 Firefox/30.2"
        record = self._base_test(ua)
        self.assertEqual(record["OS_NAME"], "Mac OS X")
        self.assertEqual(record["OS_VERSION"], "10.6")
        self.assertEqual(record["BROWSER"], "Firefox 30.2")
        self.assertEqual(record["DEVICE_NAME"], "Mac")
        self.assertEqual(record["DEVICE_TYPE"], "D")

    def test_linux(self):
        ua = "Mozilla/5.0 (X11; Linux i686 on x86_64; rv:10.0) Gecko/20100101 Firefox/42.0"
        record = self._base_test(ua)
        self.assertEqual(record["OS_NAME"], "Linux")
        self.assertEqual(record["OS_VERSION"], "")
        self.assertEqual(record["BROWSER"], "Firefox 42.0")
        self.assertEqual(record["DEVICE_NAME"], "Other")
        self.assertEqual(record["DEVICE_TYPE"], "D")

    def test_android_phone_below_version_41(self):
        ua = "Mozilla/5.0 (Android; Mobile; rv:40.0) Gecko/40.0 Firefox/40.0"
        record = self._base_test(ua)
        self.assertEqual(record["OS_NAME"], "Android")
        self.assertEqual(record["OS_VERSION"], "")
        self.assertEqual(record["BROWSER"], "Firefox Mobile 40.0")
        self.assertEqual(record["DEVICE_NAME"], "Generic Smartphone")
        self.assertEqual(record["DEVICE_TYPE"], "M")

    def test_android_tablet_below_version_41(self):
        ua = "Mozilla/5.0 (Android; Tablet; rv:40.0) Gecko/40.0 Firefox/40.0"
        record = self._base_test(ua)
        self.assertEqual(record["OS_NAME"], "Android")
        self.assertEqual(record["OS_VERSION"], "")
        self.assertEqual(record["BROWSER"], "Firefox Mobile 40.0")
        self.assertEqual(record["DEVICE_NAME"], "Generic Tablet")

    def test_android_phone_from_version_41(self):
        ua = "Mozilla/5.0 (Android 4.4; Mobile; rv:41.0) Gecko/41.0 Firefox/41.0"
        record = self._base_test(ua)
        self.assertEqual(record["OS_NAME"], "Android")
        self.assertEqual(record["OS_VERSION"], "4.4")
        self.assertEqual(record["BROWSER"], "Firefox Mobile 41.0")
        self.assertEqual(record["DEVICE_NAME"], "Generic Smartphone")
        self.assertEqual(record["DEVICE_TYPE"], "M")

    def test_android_tablet_from_version_41(self):
        ua = "Mozilla/5.0 (Android 5.0; Tablet; rv:41.0) Gecko/41.0 Firefox/41.0"
        record = self._base_test(ua)
        self.assertEqual(record["OS_NAME"], "Android")
        self.assertEqual(record["OS_VERSION"], "5.0")
        self.assertEqual(record["BROWSER"], "Firefox Mobile 41.0")
        self.assertEqual(record["DEVICE_NAME"], "Generic Tablet")

    def test_firefox_ios_iphone(self):
        ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 8_3 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) FxiOS/1.0 Mobile/12F69 Safari/600.1.4"
        record = self._base_test(ua)
        self.assertEqual(record["OS_NAME"], "iOS")
        self.assertEqual(record["OS_VERSION"], "8.3")
        self.assertEqual(record["BROWSER"], "Firefox iOS 1.0")
        self.assertEqual(record["DEVICE_NAME"], "iPhone")
        self.assertEqual(record["DEVICE_TYPE"], "M")

    def test_firefox_ios_tablet(self):
        ua = "Mozilla/5.0 (iPad; CPU iPhone OS 8_3 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) FxiOS/1.0 Mobile/12F69 Safari/600.1.4"
        record = self._base_test(ua)
        self.assertEqual(record["OS_NAME"], "iOS")
        self.assertEqual(record["OS_VERSION"], "8.3")
        self.assertEqual(record["BROWSER"], "Firefox iOS 1.0")
        self.assertEqual(record["DEVICE_NAME"], "iPad")
        self.assertEqual(record["DEVICE_TYPE"], "T")


@override_settings(
    FXA_EVENTS_VERIFIED_SFDC_ENABLE=True,
    FXA_REGISTER_NEWSLETTER="firefox-accounts-journey",
)
@patch("basket.news.tasks.get_best_language", Mock(return_value="en-US"))
@patch("basket.news.tasks.newsletter_languages", Mock(return_value=["en-US"]))
@patch("basket.news.tasks.upsert_contact")
@patch("basket.news.tasks.get_fxa_user_data")
class FxAVerifiedTests(TestCase):
    def test_success(self, fxa_data_mock, upsert_mock):
        fxa_data_mock.return_value = {"lang": "en-US"}
        data = {
            "email": "thedude@example.com",
            "uid": "the-fxa-id",
            "locale": "en-US,en",
            "service": "sync",
        }
        fxa_verified(data)
        upsert_mock.assert_called_with(
            SUBSCRIBE,
            {
                "email": data["email"],
                "newsletters": [settings.FXA_REGISTER_NEWSLETTER],
                "source_url": settings.FXA_REGISTER_SOURCE_URL,
                "country": "",
                "fxa_lang": data["locale"],
                "fxa_service": "sync",
                "fxa_id": "the-fxa-id",
                "optin": True,
                "format": "H",
            },
            fxa_data_mock(),
        )

    def test_with_newsletters(self, fxa_data_mock, upsert_mock):
        fxa_data_mock.return_value = None
        data = {
            "email": "thedude@example.com",
            "uid": "the-fxa-id",
            "locale": "en-US,en",
            "newsletters": ["test-pilot", "take-action-for-the-internet"],
            "service": "sync",
        }
        fxa_verified(data)
        upsert_mock.assert_called_with(
            SUBSCRIBE,
            {
                "email": data["email"],
                "newsletters": [
                    "test-pilot",
                    "take-action-for-the-internet",
                    settings.FXA_REGISTER_NEWSLETTER,
                ],
                "source_url": settings.FXA_REGISTER_SOURCE_URL,
                "country": "",
                "lang": "en-US",
                "fxa_lang": data["locale"],
                "fxa_service": "sync",
                "fxa_id": "the-fxa-id",
                "optin": True,
                "format": "H",
            },
            None,
        )

    def test_with_subscribe_and_metrics(self, fxa_data_mock, upsert_mock):
        fxa_data_mock.return_value = None
        data = {
            "email": "thedude@example.com",
            "uid": "the-fxa-id",
            "locale": "en-US,en",
            "metricsContext": {"utm_campaign": "bowling", "some_other_thing": "Donnie"},
            "service": "monitor",
            "countryCode": "DE",
        }
        fxa_verified(data)
        upsert_mock.assert_called_with(
            SUBSCRIBE,
            {
                "email": data["email"],
                "newsletters": [settings.FXA_REGISTER_NEWSLETTER],
                "source_url": settings.FXA_REGISTER_SOURCE_URL
                + "?utm_campaign=bowling",
                "country": "DE",
                "lang": "en-US",
                "fxa_lang": data["locale"],
                "fxa_service": "monitor",
                "fxa_id": "the-fxa-id",
                "optin": True,
                "format": "H",
            },
            None,
        )

    def test_with_createDate(self, fxa_data_mock, upsert_mock):
        fxa_data_mock.return_value = None
        create_date = 1526996035.498
        data = {
            "createDate": create_date,
            "email": "thedude@example.com",
            "uid": "the-fxa-id",
            "locale": "en-US,en",
        }
        fxa_verified(data)
        upsert_mock.assert_called_with(
            SUBSCRIBE,
            {
                "email": data["email"],
                "newsletters": [settings.FXA_REGISTER_NEWSLETTER],
                "source_url": settings.FXA_REGISTER_SOURCE_URL,
                "country": "",
                "lang": "en-US",
                "fxa_lang": data["locale"],
                "fxa_service": "",
                "fxa_id": "the-fxa-id",
                "fxa_create_date": iso_format_unix_timestamp(create_date),
                "optin": True,
                "format": "H",
            },
            None,
        )


@patch("basket.news.tasks.upsert_user")
@patch("basket.news.tasks._add_fxa_activity")
class FxALoginTests(TestCase):
    # based on real data pulled from the queue
    base_data = {
        "deviceCount": 2,
        "email": "the.dude@example.com",
        "event": "login",
        "metricsContext": {
            "device_id": "phones-ringing-dude",
            "flowBeginTime": 1508897207639,
            "flowCompleteSignal": "account.signed",
            "flowType": "login",
            "flow_id": "the-dude-goes-with-the-flow-man",
            "flow_time": 31568,
            "time": 1508897239207,
            "utm_campaign": "fxa-embedded-form-fx",
            "utm_content": "fx-56.0.1",
            "utm_medium": "referral",
            "utm_source": "firstrun_f131",
        },
        "service": "sync",
        "ts": 1508897239.207,
        "uid": "the-fxa-id-for-el-dudarino",
        "userAgent": "Mozilla/5.0 (Windows NT 10.0; WOW64; rv:56.0) Gecko/20100101 Firefox/56.0",
        "countryCode": "US",
    }

    def get_data(self):
        return deepcopy(self.base_data)

    def test_fxa_login_task_with_no_utm(self, afa_mock, upsert_mock):
        data = self.get_data()
        del data["metricsContext"]
        data["deviceCount"] = 1
        fxa_login(data)
        afa_mock.assert_called_with(
            {
                "user_agent": data["userAgent"],
                "fxa_id": data["uid"],
                "first_device": True,
                "service": "sync",
                "ts": 1508897239.207,
            },
        )
        upsert_mock.delay.assert_not_called()

    def test_fxa_login_task_with_utm_data(self, afa_mock, upsert_mock):
        data = self.get_data()
        fxa_login(data)
        afa_mock.assert_called_with(
            {
                "user_agent": data["userAgent"],
                "fxa_id": data["uid"],
                "first_device": False,
                "service": "sync",
                "ts": 1508897239.207,
            },
        )
        upsert_mock.delay.assert_called_with(
            SUBSCRIBE,
            {
                "email": "the.dude@example.com",
                "newsletters": settings.FXA_LOGIN_CAMPAIGNS["fxa-embedded-form-fx"],
                "source_url": ANY,
                "country": "US",
            },
        )
        source_url = upsert_mock.delay.call_args[0][1]["source_url"]
        assert "utm_campaign=fxa-embedded-form-fx" in source_url
        assert "utm_content=fx-56.0.1" in source_url
        assert "utm_medium=referral" in source_url
        assert "utm_source=firstrun_f131" in source_url

    def test_fxa_login_task_with_utm_data_no_subscribe(self, afa_mock, upsert_mock):
        data = self.get_data()
        # not in the FXA_LOGIN_CAMPAIGNS setting
        data["metricsContext"]["utm_campaign"] = "nonesense"
        fxa_login(data)
        afa_mock.assert_called_with(
            {
                "user_agent": data["userAgent"],
                "fxa_id": data["uid"],
                "first_device": False,
                "service": "sync",
                "ts": 1508897239.207,
            },
        )
        upsert_mock.delay.assert_not_called()


@patch("basket.news.tasks.ctms", spec_set=["update", "add"])
@patch("basket.news.tasks.sfdc")
@patch("basket.news.tasks.get_user_data")
@patch("basket.news.tasks.cache")
class FxAEmailChangedTests(TestCase):
    def test_timestamps_older_message(self, cache_mock, gud_mock, sfdc_mock, ctms_mock):
        data = {
            "ts": 1234.567,
            "uid": "the-fxa-id-for-el-dudarino",
            "email": "the-dudes-new-email@example.com",
        }
        cache_mock.get.return_value = 1234.678
        # ts higher in cache, should no-op
        gud_mock.return_value = {"id": "1234"}
        fxa_email_changed(data)
        sfdc_mock.update.assert_not_called()
        ctms_mock.update.assert_not_called()

    def test_timestamps_newer_message(self, cache_mock, gud_mock, sfdc_mock, ctms_mock):
        data = {
            "ts": 1234.567,
            "uid": "the-fxa-id-for-el-dudarino",
            "email": "the-dudes-new-email@example.com",
        }
        cache_mock.get.return_value = 1234.456
        gud_mock.return_value = {"id": "1234"}
        # ts higher in message, do the things
        fxa_email_changed(data)
        sfdc_mock.update.assert_called_with(ANY, {"fxa_primary_email": data["email"]})
        ctms_mock.update.assert_called_once_with(
            ANY, {"fxa_primary_email": data["email"]}
        )

    def test_timestamps_nothin_cached(self, cache_mock, gud_mock, sfdc_mock, ctms_mock):
        data = {
            "ts": 1234.567,
            "uid": "the-fxa-id-for-el-dudarino",
            "email": "the-dudes-new-email@example.com",
        }
        cache_mock.get.return_value = 0
        gud_mock.return_value = {"id": "1234"}
        fxa_email_changed(data)
        sfdc_mock.update.assert_called_with(ANY, {"fxa_primary_email": data["email"]})
        ctms_mock.update.assert_called_with(ANY, {"fxa_primary_email": data["email"]})

    def test_fxa_id_not_found(self, cache_mock, gud_mock, sfdc_mock, ctms_mock):
        data = {
            "ts": 1234.567,
            "uid": "the-fxa-id-for-el-dudarino",
            "email": "the-dudes-new-email@example.com",
        }
        cache_mock.get.return_value = 0
        gud_mock.side_effect = [None, {"id": "1234"}]
        fxa_email_changed(data)
        gud_mock.assert_has_calls(
            [
                call(fxa_id=data["uid"], extra_fields=["id"]),
                call(email=data["email"], extra_fields=["id"]),
            ],
        )
        sfdc_mock.update.assert_called_with(
            {"id": "1234"}, {"fxa_id": data["uid"], "fxa_primary_email": data["email"]},
        )
        ctms_mock.update.assert_called_with(
            {"id": "1234"}, {"fxa_id": data["uid"], "fxa_primary_email": data["email"]},
        )

    def test_fxa_id_nor_email_found(self, cache_mock, gud_mock, sfdc_mock, ctms_mock):
        data = {
            "ts": 1234.567,
            "uid": "the-fxa-id-for-el-dudarino",
            "email": "the-dudes-new-email@example.com",
        }
        cache_mock.get.return_value = 0
        gud_mock.return_value = None
        email_id = str(uuid4())
        ctms_mock.add.return_value = {"email": {"email_id": email_id}}
        fxa_email_changed(data)
        gud_mock.assert_has_calls(
            [
                call(fxa_id=data["uid"], extra_fields=["id"]),
                call(email=data["email"], extra_fields=["id"]),
            ],
        )
        sfdc_mock.update.assert_not_called()
        ctms_mock.update.assert_not_called()
        ctms_mock.add.assert_called_with(
            {
                "email": data["email"],
                "token": ANY,
                "fxa_id": data["uid"],
                "fxa_primary_email": data["email"],
            },
        )
        sfdc_mock.add.assert_called_with(
            {
                "email_id": email_id,
                "token": ANY,
                "email": data["email"],
                "fxa_id": data["uid"],
                "fxa_primary_email": data["email"],
            },
        )

    def test_fxa_id_nor_email_found_ctms_add_fails(
        self, cache_mock, gud_mock, sfdc_mock, ctms_mock
    ):
        data = {
            "ts": 1234.567,
            "uid": "the-fxa-id-for-el-dudarino",
            "email": "the-dudes-new-email@example.com",
        }
        cache_mock.get.return_value = 0
        gud_mock.return_value = None
        ctms_mock.add.return_value = None
        fxa_email_changed(data)
        gud_mock.assert_has_calls(
            [
                call(fxa_id=data["uid"], extra_fields=["id"]),
                call(email=data["email"], extra_fields=["id"]),
            ],
        )
        sfdc_mock.update.assert_not_called()
        ctms_mock.update.assert_not_called()
        ctms_mock.add.assert_called_with(
            {
                "email": data["email"],
                "token": ANY,
                "fxa_id": data["uid"],
                "fxa_primary_email": data["email"],
            },
        )
        sfdc_mock.add.assert_called_with(
            {
                "email": data["email"],
                "token": ANY,
                "fxa_id": data["uid"],
                "fxa_primary_email": data["email"],
            },
        )


class GmttimeTests(TestCase):
    @patch("basket.news.tasks.datetime")
    def test_no_basetime_provided(self, datetime_mock):
        # original time is 'Fri, 09 Sep 2016 13:33:55 GMT'
        datetime_mock.now.return_value = datetime.fromtimestamp(1473428035.498)
        formatted_time = gmttime()
        self.assertEqual(formatted_time, "Fri, 09 Sep 2016 13:43:55 GMT")

    def test_basetime_provided(self):
        # original time is 'Fri, 09 Sep 2016 13:33:55 GMT', updates to 13:43:55
        basetime = datetime.fromtimestamp(1473428035.498)
        formatted_time = gmttime(basetime)
        self.assertEqual(formatted_time, "Fri, 09 Sep 2016 13:43:55 GMT")


@patch("basket.news.tasks.ctms")
@patch("basket.news.tasks.sfdc")
@patch("basket.news.tasks.get_user_data")
class CommonVoiceGoalsTests(TestCase):
    def test_new_user(self, gud_mock, sfdc_mock, ctms_mock):
        gud_mock.return_value = None
        email_id = str(uuid4())
        ctms_mock.add.return_value = {"email": {"email_id": email_id}}
        data = {
            "email": "dude@example.com",
            "first_contribution_date": "2018-06-27T14:56:58Z",
            "last_active_date": "2019-07-11T10:28:32Z",
            "two_day_streak": False,
        }
        orig_data = data.copy()
        record_common_voice_update(data)
        # ensure passed in dict was not modified in place.
        # if it is modified a retry will use the modified dict.
        assert orig_data == data
        insert_data = {
            "email": "dude@example.com",
            "token": ANY,
            "source_url": "https://voice.mozilla.org",
            "newsletters": [settings.COMMON_VOICE_NEWSLETTER],
            "cv_first_contribution_date": "2018-06-27T14:56:58Z",
            "cv_last_active_date": "2019-07-11T10:28:32Z",
            "cv_two_day_streak": False,
        }
        ctms_mock.add.assert_called_with(insert_data)
        insert_data["email_id"] = email_id
        sfdc_mock.add.assert_called_with(insert_data)

    def test_existing_user(self, gud_mock, sfdc_mock, ctms_mock):
        gud_mock.return_value = {"id": "the-duder", "email_id": str(uuid4())}
        data = {
            "email": "dude@example.com",
            "first_contribution_date": "2018-06-27T14:56:58Z",
            "last_active_date": "2019-07-11T10:28:32Z",
            "two_day_streak": False,
        }
        orig_data = data.copy()
        record_common_voice_update(data)
        # ensure passed in dict was not modified in place.
        # if it is modified a retry will use the modified dict.
        assert orig_data == data
        update_data = {
            "source_url": "https://voice.mozilla.org",
            "newsletters": [settings.COMMON_VOICE_NEWSLETTER],
            "cv_first_contribution_date": "2018-06-27T14:56:58Z",
            "cv_last_active_date": "2019-07-11T10:28:32Z",
            "cv_two_day_streak": False,
        }
        sfdc_mock.update.assert_called_with(gud_mock(), update_data)
        ctms_mock.update.assert_called_with(gud_mock(), update_data)


@override_settings(SFDC_ENABLED=True)
@patch("basket.news.tasks.ctms", spec_set=["update_by_alt_id"])
@patch("basket.news.tasks.sfdc")
@patch("basket.news.tasks.upsert_amo_user_data")
class AMOSyncAddonTests(TestCase):
    def setUp(self):
        # test data from
        # https://addons-server.readthedocs.io/en/latest/topics/basket.html#example-data
        self.amo_data = {
            "authors": [
                {
                    "id": 12345,
                    "display_name": "His Dudeness",
                    "email": "dude@example.com",
                    "homepage": "https://elduder.io",
                    "last_login": "2019-08-06T10:39:44Z",
                    "location": "California, USA, Earth",
                    "deleted": False,
                },
                {
                    "display_name": "serses",
                    "email": "mozilla@virgule.net",
                    "homepage": "",
                    "id": 11263,
                    "last_login": "2019-08-06T10:39:44Z",
                    "location": "",
                    "deleted": False,
                },
            ],
            "average_daily_users": 0,
            "categories": {"firefox": ["games-entertainment"]},
            "current_version": {
                "compatibility": {"firefox": {"max": "*", "min": "48.0"}},
                "id": 35900,
                "is_strict_compatibility_enabled": False,
                "version": "2.0",
            },
            "default_locale": "en-US",
            "guid": "{85ee4a2a-51b6-4f5e-a99c-6d9abcf6782d}",
            "id": 35896,
            "is_disabled": False,
            "is_recommended": True,
            "last_updated": "2019-06-26T11:38:13Z",
            "latest_unlisted_version": {
                "compatibility": {"firefox": {"max": "*", "min": "48.0"}},
                "id": 35899,
                "is_strict_compatibility_enabled": False,
                "version": "1.0",
            },
            "name": "Ibird Jelewt Boartrica",
            "ratings": {
                "average": 4.1,
                "bayesian_average": 4.2,
                "count": 43,
                "text_count": 40,
            },
            "slug": "ibird-jelewt-boartrica",
            "status": "nominated",
            "type": "extension",
        }
        self.users_data = [
            {"id": "A1234", "amo_id": 12345, "email": "the-dude@example.com"},
            {"id": "A4321", "amo_id": 11263, "email": "the-dude@example.com"},
        ]

    def test_update_addon(self, uaud_mock, sfdc_mock, ctms_mock):
        uaud_mock.side_effect = self.users_data
        sfdc_mock.addon.get_by_custom_id.return_value = {"Id": "B5678"}
        amo_sync_addon(self.amo_data)
        uaud_mock.assert_has_calls(
            [call(self.amo_data["authors"][0]), call(self.amo_data["authors"][1])],
        )
        sfdc_mock.addon.upsert.assert_called_with(
            f'AMO_AddOn_Id__c/{self.amo_data["id"]}',
            {
                "AMO_Category__c": "firefox-games-entertainment",
                "AMO_Current_Version__c": "2.0",
                "AMO_Current_Version_Unlisted__c": "1.0",
                "AMO_Default_Language__c": "en-US",
                "AMO_GUID__c": "{85ee4a2a-51b6-4f5e-a99c-6d9abcf6782d}",
                "AMO_Rating__c": 4.1,
                "AMO_Slug__c": "ibird-jelewt-boartrica",
                "AMO_Status__c": "nominated",
                "AMO_Type__c": "extension",
                "AMO_Update__c": "2019-06-26T11:38:13Z",
                "Average_Daily_Users__c": 0,
                "Dev_Disabled__c": "No",
                "AMO_Recommended__c": True,
                "Name": "Ibird Jelewt Boartrica",
            },
        )
        sfdc_mock.dev_addon.upsert.assert_has_calls(
            [
                call(
                    "ConcatenateAMOID__c/12345-35896",
                    {"AMO_AddOn_ID__c": "B5678", "AMO_Contact_ID__c": "A1234"},
                ),
                call(
                    "ConcatenateAMOID__c/11263-35896",
                    {"AMO_AddOn_ID__c": "B5678", "AMO_Contact_ID__c": "A4321"},
                ),
            ],
        )
        ctms_mock.update_by_alt_id.assert_not_called()

    def test_null_values(self, uaud_mock, sfdc_mock, ctms_mock):
        uaud_mock.side_effect = self.users_data
        sfdc_mock.addon.get_by_custom_id.return_value = {"Id": "B5678"}
        self.amo_data["current_version"] = None
        self.amo_data["latest_unlisted_version"] = None
        amo_sync_addon(self.amo_data)
        uaud_mock.assert_has_calls(
            [call(self.amo_data["authors"][0]), call(self.amo_data["authors"][1])],
        )
        sfdc_mock.addon.upsert.assert_called_with(
            f'AMO_AddOn_Id__c/{self.amo_data["id"]}',
            {
                "AMO_Category__c": "firefox-games-entertainment",
                "AMO_Default_Language__c": "en-US",
                "AMO_GUID__c": "{85ee4a2a-51b6-4f5e-a99c-6d9abcf6782d}",
                "AMO_Rating__c": 4.1,
                "AMO_Slug__c": "ibird-jelewt-boartrica",
                "AMO_Status__c": "nominated",
                "AMO_Type__c": "extension",
                "AMO_Update__c": "2019-06-26T11:38:13Z",
                "Average_Daily_Users__c": 0,
                "Dev_Disabled__c": "No",
                "AMO_Recommended__c": True,
                "Name": "Ibird Jelewt Boartrica",
                "AMO_Current_Version__c": "",
                "AMO_Current_Version_Unlisted__c": "",
            },
        )
        sfdc_mock.dev_addon.upsert.assert_has_calls(
            [
                call(
                    "ConcatenateAMOID__c/12345-35896",
                    {"AMO_AddOn_ID__c": "B5678", "AMO_Contact_ID__c": "A1234"},
                ),
                call(
                    "ConcatenateAMOID__c/11263-35896",
                    {"AMO_AddOn_ID__c": "B5678", "AMO_Contact_ID__c": "A4321"},
                ),
            ],
        )
        ctms_mock.update_by_alt_id.assert_not_called()

    def test_deleted_addon(self, uaud_mock, sfdc_mock, ctms_mock):
        self.amo_data["status"] = "deleted"
        sfdc_mock.addon.get_by_custom_id.return_value = {
            "Id": "A9876",
        }
        sfdc_mock.sf.query.side_effect = [
            {
                # 1st response is the addon's users
                "records": [
                    {"Id": 1234, "AMO_Contact_ID__c": "A4321"},
                    {"Id": 1235, "AMO_Contact_ID__c": "A4322"},
                ],
            },
            {
                # 1st user has records
                "records": [{"Id": "123456"}],
            },
            {
                # 2nd user has none
                "records": [],
            },
        ]
        amo_sync_addon(self.amo_data)
        uaud_mock.assert_not_called()
        sfdc_mock.sf.query.assert_has_calls(
            [
                call(
                    "SELECT Id, AMO_Contact_ID__c FROM DevAddOn__c WHERE AMO_AddOn_ID__c = 'A9876'",
                ),
                call(
                    "SELECT Id FROM DevAddOn__c WHERE AMO_Contact_ID__c = 'A4321' LIMIT 1",
                ),
                call(
                    "SELECT Id FROM DevAddOn__c WHERE AMO_Contact_ID__c = 'A4322' LIMIT 1",
                ),
            ],
        )
        # it should update the 2nd user that has no returned records
        sfdc_mock.update.assert_called_once_with(
            {"id": "A4322"}, {"amo_id": None, "amo_user": False},
        )
        ctms_mock.update_by_alt_id.assert_called_once_with(
            "sfdc_id", "A4322", {"amo_deleted": True}
        )
        sfdc_mock.dev_addon.delete.has_calls([call(1234), call(1235)])
        sfdc_mock.addon.delete.assert_called_with("A9876")

    @override_settings(SFDC_ENABLED=False)
    def test_update_addon_sfdc_disabled(self, uaud_mock, sfdc_mock, ctms_mock):
        amo_sync_addon(self.amo_data)
        uaud_mock.assert_not_called()
        sfdc_mock.addon.upsert.assert_not_called()
        sfdc_mock.dev_addon.upsert.assert_not_called()
        ctms_mock.update_by_alt_id.assert_not_called()


@patch("basket.news.tasks.ctms")
@patch("basket.news.tasks.sfdc")
@patch("basket.news.tasks.get_user_data")
class AMOSyncUserTests(TestCase):
    def setUp(self):
        self.amo_data = {
            "id": 1234,
            "display_name": "His Dudeness",
            "fxa_id": "fxa_id_of_dude",
            "homepage": "https://elduder.io",
            "last_login": "2019-08-06T10:39:44Z",
            "location": "California, USA, Earth",
            "deleted": False,
        }
        self.user_data = {"id": "A1234", "amo_id": 1234, "fxa_id": "fxa_id_of_dude"}

    def test_existing_user_with_amo_id(self, gud_mock, sfdc_mock, ctms_mock):
        gud_mock.return_value = self.user_data
        amo_sync_user(self.amo_data)
        # does not include email or amo_id
        sfdc_mock.update.assert_called_with(
            self.user_data,
            {
                "amo_id": 1234,
                "amo_display_name": "His Dudeness",
                "amo_homepage": "https://elduder.io",
                "amo_last_login": "2019-08-06T10:39:44Z",
                "amo_location": "California, USA, Earth",
                "amo_deleted": False,
            },
        )
        ctms_mock.update.assert_called_with(
            self.user_data,
            {
                "amo_id": 1234,
                "amo_display_name": "His Dudeness",
                "amo_homepage": "https://elduder.io",
                "amo_last_login": "2019-08-06T10:39:44Z",
                "amo_location": "California, USA, Earth",
                "amo_deleted": False,
            },
        )

    def test_existing_user_no_amo_id(self, gud_mock, sfdc_mock, ctms_mock):
        gud_mock.side_effect = [None, self.user_data]
        amo_sync_user(self.amo_data)
        # does not include email
        sfdc_mock.update.assert_called_with(
            self.user_data,
            {
                "amo_id": 1234,
                "amo_display_name": "His Dudeness",
                "amo_homepage": "https://elduder.io",
                "amo_last_login": "2019-08-06T10:39:44Z",
                "amo_location": "California, USA, Earth",
                "amo_deleted": False,
            },
        )
        ctms_mock.update.assert_called_with(
            self.user_data,
            {
                "amo_id": 1234,
                "amo_display_name": "His Dudeness",
                "amo_homepage": "https://elduder.io",
                "amo_last_login": "2019-08-06T10:39:44Z",
                "amo_location": "California, USA, Earth",
                "amo_deleted": False,
            },
        )

    def test_new_user(self, gud_mock, sfdc_mock, ctms_mock):
        gud_mock.return_value = None
        user = amo_sync_user(self.amo_data)
        sfdc_mock.update.assert_not_called()
        ctms_mock.update.assert_not_called()
        assert user is None

    def test_deleted_user_matching_fxa_id(self, gud_mock, sfdc_mock, ctms_mock):
        self.amo_data["deleted"] = True
        gud_mock.return_value = self.user_data
        amo_sync_user(self.amo_data)
        sfdc_mock.update.assert_called_with(
            self.user_data,
            {
                "amo_display_name": "His Dudeness",
                "amo_homepage": "https://elduder.io",
                "amo_last_login": "2019-08-06T10:39:44Z",
                "amo_location": "California, USA, Earth",
                "amo_deleted": True,
                "amo_id": None,
            },
        )
        ctms_mock.update.assert_called_with(
            self.user_data,
            {
                "amo_display_name": "His Dudeness",
                "amo_homepage": "https://elduder.io",
                "amo_last_login": "2019-08-06T10:39:44Z",
                "amo_location": "California, USA, Earth",
                "amo_deleted": True,
                "amo_id": None,
            },
        )

    def test_deleted_user_fxa_id_is_None(self, gud_mock, sfdc_mock, ctms_mock):
        self.amo_data["deleted"] = True
        self.amo_data["fxa_id"] = None
        gud_mock.return_value = self.user_data
        amo_sync_user(self.amo_data)
        sfdc_mock.update.assert_called_with(
            self.user_data,
            {
                "amo_display_name": "His Dudeness",
                "amo_homepage": "https://elduder.io",
                "amo_last_login": "2019-08-06T10:39:44Z",
                "amo_location": "California, USA, Earth",
                "amo_deleted": True,
                "amo_id": None,
            },
        )
        ctms_mock.update.assert_called_with(
            self.user_data,
            {
                "amo_display_name": "His Dudeness",
                "amo_homepage": "https://elduder.io",
                "amo_last_login": "2019-08-06T10:39:44Z",
                "amo_location": "California, USA, Earth",
                "amo_deleted": True,
                "amo_id": None,
            },
        )

    def test_not_deleted_user_fxa_id_is_None(self, gud_mock, sfdc_mock, ctms_mock):
        self.amo_data["fxa_id"] = None
        gud_mock.return_value = self.user_data
        amo_sync_user(self.amo_data)
        sfdc_mock.update.assert_called_with(
            self.user_data,
            {
                "amo_display_name": "His Dudeness",
                "amo_homepage": "https://elduder.io",
                "amo_last_login": "2019-08-06T10:39:44Z",
                "amo_location": "California, USA, Earth",
                "amo_id": None,
                "amo_deleted": False,
            },
        )
        ctms_mock.update.assert_called_with(
            self.user_data,
            {
                "amo_display_name": "His Dudeness",
                "amo_homepage": "https://elduder.io",
                "amo_last_login": "2019-08-06T10:39:44Z",
                "amo_location": "California, USA, Earth",
                "amo_id": None,
                "amo_deleted": False,
            },
        )

    def test_ignore_user_no_id_or_fxa_id(self, gud_mock, sfdc_mock, ctms_mock):
        self.amo_data["fxa_id"] = None
        self.amo_data["id"] = None
        amo_sync_user(self.amo_data)
        sfdc_mock.update.assert_not_called()
        ctms_mock.update.assert_not_called()


@override_settings(COMMON_VOICE_BATCH_PROCESSING=True, COMMON_VOICE_BATCH_CHUNK_SIZE=5)
@patch("basket.news.tasks.record_common_voice_update")
class TestCommonVoiceBatch(TestCase):
    def setUp(self):
        CommonVoiceUpdate.objects.create(
            data={
                "email": "dude@example.com",
                "last_active_date": "2020-02-18T14:52:30Z",
            },
        )
        CommonVoiceUpdate.objects.create(
            data={
                "email": "dude@example.com",
                "last_active_date": "2020-02-17T14:52:30Z",
            },
        )
        CommonVoiceUpdate.objects.create(
            data={
                "email": "dude@example.com",
                "last_active_date": "2020-02-16T14:52:30Z",
            },
        )
        CommonVoiceUpdate.objects.create(
            data={
                "email": "donny@example.com",
                "last_active_date": "2020-02-15T14:52:30Z",
            },
        )
        CommonVoiceUpdate.objects.create(
            data={
                "email": "donny@example.com",
                "last_active_date": "2020-02-14T14:52:30Z",
            },
        )

    def test_batch(self, mock_rcvg):
        assert CommonVoiceUpdate.objects.filter(ack=False).count() == 5
        assert CommonVoiceUpdate.objects.filter(ack=True).count() == 0
        process_common_voice_batch()
        assert CommonVoiceUpdate.objects.filter(ack=False).count() == 0
        assert CommonVoiceUpdate.objects.filter(ack=True).count() == 5
        assert mock_rcvg.delay.call_count == 2
        assert mock_rcvg.delay.has_calls(
            [
                call(
                    {
                        "email": "dude@example.com",
                        "last_active_date": "2020-02-18T14:52:30Z",
                    },
                ),
                call(
                    {
                        "email": "donny@example.com",
                        "last_active_date": "2020-02-15T14:52:30Z",
                    },
                ),
            ],
        )

    def test_batch_cleanup(self, mock_rcvg):
        CommonVoiceUpdate.objects.update(ack=True, when=now() - timedelta(hours=25))
        assert CommonVoiceUpdate.objects.count() == 5
        process_common_voice_batch()
        assert CommonVoiceUpdate.objects.count() == 0

    def test_batch_chunking(self, mock_rcvg):
        obj = CommonVoiceUpdate.objects.create(
            data={
                "email": "dude@example.com",
                "last_active_date": "2020-02-19T14:52:30Z",
            },
        )
        CommonVoiceUpdate.objects.create(
            data={
                "email": "dude@example.com",
                "last_active_date": "2020-02-19T14:53:30Z",
            },
        )
        CommonVoiceUpdate.objects.create(
            data={
                "email": "dude@example.com",
                "last_active_date": "2020-02-19T14:54:30Z",
            },
        )
        CommonVoiceUpdate.objects.create(
            data={
                "email": "donny@example.com",
                "last_active_date": "2020-02-19T14:55:30Z",
            },
        )
        CommonVoiceUpdate.objects.create(
            data={
                "email": "donny@example.com",
                "last_active_date": "2020-02-19T14:56:30Z",
            },
        )
        assert CommonVoiceUpdate.objects.filter(ack=False).count() == 10
        assert CommonVoiceUpdate.objects.filter(ack=True).count() == 0
        process_common_voice_batch()
        assert obj in CommonVoiceUpdate.objects.filter(ack=False)
        assert CommonVoiceUpdate.objects.filter(ack=False).count() == 5
        assert CommonVoiceUpdate.objects.filter(ack=True).count() == 5
        process_common_voice_batch()
        assert CommonVoiceUpdate.objects.filter(ack=False).count() == 0
        assert CommonVoiceUpdate.objects.filter(ack=True).count() == 10


@override_settings(TASK_LOCKING_ENABLE=False)
@patch("basket.news.tasks.ctms")
@patch("basket.news.tasks.sfdc")
class TestUpdateCustomUnsub(TestCase):
    token = "the-token"
    reason = "I would like less emails."

    def test_normal(self, mock_sfdc, mock_ctms):
        """The reason is updated for the token"""
        update_custom_unsub(self.token, self.reason)
        mock_sfdc.update.assert_called_once_with(
            {"token": self.token}, {"reason": self.reason}
        )
        mock_ctms.update_by_alt_id.assert_called_once_with(
            "token", self.token, {"reason": self.reason}
        )

    def test_no_ctms_record(self, mock_sfdc, mock_ctms):
        """If there is no CTMS record, updates are skipped."""
        mock_ctms.updates_by_alt_id.side_effect = CTMSNotFoundByAltIDError(
            "token", self.token
        )
        update_custom_unsub(self.token, self.reason)
        mock_sfdc.update.assert_called_once_with(
            {"token": self.token}, {"reason": self.reason}
        )
        mock_ctms.update_by_alt_id.assert_called_once_with(
            "token", self.token, {"reason": self.reason}
        )

    def test_error_raised(self, mock_sfdc, mock_ctms):
        """A SF exception is not re-raised"""
        error_content = [{"message": "something went wrong"}]
        exc = sfapi.SalesforceMalformedRequest("url", 400, "contact", error_content)
        mock_sfdc.update.side_effect = exc
        update_custom_unsub(self.token, self.reason)
        mock_sfdc.update.assert_called_once_with(
            {"token": self.token}, {"reason": self.reason}
        )
        mock_ctms.get.assert_not_called()


@override_settings(TASK_LOCKING_ENABLE=False)
@patch("basket.news.tasks.ctms")
@patch("basket.news.tasks.sfdc")
class TestUpdateUserMeta(TestCase):
    token = "the-token"
    data = {"first_name": "Edmund", "last_name": "Gettier"}

    def test_normal(self, mock_sfdc, mock_ctms):
        """The data is updated for the token"""
        update_user_meta(self.token, self.data)
        mock_sfdc.update.assert_called_once_with({"token": self.token}, self.data)
        mock_ctms.update_by_alt_id.assert_called_once_with(
            "token", self.token, self.data
        )

    @override_settings(SFDC_ENABLED=True)
    def test_no_ctms_record(self, mock_sfdc, mock_ctms):
        """If there is no CTMS record, CTMS updates are skipped."""
        mock_ctms.update_by_alt_id.side_effect = CTMSNotFoundByAltIDError(
            "token", self.token
        )
        update_user_meta(self.token, self.data)
        mock_sfdc.update.assert_called_once_with({"token": self.token}, self.data)
        mock_ctms.update_by_alt_id.assert_called_once_with(
            "token", self.token, self.data
        )

    @override_settings(SFDC_ENABLED=False)
    def test_no_ctms_record_with_sfdc_disabled(self, mock_sfdc, mock_ctms):
        """If there is no CTMS record, an exception is raised."""
        mock_ctms.update_by_alt_id.side_effect = CTMSNotFoundByAltIDError(
            "token", self.token
        )
        self.assertRaises(
            CTMSNotFoundByAltIDError, update_user_meta, self.token, self.data
        )
        mock_sfdc.update.assert_called_once_with({"token": self.token}, self.data)
        mock_ctms.update_by_alt_id.assert_called_once_with(
            "token", self.token, self.data
        )


@patch("basket.news.tasks.ctms", spec_set=["update"])
@patch("basket.news.tasks.sfdc", spec_set=["update"])
@patch("basket.news.tasks.get_user_data")
class TestGetFxaUserData(TestCase):
    def test_found_by_fxa_id_email_match(self, mock_gud, mock_sfdc, mock_ctms):
        """A user can be found by FxA ID."""
        user_data = {
            "id": "1234",
            "token": "the-token",
            "fxa_id": "123",
            "email": "test@example.com",
        }
        mock_gud.return_value = user_data

        fxa_user_data = get_fxa_user_data("123", "test@example.com")
        assert user_data == fxa_user_data

        mock_gud.assert_called_once_with(fxa_id="123", extra_fields=["id"])
        mock_sfdc.update.assert_not_called()
        mock_ctms.update.assert_not_called()

    def test_found_by_fxa_id_email_mismatch(self, mock_gud, mock_sfdc, mock_ctms):
        """If the FxA user has a different FxA email, set fxa_primary_email."""
        user_data = {
            "id": "1234",
            "token": "the-token",
            "fxa_id": "123",
            "email": "test@example.com",
        }
        mock_gud.return_value = user_data

        fxa_user_data = get_fxa_user_data("123", "fxa@example.com")
        assert user_data == fxa_user_data

        mock_gud.assert_called_once_with(fxa_id="123", extra_fields=["id"])
        mock_sfdc.update.assert_called_once_with(
            user_data, {"fxa_primary_email": "fxa@example.com"}
        )
        mock_ctms.update.assert_called_once_with(
            user_data, {"fxa_primary_email": "fxa@example.com"}
        )

    def test_miss_by_fxa_id(self, mock_gud, mock_sfdc, mock_ctms):
        """If the FxA user has a different FxA email, set fxa_primary_email."""
        user_data = {
            "id": "1234",
            "token": "the-token",
            "email": "test@example.com",
        }
        mock_gud.side_effect = [None, user_data]

        fxa_user_data = get_fxa_user_data("123", "test@example.com")
        assert user_data == fxa_user_data

        assert mock_gud.call_count == 2
        mock_gud.assert_any_call(fxa_id="123", extra_fields=["id"])
        mock_gud.assert_called_with(email="test@example.com", extra_fields=["id"])
        mock_sfdc.update.asser
        mock_ctms.update.assert_not_called()


@patch("basket.news.tasks.ctms", spec_set=["update_by_alt_id"])
@patch("basket.news.tasks.sfdc", content=Mock(spec_set=["update"]))
class TestFxaDelete(TestCase):
    def test_delete(self, mock_sfdc, mock_ctms):
        fxa_delete({"uid": "123"})
        mock_sfdc.contact.update.assert_called_once_with(
            "FxA_Id__c/123", {"FxA_Account_Deleted__c": True}
        )
        mock_ctms.update_by_alt_id.assert_called_once_with(
            "fxa_id", "123", {"fxa_deleted": True, "newsletters": []}
        )

    def test_delete_with_sfdc_disabled(self, mock_sfdc, mock_ctms):
        """The FxA data is deleted in CTMS."""
        mock_sfdc.contact.update.side_effect = SFDCDisabled("not enabled")
        fxa_delete({"uid": "123"})
        mock_sfdc.contact.update.assert_called_once_with(
            "FxA_Id__c/123", {"FxA_Account_Deleted__c": True}
        )
        mock_ctms.update_by_alt_id.assert_called_once_with(
            "fxa_id", "123", {"fxa_deleted": True, "newsletters": []}
        )

    def test_delete_does_not_exist_success(self, mock_sfdc, mock_ctms):
        """If the record doesn't exist, the exception is caught."""
        err_content = {
            "errorCode": "REQUIRED_FIELD_MISSING",
            "fields": ["Field1", "Field2"],
            "message": "Required fields are missing: [Field1, Field2]",
        }

        exc = sfapi.SalesforceMalformedRequest("url", 400, "contact", [err_content])
        mock_sfdc.contact.update.side_effect = exc
        fxa_delete({"uid": "123"})
        mock_sfdc.contact.update.assert_called_once_with(
            "FxA_Id__c/123", {"FxA_Account_Deleted__c": True}
        )
        mock_ctms.update_by_alt_id.assert_not_called()

    def test_delete_other_exception_raised(self, mock_sfdc, mock_ctms):
        """If updating raises a different error, re-raise"""
        err_content = {
            "errorCode": "SOMETHING_ELSE",
            "message": "Something else went wrong",
        }

        exc = sfapi.SalesforceMalformedRequest("url", 400, "contact", [err_content])
        mock_sfdc.contact.update.side_effect = exc
        self.assertRaises(Retry, fxa_delete, {"uid": "123"})
        mock_ctms.update_by_alt_id.assert_not_called()

    def test_delete_ctms_not_found_succeeds(self, mock_sfdc, mock_ctms):
        """If the CTMS record is not found by FxA ID, the exception is caught."""
        mock_ctms.update_by_alt_id.side_effect = CTMSNotFoundByAltIDError(
            "fxa_id", "123"
        )
        fxa_delete({"uid": "123"})
        mock_sfdc.contact.update.assert_called_once_with(
            "FxA_Id__c/123", {"FxA_Account_Deleted__c": True}
        )
        mock_ctms.update_by_alt_id.assert_called_once_with(
            "fxa_id", "123", {"fxa_deleted": True, "newsletters": []}
        )

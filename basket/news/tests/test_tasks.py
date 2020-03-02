import json
from copy import deepcopy
from datetime import datetime, timedelta
from urllib.error import URLError

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from django.test.utils import override_settings
from django.utils.timezone import now

import simple_salesforce as sfapi
from celery.exceptions import Retry
from mock import ANY, Mock, call, patch

from basket.news.celery import app as celery_app
from basket.news.models import FailedTask, CommonVoiceUpdate
from basket.news.newsletters import clear_sms_cache
from basket.news.tasks import (
    _add_fxa_activity,
    add_sms_user,
    amo_sync_addon,
    amo_sync_user,
    et_task,
    fxa_email_changed,
    fxa_login,
    fxa_verified,
    gmttime,
    mogrify_message_id,
    NewsletterException,
    PETITION_CONTACT_FIELDS,
    process_common_voice_batch,
    process_donation,
    process_donation_event,
    process_petition_signature,
    process_subhub_event_credit_card_expiring,
    process_subhub_event_customer_created,
    process_subhub_event_payment_failed,
    process_subhub_event_subscription_cancel,
    process_subhub_event_subscription_charge,
    process_subhub_event_subscription_updated,
    record_common_voice_update,
    RECOVERY_MESSAGE_ID,
    SUBSCRIBE,
    send_recovery_message_task,
    send_message,
    get_lock,
    RetryTask,
)
from basket.news.utils import iso_format_unix_timestamp


@override_settings(TASK_LOCKING_ENABLE=False)
@patch('basket.news.tasks.upsert_user')
@patch('basket.news.tasks.get_user_data')
@patch('basket.news.tasks.sfdc')
class ProcessPetitionSignatureTests(TestCase):
    def _get_sig_data(self):
        return {
            'form': {
                'campaign_id': 'abiding',
                'email': 'dude@example.com',
                'first_name': 'Jeffery',
                'last_name': 'Lebowski',
                'country': 'us',
                'postal_code': '90210',
                'source_url': 'https://example.com/change',
                'email_subscription': False,
                'comments': 'The Dude abides',
                'metadata': {
                    'location': 'bowling alley',
                    'donnie': 'out of his element',
                }
            }
        }

    def _get_contact_data(self, data):
        data = data['form']
        contact_data = {'_set_subscriber': False}
        contact_data.update({k: data[k] for k in PETITION_CONTACT_FIELDS if k in data})
        return contact_data

    def test_signature_with_comments_metadata(self, sfdc_mock, gud_mock, uu_mock):
        data = self._get_sig_data()
        contact_data = self._get_contact_data(data)
        user_data = {
            'id': '1234',
            'token': 'the-token',
        }
        campaign_member = {
            'CampaignId': data['form']['campaign_id'],
            'ContactId': user_data['id'],
            'Full_URL__c': data['form']['source_url'],
            'Status': 'Signed',
            'Petition_Comments__c': data['form']['comments'],
            'Petition_Flex__c': json.dumps(data['form']['metadata']),
        }
        gud_mock.return_value = user_data
        process_petition_signature(data)
        sfdc_mock.update.assert_called_with(gud_mock(), contact_data)
        sfdc_mock.add.assert_not_called()
        uu_mock.delay.assert_not_called()
        sfdc_mock.campaign_member.create.assert_called_with(campaign_member)

    def test_signature_with_long_comments_metadata(self, sfdc_mock, gud_mock, uu_mock):
        data = self._get_sig_data()
        data['form']['comments'] = 'DUDER!' * 100
        data['form']['metadata']['location'] = 'bowling alley' * 100
        contact_data = self._get_contact_data(data)
        user_data = {
            'id': '1234',
            'token': 'the-token',
        }
        campaign_member = {
            'CampaignId': data['form']['campaign_id'],
            'ContactId': user_data['id'],
            'Full_URL__c': data['form']['source_url'],
            'Status': 'Signed',
            'Petition_Comments__c': data['form']['comments'][:500],
            'Petition_Flex__c': json.dumps(data['form']['metadata'])[:500],
        }
        assert data['form']['comments'] != campaign_member['Petition_Comments__c']
        gud_mock.return_value = user_data
        process_petition_signature(data)
        sfdc_mock.update.assert_called_with(gud_mock(), contact_data)
        sfdc_mock.add.assert_not_called()
        uu_mock.delay.assert_not_called()
        sfdc_mock.campaign_member.create.assert_called_with(campaign_member)

    def test_signature_without_comments_metadata(self, sfdc_mock, gud_mock, uu_mock):
        data = self._get_sig_data()
        del data['form']['comments']
        del data['form']['metadata']
        contact_data = self._get_contact_data(data)
        user_data = {
            'id': '1234',
            'token': 'the-token',
        }
        campaign_member = {
            'CampaignId': data['form']['campaign_id'],
            'ContactId': user_data['id'],
            'Full_URL__c': data['form']['source_url'],
            'Status': 'Signed',
        }
        gud_mock.return_value = user_data
        process_petition_signature(data)
        sfdc_mock.update.assert_called_with(gud_mock(), contact_data)
        sfdc_mock.add.assert_not_called()
        uu_mock.delay.assert_not_called()
        sfdc_mock.campaign_member.create.assert_called_with(campaign_member)

    def test_signature_with_subscription(self, sfdc_mock, gud_mock, uu_mock):
        data = self._get_sig_data()
        data['form']['email_subscription'] = True
        del data['form']['comments']
        del data['form']['metadata']
        contact_data = self._get_contact_data(data)
        user_data = {
            'id': '1234',
            'token': 'the-token',
        }
        campaign_member = {
            'CampaignId': data['form']['campaign_id'],
            'ContactId': user_data['id'],
            'Full_URL__c': data['form']['source_url'],
            'Status': 'Signed',
        }
        gud_mock.return_value = user_data
        process_petition_signature(data)
        sfdc_mock.update.assert_called_with(gud_mock(), contact_data)
        sfdc_mock.add.assert_not_called()
        uu_mock.delay.assert_called_with(SUBSCRIBE, {
            'token': user_data['token'],
            'lang': 'en-US',
            'newsletters': 'mozilla-foundation',
            'source_url': data['form']['source_url'],
        })
        sfdc_mock.campaign_member.create.assert_called_with(campaign_member)

    @patch('basket.news.tasks.generate_token')
    def test_signature_with_new_user(self, gt_mock, sfdc_mock, gud_mock, uu_mock):
        data = self._get_sig_data()
        del data['form']['comments']
        del data['form']['metadata']
        contact_data = self._get_contact_data(data)
        contact_data['token'] = gt_mock()
        contact_data['email'] = data['form']['email']
        contact_data['record_type'] = settings.DONATE_CONTACT_RECORD_TYPE
        user_data = {
            'id': '1234',
            'token': 'the-token',
        }
        campaign_member = {
            'CampaignId': data['form']['campaign_id'],
            'ContactId': user_data['id'],
            'Full_URL__c': data['form']['source_url'],
            'Status': 'Signed',
        }
        gud_mock.side_effect = [None, user_data]
        process_petition_signature(data)
        sfdc_mock.update.assert_not_called()
        sfdc_mock.add.assert_called_with(contact_data)
        uu_mock.delay.assert_not_called()
        sfdc_mock.campaign_member.create.assert_called_with(campaign_member)

    @patch('basket.news.tasks.generate_token')
    def test_signature_with_new_user_retry(self, gt_mock, sfdc_mock, gud_mock, uu_mock):
        data = self._get_sig_data()
        del data['form']['comments']
        del data['form']['metadata']
        contact_data = self._get_contact_data(data)
        contact_data['token'] = gt_mock()
        contact_data['email'] = data['form']['email']
        contact_data['record_type'] = settings.DONATE_CONTACT_RECORD_TYPE
        gud_mock.return_value = None
        with self.assertRaises(Retry):
            process_petition_signature(data)

        sfdc_mock.update.assert_not_called()
        sfdc_mock.add.assert_called_with(contact_data)
        uu_mock.delay.assert_not_called()
        sfdc_mock.campaign_member.create.assert_not_called()


@override_settings(TASK_LOCKING_ENABLE=False)
@patch('basket.news.tasks.sfdc')
class ProcessDonationEventTests(TestCase):
    def test_charge_failed(self, sfdc_mock):
        process_donation_event({
            'event_type': 'charge.failed',
            'transaction_id': 'el-dudarino',
            'failure_code': 'expired_card',
        })
        sfdc_mock.opportunity.update.assert_called_with('PMT_Transaction_ID__c/el-dudarino', {
            'PMT_Type_Lost__c': 'charge.failed',
            'PMT_Reason_Lost__c': 'expired_card',
            'StageName': 'Closed Lost',
        })

    def test_charge_refunded_ignored(self, sfdc_mock):
        process_donation_event({
            'event_type': 'charge.refunded',
            'transaction_id': 'el-dudarino',
            'reason': 'requested_by_customer',
            'status': 'pending',
        })
        sfdc_mock.opportunity.update.assert_not_called()

    def test_charge_refunded(self, sfdc_mock):
        process_donation_event({
            'event_type': 'charge.refunded',
            'transaction_id': 'el-dudarino',
            'reason': 'requested_by_customer',
            'status': 'succeeded',
        })
        sfdc_mock.opportunity.update.assert_called_with('PMT_Transaction_ID__c/el-dudarino', {
            'PMT_Type_Lost__c': 'charge.refunded',
            'PMT_Reason_Lost__c': 'requested_by_customer',
            'StageName': 'Closed Lost',
        })

    def test_charge_disputed_ignored(self, sfdc_mock):
        process_donation_event({
            'event_type': 'charge.dispute.closed',
            'transaction_id': 'el-dudarino',
            'reason': 'fraudulent',
            'status': 'under_review',
        })
        sfdc_mock.opportunity.update.assert_not_called()

    def test_charge_disputed(self, sfdc_mock):
        process_donation_event({
            'event_type': 'charge.dispute.closed',
            'transaction_id': 'el-dudarino',
            'reason': 'fraudulent',
            'status': 'lost',
        })
        sfdc_mock.opportunity.update.assert_called_with('PMT_Transaction_ID__c/el-dudarino', {
            'PMT_Type_Lost__c': 'charge.dispute.closed',
            'PMT_Reason_Lost__c': 'fraudulent',
            'StageName': 'Closed Lost',
        })


@override_settings(TASK_LOCKING_ENABLE=False)
@patch('basket.news.tasks.get_user_data')
@patch('basket.news.tasks.sfdc')
class SubHubEventSubUpdatedTests(TestCase):
    def _get_data(self, direction='up'):
        return {
            'event_id': 'the-event-id',
            'event_type': f'customer.subscription.{direction}grade',
            'customer_id': 'cus_1234',
            'plan_amount_new': '1000',
            'plan_amount_old': '100',
            'current_period_end': '1566305505',
            'close_date': '1566305509',
            'interval': 'monthly',
            'invoice_number': 'abc123',
            'invoice_id': 'inv_abc123',
            'proration_amount': '5',
            'subscription_id': 'sub_123',
            'charge': '8675309',
            'nickname_old': 'bowling',
            'nickname_new': 'abide',
        }

    def test_upgrade(self, sfdc_mock, gud_mock):
        gud_mock.return_value = {'id': '1234'}
        data = self._get_data()
        process_subhub_event_subscription_updated(data)
        sfdc_mock.opportunity.create.assert_called_with({
            'Amount': 10.0,
            'Plan_Amount_Old__c': 1.0,
            'Billing_Cycle_End__c': '2019-08-20T12:51:45',
            'CloseDate': '2019-08-20T12:51:49',
            'Donation_Contact__c': '1234',
            'Event_Id__c': 'the-event-id',
            'Event_Name__c': 'customer.subscription.upgrade',
            'Invoice_Number__c': data['invoice_number'],
            'Name': 'Subscription Services',
            'Payment_Interval__c': data['interval'],
            'Payment_Source__c': 'Stripe',
            'PMT_Invoice_ID__c': data['invoice_id'],
            'PMT_Subscription_ID__c': data['subscription_id'],
            'Proration_Amount__c': 0.05,
            'RecordTypeId': settings.SUBHUB_OPP_RECORD_TYPE,
            'Service_Plan__c': data['nickname_new'],
            'Nickname_Old__c': data['nickname_old'],
            'StageName': 'Subscription Upgrade',
        })

    def test_downgrade(self, sfdc_mock, gud_mock):
        gud_mock.return_value = {'id': '1234'}
        data = self._get_data('down')
        process_subhub_event_subscription_updated(data)
        sfdc_mock.opportunity.create.assert_called_with({
            'Amount': 10.0,
            'Plan_Amount_Old__c': 1.0,
            'Billing_Cycle_End__c': '2019-08-20T12:51:45',
            'CloseDate': '2019-08-20T12:51:49',
            'Donation_Contact__c': '1234',
            'Event_Id__c': 'the-event-id',
            'Event_Name__c': 'customer.subscription.downgrade',
            'Invoice_Number__c': data['invoice_number'],
            'Name': 'Subscription Services',
            'Payment_Interval__c': data['interval'],
            'Payment_Source__c': 'Stripe',
            'PMT_Invoice_ID__c': data['invoice_id'],
            'PMT_Subscription_ID__c': data['subscription_id'],
            'Proration_Amount__c': 0.05,
            'RecordTypeId': settings.SUBHUB_OPP_RECORD_TYPE,
            'Service_Plan__c': data['nickname_new'],
            'Nickname_Old__c': data['nickname_old'],
            'StageName': 'Subscription Downgrade',
        })


@override_settings(TASK_LOCKING_ENABLE=False)
@patch('basket.news.tasks.get_user_data')
@patch('basket.news.tasks.sfdc')
class SubHubEventTests(TestCase):
    charge_data = {
        'event_id': 'the-event-id',
        'event_type': 'customer.source.expiring',
        'customer_id': 'cus_1234',
        'plan_amount': '1000',
        'current_period_end': '1566305505',
        'current_period_start': '1566305502',
        'next_invoice_date': '1566305605',
        'created': '1566305509',
        'brand': 'visa',
        'last4': '1111',
        'currency': 'us',
        'invoice_number': 'abc123',
        'invoice_id': 'inv_abc123',
        'subscription_id': 'sub_123',
        'charge': '8675309',
        'nickname': 'bowling',
    }

    @patch('basket.news.tasks.sfmc')
    def test_credit_card_expiring(self, sfmc_mock, sfdc_mock, gud_mock):
        process_subhub_event_credit_card_expiring({
            'email': 'dude@example.com',
        })

        sfmc_mock.send_mail.assert_called_with(settings.SUBHUB_CC_EXPIRE_TRIGGER,
            'dude@example.com', 'dude@example.com')

    def test_customer_created_customer_found(self, sfdc_mock, gud_mock):
        """
        Contact found by email only
        """
        user_data = {
            'first_name': 'Jeffrey',
            'last_name': '_',
        }

        gud_mock.side_effect = [None, user_data]

        process_subhub_event_customer_created({
            'name': 'Jeffrey Lebowski',
            'email': 'thedude@thedude.io',
            'user_id': '1234',
            'customer_id': 'cus_1234',
        })

        sfdc_mock.update.assert_called_with(user_data, {
            'fxa_id': '1234',
            'payee_id': 'cus_1234',
            'last_name': 'Lebowski',
        })

    def test_customer_created_customer_not_found(self, sfdc_mock, gud_mock):
        """
        No contact found at all
        """
        gud_mock.return_value = None

        process_subhub_event_customer_created({
            'name': 'Walter Sobchak',
            'email': 'walter@thedude.io',
            'user_id': '1234',
            'customer_id': 'cus_1234',
        })

        sfdc_mock.update.assert_not_called()

        sfdc_mock.add.assert_called_with({
            'fxa_id': '1234',
            'payee_id': 'cus_1234',
            'first_name': 'Walter',
            'last_name': 'Sobchak',
            'email': 'walter@thedude.io',
        })

    def test_customer_created_customer_fxa_found_match(self, sfdc_mock, gud_mock):
        """
        Contact found by FxA_ID and email matches
        """
        user_data = {
            'first_name': 'Jeffrey',
            'last_name': '_',
            'email': 'walter@thedude.io'
        }
        gud_mock.return_value = user_data

        process_subhub_event_customer_created({
            'name': 'Walter Sobchak',
            'email': 'walter@thedude.io',
            'user_id': '1234',
            'customer_id': 'cus_1234',
        })

        gud_mock.assert_called_once_with(fxa_id='1234', extra_fields=['id'])
        sfdc_mock.update.assert_called_once_with(user_data, {
            'fxa_id': '1234',
            'payee_id': 'cus_1234',
            'last_name': 'Sobchak',
        })

    def test_customer_created_customer_fxa_found_no_match_yes_other(self, sfdc_mock, gud_mock):
        """
        Contact found by FxA_ID and email does not match, and other found by email
        """
        user_data_fxa = {
            'first_name': 'Jeffrey',
            'last_name': '_',
            'email': 'dude@thedude.io'
        }
        user_data = {
            'first_name': 'Jeffrey',
            'last_name': '_',
            'email': 'walter@thedude.io'
        }
        gud_mock.side_effect = [user_data_fxa, user_data]

        process_subhub_event_customer_created({
            'name': 'Walter Sobchak',
            'email': 'water@thedude.io',
            'user_id': '1234',
            'customer_id': 'cus_1234',
        })

        sfdc_mock.update.assert_has_calls([
            call(user_data_fxa, {
                'fxa_id': 'DUPE:1234',
                'fxa_deleted': True,
            }),
            call(user_data, {
                'fxa_id': '1234',
                'payee_id': 'cus_1234',
                'last_name': 'Sobchak',
            })
        ])

    def test_customer_created_customer_fxa_found_no_match_no_other(self, sfdc_mock, gud_mock):
        """
        Contact found by FxA_ID and email does not match, and no other found by email
        """
        user_data_fxa = {
            'first_name': 'Jeffrey',
            'last_name': '_',
            'email': 'dude@thedude.io'
        }
        gud_mock.side_effect = [user_data_fxa, None]

        process_subhub_event_customer_created({
            'name': 'Walter Sobchak',
            'email': 'water@thedude.io',
            'user_id': '1234',
            'customer_id': 'cus_1234',
        })

        sfdc_mock.update.assert_called_once_with(user_data_fxa, {
            'fxa_id': 'DUPE:1234',
            'fxa_deleted': True,
        })
        sfdc_mock.add.assert_called_with({
            'fxa_id': '1234',
            'payee_id': 'cus_1234',
            'first_name': 'Walter',
            'last_name': 'Sobchak',
            'email': 'water@thedude.io',
        })

    def test_payment_failed(self, sfdc_mock, gud_mock):
        gud_mock.return_value = {'id': '1234'}

        data = {
            'event_id': 'the-event-id',
            'event_type': 'invoice.payment_failed',
            'customer_id': 'cus_1234',
            'amount_due': '1000',
            'created': '1566305505',
            'subscription_id': 'sub_123',
            'charge_id': '8675309',
            'nickname': 'bowling',
            'currency': 'us',
        }

        process_subhub_event_payment_failed(data)

        gud_mock.assert_called_with(payee_id=data['customer_id'], extra_fields=['id'])

        sfdc_mock.opportunity.create.assert_called_with({
            'Amount': 10.00,
            'CloseDate': '2019-08-20T12:51:45',
            'Donation_Contact__c': '1234',
            'Event_Id__c': data['event_id'],
            'Event_Name__c': data['event_type'],
            'Name': 'Subscription Services',
            'PMT_Subscription_ID__c': data['subscription_id'],
            'PMT_Transaction_ID__c': data['charge_id'],
            'Payment_Source__c': 'Stripe',
            'RecordTypeId': settings.SUBHUB_OPP_RECORD_TYPE,
            'Service_Plan__c': data['nickname'],
            'StageName': 'Payment Failed',
            'currency__c': data['currency'],
        })

    def test_subscription_cancel(self, sfdc_mock, gud_mock):
        gud_mock.return_value = {'id': '1234'}

        data = {
            'event_id': 'the-event-id',
            'event_type': 'customer.subscription_cancelled',
            'customer_id': 'cus_1234',
            'plan_amount': '1000',
            'current_period_end': '1566305505',
            'current_period_start': '1566305502',
            'cancel_at': '1566305509',
            'subscription_id': 'sub_123',
            'nickname': 'bowling',
        }

        process_subhub_event_subscription_cancel(data)

        gud_mock.assert_called_with(payee_id=data['customer_id'], extra_fields=['id'])

        sfdc_mock.opportunity.create.assert_called_with({
            'Amount': 10.00,
            'Billing_Cycle_End__c': '2019-08-20T12:51:45',
            'Billing_Cycle_Start__c': '2019-08-20T12:51:42',
            'CloseDate': '2019-08-20T12:51:49',
            'Donation_Contact__c': '1234',
            'Event_Id__c': data['event_id'],
            'Event_Name__c': data['event_type'],
            'Name': 'Subscription Services',
            'Payment_Source__c': 'Stripe',
            'PMT_Subscription_ID__c': data['subscription_id'],
            'RecordTypeId': settings.SUBHUB_OPP_RECORD_TYPE,
            'Service_Plan__c': data['nickname'],
            'StageName': 'Subscription Canceled',
        })

    def test_subscription_cancel_list_nickname(self, sfdc_mock, gud_mock):
        gud_mock.return_value = {'id': '1234'}

        data = {
            'event_id': 'the-event-id',
            'event_type': 'customer.subscription_cancelled',
            'customer_id': 'cus_1234',
            'plan_amount': '1000',
            'current_period_end': '1566305505',
            'current_period_start': '1566305502',
            'cancel_at': '1566305509',
            'subscription_id': 'sub_123',
            'nickname': ['bowling', 'golfing'],
        }

        process_subhub_event_subscription_cancel(data)

        gud_mock.assert_called_with(payee_id=data['customer_id'], extra_fields=['id'])

        sfdc_mock.opportunity.create.assert_called_with({
            'Amount': 10.00,
            'Billing_Cycle_End__c': '2019-08-20T12:51:45',
            'Billing_Cycle_Start__c': '2019-08-20T12:51:42',
            'CloseDate': '2019-08-20T12:51:49',
            'Donation_Contact__c': '1234',
            'Event_Id__c': data['event_id'],
            'Event_Name__c': data['event_type'],
            'Name': 'Subscription Services',
            'Payment_Source__c': 'Stripe',
            'PMT_Subscription_ID__c': data['subscription_id'],
            'RecordTypeId': settings.SUBHUB_OPP_RECORD_TYPE,
            'Service_Plan__c': data['nickname'][0],
            'StageName': 'Subscription Canceled',
        })

    def test_subscription_cancel_empty_list_nickname(self, sfdc_mock, gud_mock):
        gud_mock.return_value = {'id': '1234'}

        data = {
            'event_id': 'the-event-id',
            'event_type': 'customer.subscription_cancelled',
            'customer_id': 'cus_1234',
            'plan_amount': '1000',
            'current_period_end': '1566305505',
            'current_period_start': '1566305502',
            'cancel_at': '1566305509',
            'subscription_id': 'sub_123',
            'nickname': [],
        }

        process_subhub_event_subscription_cancel(data)

        gud_mock.assert_called_with(payee_id=data['customer_id'], extra_fields=['id'])

        sfdc_mock.opportunity.create.assert_called_with({
            'Amount': 10.00,
            'Billing_Cycle_End__c': '2019-08-20T12:51:45',
            'Billing_Cycle_Start__c': '2019-08-20T12:51:42',
            'CloseDate': '2019-08-20T12:51:49',
            'Donation_Contact__c': '1234',
            'Event_Id__c': data['event_id'],
            'Event_Name__c': data['event_type'],
            'Name': 'Subscription Services',
            'Payment_Source__c': 'Stripe',
            'PMT_Subscription_ID__c': data['subscription_id'],
            'RecordTypeId': settings.SUBHUB_OPP_RECORD_TYPE,
            'Service_Plan__c': '',
            'StageName': 'Subscription Canceled',
        })

    def test_subscription_charge_initial(self, sfdc_mock, gud_mock):
        gud_mock.return_value = {'id': '1234'}

        data = self.charge_data.copy()
        data['event_type'] = 'customer.subscription.created'

        process_subhub_event_subscription_charge(data)

        gud_mock.assert_called_with(payee_id=data['customer_id'], extra_fields=['id'])

        sfdc_mock.opportunity.upsert.assert_called_with('PMT_Invoice_ID__c/inv_abc123', {
            'Amount': 10.00,
            'Billing_Cycle_End__c': '2019-08-20T12:51:45',
            'Billing_Cycle_Start__c': '2019-08-20T12:51:42',
            'CloseDate': '2019-08-20T12:51:49',
            'Credit_Card_Type__c': data['brand'],
            'currency__c': data['currency'],
            'Donation_Contact__c': '1234',
            'Event_Id__c': data['event_id'],
            'Event_Name__c': data['event_type'],
            'Initial_Purchase__c': True,
            'Invoice_Number__c': data['invoice_number'],
            'Last_4_Digits__c': data['last4'],
            'Name': 'Subscription Services',
            'Next_Invoice_Date__c': '2019-08-20T12:53:25',
            'Payment_Source__c': 'Stripe',
            'PMT_Subscription_ID__c': data['subscription_id'],
            'PMT_Transaction_ID__c': data['charge'],
            'RecordTypeId': settings.SUBHUB_OPP_RECORD_TYPE,
            'Service_Plan__c': data['nickname'],
            'StageName': 'Closed Won',
        })

    def test_subscription_charge_recurring(self, sfdc_mock, gud_mock):
        gud_mock.return_value = {'id': '1234'}

        data = self.charge_data.copy()
        data.update({
            'event_type': 'customer.recurring_charge',
            'proration_amount': 250,
            'total_amount': 350,
        })

        process_subhub_event_subscription_charge(data)

        gud_mock.assert_called_with(payee_id=data['customer_id'], extra_fields=['id'])

        sfdc_mock.opportunity.upsert.assert_called_with('PMT_Invoice_ID__c/inv_abc123', {
            'Amount': 10.00,
            'Billing_Cycle_End__c': '2019-08-20T12:51:45',
            'Billing_Cycle_Start__c': '2019-08-20T12:51:42',
            'CloseDate': '2019-08-20T12:51:49',
            'Credit_Card_Type__c': data['brand'],
            'currency__c': data['currency'],
            'Donation_Contact__c': '1234',
            'Event_Id__c': data['event_id'],
            'Event_Name__c': data['event_type'],
            'Initial_Purchase__c': False,
            'Invoice_Number__c': data['invoice_number'],
            'Last_4_Digits__c': data['last4'],
            'Name': 'Subscription Services',
            'Next_Invoice_Date__c': '2019-08-20T12:53:25',
            'Payment_Source__c': 'Stripe',
            'PMT_Subscription_ID__c': data['subscription_id'],
            'PMT_Transaction_ID__c': data['charge'],
            'Proration_Amount__c': 2.5,
            'RecordTypeId': settings.SUBHUB_OPP_RECORD_TYPE,
            'Service_Plan__c': data['nickname'],
            'StageName': 'Closed Won',
            'Total_Amount__c': 3.5,
        })


@override_settings(TASK_LOCKING_ENABLE=False)
@patch('basket.news.tasks.get_user_data')
@patch('basket.news.tasks.sfdc')
class ProcessDonationTests(TestCase):
    donate_data = {
        'created': 1479746809.327,
        'locale': 'pt-BR',
        'currency': 'USD',
        'donation_amount': '75.00',
        'transaction_fee': 0.42,
        'net_amount': 75.42,
        'conversion_amount': 42.75,
        'last_4': '5309',
        'email': 'dude@example.com',
        'first_name': 'Jeffery',
        'last_name': 'Lebowski',
        'project': 'mozillafoundation',
        'source_url': 'https://example.com/donate',
        'recurring': True,
        'service': 'paypal',
        'transaction_id': 'NLEKFRBED3BQ614797468093.25',
        'campaign_id': 'were-you-listening-to-the-dudes-story',
    }

    def test_one_name(self, sfdc_mock, gud_mock):
        data = self.donate_data.copy()
        gud_mock.return_value = {
            'id': '1234',
            'first_name': '',
            'last_name': '_',
        }
        del data['first_name']
        data['last_name'] = 'Donnie'
        process_donation(data)
        sfdc_mock.update.assert_called_with(gud_mock(), {
            '_set_subscriber': False,
            'last_name': 'Donnie',
        })

    def test_name_splitting(self, sfdc_mock, gud_mock):
        data = self.donate_data.copy()
        gud_mock.return_value = None
        del data['first_name']
        data['last_name'] = 'Theodore Donald Kerabatsos'
        process_donation(data)
        sfdc_mock.add.assert_called_with({
            '_set_subscriber': False,
            'token': ANY,
            'record_type': ANY,
            'email': 'dude@example.com',
            'first_name': 'Theodore Donald',
            'last_name': 'Kerabatsos',
        })

    def test_name_empty(self, sfdc_mock, gud_mock):
        """Should be okay if only last_name is provided and is just spaces.

        https://github.com/mozmeao/basket/issues/45
        """
        data = self.donate_data.copy()
        gud_mock.return_value = None
        del data['first_name']
        data['last_name'] = '  '
        process_donation(data)
        sfdc_mock.add.assert_called_with({
            '_set_subscriber': False,
            'token': ANY,
            'record_type': ANY,
            'email': 'dude@example.com',
        })

    def test_name_none(self, sfdc_mock, gud_mock):
        """Should be okay if only last_name is provided and is None.

        https://sentry.prod.mozaws.net/operations/basket-prod/issues/683973/
        """
        data = self.donate_data.copy()
        gud_mock.return_value = None
        del data['first_name']
        data['last_name'] = None
        process_donation(data)
        sfdc_mock.add.assert_called_with({
            '_set_subscriber': False,
            'token': ANY,
            'record_type': ANY,
            'email': 'dude@example.com',
        })

    def test_only_update_contact_if_modified(self, sfdc_mock, gud_mock):
        data = self.donate_data.copy()
        gud_mock.return_value = {
            'id': '1234',
            'first_name': '',
            'last_name': '_',
        }
        process_donation(data)
        sfdc_mock.update.assert_called_with(gud_mock(), {
            '_set_subscriber': False,
            'first_name': 'Jeffery',
            'last_name': 'Lebowski',
        })

        sfdc_mock.reset_mock()
        data = self.donate_data.copy()
        gud_mock.return_value = {
            'id': '1234',
            'first_name': 'Jeffery',
            'last_name': 'Lebowski',
        }
        process_donation(data)
        sfdc_mock.update.assert_not_called()

    def test_donation_data(self, sfdc_mock, gud_mock):
        data = self.donate_data.copy()
        gud_mock.return_value = {
            'id': '1234',
            'first_name': 'Jeffery',
            'last_name': 'Lebowski',
        }
        process_donation(data)
        sfdc_mock.opportunity.create.assert_called_with({
            'RecordTypeId': ANY,
            'Name': 'Foundation Donation',
            'Donation_Contact__c': '1234',
            'StageName': 'Closed Won',
            # calculated from data['created']
            'CloseDate': '2016-11-21T16:46:49.327000',
            'Amount': float(data['donation_amount']),
            'Currency__c': 'USD',
            'Payment_Source__c': 'paypal',
            'PMT_Transaction_ID__c': data['transaction_id'],
            'Payment_Type__c': 'Recurring',
            'SourceURL__c': data['source_url'],
            'Project__c': data['project'],
            'Donation_Locale__c': data['locale'],
            'Processors_Fee__c': data['transaction_fee'],
            'Net_Amount__c': data['net_amount'],
            'Conversion_Amount__c': data['conversion_amount'],
            'Last_4_Digits__c': data['last_4'],
            'CampaignId': data['campaign_id'],
        })

    def test_donation_data_optional_null(self, sfdc_mock, gud_mock):
        """Having a `None` in an optional field used to throw a TypeError.

        https://github.com/mozmeao/basket/issues/366
        """
        data = self.donate_data.copy()
        data['subscription_id'] = None
        gud_mock.return_value = {
            'id': '1234',
            'first_name': 'Jeffery',
            'last_name': 'Lebowski',
        }
        process_donation(data)
        sfdc_mock.opportunity.create.assert_called_with({
            'RecordTypeId': ANY,
            'Name': 'Foundation Donation',
            'Donation_Contact__c': '1234',
            'StageName': 'Closed Won',
            # calculated from data['created']
            'CloseDate': '2016-11-21T16:46:49.327000',
            'Amount': float(data['donation_amount']),
            'Currency__c': 'USD',
            'Payment_Source__c': 'paypal',
            'PMT_Transaction_ID__c': data['transaction_id'],
            'Payment_Type__c': 'Recurring',
            'SourceURL__c': data['source_url'],
            'Project__c': data['project'],
            'Donation_Locale__c': data['locale'],
            'Processors_Fee__c': data['transaction_fee'],
            'Net_Amount__c': data['net_amount'],
            'Conversion_Amount__c': data['conversion_amount'],
            'Last_4_Digits__c': data['last_4'],
            'CampaignId': data['campaign_id'],
        })

    def test_donation_silent_failure_on_dupe(self, sfdc_mock, gud_mock):
        data = self.donate_data.copy()
        gud_mock.return_value = {
            'id': '1234',
            'first_name': 'Jeffery',
            'last_name': 'Lebowski',
        }
        error_content = [{
            'errorCode': 'DUPLICATE_VALUE',
            'fields': [],
            'message': 'duplicate value found: PMT_Transaction_ID__c '
                       'duplicates value on record with id: blah-blah',
        }]
        exc = sfapi.SalesforceMalformedRequest('url', 400, 'opportunity', error_content)
        sfdc_mock.opportunity.create.side_effect = exc
        process_donation(data)

    def test_donation_normal_failure_not_dupe(self, sfdc_mock, gud_mock):
        data = self.donate_data.copy()
        gud_mock.return_value = {
            'id': '1234',
            'first_name': 'Jeffery',
            'last_name': 'Lebowski',
        }
        error_content = [{
            'errorCode': 'OTHER_ERROR',
            'fields': [],
            'message': 'Some other non-dupe problem',
        }]
        exc = sfapi.SalesforceMalformedRequest('url', 400, 'opportunity', error_content)
        sfdc_mock.opportunity.create.side_effect = exc
        with self.assertRaises(Retry):
            process_donation(data)


@override_settings(TASK_LOCKING_ENABLE=True)
class TaskDuplicationLockingTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_locks_work(self):
        """Calling get_lock more than once quickly with the same key should be locked"""
        get_lock('dude@example.com')
        with self.assertRaises(RetryTask):
            get_lock('dude@example.com')

    def test_lock_prefix_works(self):
        """Should allow same key to not lock other prefixes"""
        get_lock('dude@example.com', prefix='malibu')
        get_lock('dude@example.com', prefix='in-n-out')
        with self.assertRaises(RetryTask):
            get_lock('dude@example.com', prefix='malibu')

    @patch('basket.news.tasks.cache')
    def test_locks_do_not_leak_info(self, cache_mock):
        """Should not use plaintext key in lock name"""
        email = 'donny@example.com'
        cache_mock.add.return_value = True
        get_lock(email)
        key = cache_mock.add.call_args[0][0]
        self.assertNotIn(email, key)


class FailedTaskTest(TestCase):
    """Test that failed tasks are logged in our FailedTask table"""

    @patch('basket.news.tasks.sfmc')
    def test_failed_task_logging(self, mock_sfmc):
        """Failed task is logged in FailedTask table"""
        mock_sfmc.send_mail.side_effect = Exception("Test exception")
        self.assertEqual(0, FailedTask.objects.count())
        args = ['msg_id', 'you@example.com', 'SFDCID']
        kwargs = {'token': 3}
        result = send_message.apply(args=args, kwargs=kwargs)
        fail = FailedTask.objects.get()
        self.assertEqual('news.tasks.send_message', fail.name)
        self.assertEqual(result.task_id, fail.task_id)
        self.assertEqual(args, fail.args)
        self.assertEqual(kwargs, fail.kwargs)
        self.assertEqual("Exception('Test exception')", fail.exc)
        self.assertIn("Exception: Test exception", fail.einfo)


class RetryTaskTest(TestCase):
    """Test that we can retry a task"""
    @patch('django.contrib.messages.info', autospec=True)
    def test_retry_task(self, info):
        TASK_NAME = 'news.tasks.update_phonebook'
        failed_task = FailedTask(name=TASK_NAME,
                                 task_id=4,
                                 args=[1, 2],
                                 kwargs={'token': 3},
                                 exc='',
                                 einfo='')
        # Failed task is deleted after queuing, but that only works on records
        # that have been saved, so just mock that and check later that it was
        # called.
        failed_task.delete = Mock(spec=failed_task.delete)
        with patch.object(celery_app, 'send_task') as send_task_mock:
            # Let's retry.
            failed_task.retry()
        # Task was submitted again
        send_task_mock.assert_called_with(TASK_NAME, args=[1, 2], kwargs={'token': 3})
        # Previous failed task was deleted
        self.assertTrue(failed_task.delete.called)


@patch('basket.news.tasks.send_message', autospec=True)
@patch('basket.news.tasks.get_user_data', autospec=True)
class RecoveryMessageTask(TestCase):
    def setUp(self):
        self.email = "dude@example.com"

    def test_unknown_email(self, mock_look_for_user, mock_send):
        """Email not in basket or ET"""
        # Should log error and return
        mock_look_for_user.return_value = None
        send_recovery_message_task(self.email)
        self.assertFalse(mock_send.called)

    def test_et_error(self, mock_look_for_user, mock_send):
        """Error talking to Basket. I'm shocked, SHOCKED!"""
        mock_look_for_user.side_effect = NewsletterException('ET has failed to achieve.')

        with self.assertRaises(Retry):
            send_recovery_message_task(self.email)

        self.assertFalse(mock_send.called)

    @override_settings(RECOVER_MSG_LANGS=['fr'])
    def test_email_in_et(self, mock_look_for_user, mock_send):
        """Email not in basket but in ET"""
        # Should trigger message. We can follow the user's format and lang pref
        format = 'T'
        lang = 'fr'
        mock_look_for_user.return_value = {
            'id': 'SFDCID',
            'status': 'ok',
            'email': self.email,
            'format': format,
            'country': '',
            'lang': lang,
            'token': 'USERTOKEN',
            'newsletters': [],
        }
        send_recovery_message_task(self.email)
        message_id = mogrify_message_id(RECOVERY_MESSAGE_ID, lang, format)
        mock_send.delay.assert_called_with(message_id, self.email, 'SFDCID',
                                           token='USERTOKEN')

    @override_settings(RECOVER_MSG_LANGS=['en'])
    def test_lang_not_available(self, mock_look_for_user, mock_send):
        """Language not available for recover message"""
        # Should trigger message in english if not available in user lang
        format = 'T'
        mock_look_for_user.return_value = {
            'id': 'SFDCID',
            'status': 'ok',
            'email': self.email,
            'format': format,
            'country': '',
            'lang': 'fr',
            'token': 'USERTOKEN',
            'newsletters': [],
        }
        send_recovery_message_task(self.email)
        message_id = mogrify_message_id(RECOVERY_MESSAGE_ID, 'en', format)
        mock_send.delay.assert_called_with(message_id, self.email, 'SFDCID',
                                           token='USERTOKEN')


@override_settings(ET_CLIENT_ID='client_id', ET_CLIENT_SECRET='client_secret')
class AddSMSUserTests(TestCase):
    def setUp(self):
        clear_sms_cache()
        patcher = patch('basket.news.backends.sfmc.sfmc.send_sms')
        self.send_sms = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch('basket.news.tasks.get_sms_vendor_id')
        self.get_sms_vendor_id = patcher.start()
        self.get_sms_vendor_id.return_value = 'bar'
        self.addCleanup(patcher.stop)

    def test_send_name_invalid(self):
        """If the send_name is invalid, return immediately."""
        self.get_sms_vendor_id.return_value = None
        add_sms_user('baffle', '8675309', False)
        self.send_sms.assert_not_called()

    def test_success(self):
        add_sms_user('foo', '8675309', False)
        self.send_sms.assert_called_with('8675309', 'bar')

    def test_success_with_vendor_id(self):
        add_sms_user('foo', '8675309', False, vendor_id='foo')
        self.send_sms.assert_called_with('8675309', 'foo')
        self.get_sms_vendor_id.assert_not_called()

    def test_success_with_optin(self):
        """
        If optin is True, add a Mobile_Subscribers record for the
        number.
        """
        with patch('basket.news.tasks.sfmc') as sfmc_mock:
            add_sms_user('foo', '8675309', True)

            sfmc_mock.add_row.assert_called_with('Mobile_Subscribers', {
                'Phone': '8675309',
                'SubscriberKey': '8675309',
            })


class ETTaskTests(TestCase):
    @patch('basket.news.tasks.exponential_backoff')
    def test_retry_increase(self, mock_backoff):
        """
        The delay for retrying a task should increase geometrically by a
        power of 2. I really hope I said that correctly.
        """
        error = URLError(reason=Exception('foo bar!'))

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


class AddFxaActivityTests(TestCase):
    def _base_test(self, user_agent=False, fxa_id='123', first_device=True):
        if not user_agent:
            user_agent = 'Mozilla/5.0 (Windows NT 6.1; rv:10.0) Gecko/20100101 Firefox/10.0'

        data = {
            'fxa_id': fxa_id,
            'first_device': first_device,
            'user_agent': user_agent,
            'service': 'sync',
        }

        with patch('basket.news.tasks.apply_updates') as apply_updates_mock:
            _add_fxa_activity(data)
        record = apply_updates_mock.call_args[0][1]
        return record

    def test_login_date(self):
        with patch('basket.news.tasks.gmttime') as gmttime_mock:
            gmttime_mock.return_value = 'this is time'
            record = self._base_test()
        self.assertEqual(record['LOGIN_DATE'], 'this is time')

    def test_first_device(self):
        record = self._base_test(first_device=True)
        self.assertEqual(record['FIRST_DEVICE'], 'y')

        record = self._base_test(first_device=False)
        self.assertEqual(record['FIRST_DEVICE'], 'n')

    def test_fxa_id(self):
        record = self._base_test(fxa_id='This is id')
        self.assertEqual(record['FXA_ID'], 'This is id')

    def test_windows(self):
        ua = 'Mozilla/5.0 (Windows NT 6.1; rv:10.0) Gecko/20100101 Firefox/10.0'
        record = self._base_test(ua)
        self.assertEqual(record['OS'], 'Windows')
        self.assertEqual(record['OS_VERSION'], '7')  # Not sure if we expect '7' here.
        self.assertEqual(record['BROWSER'], 'Firefox 10.0')
        self.assertEqual(record['DEVICE_NAME'], 'Other')
        self.assertEqual(record['DEVICE_TYPE'], 'D')

    def test_mac(self):
        ua = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.6; rv:10.0) Gecko/20100101 Firefox/30.2'
        record = self._base_test(ua)
        self.assertEqual(record['OS'], 'Mac OS X')
        self.assertEqual(record['OS_VERSION'], '10.6')
        self.assertEqual(record['BROWSER'], 'Firefox 30.2')
        self.assertEqual(record['DEVICE_NAME'], 'Mac')
        self.assertEqual(record['DEVICE_TYPE'], 'D')

    def test_linux(self):
        ua = 'Mozilla/5.0 (X11; Linux i686 on x86_64; rv:10.0) Gecko/20100101 Firefox/42.0'
        record = self._base_test(ua)
        self.assertEqual(record['OS'], 'Linux')
        self.assertEqual(record['OS_VERSION'], '')
        self.assertEqual(record['BROWSER'], 'Firefox 42.0')
        self.assertEqual(record['DEVICE_NAME'], 'Other')
        self.assertEqual(record['DEVICE_TYPE'], 'D')

    def test_android_phone_below_version_41(self):
        ua = 'Mozilla/5.0 (Android; Mobile; rv:40.0) Gecko/40.0 Firefox/40.0'
        record = self._base_test(ua)
        self.assertEqual(record['OS'], 'Android')
        self.assertEqual(record['OS_VERSION'], '')
        self.assertEqual(record['BROWSER'], 'Firefox Mobile 40.0')
        self.assertEqual(record['DEVICE_NAME'], 'Generic Smartphone')
        self.assertEqual(record['DEVICE_TYPE'], 'M')

    def test_android_tablet_below_version_41(self):
        ua = 'Mozilla/5.0 (Android; Tablet; rv:40.0) Gecko/40.0 Firefox/40.0'
        record = self._base_test(ua)
        self.assertEqual(record['OS'], 'Android')
        self.assertEqual(record['OS_VERSION'], '')
        self.assertEqual(record['BROWSER'], 'Firefox Mobile 40.0')
        self.assertEqual(record['DEVICE_NAME'], 'Generic Tablet')

    def test_android_phone_from_version_41(self):
        ua = 'Mozilla/5.0 (Android 4.4; Mobile; rv:41.0) Gecko/41.0 Firefox/41.0'
        record = self._base_test(ua)
        self.assertEqual(record['OS'], 'Android')
        self.assertEqual(record['OS_VERSION'], '4.4')
        self.assertEqual(record['BROWSER'], 'Firefox Mobile 41.0')
        self.assertEqual(record['DEVICE_NAME'], 'Generic Smartphone')
        self.assertEqual(record['DEVICE_TYPE'], 'M')

    def test_android_tablet_from_version_41(self):
        ua = 'Mozilla/5.0 (Android 5.0; Tablet; rv:41.0) Gecko/41.0 Firefox/41.0'
        record = self._base_test(ua)
        self.assertEqual(record['OS'], 'Android')
        self.assertEqual(record['OS_VERSION'], '5.0')
        self.assertEqual(record['BROWSER'], 'Firefox Mobile 41.0')
        self.assertEqual(record['DEVICE_NAME'], 'Generic Tablet')

    def test_firefox_ios_iphone(self):
        ua = 'Mozilla/5.0 (iPhone; CPU iPhone OS 8_3 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) FxiOS/1.0 Mobile/12F69 Safari/600.1.4'
        record = self._base_test(ua)
        self.assertEqual(record['OS'], 'iOS')
        self.assertEqual(record['OS_VERSION'], '8.3')
        self.assertEqual(record['BROWSER'], 'Firefox iOS 1.0')
        self.assertEqual(record['DEVICE_NAME'], 'iPhone')
        self.assertEqual(record['DEVICE_TYPE'], 'M')

    def test_firefox_ios_tablet(self):
        ua = 'Mozilla/5.0 (iPad; CPU iPhone OS 8_3 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) FxiOS/1.0 Mobile/12F69 Safari/600.1.4'
        record = self._base_test(ua)
        self.assertEqual(record['OS'], 'iOS')
        self.assertEqual(record['OS_VERSION'], '8.3')
        self.assertEqual(record['BROWSER'], 'Firefox iOS 1.0')
        self.assertEqual(record['DEVICE_NAME'], 'iPad')
        self.assertEqual(record['DEVICE_TYPE'], 'T')


@override_settings(FXA_EVENTS_VERIFIED_SFDC_ENABLE=True,
                   FXA_REGISTER_NEWSLETTER='firefox-accounts-journey')
@patch('basket.news.tasks.get_best_language', Mock(return_value='en-US'))
@patch('basket.news.tasks.newsletter_languages', Mock(return_value=['en-US']))
@patch('basket.news.tasks.apply_updates')
@patch('basket.news.tasks.upsert_contact')
@patch('basket.news.tasks.get_fxa_user_data')
class FxAVerifiedTests(TestCase):
    def test_success(self, fxa_data_mock, upsert_mock, apply_mock):
        fxa_data_mock.return_value = {'lang': 'en-US'}
        data = {
            'email': 'thedude@example.com',
            'uid': 'the-fxa-id',
            'locale': 'en-US,en',
            'service': 'sync',
        }
        fxa_verified(data)
        upsert_mock.assert_called_with(SUBSCRIBE, {
            'email': data['email'],
            'newsletters': settings.FXA_REGISTER_NEWSLETTER,
            'source_url': settings.FXA_REGISTER_SOURCE_URL,
            'country': '',
            'fxa_lang': data['locale'],
            'fxa_service': 'sync',
            'fxa_id': 'the-fxa-id',
            'optin': True,
            'format': 'H',
        }, fxa_data_mock())
        apply_mock.assert_called_with('Firefox_Account_ID', {
            'EMAIL_ADDRESS_': data['email'],
            'CREATED_DATE_': ANY,
            'FXA_ID': 'the-fxa-id',
            'FXA_LANGUAGE_ISO2': 'en-US',
            'SERVICE': 'sync',
        })

    def test_with_newsletters(self, fxa_data_mock, upsert_mock, apply_mock):
        fxa_data_mock.return_value = None
        data = {
            'email': 'thedude@example.com',
            'uid': 'the-fxa-id',
            'locale': 'en-US,en',
            'newsletters': ['test-pilot', 'take-action-for-the-internet'],
            'service': 'sync',
        }
        fxa_verified(data)
        upsert_mock.assert_called_with(SUBSCRIBE, {
            'email': data['email'],
            'newsletters': 'test-pilot,take-action-for-the-internet,' + settings.FXA_REGISTER_NEWSLETTER,
            'source_url': settings.FXA_REGISTER_SOURCE_URL,
            'country': '',
            'lang': 'en-US',
            'fxa_lang': data['locale'],
            'fxa_service': 'sync',
            'fxa_id': 'the-fxa-id',
            'optin': True,
            'format': 'H',
        }, None)
        apply_mock.assert_called_with('Firefox_Account_ID', {
            'EMAIL_ADDRESS_': data['email'],
            'CREATED_DATE_': ANY,
            'FXA_ID': 'the-fxa-id',
            'FXA_LANGUAGE_ISO2': 'en-US',
            'SERVICE': 'sync',
        })

    def test_with_subscribe_and_metrics(self, fxa_data_mock, upsert_mock, apply_mock):
        fxa_data_mock.return_value = None
        data = {
            'email': 'thedude@example.com',
            'uid': 'the-fxa-id',
            'locale': 'en-US,en',
            'metricsContext': {
                'utm_campaign': 'bowling',
                'some_other_thing': 'Donnie',
            },
            'service': 'monitor',
            'countryCode': 'DE',
        }
        fxa_verified(data)
        upsert_mock.assert_called_with(SUBSCRIBE, {
            'email': data['email'],
            'newsletters': settings.FXA_REGISTER_NEWSLETTER,
            'source_url': settings.FXA_REGISTER_SOURCE_URL + '?utm_campaign=bowling',
            'country': 'DE',
            'lang': 'en-US',
            'fxa_lang': data['locale'],
            'fxa_service': 'monitor',
            'fxa_id': 'the-fxa-id',
            'optin': True,
            'format': 'H',
        }, None)
        apply_mock.assert_called_with('Firefox_Account_ID', {
            'EMAIL_ADDRESS_': data['email'],
            'CREATED_DATE_': ANY,
            'FXA_ID': 'the-fxa-id',
            'FXA_LANGUAGE_ISO2': 'en-US',
            'SERVICE': 'monitor',
        })

    def test_with_createDate(self, fxa_data_mock, upsert_mock, apply_mock):
        fxa_data_mock.return_value = None
        create_date = 1526996035.498
        data = {
            'createDate': create_date,
            'email': 'thedude@example.com',
            'uid': 'the-fxa-id',
            'locale': 'en-US,en'
        }
        fxa_verified(data)
        upsert_mock.assert_called_with(SUBSCRIBE, {
            'email': data['email'],
            'newsletters': settings.FXA_REGISTER_NEWSLETTER,
            'source_url': settings.FXA_REGISTER_SOURCE_URL,
            'country': '',
            'lang': 'en-US',
            'fxa_lang': data['locale'],
            'fxa_service': '',
            'fxa_id': 'the-fxa-id',
            'fxa_create_date': iso_format_unix_timestamp(create_date),
            'optin': True,
            'format': 'H',
        }, None)
        apply_mock.assert_called_with('Firefox_Account_ID', {
            'EMAIL_ADDRESS_': data['email'],
            'CREATED_DATE_': gmttime(datetime.fromtimestamp(create_date)),
            'FXA_ID': 'the-fxa-id',
            'FXA_LANGUAGE_ISO2': 'en-US',
            'SERVICE': '',
        })


@patch('basket.news.tasks.upsert_user')
@patch('basket.news.tasks._add_fxa_activity')
class FxALoginTests(TestCase):
    # based on real data pulled from the queue
    base_data = {
        'deviceCount': 2,
        'email': 'the.dude@example.com',
        'event': 'login',
        'metricsContext': {
            'device_id': 'phones-ringing-dude',
            'flowBeginTime': 1508897207639,
            'flowCompleteSignal': 'account.signed',
            'flowType': 'login',
            'flow_id': 'the-dude-goes-with-the-flow-man',
            'flow_time': 31568,
            'time': 1508897239207,
            'utm_campaign': 'fxa-embedded-form-fx',
            'utm_content': 'fx-56.0.1',
            'utm_medium': 'referral',
            'utm_source': 'firstrun_f131',
        },
        'service': 'sync',
        'ts': 1508897239.207,
        'uid': 'the-fxa-id-for-el-dudarino',
        'userAgent': 'Mozilla/5.0 (Windows NT 10.0; WOW64; rv:56.0) Gecko/20100101 Firefox/56.0',
        'countryCode': 'US',
    }

    def get_data(self):
        return deepcopy(self.base_data)

    def test_fxa_login_task_with_no_utm(self, afa_mock, upsert_mock):
        data = self.get_data()
        del data['metricsContext']
        data['deviceCount'] = 1
        fxa_login(data)
        afa_mock.assert_called_with({
            'user_agent': data['userAgent'],
            'fxa_id': data['uid'],
            'first_device': True,
            'service': 'sync',
        })
        upsert_mock.delay.assert_not_called()

    def test_fxa_login_task_with_utm_data(self, afa_mock, upsert_mock):
        data = self.get_data()
        fxa_login(data)
        afa_mock.assert_called_with({
            'user_agent': data['userAgent'],
            'fxa_id': data['uid'],
            'first_device': False,
            'service': 'sync',
        })
        upsert_mock.delay.assert_called_with(SUBSCRIBE, {
            'email': 'the.dude@example.com',
            'newsletters': settings.FXA_LOGIN_CAMPAIGNS['fxa-embedded-form-fx'],
            'source_url': ANY,
            'country': 'US',
        })
        source_url = upsert_mock.delay.call_args[0][1]['source_url']
        assert 'utm_campaign=fxa-embedded-form-fx' in source_url
        assert 'utm_content=fx-56.0.1' in source_url
        assert 'utm_medium=referral' in source_url
        assert 'utm_source=firstrun_f131' in source_url

    def test_fxa_login_task_with_utm_data_no_subscribe(self, afa_mock, upsert_mock):
        data = self.get_data()
        # not in the FXA_LOGIN_CAMPAIGNS setting
        data['metricsContext']['utm_campaign'] = 'nonesense'
        fxa_login(data)
        afa_mock.assert_called_with({
            'user_agent': data['userAgent'],
            'fxa_id': data['uid'],
            'first_device': False,
            'service': 'sync',
        })
        upsert_mock.delay.assert_not_called()


@patch('basket.news.tasks.sfmc')
@patch('basket.news.tasks.cache')
class FxAEmailChangedTests(TestCase):
    def test_timestamps_older_message(self, cache_mock, sfmc_mock):
        data = {
            'ts': 1234.567,
            'uid': 'the-fxa-id-for-el-dudarino',
            'email': 'the-dudes-new-email@example.com',
        }
        cache_mock.get.return_value = 1234.678
        # ts higher in cache, should no-op
        fxa_email_changed(data)
        sfmc_mock.upsert_row.assert_not_called()

    def test_timestamps_newer_message(self, cache_mock, sfmc_mock):
        data = {
            'ts': 1234.567,
            'uid': 'the-fxa-id-for-el-dudarino',
            'email': 'the-dudes-new-email@example.com',
        }
        cache_mock.get.return_value = 1234.456
        # ts higher in message, do the things
        fxa_email_changed(data)
        sfmc_mock.upsert_row.assert_called_with('FXA_EmailUpdated', {
            'FXA_ID': data['uid'],
            'NewEmailAddress': data['email'],
        })

    def test_timestamps_nothin_cached(self, cache_mock, sfmc_mock):
        data = {
            'ts': 1234.567,
            'uid': 'the-fxa-id-for-el-dudarino',
            'email': 'the-dudes-new-email@example.com',
        }
        cache_mock.get.return_value = 0
        fxa_email_changed(data)
        sfmc_mock.upsert_row.assert_called_with('FXA_EmailUpdated', {
            'FXA_ID': data['uid'],
            'NewEmailAddress': data['email'],
        })


class GmttimeTests(TestCase):
    @patch('basket.news.tasks.datetime')
    def test_no_basetime_provided(self, datetime_mock):
        # original time is 'Fri, 09 Sep 2016 13:33:55 GMT'
        datetime_mock.now.return_value = datetime.fromtimestamp(1473428035.498)
        formatted_time = gmttime()
        self.assertEqual(formatted_time, 'Fri, 09 Sep 2016 13:43:55 GMT')

    def test_basetime_provided(self):
        # original time is 'Fri, 09 Sep 2016 13:33:55 GMT', updates to 13:43:55
        basetime = datetime.fromtimestamp(1473428035.498)
        formatted_time = gmttime(basetime)
        self.assertEqual(formatted_time, 'Fri, 09 Sep 2016 13:43:55 GMT')


@patch('basket.news.tasks.sfdc')
@patch('basket.news.tasks.get_user_data')
class CommonVoiceGoalsTests(TestCase):
    def test_new_user(self, gud_mock, sfdc_mock):
        gud_mock.return_value = None
        data = {
            'email': 'dude@example.com',
            'first_contribution_date': '2018-06-27T14:56:58Z',
            'last_active_date': '2019-07-11T10:28:32Z',
            'two_day_streak': False,
        }
        orig_data = data.copy()
        record_common_voice_update(data)
        # ensure passed in dict was not modified in place.
        # if it is modified a retry will use the modified dict.
        assert orig_data == data
        sfdc_mock.add.assert_called_with({
            'email': 'dude@example.com',
            'token': ANY,
            'source_url': 'https://voice.mozilla.org',
            'newsletters': [settings.COMMON_VOICE_NEWSLETTER],
            'cv_first_contribution_date': '2018-06-27T14:56:58Z',
            'cv_last_active_date': '2019-07-11T10:28:32Z',
            'cv_two_day_streak': False,
        })

    def test_existing_user(self, gud_mock, sfdc_mock):
        gud_mock.return_value = {'id': 'the-duder'}
        data = {
            'email': 'dude@example.com',
            'first_contribution_date': '2018-06-27T14:56:58Z',
            'last_active_date': '2019-07-11T10:28:32Z',
            'two_day_streak': False,
        }
        orig_data = data.copy()
        record_common_voice_update(data)
        # ensure passed in dict was not modified in place.
        # if it is modified a retry will use the modified dict.
        assert orig_data == data
        sfdc_mock.update.assert_called_with(gud_mock(), {
            'source_url': 'https://voice.mozilla.org',
            'newsletters': [settings.COMMON_VOICE_NEWSLETTER],
            'cv_first_contribution_date': '2018-06-27T14:56:58Z',
            'cv_last_active_date': '2019-07-11T10:28:32Z',
            'cv_two_day_streak': False,
        })


@patch('basket.news.tasks.sfdc')
@patch('basket.news.tasks.upsert_amo_user_data')
class AMOSyncAddonTests(TestCase):
    def setUp(self):
        # test data from
        # https://addons-server.readthedocs.io/en/latest/topics/basket.html#example-data
        self.amo_data = {
            'authors': [
                {
                    'id': 12345,
                    'display_name': 'His Dudeness',
                    'email': 'dude@example.com',
                    'homepage': 'https://elduder.io',
                    'last_login': '2019-08-06T10:39:44Z',
                    'location': 'California, USA, Earth',
                    'deleted': False,
                },
                {
                    'display_name': 'serses',
                    'email': 'mozilla@virgule.net',
                    'homepage': '',
                    'id': 11263,
                    'last_login': '2019-08-06T10:39:44Z',
                    'location': '',
                    'deleted': False,
                },
            ],
            'average_daily_users': 0,
            'categories': {
                'firefox': ['games-entertainment'],
            },
            'current_version': {
                'compatibility': {
                    'firefox': {'max': '*', 'min': '48.0'},
                },
                'id': 35900,
                'is_strict_compatibility_enabled': False,
                'version': '2.0',
            },
            'default_locale': 'en-US',
            'guid': '{85ee4a2a-51b6-4f5e-a99c-6d9abcf6782d}',
            'id': 35896,
            'is_disabled': False,
            'is_recommended': False,
            'last_updated': '2019-06-26T11:38:13Z',
            'latest_unlisted_version': {
                'compatibility': {
                    'firefox': {
                        'max': '*',
                        'min': '48.0',
                    }
                },
                'id': 35899,
                'is_strict_compatibility_enabled': False,
                'version': '1.0',
            },
            'name': 'Ibird Jelewt Boartrica',
            'ratings': {
                'average': 4.1,
                'bayesian_average': 4.2,
                'count': 43,
                'text_count': 40,
            },
            'slug': 'ibird-jelewt-boartrica',
            'status': 'nominated',
            'type': 'extension',
        }
        self.users_data = [
            {
                'id': 'A1234',
                'amo_id': 12345,
                'email': 'the-dude@example.com'
            },
            {
                'id': 'A4321',
                'amo_id': 11263,
                'email': 'the-dude@example.com'
            },
        ]

    def test_update_addon(self, uaud_mock, sfdc_mock):
        uaud_mock.side_effect = self.users_data
        sfdc_mock.addon.get_by_custom_id.return_value = {'Id': 'B5678'}
        amo_sync_addon(self.amo_data)
        uaud_mock.assert_has_calls([call(self.amo_data['authors'][0]),
                                    call(self.amo_data['authors'][1])])
        sfdc_mock.addon.upsert.assert_called_with(f'AMO_AddOn_Id__c/{self.amo_data["id"]}', {
            'AMO_Category__c': 'firefox-games-entertainment',
            'AMO_Current_Version__c': '2.0',
            'AMO_Current_Version_Unlisted__c': '1.0',
            'AMO_Default_Language__c': 'en-US',
            'AMO_GUID__c': '{85ee4a2a-51b6-4f5e-a99c-6d9abcf6782d}',
            'AMO_Rating__c': 4.1,
            'AMO_Slug__c': 'ibird-jelewt-boartrica',
            'AMO_Status__c': 'nominated',
            'AMO_Type__c': 'extension',
            'AMO_Update__c': '2019-06-26T11:38:13Z',
            'Average_Daily_Users__c': 0,
            'Dev_Disabled__c': 'No',
            'Name': 'Ibird Jelewt Boartrica',
        })
        sfdc_mock.dev_addon.upsert.assert_has_calls([
            call('ConcatenateAMOID__c/12345-35896', {
                'AMO_AddOn_ID__c': 'B5678',
                'AMO_Contact_ID__c': 'A1234',
            }),
            call('ConcatenateAMOID__c/11263-35896', {
                'AMO_AddOn_ID__c': 'B5678',
                'AMO_Contact_ID__c': 'A4321',
            })
        ])

    def test_null_values(self, uaud_mock, sfdc_mock):
        uaud_mock.side_effect = self.users_data
        sfdc_mock.addon.get_by_custom_id.return_value = {'Id': 'B5678'}
        self.amo_data['current_version'] = None
        self.amo_data['latest_unlisted_version'] = None
        amo_sync_addon(self.amo_data)
        uaud_mock.assert_has_calls([call(self.amo_data['authors'][0]),
                                    call(self.amo_data['authors'][1])])
        sfdc_mock.addon.upsert.assert_called_with(f'AMO_AddOn_Id__c/{self.amo_data["id"]}', {
            'AMO_Category__c': 'firefox-games-entertainment',
            'AMO_Default_Language__c': 'en-US',
            'AMO_GUID__c': '{85ee4a2a-51b6-4f5e-a99c-6d9abcf6782d}',
            'AMO_Rating__c': 4.1,
            'AMO_Slug__c': 'ibird-jelewt-boartrica',
            'AMO_Status__c': 'nominated',
            'AMO_Type__c': 'extension',
            'AMO_Update__c': '2019-06-26T11:38:13Z',
            'Average_Daily_Users__c': 0,
            'Dev_Disabled__c': 'No',
            'Name': 'Ibird Jelewt Boartrica',
            'AMO_Current_Version__c': '',
            'AMO_Current_Version_Unlisted__c': '',
        })
        sfdc_mock.dev_addon.upsert.assert_has_calls([
            call('ConcatenateAMOID__c/12345-35896', {
                'AMO_AddOn_ID__c': 'B5678',
                'AMO_Contact_ID__c': 'A1234',
            }),
            call('ConcatenateAMOID__c/11263-35896', {
                'AMO_AddOn_ID__c': 'B5678',
                'AMO_Contact_ID__c': 'A4321',
            })
        ])


@patch('basket.news.tasks.sfdc')
@patch('basket.news.tasks.get_user_data')
class AMOSyncUserTests(TestCase):
    def setUp(self):
        self.amo_data = {
            'id': 1234,
            'display_name': 'His Dudeness',
            'email': 'dude@example.com',
            'homepage': 'https://elduder.io',
            'last_login': '2019-08-06T10:39:44Z',
            'location': 'California, USA, Earth',
            'deleted': False,
        }
        self.user_data = {
            'id': 'A1234',
            'amo_id': 1234,
            'email': 'the-dude@example.com'
        }

    def test_existing_user_with_amo_id(self, gud_mock, sfdc_mock):
        gud_mock.return_value = self.user_data
        amo_sync_user(self.amo_data)
        # does not include email or amo_id
        sfdc_mock.update.assert_called_with(self.user_data, {
            'amo_display_name': 'His Dudeness',
            'amo_homepage': 'https://elduder.io',
            'amo_last_login': '2019-08-06T10:39:44Z',
            'amo_location': 'California, USA, Earth',
            'amo_user': True,
        })

    def test_existing_user_no_amo_id(self, gud_mock, sfdc_mock):
        gud_mock.side_effect = [None, self.user_data]
        amo_sync_user(self.amo_data)
        # does not include email
        sfdc_mock.update.assert_called_with(self.user_data, {
            'amo_id': 1234,
            'amo_display_name': 'His Dudeness',
            'amo_homepage': 'https://elduder.io',
            'amo_last_login': '2019-08-06T10:39:44Z',
            'amo_location': 'California, USA, Earth',
            'amo_user': True,
        })

    def test_new_user(self, gud_mock, sfdc_mock):
        gud_mock.return_value = None
        amo_sync_user(self.amo_data)
        sfdc_mock.update.assert_not_called()
        # includes email and amo_id
        sfdc_mock.add.assert_called_with({
            'email': 'dude@example.com',
            'amo_id': 1234,
            'amo_display_name': 'His Dudeness',
            'amo_homepage': 'https://elduder.io',
            'amo_last_login': '2019-08-06T10:39:44Z',
            'amo_location': 'California, USA, Earth',
            'source_url': 'https://addons.mozilla.org/',
            'amo_user': True,
        })

    def test_deleted_user(self, gud_mock, sfdc_mock):
        self.amo_data['deleted'] = True
        gud_mock.return_value = self.user_data
        amo_sync_user(self.amo_data)
        # does not include email or amo_id
        sfdc_mock.update.assert_called_with(self.user_data, {
            'amo_display_name': 'His Dudeness',
            'amo_homepage': 'https://elduder.io',
            'amo_last_login': '2019-08-06T10:39:44Z',
            'amo_location': 'California, USA, Earth',
            'amo_user': False,
        })

    def test_null_values(self, gud_mock, sfdc_mock):
        gud_mock.return_value = None
        self.amo_data['display_name'] = None
        self.amo_data['last_login'] = None
        self.amo_data['location'] = None
        amo_sync_user(self.amo_data)
        sfdc_mock.add.assert_called_with({
            'email': 'dude@example.com',
            'amo_id': 1234,
            'amo_homepage': 'https://elduder.io',
            'source_url': 'https://addons.mozilla.org/',
            'amo_user': True,
        })


@override_settings(COMMON_VOICE_BATCH_PROCESSING=True,
                   COMMON_VOICE_BATCH_CHUNK_SIZE=5)
@patch('basket.news.tasks.record_common_voice_update')
class TestCommonVoiceBatch(TestCase):
    def setUp(self):
        CommonVoiceUpdate.objects.create(
            data={'email': 'dude@example.com', 'last_active_date': '2020-02-18T14:52:30Z'}
        )
        CommonVoiceUpdate.objects.create(
            data={'email': 'dude@example.com', 'last_active_date': '2020-02-17T14:52:30Z'}
        )
        CommonVoiceUpdate.objects.create(
            data={'email': 'dude@example.com', 'last_active_date': '2020-02-16T14:52:30Z'}
        )
        CommonVoiceUpdate.objects.create(
            data={'email': 'donny@example.com', 'last_active_date': '2020-02-15T14:52:30Z'}
        )
        CommonVoiceUpdate.objects.create(
            data={'email': 'donny@example.com', 'last_active_date': '2020-02-14T14:52:30Z'}
        )

    def test_batch(self, mock_rcvg):
        assert CommonVoiceUpdate.objects.filter(ack=False).count() == 5
        assert CommonVoiceUpdate.objects.filter(ack=True).count() == 0
        process_common_voice_batch()
        assert CommonVoiceUpdate.objects.filter(ack=False).count() == 0
        assert CommonVoiceUpdate.objects.filter(ack=True).count() == 5
        assert mock_rcvg.delay.call_count == 2
        assert mock_rcvg.delay.has_calls([
            call({'email': 'dude@example.com', 'last_active_date': '2020-02-18T14:52:30Z'}),
            call({'email': 'donny@example.com', 'last_active_date': '2020-02-15T14:52:30Z'})
        ])

    def test_batch_cleanup(self, mock_rcvg):
        CommonVoiceUpdate.objects.update(ack=True, when=now() - timedelta(hours=25))
        assert CommonVoiceUpdate.objects.count() == 5
        process_common_voice_batch()
        assert CommonVoiceUpdate.objects.count() == 0

    def test_batch_chunking(self, mock_rcvg):
        obj = CommonVoiceUpdate.objects.create(
            data={'email': 'dude@example.com', 'last_active_date': '2020-02-19T14:52:30Z'}
        )
        CommonVoiceUpdate.objects.create(
            data={'email': 'dude@example.com', 'last_active_date': '2020-02-19T14:53:30Z'}
        )
        CommonVoiceUpdate.objects.create(
            data={'email': 'dude@example.com', 'last_active_date': '2020-02-19T14:54:30Z'}
        )
        CommonVoiceUpdate.objects.create(
            data={'email': 'donny@example.com', 'last_active_date': '2020-02-19T14:55:30Z'}
        )
        CommonVoiceUpdate.objects.create(
            data={'email': 'donny@example.com', 'last_active_date': '2020-02-19T14:56:30Z'}
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

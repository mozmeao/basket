from copy import deepcopy
from unittest.mock import ANY, Mock, call, patch
from uuid import uuid4

from django.conf import settings
from django.test import TestCase
from django.test.utils import override_settings

from basket.news.backends.ctms import CTMSNotFoundByAltIDError
from basket.news.models import BrazeTxEmailMessage, FailedTask
from basket.news.tasks import (
    SUBSCRIBE,
    fxa_delete,
    fxa_email_changed,
    fxa_login,
    fxa_verified,
    get_fxa_user_data,
    record_common_voice_update,
    send_confirm_message,
    send_recovery_message,
    send_tx_message,
    send_tx_messages,
    update_custom_unsub,
    update_user_meta,
)
from basket.news.utils import iso_format_unix_timestamp


class RetryTaskTest(TestCase):
    """Test that we can retry a task"""

    @override_settings(RQ_MAX_RETRIES=2)
    @patch("django.contrib.messages.info", autospec=True)
    @patch("basket.base.rq.random")
    @patch("basket.base.rq.Queue.enqueue")
    def test_retry_task(self, mock_enqueue, mock_random, info):
        mock_random.randrange.side_effect = [60, 90]
        TASK_NAME = "news.tasks.update_phonebook"
        args = [1, 2]
        kwargs = {"token": 3}
        failed_task = FailedTask(
            name=TASK_NAME,
            task_id=4,
            args=args,
            kwargs=kwargs,
            exc="",
            einfo="",
        )
        # Failed task is deleted after queuing, but that only works on records
        # that have been saved, so just mock that and check later that it was
        # called.
        failed_task.delete = Mock(spec=failed_task.delete)
        failed_task.retry()
        # Task was submitted again
        mock_enqueue.assert_called_once()
        assert mock_enqueue.call_args.args[0] == TASK_NAME
        assert mock_enqueue.call_args.kwargs["args"] == args
        assert mock_enqueue.call_args.kwargs["kwargs"] == kwargs
        assert mock_enqueue.call_args.kwargs["retry"].intervals == [60, 90]
        # Previous failed task was deleted
        self.assertTrue(failed_task.delete.called)


@override_settings(
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
                "source_url": settings.FXA_REGISTER_SOURCE_URL + "?utm_campaign=bowling",
                "country": "DE",
                "lang": "en-US",
                "fxa_lang": data["locale"],
                "fxa_service": "monitor",
                "fxa_id": "the-fxa-id",
                "optin": True,
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
            },
            None,
        )


@patch("basket.news.tasks.upsert_user")
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

    def test_fxa_login_task_with_no_utm(self, upsert_mock):
        data = self.get_data()
        del data["metricsContext"]
        data["deviceCount"] = 1
        fxa_login(data)
        upsert_mock.delay.assert_not_called()

    def test_fxa_login_task_with_utm_data(self, upsert_mock):
        data = self.get_data()
        fxa_login(data)
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

    def test_fxa_login_task_with_utm_data_no_subscribe(self, upsert_mock):
        data = self.get_data()
        # not in the FXA_LOGIN_CAMPAIGNS setting
        data["metricsContext"]["utm_campaign"] = "nonesense"
        fxa_login(data)
        upsert_mock.delay.assert_not_called()


@patch("basket.news.tasks.ctms", spec_set=["update", "add"])
@patch("basket.news.tasks.get_user_data")
@patch("basket.news.tasks.cache")
class FxAEmailChangedTests(TestCase):
    def test_timestamps_older_message(self, cache_mock, gud_mock, ctms_mock):
        data = {
            "ts": 1234.567,
            "uid": "the-fxa-id-for-el-dudarino",
            "email": "the-dudes-new-email@example.com",
        }
        cache_mock.get.return_value = 1234.678
        # ts higher in cache, should no-op
        gud_mock.return_value = {"id": "1234"}
        fxa_email_changed(data)
        ctms_mock.update.assert_not_called()

    def test_timestamps_newer_message(self, cache_mock, gud_mock, ctms_mock):
        data = {
            "ts": 1234.567,
            "uid": "the-fxa-id-for-el-dudarino",
            "email": "the-dudes-new-email@example.com",
        }
        cache_mock.get.return_value = 1234.456
        gud_mock.return_value = {"id": "1234"}
        # ts higher in message, do the things
        fxa_email_changed(data)
        ctms_mock.update.assert_called_once_with(
            ANY,
            {"fxa_primary_email": data["email"]},
        )

    def test_timestamps_nothin_cached(self, cache_mock, gud_mock, ctms_mock):
        data = {
            "ts": 1234.567,
            "uid": "the-fxa-id-for-el-dudarino",
            "email": "the-dudes-new-email@example.com",
        }
        cache_mock.get.return_value = 0
        gud_mock.return_value = {"id": "1234"}
        fxa_email_changed(data)
        ctms_mock.update.assert_called_with(ANY, {"fxa_primary_email": data["email"]})

    def test_fxa_id_not_found(self, cache_mock, gud_mock, ctms_mock):
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
        ctms_mock.update.assert_called_with(
            {"id": "1234"},
            {"fxa_id": data["uid"], "fxa_primary_email": data["email"]},
        )

    def test_fxa_id_nor_email_found(self, cache_mock, gud_mock, ctms_mock):
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
        ctms_mock.update.assert_not_called()
        ctms_mock.add.assert_called_with(
            {
                "email": data["email"],
                "token": ANY,
                "fxa_id": data["uid"],
                "fxa_primary_email": data["email"],
            },
        )

    def test_fxa_id_nor_email_found_ctms_add_fails(
        self,
        cache_mock,
        gud_mock,
        ctms_mock,
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
        ctms_mock.update.assert_not_called()
        ctms_mock.add.assert_called_with(
            {
                "email": data["email"],
                "token": ANY,
                "fxa_id": data["uid"],
                "fxa_primary_email": data["email"],
            },
        )


@patch("basket.news.tasks.ctms")
@patch("basket.news.tasks.get_user_data")
class CommonVoiceGoalsTests(TestCase):
    def test_new_user(self, gud_mock, ctms_mock):
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

    def test_existing_user(self, gud_mock, ctms_mock):
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
        ctms_mock.update.assert_called_with(gud_mock(), update_data)


@patch("basket.news.tasks.ctms")
class TestUpdateCustomUnsub(TestCase):
    token = "the-token"
    reason = "I would like less emails."

    def test_normal(self, mock_ctms):
        """The reason is updated for the token"""
        update_custom_unsub(self.token, self.reason)
        mock_ctms.update_by_alt_id.assert_called_once_with(
            "token",
            self.token,
            {"reason": self.reason},
        )

    def test_no_ctms_record(self, mock_ctms):
        """If there is no CTMS record, updates are skipped."""
        mock_ctms.updates_by_alt_id.side_effect = CTMSNotFoundByAltIDError(
            "token",
            self.token,
        )
        update_custom_unsub(self.token, self.reason)
        mock_ctms.update_by_alt_id.assert_called_once_with(
            "token",
            self.token,
            {"reason": self.reason},
        )

    def test_error_raised(self, mock_ctms):
        """A SF exception is not re-raised"""
        update_custom_unsub(self.token, self.reason)
        mock_ctms.get.assert_not_called()


@patch("basket.news.tasks.ctms")
class TestUpdateUserMeta(TestCase):
    token = "the-token"
    data = {"first_name": "Edmund", "last_name": "Gettier"}

    def test_normal(self, mock_ctms):
        """The data is updated for the token"""
        update_user_meta(self.token, self.data)
        mock_ctms.update_by_alt_id.assert_called_once_with(
            "token",
            self.token,
            self.data,
        )

    def test_no_ctms_record(self, mock_ctms):
        """If there is no CTMS record, an exception is raised."""
        mock_ctms.update_by_alt_id.side_effect = CTMSNotFoundByAltIDError(
            "token",
            self.token,
        )
        self.assertRaises(
            CTMSNotFoundByAltIDError,
            update_user_meta,
            self.token,
            self.data,
        )
        mock_ctms.update_by_alt_id.assert_called_once_with(
            "token",
            self.token,
            self.data,
        )


@patch("basket.news.tasks.ctms", spec_set=["update"])
@patch("basket.news.tasks.get_user_data")
class TestGetFxaUserData(TestCase):
    def test_found_by_fxa_id_email_match(self, mock_gud, mock_ctms):
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
        mock_ctms.update.assert_not_called()

    def test_found_by_fxa_id_email_mismatch(self, mock_gud, mock_ctms):
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
        mock_ctms.update.assert_called_once_with(
            user_data,
            {"fxa_primary_email": "fxa@example.com"},
        )

    def test_miss_by_fxa_id(self, mock_gud, mock_ctms):
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
        mock_ctms.update.assert_not_called()


@patch("basket.news.tasks.ctms", spec_set=["update_by_alt_id"])
class TestFxaDelete(TestCase):
    def test_delete(self, mock_ctms):
        fxa_delete({"uid": "123"})
        mock_ctms.update_by_alt_id.assert_called_once_with(
            "fxa_id",
            "123",
            {"fxa_deleted": True},
        )

    def test_delete_ctms_not_found_succeeds(self, mock_ctms):
        """If the CTMS record is not found by FxA ID, the exception is caught."""
        mock_ctms.update_by_alt_id.side_effect = CTMSNotFoundByAltIDError(
            "fxa_id",
            "123",
        )
        fxa_delete({"uid": "123"})
        mock_ctms.update_by_alt_id.assert_called_once_with(
            "fxa_id",
            "123",
            {"fxa_deleted": True},
        )


@patch("basket.news.tasks.braze")
def test_send_tx_message(mock_braze, metricsmock):
    send_tx_message("test@example.com", "download-foo", "en-US")
    mock_braze.track_user.assert_called_once_with("test@example.com", event="send-download-foo-en-US", user_data=None)
    metricsmock.assert_incr_once("news.tasks.send_tx_message", tags=["message_id:download-foo", "language:en-US"])


@patch("basket.news.tasks.braze")
@patch("basket.news.models.BrazeTxEmailMessage.objects.get_message")
def test_send_tx_messages(mock_model, mock_braze, metricsmock):
    """Test multipe message IDs, but only one is a transactional message."""
    mock_model.side_effect = [BrazeTxEmailMessage(message_id="download-foo", language="en-US"), None]
    send_tx_messages("test@example.com", "en-US", ["newsletter", "download-foo"])
    mock_braze.track_user.assert_called_once_with("test@example.com", event="send-download-foo-en-US", user_data=None)
    metricsmock.assert_incr_once("news.tasks.send_tx_message", tags=["message_id:download-foo", "language:en-US"])


@override_settings(BRAZE_MESSAGE_ID_MAP={"download-zzz": "download-foo"})
@patch("basket.news.tasks.braze")
@patch("basket.news.models.BrazeTxEmailMessage.objects.get_message")
def test_send_tx_messages_with_map(mock_model, mock_braze, metricsmock):
    """Test multipe message IDs, but only one is a transactional message."""
    mock_model.side_effect = [BrazeTxEmailMessage(message_id="download-foo", language="en-US"), None]
    send_tx_messages("test@example.com", "en-US", ["newsletter", "download-foo"])
    mock_braze.track_user.assert_called_once_with("test@example.com", event="send-download-foo-en-US", user_data=None)
    metricsmock.assert_incr_once("news.tasks.send_tx_message", tags=["message_id:download-foo", "language:en-US"])


@patch("basket.news.tasks.braze")
@patch("basket.news.models.BrazeTxEmailMessage.objects.get_message")
def test_send_confirm_message(mock_get_message, mock_braze, metricsmock):
    mock_get_message.return_value = BrazeTxEmailMessage(message_id="newsletter-confirm-fx", language="en-US")
    send_confirm_message("test@example.com", "abc123", "en", "fx", "fed654")
    mock_braze.track_user.assert_called_once_with(
        "test@example.com", event="send-newsletter-confirm-fx-en-US", user_data={"basket_token": "abc123", "email_id": "fed654"}
    )
    metricsmock.assert_incr_once("news.tasks.send_tx_message", tags=["message_id:newsletter-confirm-fx", "language:en-US"])


@patch("basket.news.tasks.braze")
@patch("basket.news.models.BrazeTxEmailMessage.objects.get_message")
def test_send_recovery_message(mock_get_message, mock_braze, metricsmock):
    mock_get_message.return_value = BrazeTxEmailMessage(message_id="newsletter-confirm-fx", language="en-US")
    send_recovery_message("test@example.com", "abc123", "en", "fed654")
    mock_braze.track_user.assert_called_once_with(
        "test@example.com", event="send-newsletter-confirm-fx-en-US", user_data={"basket_token": "abc123", "email_id": "fed654"}
    )
    metricsmock.assert_incr_once("news.tasks.send_tx_message", tags=["message_id:newsletter-confirm-fx", "language:en-US"])

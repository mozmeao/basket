from copy import deepcopy
from datetime import datetime, timedelta
from unittest.mock import ANY, Mock, call, patch
from urllib.error import URLError
from uuid import uuid4

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from django.test.utils import override_settings
from django.utils.timezone import now

from requests.exceptions import ConnectionError as RequestsConnectionError

from basket.news.backends.ctms import CTMSNotFoundByAltIDError
from basket.news.celery import app as celery_app
from basket.news.models import CommonVoiceUpdate, FailedTask
from basket.news.tasks import (
    SUBSCRIBE,
    RetryTask,
    _add_fxa_activity,
    et_task,
    fxa_delete,
    fxa_email_changed,
    fxa_login,
    fxa_verified,
    get_fxa_user_data,
    get_lock,
    gmttime,
    process_common_voice_batch,
    record_common_voice_update,
    send_acoustic_tx_message,
    update_custom_unsub,
    update_user_meta,
)
from basket.news.utils import iso_format_unix_timestamp


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
        with self.assertRaises(Exception):  # noqa: B017
            myfunc.run()

        mock_backoff.assert_called_with(4)
        myfunc.retry.assert_called_with(countdown=mock_backoff())

    @patch("basket.news.tasks.exponential_backoff")
    def test_urlerror(self, mock_backoff):
        self._test_retry_increase(mock_backoff, URLError(reason=Exception("foo bar!")))

    @patch("basket.news.tasks.exponential_backoff")
    def test_requests_connection_error(self, mock_backoff):
        self._test_retry_increase(
            mock_backoff,
            RequestsConnectionError("Connection aborted."),
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


@override_settings(TASK_LOCKING_ENABLE=False)
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

from urllib2 import URLError

from django.test import TestCase
from django.test.utils import override_settings

import celery
from mock import Mock, patch

from news.backends.exacttarget_rest import ETRestError, ExactTargetRest
from news.models import FailedTask, Subscriber
from news.newsletters import clear_sms_cache
from news.tasks import (
    add_fxa_activity,
    add_sms_user,
    et_task,
    mogrify_message_id,
    NewsletterException,
    RECOVERY_MESSAGE_ID,
    send_recovery_message_task,
    SUBSCRIBE,
    update_phonebook,
    update_user,
)


class FailedTaskTest(TestCase):
    """Test that failed tasks are logged in our FailedTask table"""

    @patch('news.tasks.ExactTarget', autospec=True)
    def test_failed_task_logging(self, mock_exact_target):
        """Failed task is logged in FailedTask table"""
        mock_exact_target.side_effect = Exception("Test exception")
        self.assertEqual(0, FailedTask.objects.count())
        args = [{'arg1': 1, 'arg2': 2}, "foo@example.com"]
        kwargs = {'token': 3}
        result = update_phonebook.apply(args=args, kwargs=kwargs)
        fail = FailedTask.objects.get()
        self.assertEqual('news.tasks.update_phonebook', fail.name)
        self.assertEqual(result.task_id, fail.task_id)
        self.assertEqual(args, fail.args)
        self.assertEqual(kwargs, fail.kwargs)
        self.assertEqual(u"Exception('Test exception',)", fail.exc)
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
        # Mock the actual task (already registered with celery):
        mock_update_phonebook = Mock(spec=update_phonebook)
        with patch.dict(celery.registry.tasks, {TASK_NAME: mock_update_phonebook}):
            # Let's retry.
            failed_task.retry()
        # Task was submitted again
        mock_update_phonebook.apply_async.assert_called_with((1, 2), {'token': 3})
        # Previous failed task was deleted
        self.assertTrue(failed_task.delete.called)


@patch('news.tasks.send_message', autospec=True)
@patch('news.utils.look_for_user', autospec=True)
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

        with self.assertRaises(NewsletterException):
            send_recovery_message_task(self.email)

        self.assertFalse(mock_send.called)

    def test_email_only_in_et(self, mock_look_for_user, mock_send):
        """Email not in basket but in ET"""
        # Should create new subscriber with ET data, then trigger message
        # We can follow the user's format and lang pref
        format = 'T'
        lang = 'fr'
        mock_look_for_user.return_value = {
            'status': 'ok',
            'email': self.email,
            'format': format,
            'country': '',
            'lang': lang,
            'token': 'USERTOKEN',
            'newsletters': [],
        }
        send_recovery_message_task(self.email)
        subscriber = Subscriber.objects.get(email=self.email)
        self.assertEqual('USERTOKEN', subscriber.token)
        message_id = mogrify_message_id(RECOVERY_MESSAGE_ID, lang, format)
        mock_send.delay.assert_called_with(message_id, self.email,
                                           subscriber.token, format)

    def test_email_only_in_basket(self, mock_look_for_user, mock_send):
        """Email known in basket, not in ET"""
        # Should log error and return
        Subscriber.objects.create(email=self.email)
        mock_look_for_user.return_value = None
        send_recovery_message_task(self.email)
        self.assertFalse(mock_send.called)

    def test_email_in_both(self, mock_look_for_user, mock_send):
        """Email known in both basket and ET"""
        # We can follow the user's format and lang pref
        subscriber = Subscriber.objects.create(email=self.email)
        format = 'T'
        lang = 'fr'
        mock_look_for_user.return_value = {
            'status': 'ok',
            'email': self.email,
            'format': format,
            'country': '',
            'lang': lang,
            'token': subscriber.token,
            'newsletters': [],
        }
        send_recovery_message_task(self.email)
        message_id = mogrify_message_id(RECOVERY_MESSAGE_ID, lang, format)
        mock_send.delay.assert_called_with(message_id, self.email,
                                           subscriber.token, format)


class UpdateUserTests(TestCase):
    def _patch_tasks(self, attr, **kwargs):
        patcher = patch('news.tasks.' + attr, **kwargs)
        setattr(self, attr, patcher.start())
        self.addCleanup(patcher.stop)

    def setUp(self):
        self._patch_tasks('lookup_subscriber')
        self._patch_tasks('get_user_data')
        self._patch_tasks('parse_newsletters', return_value=([], []))
        self._patch_tasks('apply_updates')
        self._patch_tasks('confirm_user')
        self._patch_tasks('send_welcomes')
        self._patch_tasks('send_confirm_notice')

    def self_test_success_no_token_create_user(self):
        """
        If no token is provided, use lookup_subscriber to find (and
        possibly create) a user with a matching email.
        """
        subscriber = Mock(email='a@example.com', token='mytoken')
        self.lookup_subscriber.return_value = subscriber, None, False
        self.get_user_data.return_value = None

        update_user({}, 'a@example.com', None, SUBSCRIBE, True)
        self.get_user_data.assert_called_with(token='mytoken')


@override_settings(ET_CLIENT_ID='client_id', ET_CLIENT_SECRET='client_secret')
@patch('news.newsletters.SMS_MESSAGES', {'foo': 'bar'})
class AddSMSUserTests(TestCase):
    def setUp(self):
        clear_sms_cache()
        patcher = patch.object(ExactTargetRest, 'send_sms')
        self.send_sms = patcher.start()
        self.addCleanup(patcher.stop)

    def test_send_name_invalid(self):
        """If the send_name is invalid, return immediately."""
        add_sms_user('baffle', '8675309', False)
        self.assertFalse(self.send_sms.called)

    def test_retry_on_error(self):
        """If an ETRestError is raised while sending an SMS, retry."""
        error = ETRestError()
        self.send_sms.side_effect = error

        with patch.object(add_sms_user, 'retry') as retry:
            add_sms_user('foo', '8675309', False)
            self.send_sms.assert_called_with(['8675309'], 'bar')
            retry.assert_called_with(exc=error)

    def test_success(self):
        add_sms_user('foo', '8675309', False)
        self.send_sms.assert_called_with(['8675309'], 'bar')

    def test_success_with_optin(self):
        """
        If optin is True, add a Mobile_Subscribers record for the
        number.
        """
        with patch('news.tasks.ExactTargetDataExt') as ExactTargetDataExt:
            with self.settings(EXACTTARGET_USER='user', EXACTTARGET_PASS='asdf'):
                add_sms_user('foo', '8675309', True)

            ExactTargetDataExt.assert_called_with('user', 'asdf')
            data_ext = ExactTargetDataExt.return_value
            call_args = data_ext.add_record.call_args

            self.assertEqual(call_args[0][0], 'Mobile_Subscribers')
            self.assertEqual(set(['Phone', 'SubscriberKey']), set(call_args[0][1]))
            self.assertEqual(['8675309', '8675309'], call_args[0][2])


class ETTaskTests(TestCase):
    def test_retry_increase(self):
        """
        The delay for retrying a task should increase geometrically by a
        power of 2. I really hope I said that correctly.
        """
        error = URLError(reason=Exception('foo bar!'))

        @et_task
        def myfunc():
            raise error

        myfunc.request.retries = 4
        myfunc.retry = Mock()
        myfunc()

        myfunc.retry.assert_called_with(exc=error, countdown=16 * 60)


class AddFxaActivityTests(TestCase):
    def _base_test(self, user_agent=None, fxa_id='123', first_device=True):
        if not user_agent:
            user_agent = 'Mozilla/5.0 (Windows NT 6.1; rv:10.0) Gecko/20100101 Firefox/10.0'

        data = {
            'fxa_id': fxa_id,
            'first_device': first_device,
            'user_agent': user_agent
            }
        with patch('news.tasks.apply_updates') as apply_updates_mock:
            add_fxa_activity(data)
        record = apply_updates_mock.call_args[0][1]
        return record

    def test_login_date(self):
        with patch('news.tasks.gmttime') as gmttime_mock:
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
        self.assertEqual(record['OS'], 'Windows 7')
        self.assertEqual(record['OS_VERSION'], '')  # Not sure if we expect '7' here.
        self.assertEqual(record['BROWSER'], 'Firefox 10')
        self.assertEqual(record['DEVICE_NAME'], 'Other')
        self.assertEqual(record['DEVICE_TYPE'], 'D')

    def test_mac(self):
        ua = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.6; rv:10.0) Gecko/20100101 Firefox/30.2'
        record = self._base_test(ua)
        self.assertEqual(record['OS'], 'Mac OS X')
        self.assertEqual(record['OS_VERSION'], '10.6')
        self.assertEqual(record['BROWSER'], 'Firefox 30.2')
        self.assertEqual(record['DEVICE_NAME'], 'Other')
        self.assertEqual(record['DEVICE_TYPE'], 'D')

    def test_linux(self):
        ua = 'Mozilla/5.0 (X11; Linux i686 on x86_64; rv:10.0) Gecko/20100101 Firefox/42.0'
        record = self._base_test(ua)
        self.assertEqual(record['OS'], 'Linux')
        self.assertEqual(record['OS_VERSION'], '')
        self.assertEqual(record['BROWSER'], 'Firefox 42')
        self.assertEqual(record['DEVICE_NAME'], 'Other')
        self.assertEqual(record['DEVICE_TYPE'], 'D')

    def test_android_phone_below_version_41(self):
        ua = 'Mozilla/5.0 (Android; Mobile; rv:40.0) Gecko/40.0 Firefox/40.0'
        record = self._base_test(ua)
        self.assertEqual(record['OS'], 'Android')
        self.assertEqual(record['OS_VERSION'], '')
        self.assertEqual(record['BROWSER'], 'Firefox Mobile 40')
        self.assertEqual(record['DEVICE_NAME'], 'Generic Smartphone')
        self.assertEqual(record['DEVICE_TYPE'], 'M')

    def test_android_tablet_below_version_41(self):
        ua = 'Mozilla/5.0 (Android; Tablet; rv:40.0) Gecko/40.0 Firefox/40.0'
        record = self._base_test(ua)
        self.assertEqual(record['OS'], 'Android')
        self.assertEqual(record['OS_VERSION'], '')
        self.assertEqual(record['BROWSER'], 'Firefox 40')
        self.assertEqual(record['DEVICE_NAME'], 'Generic Tablet')
        self.assertEqual(record['DEVICE_TYPE'], 'T')

    def test_android_phone_from_version_41(self):
        ua = 'Mozilla/5.0 (Android 4.4; Mobile; rv:41.0) Gecko/41.0 Firefox/41.0'
        record = self._base_test(ua)
        self.assertEqual(record['OS'], 'Android')
        self.assertEqual(record['OS_VERSION'], '4.4')
        self.assertEqual(record['BROWSER'], 'Firefox Mobile 41')
        self.assertEqual(record['DEVICE_NAME'], 'Generic Smartphone')
        self.assertEqual(record['DEVICE_TYPE'], 'M')

    # TODO This reports Android 5 instead of Firefox 40
    #
    # def test_android_tablet_from_version_41(self):
    #     ua = 'Mozilla/5.0 (Android 5.0; Tablet; rv:41.0) Gecko/41.0 Firefox/41.0'
    #     record = self._base_test(ua)
    #     self.assertEqual(record['OS'], 'Android')
    #     self.assertEqual(record['OS_VERSION'], '5')
    #     self.assertEqual(record['BROWSER'], 'Firefox 40')
    #     self.assertEqual(record['DEVICE_NAME'], 'Generic Tablet')
    #     self.assertEqual(record['DEVICE_TYPE'], 'T')

    def test_firefox_os_phone(self):
        ua = 'Mozilla/5.0 (Mobile; rv:26.0) Gecko/26.0 Firefox/26.0'
        record = self._base_test(ua)
        self.assertEqual(record['OS'], 'Firefox OS')
        self.assertEqual(record['OS_VERSION'], '1.2')
        self.assertEqual(record['BROWSER'], 'Firefox Mobile 26')
        self.assertEqual(record['DEVICE_NAME'], 'Generic Smartphone')
        self.assertEqual(record['DEVICE_TYPE'], 'M')

    def test_firefox_os_tablet(self):
        ua = 'Mozilla/5.0 (Tablet; rv:26.0) Gecko/26.0 Firefox/26.0'
        record = self._base_test(ua)

        self.assertEqual(record['OS'], 'Firefox OS')
        self.assertEqual(record['OS_VERSION'], '1.2')
        self.assertEqual(record['BROWSER'], 'Firefox 26')
        self.assertEqual(record['DEVICE_NAME'], 'Generic Tablet')
        self.assertEqual(record['DEVICE_TYPE'], 'T')

    def test_firefox_os_device_specific(self):
        ua = 'Mozilla/5.0 (Mobile; ZTEOPEN; rv:18.1) Gecko/18.1 Firefox/18.1'
        record = self._base_test(ua)
        self.assertEqual(record['OS'], 'Firefox OS')
        self.assertEqual(record['OS_VERSION'], '1.1')
        self.assertEqual(record['BROWSER'], 'Firefox Mobile 18.1')
        self.assertEqual(record['DEVICE_NAME'], 'ZTE OPEN')
        self.assertEqual(record['DEVICE_TYPE'], 'M')

    def test_firefox_ios_iphone(self):
        ua = 'Mozilla/5.0 (iPhone; CPU iPhone OS 8_3 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) FxiOS/1.0 Mobile/12F69 Safari/600.1.4'
        record = self._base_test(ua)
        self.assertEqual(record['OS'], 'iOS')
        self.assertEqual(record['OS_VERSION'], '8.3')
        self.assertEqual(record['BROWSER'], 'Firefox iOS 1')
        self.assertEqual(record['DEVICE_NAME'], 'iPhone')
        self.assertEqual(record['DEVICE_TYPE'], 'M')

    def test_firefox_ios_tablet(self):
        ua = 'Mozilla/5.0 (iPad; CPU iPhone OS 8_3 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) FxiOS/1.0 Mobile/12F69 Safari/600.1.4'
        record = self._base_test(ua)
        self.assertEqual(record['OS'], 'iOS')
        self.assertEqual(record['OS_VERSION'], '8.3')
        self.assertEqual(record['BROWSER'], 'Firefox iOS 1')
        self.assertEqual(record['DEVICE_NAME'], 'iPad')
        self.assertEqual(record['DEVICE_TYPE'], 'T')

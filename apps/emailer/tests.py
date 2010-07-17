import mock
import test_utils
from nose.tools import eq_

import mysmtp


@mock.patch('mysmtp.EmailBackend.open')
@mock.patch('mysmtp.EmailBackend._send')
def test_smtp_backend_no_connection(send_mock, open_mock):
    backend = mysmtp.EmailBackend()
    msgs = ['failed', 'failed', 'failed']
    rv = backend.send_messages(msgs)
    eq_(rv, ([], msgs))


@mock.patch('mysmtp.EmailBackend.open')
@mock.patch('mysmtp.EmailBackend._send')
def test_send_failure(send_mock, open_mock):
    sent = [True, False, True]
    send_mock.side_effect = lambda *a, **k: sent.pop()

    backend = mysmtp.EmailBackend()
    backend.connection = mock.Mock()

    expected = ['sent', 'sent'], ['failed']
    rv = backend.send_messages(['sent', 'failed', 'sent'])
    eq_(send_mock.call_count, 3)
    eq_(rv, expected)

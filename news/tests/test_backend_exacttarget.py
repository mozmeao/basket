from django.test import TestCase
from django.test.utils import override_settings

from mock import patch, Mock

from news.backends.exacttarget import logged_in


@patch('news.backends.exacttarget.Client')
class TestWSDLSwitch(TestCase):
    def setUp(self):
        # clear the cached client
        logged_in.cached_client = None
        self.test_function = logged_in(lambda x: None)

    @override_settings(EXACTTARGET_USE_SANDBOX=True)
    def test_sandbox_wsdl(self, client_mock):
        """When using sandbox should use sandbox wsdl file."""
        self.test_function(Mock(client=None))

        call_args = client_mock.call_args
        assert call_args[0][0].endswith('et-sandbox-wsdl.txt')

    @override_settings(EXACTTARGET_USE_SANDBOX=False)
    def test_prod_wsdl(self, client_mock):
        """When not using sandbox should not use sandbox wsdl file."""
        self.test_function(Mock(client=None))

        call_args = client_mock.call_args
        assert call_args[0][0].endswith('et-wsdl.txt')

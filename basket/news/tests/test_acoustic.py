from unittest.mock import Mock, patch

from django.test import TestCase

from basket.news.backends.acoustic import acoustic, acoustic_tx


class TestAcousticBackend(TestCase):
    @patch("requests_oauthlib.OAuth2Session.post")
    def test_content_type_xml(self, mock_session_post):
        """
        Test that we add the correct content-type headers.
        """
        # Need a valid XML response to avoid a parse error.
        mock_session_post.return_value = Mock(text='<?xml version="1.0"?><test></test>')

        acoustic.send_mailing("mailing-ID", "contact@example.com")

        assert mock_session_post.call_args.kwargs["headers"] == {
            "Content-Type": "text/xml"
        }


class TestAcousticTxBackend(TestCase):
    @patch("requests_oauthlib.OAuth2Session.post")
    def test_content_type_xml(self, mock_session_post):
        """
        Test that we add the correct content-type headers.
        """
        # Need a valid XML response to avoid a parse error.
        mock_session_post.return_value = Mock(text='<?xml version="1.0"?><test></test>')

        acoustic_tx.send_mail("contact@example.com", "AAAA")

        assert mock_session_post.call_args.kwargs["headers"] == {
            "Content-Type": "text/xml"
        }

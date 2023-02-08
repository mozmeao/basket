# -*- coding: utf8 -*-

from unittest.mock import Mock, patch

import fxa.constants
import fxa.errors
from django.test import RequestFactory, TestCase, override_settings

from basket.news.models import BlockedEmail
from basket.news.utils import (
    email_block_list_cache,
    email_is_blocked,
    get_accept_languages,
    get_best_language,
    get_best_supported_lang,
    get_email_block_list,
    get_fxa_clients,
    has_valid_fxa_oauth,
    is_authorized,
    language_code_is_valid,
    mask_email,
    parse_newsletters_csv,
    process_email,
)


@override_settings(
    FXA_OAUTH_SERVER_ENV="stable",
    FXA_CLIENT_ID="dude",
    FXA_CLIENT_SECRET="abides",
)
@patch("basket.news.utils.fxa.oauth")
@patch("basket.news.utils.fxa.profile")
class GetFxAClientsTests(TestCase):
    def test_get_fxa_clients(self, profile_mock, oauth_mock):
        oauth, profile = get_fxa_clients()
        oauth_mock.Client.assert_called_with(
            server_url=fxa.constants.STABLE_URLS["oauth"],
            client_id="dude",
            client_secret="abides",
        )
        profile_mock.Client.assert_called_with(
            server_url=fxa.constants.STABLE_URLS["profile"],
        )
        assert oauth == oauth_mock.Client.return_value
        assert profile == profile_mock.Client.return_value

        get_fxa_clients()
        assert oauth_mock.Client.call_count == 1


@patch("basket.news.utils.get_fxa_clients")
class FxAOauthTests(TestCase):
    def request(self, bearer=None):
        rf = RequestFactory()
        kwargs = {}
        if bearer:
            kwargs["HTTP_AUTHORIZATION"] = "Bearer %s" % bearer
        return rf.get("/", **kwargs)

    def test_bad_oauth_verify(self, gfc_mock):
        request = self.request("dude-token")
        email = "dude@example.com"
        oauth_mock, profile_mock = Mock(), Mock()
        gfc_mock.return_value = oauth_mock, profile_mock
        verify_token = oauth_mock.verify_token
        verify_token.side_effect = fxa.errors.ClientError()
        assert not has_valid_fxa_oauth(request, email)
        verify_token.assert_called_with("dude-token", scope=["basket", "profile:email"])

    def test_bad_oauth_profile(self, gfc_mock):
        request = self.request("dude-token")
        email = "dude@example.com"
        oauth_mock, profile_mock = Mock(), Mock()
        gfc_mock.return_value = oauth_mock, profile_mock
        verify_token = oauth_mock.verify_token
        get_email = profile_mock.get_email
        get_email.side_effect = fxa.errors.ClientError()
        assert not has_valid_fxa_oauth(request, email)
        get_email.assert_called_with("dude-token")
        verify_token.assert_called_with("dude-token", scope=["basket", "profile:email"])

    def test_oauth_profile_email_no_match(self, gfc_mock):
        request = self.request("dude-token")
        email = "dude@example.com"
        oauth_mock, profile_mock = Mock(), Mock()
        gfc_mock.return_value = oauth_mock, profile_mock
        verify_token = oauth_mock.verify_token
        get_email = profile_mock.get_email
        get_email.return_value = "walter@example.com"
        assert not has_valid_fxa_oauth(request, email)
        get_email.assert_called_with("dude-token")
        verify_token.assert_called_with("dude-token", scope=["basket", "profile:email"])

    def test_oauth_success(self, gfc_mock):
        request = self.request("dude-token")
        email = "dude@example.com"
        oauth_mock, profile_mock = Mock(), Mock()
        gfc_mock.return_value = oauth_mock, profile_mock
        verify_token = oauth_mock.verify_token
        get_email = profile_mock.get_email
        get_email.return_value = "dude@example.com"
        assert has_valid_fxa_oauth(request, email)
        get_email.assert_called_with("dude-token")
        verify_token.assert_called_with("dude-token", scope=["basket", "profile:email"])

    def test_bad_bearer_header(self, gfc_mock):
        # should cause a header parse problem
        request = self.request(" ")
        email = "dude@example.com"
        assert not has_valid_fxa_oauth(request, email)
        gfc_mock.assert_not_called()

    def test_no_bearer_header(self, gfc_mock):
        request = self.request()
        email = "dude@example.com"
        assert not has_valid_fxa_oauth(request, email)
        gfc_mock.assert_not_called()


@patch("basket.news.utils.has_valid_api_key")
@patch("basket.news.utils.has_valid_fxa_oauth")
class IsAuthorizedTests(TestCase):
    def test_good_api_key(self, hvfo_mock, hvak_mock):
        hvak_mock.return_value = True
        request = Mock()
        assert is_authorized(request, "dude@example.com")
        hvak_mock.assert_called_with(request)
        hvfo_mock.assert_not_called()

    def test_good_fxa_oauth(self, hvfo_mock, hvak_mock):
        hvak_mock.return_value = False
        hvfo_mock.return_value = True
        request = Mock()
        assert is_authorized(request, "dude@example.com")
        hvak_mock.assert_called_with(request)
        hvfo_mock.assert_called_with(request, "dude@example.com")

    def test_no_email(self, hvfo_mock, hvak_mock):
        hvak_mock.return_value = False
        request = Mock()
        assert not is_authorized(request)
        hvak_mock.assert_called_with(request)
        hvfo_mock.assert_not_called()

    def test_no_auth(self, hvfo_mock, hvak_mock):
        hvak_mock.return_value = False
        hvfo_mock.return_value = False
        request = Mock()
        assert not is_authorized(request, "dude@example.com")
        hvak_mock.assert_called_with(request)
        hvfo_mock.assert_called_with(request, "dude@example.com")


class ParseNewslettersCSVTests(TestCase):
    def test_values(self):
        self.assertEqual(parse_newsletters_csv("dude,walter"), ["dude", "walter"])
        self.assertEqual(parse_newsletters_csv(" dude,  walter  "), ["dude", "walter"])
        self.assertEqual(parse_newsletters_csv(", dude, ,walter, "), ["dude", "walter"])
        self.assertEqual(parse_newsletters_csv(False), [])
        self.assertEqual(parse_newsletters_csv(None), [])
        self.assertEqual(parse_newsletters_csv(["dude", "donny"]), ["dude", "donny"])


class EmailIsBlockedTests(TestCase):
    def tearDown(self):
        email_block_list_cache.clear()

    def test_email_block_list(self):
        """Should return a list from the database."""
        BlockedEmail.objects.create(email_domain="stuff.web")
        BlockedEmail.objects.create(email_domain="whatnot.dude")
        BlockedEmail.objects.create(email_domain=".ninja")
        blocklist = get_email_block_list()
        expected = set(["stuff.web", "whatnot.dude", ".ninja"])
        self.assertSetEqual(set(blocklist), expected)

    @patch("basket.news.utils.BlockedEmail")
    def test_email_is_blocked(self, BlockedEmailMock):
        """Asking if blocked should only hit the DB once."""
        BlockedEmailMock.objects.values_list.return_value = [".ninja", "stuff.web"]
        self.assertTrue(email_is_blocked("dude@bowling.ninja"))
        self.assertTrue(email_is_blocked("walter@stuff.web"))
        self.assertFalse(email_is_blocked("donnie@example.com"))
        self.assertEqual(BlockedEmailMock.objects.values_list.call_count, 1)


class TestGetAcceptLanguages(TestCase):
    # mostly stolen from bedrock

    def setUp(self):
        patcher = patch(
            "basket.news.utils.newsletter_languages",
            return_value=["de", "en", "es", "fr", "id", "pt-BR", "ru", "pl", "hu"],
        )
        self.addCleanup(patcher.stop)
        patcher.start()

    def _test(self, accept_lang, good_list):
        self.assertListEqual(get_accept_languages(accept_lang), good_list)

    def test_valid_lang_codes(self):
        """
        Should return a list of valid lang codes
        """
        self._test("fr-FR", ["fr"])
        self._test("en-us,en;q=0.5", ["en"])
        self._test(
            "pt-pt,fr;q=0.8,it-it;q=0.5,de;q=0.3",
            ["pt-PT", "fr", "it-IT", "de"],
        )
        self._test("ja-JP-mac,ja-JP;q=0.7,ja;q=0.3", ["ja-JP", "ja"])
        self._test("foo,bar;q=0.5", ["foo", "bar"])

    def test_invalid_lang_codes_underscores(self):
        """
        Even though 'en_US' is invalid according to the spec, we get what it means.
        Let's accept it. Bug 1102652.
        """
        self._test("en_US", ["en"])
        self._test(
            "pt_pt,fr;q=0.8,it_it;q=0.5,de;q=0.3",
            ["pt-PT", "fr", "it-IT", "de"],
        )

    def test_invalid_lang_codes(self):
        """
        Should return a list of valid lang codes or an empty list
        """
        self._test(None, [])
        self._test("", [])
        self._test("en/us,en*;q=0.5", [])
        self._test("Chinese,zh-cn;q=0.5", ["zh-CN"])


class GetBestLanguageTests(TestCase):
    def setUp(self):
        patcher = patch(
            "basket.news.utils.newsletter_languages",
            return_value=["de", "en", "es", "fr", "id", "pt-BR", "ru", "pl", "hu"],
        )
        self.addCleanup(patcher.stop)
        patcher.start()

    def _test(self, langs_list, expected_lang):
        self.assertEqual(get_best_language(langs_list), expected_lang)

    def test_returns_first_good_lang(self):
        """Should return first language in the list that a newsletter supports."""
        self._test(["zh-TW", "es", "de", "en"], "es")
        self._test(["pt-PT", "zh-TW", "pt-BR", "en"], "pt-BR")

    def test_returns_first_good_lang_2_letter(self):
        """Should return first 2 letter prefix language in the list that a newsletter supports."""
        self._test(["pt-PT", "zh-TW", "es-AR", "ar"], "es")

    def test_returns_first_lang_no_good(self):
        """Should return the first in the list if no supported are found."""
        self._test(["pt-PT", "zh-TW", "zh-CN", "ar"], "pt-PT")

    def test_no_langs(self):
        """Should return none if no langs given."""
        self._test([], None)


class TestGetBestSupportedLang(TestCase):
    def setUp(self):
        patcher = patch(
            "basket.news.utils.newsletter_languages",
            return_value=[
                "de",
                "en",
                "es",
                "fr",
                "id",
                "pt",
                "ru",
                "pl",
                "hu",
                "zh-TW",
            ],
        )
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_empty_string(self):
        """Empty string is accepted as a language code"""
        self.assertEqual(get_best_supported_lang(""), "en")

    def test_exact_codes(self):
        """2 or 5 character code that's in the list is valid"""
        self.assertEqual(get_best_supported_lang("es"), "es")
        self.assertEqual(get_best_supported_lang("zh-TW"), "zh-TW")

    def test_case_insensitive(self):
        """Matching is not case sensitive"""
        self.assertEqual(get_best_supported_lang("ES"), "es")
        self.assertEqual(get_best_supported_lang("es-MX"), "es")
        self.assertEqual(get_best_supported_lang("PT-br"), "pt")

    def test_invalid_codes(self):
        """A code that's not in the list gets the default."""
        self.assertEqual(get_best_supported_lang("hi"), "en")
        self.assertEqual(get_best_supported_lang("hi-IN"), "en")
        self.assertEqual(get_best_supported_lang("dude"), "en")

    def test_weak_match(self):
        """Matching is best based on first 2 characters."""
        self.assertEqual(get_best_supported_lang("es-MX"), "es")
        self.assertEqual(get_best_supported_lang("pt-BR"), "pt")
        self.assertEqual(get_best_supported_lang("en-ZA"), "en")
        self.assertEqual(get_best_supported_lang("zh-CN"), "zh-TW")
        self.assertEqual(get_best_supported_lang("zh"), "zh-TW")


class TestLanguageCodeIsValid(TestCase):
    def test_empty_string(self):
        """Empty string is accepted as a language code"""
        self.assertTrue(language_code_is_valid(""))

    def test_none(self):
        """None is a TypeError"""
        with self.assertRaises(TypeError):
            language_code_is_valid(None)

    def test_zero(self):
        """0 is a TypeError"""
        with self.assertRaises(TypeError):
            language_code_is_valid(0)

    def test_exact_2_letter(self):
        """2-letter code that's in the list is valid"""
        self.assertTrue(language_code_is_valid("az"))

    def test_exact_3_letter(self):
        """3-letter code is valid.

        There are a few of these."""
        self.assertTrue(language_code_is_valid("azq"))

    def test_exact_5_letter(self):
        """5-letter code that's in the list is valid"""
        self.assertTrue(language_code_is_valid("az-BY"))

    def test_case_insensitive(self):
        """Matching is not case sensitive"""
        self.assertTrue(language_code_is_valid("az-BY"))
        self.assertTrue(language_code_is_valid("aZ"))
        self.assertTrue(language_code_is_valid("QW"))

    def test_wrong_length(self):
        """A code that's not a valid length is not valid."""
        self.assertFalse(language_code_is_valid("az-"))
        self.assertFalse(language_code_is_valid("a"))
        self.assertFalse(language_code_is_valid("azqr"))
        self.assertFalse(language_code_is_valid("az-BY2"))

    def test_wrong_format(self):
        """A code that's not a valid format is not valid."""
        self.assertFalse(language_code_is_valid("a2"))
        self.assertFalse(language_code_is_valid("asdfj"))
        self.assertFalse(language_code_is_valid("az_BY"))


class TestProcessEmail(TestCase):
    def test_non_ascii_email_domain(self):
        """Should return IDNA version of domain"""
        self.assertEqual(process_email("dude@黒川.日本"), "dude@xn--5rtw95l.xn--wgv71a")
        self.assertEqual(process_email("dude@黒川.日本"), "dude@xn--5rtw95l.xn--wgv71a")

    def test_non_ascii_email_username(self):
        """Should return none as SFDC does not support non-ascii characters in emails"""
        self.assertIsNone(process_email("düde@黒川.日本"))
        self.assertIsNone(process_email("düde@example.com"))

    def test_valid_email(self):
        """Should not return None for valid email."""
        self.assertEqual(process_email("dude@example.com"), "dude@example.com")
        self.assertEqual(process_email("dude@example.coop"), "dude@example.coop")
        self.assertEqual(process_email("dude@example.biz"), "dude@example.biz")

    def test_invalid_email(self):
        """Should return None for invalid email."""
        self.assertIsNone(process_email("dude@home@example.com"))
        self.assertIsNone(process_email(""))
        self.assertIsNone(process_email(None))


class TestMaskEmail(TestCase):
    def test_mask(self):
        self.assertEqual(mask_email("dude@example.com"), "d**e@e*****e.com")
        self.assertEqual(mask_email("the.dude@example.com"), "t******e@e*****e.com")
        self.assertEqual(mask_email("dude@sub.example.com"), "d**e@s*********e.com")

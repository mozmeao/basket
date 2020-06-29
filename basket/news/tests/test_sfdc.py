from django.test import TestCase
from django.test.utils import override_settings

from mock import patch, Mock

from basket.news.backends.sfdc import to_vendor, from_vendor


@patch("basket.news.backends.sfdc.is_supported_newsletter_language", Mock(return_value=True))
class VendorConversionTests(TestCase):
    @patch("basket.news.backends.sfdc.newsletter_map")
    def test_to_vendor(self, nm_mock):
        nm_mock.return_value = {
            "chillin": "Sub_Chillin__c",
            "bowlin": "Sub_Bowlin__c",
            "white-russian-recipes": "Sub_Caucasians__c",
        }
        data = {
            "email": "dude@example.com ",
            "token": "    totally-token-man",
            "format": "H",
            "country": "US   ",
            "lang": "  en",
            "source_url": "https://www.example.com",
            "first_name": "The",
            "last_name": "Dude",
            "newsletters": ["chillin", "bowlin", "white-russian-recipes"],
        }
        contact = {
            "Email_Format__c": "H",
            "FirstName": "The",
            "LastName": "Dude",
            "Subscriber__c": True,
            "Email_Language__c": "en",
            "Signup_Source_URL__c": "https://www.example.com",
            "Token__c": "totally-token-man",
            "Email": "dude@example.com",
            "MailingCountryCode": "us",
            "Sub_Chillin__c": True,
            "Sub_Bowlin__c": True,
            "Sub_Caucasians__c": True,
        }
        self.assertDictEqual(to_vendor(data), contact)

    @override_settings(TESTING_EMAIL_DOMAINS=["example.com"], USE_SANDBOX_BACKEND=False)
    @patch("basket.news.backends.sfdc.newsletter_map")
    def test_to_vendor_test_domain(self, nm_mock):
        """Same as main test but should flip UAT_Test_Data__c switch"""
        nm_mock.return_value = {
            "chillin": "Sub_Chillin__c",
            "bowlin": "Sub_Bowlin__c",
            "white-russian-recipes": "Sub_Caucasians__c",
        }
        data = {
            "email": "dude@example.com",
            "token": "totally-token-man",
            "format": "H",
            "country": "US",
            "lang": "en",
            "source_url": "https://www.example.com",
            "first_name": "The",
            "last_name": "Dude",
            "newsletters": ["chillin", "bowlin", "white-russian-recipes"],
        }
        contact = {
            "Email_Format__c": "H",
            "FirstName": "The",
            "LastName": "Dude",
            "Subscriber__c": True,
            "Email_Language__c": "en",
            "Signup_Source_URL__c": "https://www.example.com",
            "Token__c": "totally-token-man",
            "Email": "dude@example.com",
            "MailingCountryCode": "us",
            "Sub_Chillin__c": True,
            "Sub_Bowlin__c": True,
            "Sub_Caucasians__c": True,
            "UAT_Test_Data__c": True,
        }
        self.assertDictEqual(to_vendor(data), contact)

    @patch("basket.news.backends.sfdc.newsletter_map")
    def test_to_vendor_dict_newsletters(self, nm_mock):
        nm_mock.return_value = {
            "chillin": "Sub_Chillin__c",
            "bowlin": "Sub_Bowlin__c",
            "fightin": "Sub_Fightin__c",
        }
        data = {
            "email": "dude@example.com",
            "token": "totally-token-man",
            "format": "T",
            "country": "mx",
            "lang": "es",
            "source_url": "https://www.example.com",
            "first_name": "Senior",
            "last_name": "Lebowski",
            "newsletters": {"chillin": True, "bowlin": True, "fightin": False},
        }
        contact = {
            "Email_Format__c": "T",
            "FirstName": "Senior",
            "LastName": "Lebowski",
            "Subscriber__c": True,
            "Email_Language__c": "es",
            "Signup_Source_URL__c": "https://www.example.com",
            "Token__c": "totally-token-man",
            "Email": "dude@example.com",
            "MailingCountryCode": "mx",
            "Sub_Chillin__c": True,
            "Sub_Bowlin__c": True,
            "Sub_Fightin__c": False,
        }
        self.assertDictEqual(to_vendor(data), contact)

    @patch("basket.news.backends.sfdc.newsletter_inv_map")
    def test_from_vendor(self, nm_mock):
        nm_mock.return_value = {
            "Sub_Bowlin__c": "bowlin",
            "Sub_Caucasians__c": "white-russian-recipes",
            "Sub_Chillin__c": "chillin",
            "Sub_Fightin__c": "fightin",
        }
        data = {
            "id": "vendor-id",
            "email": "dude@example.com",
            "token": "totally-token-man",
            "format": "H",
            "country": "us",
            "lang": "en",
            "source_url": "https://www.example.com",
            "first_name": "The",
            "last_name": "Dude",
            "newsletters": ["bowlin", "white-russian-recipes"],
        }
        contact = {
            "Id": "vendor-id",
            "Email_Format__c": "H",
            "FirstName": "The",
            "LastName": "Dude",
            "Subscriber__c": True,
            "Email_Language__c": "en",
            "Signup_Source_URL__c": "https://www.example.com",
            "Token__c": "totally-token-man",
            "Email": "dude@example.com",
            "MailingCountryCode": "US",
            "Sub_Chillin__c": False,
            "Sub_Bowlin__c": True,
            "Sub_Caucasians__c": True,
            "Sub_Fightin__c": False,
        }
        self.assertDictEqual(from_vendor(contact), data)

    def test_to_vendor_blank_values(self):
        data = {
            "email": "dude@example.com",
            "token": "totally-token-man",
            "format": "H",
            "country": "US",
            "lang": "en",
            "source_url": "https://www.example.com",
            "first_name": "",
            "last_name": "",
            "fsa_allow_share": "y",
            "optout": "no",
            "optin": "true",
        }
        contact = {
            "Email_Format__c": "H",
            "Subscriber__c": True,
            "Email_Language__c": "en",
            "Signup_Source_URL__c": "https://www.example.com",
            "Token__c": "totally-token-man",
            "Email": "dude@example.com",
            "MailingCountryCode": "us",
            "FSA_Allow_Info_Shared__c": True,
            "HasOptedOutOfEmail": False,
            "Double_Opt_In__c": True,
        }
        self.assertDictEqual(to_vendor(data), contact)

    def test_to_vendor_none_values(self):
        data = {
            "email": "dude@example.com",
            "token": "totally-token-man",
            "format": "H",
            "country": "US",
            "lang": "en",
            "source_url": "https://www.example.com",
            "first_name": None,
            "last_name": None,
            "fsa_allow_share": "y",
            "optout": "no",
            "optin": "true",
        }
        contact = {
            "Email_Format__c": "H",
            "Subscriber__c": True,
            "Email_Language__c": "en",
            "Signup_Source_URL__c": "https://www.example.com",
            "Token__c": "totally-token-man",
            "Email": "dude@example.com",
            "MailingCountryCode": "us",
            "FSA_Allow_Info_Shared__c": True,
            "HasOptedOutOfEmail": False,
            "Double_Opt_In__c": True,
        }
        self.assertDictEqual(to_vendor(data), contact)

    def test_to_vendor_truncated_values(self):
        data = {
            "email": "dude@example.com",
            "token": "totally-token-man",
            "format": "H",
            "country": "US",
            "lang": "en",
            "source_url": "https://www.example.com",
            "first_name": "x" * 50,  # limited to 40 chars
            "last_name": "x" * 90,  # limited to 80 chars
            "fsa_allow_share": "y",
            "optout": "no",
            "optin": "true",
        }
        contact = {
            "Email_Format__c": "H",
            "Subscriber__c": True,
            "FirstName": "x" * 40,
            "LastName": "x" * 80,
            "Email_Language__c": "en",
            "Signup_Source_URL__c": "https://www.example.com",
            "Token__c": "totally-token-man",
            "Email": "dude@example.com",
            "MailingCountryCode": "us",
            "FSA_Allow_Info_Shared__c": True,
            "HasOptedOutOfEmail": False,
            "Double_Opt_In__c": True,
        }
        self.assertDictEqual(to_vendor(data), contact)

    def test_to_vendor_boolean_casting(self):
        data = {
            "email": "dude@example.com",
            "token": "totally-token-man",
            "format": "H",
            "country": "US",
            "lang": "en",
            "source_url": "https://www.example.com",
            "first_name": "The",
            "last_name": "Dude",
            "fsa_allow_share": "y",
            "optout": "no",
            "optin": "true",
        }
        contact = {
            "Email_Format__c": "H",
            "FirstName": "The",
            "LastName": "Dude",
            "Subscriber__c": True,
            "Email_Language__c": "en",
            "Signup_Source_URL__c": "https://www.example.com",
            "Token__c": "totally-token-man",
            "Email": "dude@example.com",
            "MailingCountryCode": "us",
            "FSA_Allow_Info_Shared__c": True,
            "HasOptedOutOfEmail": False,
            "Double_Opt_In__c": True,
        }
        self.assertDictEqual(to_vendor(data), contact)

    def test_to_vendor_boolean_casting_with_booleans(self):
        data = {
            "email": "dude@example.com",
            "token": "totally-token-man",
            "format": "H",
            "country": "US",
            "lang": "en",
            "source_url": "https://www.example.com",
            "first_name": "The",
            "last_name": "Dude",
            "fsa_allow_share": True,
            "optout": False,
            "optin": True,
        }
        contact = {
            "Email_Format__c": "H",
            "FirstName": "The",
            "LastName": "Dude",
            "Subscriber__c": True,
            "Email_Language__c": "en",
            "Signup_Source_URL__c": "https://www.example.com",
            "Token__c": "totally-token-man",
            "Email": "dude@example.com",
            "MailingCountryCode": "us",
            "FSA_Allow_Info_Shared__c": True,
            "HasOptedOutOfEmail": False,
            "Double_Opt_In__c": True,
        }
        self.assertDictEqual(to_vendor(data), contact)

    @override_settings(EXTRA_SUPPORTED_LANGS=["zh-tw"])
    def test_to_vendor_extra_langs(self):
        data = {
            "email": "dude@example.com",
            "token": "totally-token-man",
            "format": "H",
            "country": "US",
            "lang": "zh-TW",
            "source_url": "https://www.example.com",
            "first_name": "The",
            "last_name": "Dude",
            "fsa_allow_share": "y",
            "optout": "no",
            "optin": "true",
        }
        contact = {
            "Email_Format__c": "H",
            "FirstName": "The",
            "LastName": "Dude",
            "Subscriber__c": True,
            "Email_Language__c": "zh-TW",
            "Signup_Source_URL__c": "https://www.example.com",
            "Token__c": "totally-token-man",
            "Email": "dude@example.com",
            "MailingCountryCode": "us",
            "FSA_Allow_Info_Shared__c": True,
            "HasOptedOutOfEmail": False,
            "Double_Opt_In__c": True,
        }
        self.assertDictEqual(to_vendor(data), contact)

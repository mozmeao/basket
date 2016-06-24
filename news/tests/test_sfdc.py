from django.test import TestCase

from mock import patch, Mock

from news.backends.sfdc import to_vendor, from_vendor


@patch('news.backends.sfdc.is_supported_newsletter_language', Mock(return_value=True))
class SFDCTests(TestCase):
    @patch('news.backends.sfdc.newsletter_map')
    def test_to_vendor(self, nm_mock):
        nm_mock.return_value = {
            'chillin': 'Sub_Chillin__c',
            'bowlin': 'Sub_Bowlin__c',
            'white-russian-recipes': 'Sub_Caucasians__c',
        }
        data = {
            'email': 'dude@example.com',
            'token': 'totally-token-man',
            'format': 'H',
            'country': 'US',
            'lang': 'en',
            'source_url': 'https://www.example.com',
            'first_name': 'The',
            'last_name': 'Dude',
            'newsletters': [
                'chillin',
                'bowlin',
                'white-russian-recipes',
            ]
        }
        contact = {
            'Email_Format__c': 'H',
            'FirstName': 'The',
            'LastName': 'Dude',
            'Subscriber__c': True,
            'Email_Language__c': 'en',
            'Signup_Source_URL__c': 'https://www.example.com',
            'Token__c': 'totally-token-man',
            'Email': 'dude@example.com',
            'MailingCountryCode': 'us',
            'Sub_Chillin__c': True,
            'Sub_Bowlin__c': True,
            'Sub_Caucasians__c': True,
        }
        self.assertDictEqual(to_vendor(data), contact)

    @patch('news.backends.sfdc.newsletter_map')
    def test_to_vendor_dict_newsletters(self, nm_mock):
        nm_mock.return_value = {
            'chillin': 'Sub_Chillin__c',
            'bowlin': 'Sub_Bowlin__c',
            'fightin': 'Sub_Fightin__c',
        }
        data = {
            'email': 'dude@example.com',
            'token': 'totally-token-man',
            'format': 'T',
            'country': 'mx',
            'lang': 'es',
            'source_url': 'https://www.example.com',
            'first_name': 'Senior',
            'last_name': 'Lebowski',
            'newsletters': {
                'chillin': True,
                'bowlin': True,
                'fightin': False,
            }
        }
        contact = {
            'Email_Format__c': 'T',
            'FirstName': 'Senior',
            'LastName': 'Lebowski',
            'Subscriber__c': True,
            'Email_Language__c': 'es',
            'Signup_Source_URL__c': 'https://www.example.com',
            'Token__c': 'totally-token-man',
            'Email': 'dude@example.com',
            'MailingCountryCode': 'mx',
            'Sub_Chillin__c': True,
            'Sub_Bowlin__c': True,
            'Sub_Fightin__c': False,
        }
        self.assertDictEqual(to_vendor(data), contact)

    @patch('news.backends.sfdc.newsletter_inv_map')
    def test_from_vendor(self, nm_mock):
        nm_mock.return_value = {
            'Sub_Bowlin__c': 'bowlin',
            'Sub_Caucasians__c': 'white-russian-recipes',
            'Sub_Chillin__c': 'chillin',
            'Sub_Fightin__c': 'fightin'
        }
        data = {
            'id': 'vendor-id',
            'email': 'dude@example.com',
            'token': 'totally-token-man',
            'format': 'H',
            'country': 'us',
            'lang': 'en',
            'source_url': 'https://www.example.com',
            'first_name': 'The',
            'last_name': 'Dude',
            'newsletters': [
                'bowlin',
                'white-russian-recipes',
            ]
        }
        contact = {
            'Id': 'vendor-id',
            'Email_Format__c': 'H',
            'FirstName': 'The',
            'LastName': 'Dude',
            'Subscriber__c': True,
            'Email_Language__c': 'en',
            'Signup_Source_URL__c': 'https://www.example.com',
            'Token__c': 'totally-token-man',
            'Email': 'dude@example.com',
            'MailingCountryCode': 'US',
            'Sub_Chillin__c': False,
            'Sub_Bowlin__c': True,
            'Sub_Caucasians__c': True,
            'Sub_Fightin__c': False,
        }
        self.assertDictEqual(from_vendor(contact), data)

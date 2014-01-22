import json

from django.core.urlresolvers import reverse
from django.test import TestCase
from django.test.client import RequestFactory

from basket import errors
from mock import patch, ANY

from news import models, views
from news.models import APIUser, Newsletter
from news.newsletters import newsletter_languages, newsletter_fields
from news.views import language_code_is_valid


@patch('news.views.update_user_task')
class FxOSMalformedPOSTTest(TestCase):
    """Bug 962225"""

    def setUp(self):
        self.rf = RequestFactory()

    def test_deals_with_broken_post_data(self, update_user_mock):
        """Should be able to parse data from the raw request body.

        FxOS sends POST requests with the wrong mime-type, so request.POST is never
        filled out. We should parse the raw request body to get the data until this
        is fixed in FxOS in bug 949170.
        """
        req = self.rf.generic('POST', '/news/subscribe/',
                              data='email=dude@example.com&newsletters=firefox-os',
                              content_type='text/plain; charset=UTF-8')
        self.assertFalse(bool(req.POST))
        views.subscribe(req)
        update_user_mock.assert_called_with(req, views.SUBSCRIBE, data=ANY, optin=True, sync=False)
        data = update_user_mock.call_args[1]['data']
        self.assertDictEqual(data.dict(), {
            'email': 'dude@example.com',
            'newsletters': 'firefox-os',
        })


class SubscribeTest(TestCase):
    def setUp(self):
        kwargs = {
            "vendor_id": "MOZILLA_AND_YOU",
            "description": "A monthly newsletter packed with tips to "
                           "improve your browsing experience.",
            "show": True,
            "welcome": "",
            "languages": "de,en,es,fr,id,pt-BR,ru",
            "active": True,
            "title": "Firefox & You",
            "slug": "mozilla-and-you"
        }
        Newsletter.objects.create(**kwargs)

    def ssl_post(self, url, params=None, **extra):
        """Fake a post that used SSL"""
        extra['wsgi.url_scheme'] = 'https'
        params = params or {}
        return self.client.post(url, data=params, **extra)

    def test_no_newsletters_error(self):
        """
        Should return an error and not create a subscriber if
        no newsletters were specified.
        """
        resp = self.client.post('/news/subscribe/', {
            'email': 'dude@example.com',
        })
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'error')
        self.assertEqual(data['desc'], 'newsletters is missing')
        with self.assertRaises(models.Subscriber.DoesNotExist):
            models.Subscriber.objects.get(email='dude@example.com')

        resp = self.client.post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': '',
        })
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'error')
        self.assertEqual(data['desc'], 'newsletters is missing')
        with self.assertRaises(models.Subscriber.DoesNotExist):
            models.Subscriber.objects.get(email='dude@example.com')

    def test_invalid_newsletters_error(self):
        """
        Should return an error and not create a subscriber if
        newsletters are invalid.
        """
        resp = self.client.post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': 'mozilla-and-you,does-not-exist',
        })
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'error')
        self.assertEqual(data['desc'], 'invalid newsletter')
        with self.assertRaises(models.Subscriber.DoesNotExist):
            models.Subscriber.objects.get(email='dude@example.com')

    def test_invalid_language_error(self):
        """
        Should return an error and not create a subscriber if
        language invalid.
        """
        resp = self.client.post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': 'mozilla-and-you',
            'lang': 'zz'
        })
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'error')
        self.assertEqual(data['desc'], 'invalid language')
        with self.assertRaises(models.Subscriber.DoesNotExist):
            models.Subscriber.objects.get(email='dude@example.com')

    @patch('news.views.get_user_data')
    @patch('news.views.update_user.delay')
    def test_blank_language_okay(self, uu_mock, get_user_data):
        """
        Should work if language is left blank.
        """
        get_user_data.return_value = None  # new user
        resp = self.client.post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': 'mozilla-and-you',
            'lang': ''
        })
        self.assertEqual(resp.status_code, 200, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'ok')
        sub = models.Subscriber.objects.get(email='dude@example.com')
        uu_mock.assert_called_with(ANY, sub.email, sub.token,
                                   True, views.SUBSCRIBE, True)

    @patch('news.views.get_user_data')
    @patch('news.views.update_user.delay')
    def test_subscribe_success(self, uu_mock, get_user_data):
        """Subscription should work."""
        get_user_data.return_value = None  # new user
        resp = self.client.post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': 'mozilla-and-you',
        })
        self.assertEqual(resp.status_code, 200, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'ok')
        sub = models.Subscriber.objects.get(email='dude@example.com')
        uu_mock.assert_called_with(ANY, sub.email, sub.token,
                                   True, views.SUBSCRIBE, True)

    @patch('news.views.get_user_data')
    def test_sync_requires_ssl(self, get_user_data):
        """sync=Y requires SSL"""
        get_user_data.return_value = None  # new user
        resp = self.client.post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': 'mozilla-and-you',
            'lang': 'en',
            'sync': 'Y',
        })
        self.assertEqual(resp.status_code, 401, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(errors.BASKET_SSL_REQUIRED, data['code'])

    @patch('news.views.get_user_data')
    def test_sync_requires_api_key(self, get_user_data):
        """sync=Y requires API key"""
        get_user_data.return_value = None  # new user
        # Use SSL but no API key
        resp = self.ssl_post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': 'mozilla-and-you',
            'lang': 'en',
            'sync': 'Y',
        })
        self.assertEqual(resp.status_code, 401, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(errors.BASKET_AUTH_ERROR, data['code'])

    @patch('news.views.get_user_data')
    @patch('news.views.update_user.delay')
    def test_sync_with_ssl_and_api_key(self, uu_mock, get_user_data):
        """sync=Y with SSL and api key should work."""
        get_user_data.return_value = None  # new user
        auth = APIUser.objects.create(name="test")
        resp = self.ssl_post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': 'mozilla-and-you',
            'sync': 'Y',
            'api-key': auth.api_key,
        })
        self.assertEqual(resp.status_code, 200, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'ok')
        sub = models.Subscriber.objects.get(email='dude@example.com')
        uu_mock.assert_called_with(ANY, sub.email, sub.token,
                                   True, views.SUBSCRIBE, True)


class TestNewslettersAPI(TestCase):
    def setUp(self):
        self.url = reverse('newsletters_api')
        self.rf = RequestFactory()

    def test_newsletters_view(self):
        # We can fetch the newsletter data
        nl1 = models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=False,
            languages='en-US,fr',
            vendor_id='VENDOR1',
        )

        models.Newsletter.objects.create(slug='slug2', vendor_id='VENDOR2')

        req = self.rf.get(self.url)
        resp = views.newsletters(req)
        data = json.loads(resp.content)
        newsletters = data['newsletters']
        self.assertEqual(2, len(newsletters))
        # Find the 'slug' newsletter in the response
        obj = newsletters['slug']

        self.assertEqual(nl1.title, obj['title'])
        self.assertEqual(nl1.active, obj['active'])
        for lang in ['en-US', 'fr']:
            self.assertIn(lang, obj['languages'])

    def test_strip_languages(self):
        # If someone edits Newsletter and puts whitespace in the languages
        # field, we strip it on save
        nl1 = models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=False,
            languages='en-US, fr, de ',
            vendor_id='VENDOR1',
        )
        nl1 = models.Newsletter.objects.get(id=nl1.id)
        self.assertEqual('en-US,fr,de', nl1.languages)

    def test_newsletter_languages(self):
        # newsletter_languages() returns the set of languages
        # of the newsletters
        # (Note that newsletter_languages() is not part of the external
        # API, but is used internally)
        models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=False,
            languages='en-US',
            vendor_id='VENDOR1',
        )
        models.Newsletter.objects.create(
            slug='slug2',
            title='title',
            active=False,
            languages='fr, de ',
            vendor_id='VENDOR2',
        )
        models.Newsletter.objects.create(
            slug='slug3',
            title='title',
            active=False,
            languages='en-US, fr',
            vendor_id='VENDOR3',
        )
        expect = set(['en-US', 'fr', 'de'])
        self.assertEqual(expect, newsletter_languages())

    def test_newsletters_cached(self):
        models.Newsletter.objects.create(
            slug='slug',
            title='title',
            vendor_id='VEND1',
            active=False,
            languages='en-US, fr, de ',
        )
        # This should get the data cached
        newsletter_fields()
        # Now request it again and it shouldn't have to generate the
        # data from scratch.
        with patch('news.newsletters._get_newsletters_data') as get:
            newsletter_fields()
        self.assertFalse(get.called)

    def test_cache_clearing(self):
        # Our caching of newsletter data doesn't result in wrong answers
        # when newsletters change
        models.Newsletter.objects.create(
            slug='slug',
            title='title',
            vendor_id='VEND1',
            active=False,
            languages='en-US, fr, de ',
        )
        vendor_ids = newsletter_fields()
        self.assertEqual([u'VEND1'], vendor_ids)
        # Now add another newsletter
        models.Newsletter.objects.create(
            slug='slug2',
            title='title2',
            vendor_id='VEND2',
            active=False,
            languages='en-US, fr, de ',
        )
        vendor_ids2 = set(newsletter_fields())
        self.assertEqual(set([u'VEND1', u'VEND2']), vendor_ids2)

    def test_cache_clear_on_delete(self):
        # Our caching of newsletter data doesn't result in wrong answers
        # when newsletters are deleted
        nl1 = models.Newsletter.objects.create(
            slug='slug',
            title='title',
            vendor_id='VEND1',
            active=False,
            languages='en-US, fr, de ',
        )
        vendor_ids = newsletter_fields()
        self.assertEqual([u'VEND1'], vendor_ids)
        # Now delete it
        nl1.delete()
        vendor_ids = newsletter_fields()
        self.assertEqual([], vendor_ids)


class TestLanguageCodeIsValid(TestCase):
    @patch('news.views.newsletter_languages')
    def test_empty_string(self, n_l):
        """Empty string is accepted as a language code"""
        self.assertTrue(language_code_is_valid(''))

    @patch('news.views.newsletter_languages')
    def test_none(self, n_l):
        """None is a TypeError"""
        with self.assertRaises(TypeError):
            language_code_is_valid(None)

    @patch('news.views.newsletter_languages')
    def test_zero(self, n_l):
        """0 is a TypeError"""
        with self.assertRaises(TypeError):
            language_code_is_valid(0)

    @patch('news.views.newsletter_languages')
    def test_exact_2_letter(self, n_l):
        """2-letter code that's in the list is valid"""
        n_l.return_value = ['az']
        self.assertTrue(language_code_is_valid('az'))

    @patch('news.views.newsletter_languages')
    def test_exact_5_letter(self, n_l):
        """5-letter code that's in the list is valid"""
        n_l.return_value = ['az-BY']
        self.assertTrue(language_code_is_valid('az-BY'))

    @patch('news.views.newsletter_languages')
    def test_prefix(self, n_l):
        """2-letter code that's a prefix of something in the list is valid"""
        n_l.return_value = ['az-BY']
        self.assertTrue(language_code_is_valid('az'))

    @patch('news.views.newsletter_languages')
    def test_long_version(self, n_l):
        """5-letter code is valid if an entry in the list is a prefix of it"""
        n_l.return_value = ['az']
        self.assertTrue(language_code_is_valid('az-BY'))

    @patch('news.views.newsletter_languages')
    def test_case_insensitive(self, n_l):
        """Matching is not case sensitive"""
        n_l.return_value = ['aZ', 'Qw-wE']
        self.assertTrue(language_code_is_valid('az-BY'))
        self.assertTrue(language_code_is_valid('az'))
        self.assertTrue(language_code_is_valid('QW'))

    @patch('news.views.newsletter_languages')
    def test_wrong_length(self, n_l):
        """A code that's a prefix of something in the list, but not a valid
        length, is not valid. Or vice-versa."""
        n_l.return_value = ['az-BY']
        self.assertFalse(language_code_is_valid('az-'))
        self.assertFalse(language_code_is_valid('a'))
        self.assertFalse(language_code_is_valid('az-BY2'))

    @patch('news.views.newsletter_languages')
    def test_no_match(self, n_l):
        """Return False if there's no match any way we try."""
        n_l.return_value = ['az']
        self.assertFalse(language_code_is_valid('by'))


class RecoveryViewTest(TestCase):
    # See the task tests for more
    def setUp(self):
        self.url = reverse('send_recovery_message')

    def test_no_email(self):
        """email not provided - return 400"""
        resp = self.client.post(self.url, {})
        self.assertEqual(400, resp.status_code)

    def test_bad_email(self):
        """Invalid email should return 400"""
        resp = self.client.post(self.url, {'email': 'not_an_email'})
        self.assertEqual(400, resp.status_code)

    @patch('news.views.get_user_data', autospec=True)
    def test_unknown_email(self, mock_get_user_data):
        """Unknown email should return 404"""
        email = 'dude@example.com'
        mock_get_user_data.return_value = None
        resp = self.client.post(self.url, {'email': email})
        self.assertEqual(404, resp.status_code)

    @patch('news.views.get_user_data', autospec=True)
    @patch('news.views.send_recovery_message_task.delay', autospec=True)
    def test_known_email(self, mock_send_recovery_message_task,
                         mock_get_user_data):
        """email provided - pass to the task, return 200"""
        email = 'dude@example.com'
        mock_get_user_data.return_value = {'dummy': 2}
        # It should pass the email to the task
        resp = self.client.post(self.url, {'email': email})
        self.assertEqual(200, resp.status_code)
        mock_send_recovery_message_task.assert_called_with(email)

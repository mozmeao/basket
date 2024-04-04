from unittest.mock import ANY, patch
from uuid import uuid4

from django.test import TestCase, override_settings

from basket.news import models
from basket.news.tasks import upsert_user
from basket.news.utils import SET, SUBSCRIBE, UNSUBSCRIBE, generate_token


@override_settings(SEND_CONFIRM_MESSAGES=True)
@patch("basket.news.tasks.send_confirm_message")
@patch("basket.news.tasks.ctms")
@patch("basket.news.tasks.get_user_data")
class UpsertUserTests(TestCase):
    def setUp(self):
        self.token = generate_token()
        self.email = "dude@example.com"
        # User data in format that get_user_data() returns it
        self.get_user_data = {
            "email": self.email,
            "token": self.token,
            "country": "us",
            "lang": "en",
            "newsletters": ["slug"],
            "status": "ok",
        }

    def test_update_first_last_names(
        self,
        get_user_mock,
        ctms_mock,
        confirm_mock,
    ):
        """sending name fields should result in names being passed to SF/CTMS"""
        get_user_mock.return_value = None  # Does not exist yet
        email_id = str(uuid4())
        ctms_mock.add.return_value = {"email": {"email_id": email_id}}
        models.Newsletter.objects.create(
            slug="slug",
            title="title",
            active=True,
            languages="en,fr",
            vendor_id="VENDOR1",
            requires_double_optin=True,
        )
        data = {
            "country": "US",
            "lang": "en",
            "newsletters": "slug",
            "first_name": "The",
            "last_name": "Dude",
            "email": self.email,
        }
        upsert_user(SUBSCRIBE, data)
        update_data = data.copy()
        update_data["newsletters"] = {"slug": True}
        update_data["token"] = ANY
        ctms_mock.add.assert_called_with(update_data)
        update_data["email_id"] = email_id

    def test_update_user_set_works_if_no_newsletters(
        self,
        get_user_mock,
        ctms_mock,
        confirm_mock,
    ):
        """
        A blank `newsletters` field when the update type is SET indicates
        that the person wishes to unsubscribe from all newsletters. This has
        caused exceptions because '' is not a valid newsletter name.
        """
        models.Newsletter.objects.create(
            slug="slug",
            title="title",
            active=True,
            languages="en-US,fr",
            vendor_id="TITLE_UNKNOWN",
        )
        data = {
            "lang": "en",
            "country": "US",
            "newsletters": "",
            "email": self.email,
            "token": self.token,
        }
        update_data = data.copy()
        update_data["newsletters"] = {"slug": False}

        get_user_mock.return_value = self.get_user_data

        upsert_user(SET, data)
        # We should have looked up the user's data
        get_user_mock.assert_called()
        # We'll specifically unsubscribe each newsletter the user is
        # subscribed to.
        ctms_mock.update.assert_called_with(self.get_user_data, update_data)

    def test_resubscribe_doesnt_update_newsletter(
        self,
        get_user_mock,
        ctms_mock,
        confirm_mock,
    ):
        """
        When subscribing to things the user is already subscribed to, we
        do not pass that newsletter to CTMS because we don't want that newsletter
        to be updated for no reason as that could cause another welcome to be sent.
        """
        models.Newsletter.objects.create(
            slug="slug",
            title="title",
            active=True,
            languages="en-US,fr",
            vendor_id="TITLE_UNKNOWN",
        )
        # We're going to ask to subscribe to this one again
        data = {
            "lang": "en",
            "country": "US",
            "newsletters": "slug",
            "email": self.email,
        }
        update_data = data.copy()
        update_data["newsletters"] = {}

        get_user_mock.return_value = self.get_user_data

        upsert_user(SUBSCRIBE, data)
        # We should have looked up the user's data
        get_user_mock.assert_called()
        # We should not have mentioned this newsletter in our call to ET
        ctms_mock.update.assert_called_with(self.get_user_data, update_data)

    def test_set_doesnt_update_newsletter(
        self,
        get_user_mock,
        ctms_mock,
        confirm_mock,
    ):
        """
        When setting the newsletters to ones the user is already subscribed
        to, we do not pass that newsletter to CTMS because we
        don't want that newsletter to send a new welcome.
        """
        models.Newsletter.objects.create(
            slug="slug",
            title="title",
            active=True,
            languages="en-US,fr",
            vendor_id="TITLE_UNKNOWN",
        )
        # We're going to ask to subscribe to this one again
        data = {
            "lang": "en",
            "country": "US",
            "newsletters": "slug",
            "email": self.email,
            "token": self.token,
        }
        update_data = data.copy()
        update_data["newsletters"] = {}

        # Mock user data - we want our user subbed to our newsletter to start
        get_user_mock.return_value = self.get_user_data

        upsert_user(SET, data)
        # We should have looked up the user's data
        self.assertTrue(get_user_mock.called)
        # We should not have mentioned this newsletter in our call to CTMS
        ctms_mock.update.assert_called_with(self.get_user_data, update_data)

    def test_unsub_is_careful(self, get_user_mock, ctms_mock, confirm_mock):
        """
        When unsubscribing, we only unsubscribe things the user is
        currently subscribed to.
        """
        models.Newsletter.objects.create(
            slug="slug",
            title="title",
            active=True,
            languages="en-US,fr",
            vendor_id="TITLE_UNKNOWN",
        )
        models.Newsletter.objects.create(
            slug="slug2",
            title="title2",
            active=True,
            languages="en-US,fr",
            vendor_id="TITLE2_UNKNOWN",
        )
        # We're going to ask to unsubscribe from both
        data = {
            "lang": "en",
            "country": "US",
            "newsletters": "slug,slug2",
            "token": self.token,
        }
        update_data = data.copy()
        # We should only mention slug, not slug2
        update_data["newsletters"] = {"slug": False}
        get_user_mock.return_value = self.get_user_data

        upsert_user(UNSUBSCRIBE, data)
        # We should have looked up the user's data
        self.assertTrue(get_user_mock.called)
        ctms_mock.update.assert_called_with(self.get_user_data, update_data)

    def test_update_user_with_email_id(
        self,
        get_user_mock,
        ctms_mock,
        confirm_mock,
    ):
        """
        If the SF data has an email_id, updates are sent to CTMS as well.
        """
        models.Newsletter.objects.create(
            slug="slug",
            title="title",
            active=True,
            languages="en-US,fr",
            vendor_id="TITLE_UNKNOWN",
        )
        get_user_mock.return_value = {
            "status": "ok",
            "email": "dude@example.com",
            "token": "foo-token",
            "email_id": "ctms-email-id",
            "newsletters": ["other-one"],
            "optin": True,
        }
        data = {
            "lang": "en",
            "country": "US",
            "newsletters": "slug",
            "email": "dude@example.com",
        }
        update_data = data.copy()
        update_data["newsletters"] = {
            "slug": True,
        }  # Only the set newsletter is mentioned
        upsert_user(SUBSCRIBE, data)
        ctms_mock.update.assert_called_with(get_user_mock.return_value, update_data)

    def test_send_confirm(self, get_user_mock, ctms_mock, confirm_mock):
        """Subscribing to a newsletter should send a confirm email"""
        get_user_mock.return_value = None  # Does not exist yet
        email_id = str(uuid4())
        ctms_mock.add.return_value = {"email": {"email_id": email_id}}
        models.Newsletter.objects.create(
            slug="slug",
            title="title",
            active=True,
            languages="en,fr",
            vendor_id="VENDOR1",
            requires_double_optin=True,
        )
        data = {
            "country": "US",
            "lang": "en",
            "newsletters": "slug",
            "email": self.email,
        }
        upsert_user(SUBSCRIBE, data)
        update_data = data.copy()
        update_data["newsletters"] = {"slug": True}
        update_data["token"] = ANY
        ctms_mock.add.assert_called_with(update_data)
        update_data["email_id"] = email_id
        confirm_mock.delay.assert_called_with(self.email, ANY, "en", "moz", email_id)

    def test_send_fx_confirm(self, get_user_mock, ctms_mock, confirm_mock):
        """Subscribing to a Fx newsletter should send a Fx confirm email"""
        get_user_mock.return_value = None  # Does not exist yet
        email_id = str(uuid4())
        ctms_mock.add.return_value = {"email": {"email_id": email_id}}
        models.Newsletter.objects.create(
            slug="slug",
            title="title",
            active=True,
            languages="en,fr",
            vendor_id="VENDOR1",
            requires_double_optin=True,
            firefox_confirm=True,
        )
        data = {
            "country": "US",
            "lang": "en",
            "newsletters": "slug",
            "email": self.email,
        }
        upsert_user(SUBSCRIBE, data)
        update_data = data.copy()
        update_data["newsletters"] = {"slug": True}
        update_data["token"] = ANY
        ctms_mock.add.assert_called_with(update_data)
        update_data["email_id"] = email_id
        confirm_mock.delay.assert_called_with(self.email, ANY, "en", "fx", email_id)

    def test_send_moz_confirm(self, get_user_mock, ctms_mock, confirm_mock):
        """Subscribing to a Fx and moz newsletters should send a moz confirm email"""
        get_user_mock.return_value = None  # Does not exist yet
        email_id = str(uuid4())
        ctms_mock.add.return_value = {"email": {"email_id": email_id}}
        models.Newsletter.objects.create(
            slug="slug",
            title="title",
            active=True,
            languages="en,fr",
            vendor_id="VENDOR1",
            requires_double_optin=True,
            firefox_confirm=True,
        )
        models.Newsletter.objects.create(
            slug="slug2",
            title="title",
            active=True,
            languages="en,fr",
            vendor_id="VENDOR2",
            requires_double_optin=True,
            firefox_confirm=False,
        )
        data = {
            "country": "US",
            "lang": "en",
            "newsletters": "slug,slug2",
            "email": self.email,
        }
        upsert_user(SUBSCRIBE, data)
        update_data = data.copy()
        update_data["newsletters"] = {"slug": True, "slug2": True}
        update_data["token"] = ANY
        ctms_mock.add.assert_called_with(update_data)
        update_data["email_id"] = email_id
        confirm_mock.delay.assert_called_with(self.email, ANY, "en", "moz", email_id)

    def test_no_send_confirm_newsletter(
        self,
        get_user_mock,
        ctms_mock,
        confirm_mock,
    ):
        """
        Subscribing to a newsletter should not send a confirm email
        if the newsletter does not require it
        """
        get_user_mock.return_value = None  # Does not exist yet
        email_id = str(uuid4())
        ctms_mock.add.return_value = {"email": {"email_id": email_id}}
        models.Newsletter.objects.create(
            slug="slug",
            title="title",
            active=True,
            languages="en,fr",
            vendor_id="VENDOR1",
            requires_double_optin=False,
        )
        data = {
            "country": "US",
            "lang": "en",
            "newsletters": "slug",
            "email": self.email,
        }
        upsert_user(SUBSCRIBE, data)
        update_data = data.copy()
        update_data["newsletters"] = {"slug": True}
        update_data["token"] = ANY
        update_data["optin"] = True
        ctms_mock.add.assert_called_with(update_data)
        update_data["email_id"] = email_id
        confirm_mock.delay.assert_not_called()

    def test_no_send_confirm_user(
        self,
        get_user_mock,
        ctms_mock,
        confirm_mock,
    ):
        """
        Subscribing to a newsletter should not send a confirm email
        if the user is already confirmed
        """
        user_data = self.get_user_data.copy()
        user_data["optin"] = True
        user_data["newsletters"] = ["not-slug"]
        get_user_mock.return_value = user_data
        models.Newsletter.objects.create(
            slug="slug",
            title="title",
            active=True,
            languages="en,fr",
            vendor_id="VENDOR1",
            requires_double_optin=True,
        )
        data = {
            "country": "US",
            "lang": "en",
            "newsletters": "slug",
            "email": self.email,
        }
        upsert_user(SUBSCRIBE, data)
        update_data = data.copy()
        update_data["newsletters"] = {"slug": True}
        ctms_mock.update.assert_called_with(user_data, update_data)
        confirm_mock.delay.assert_not_called()

    def test_send_confirm_optin_false_double_opt_in(
        self,
        get_user_mock,
        ctms_mock,
        confirm_mock,
    ):
        """
        Re-subscribing to a newsletter should send a confirm email if the user is not already confirmed
        """
        user_data = self.get_user_data.copy()
        user_data["optin"] = False
        user_data["newsletters"] = ["slug"]
        get_user_mock.return_value = user_data
        models.Newsletter.objects.create(
            slug="slug",
            title="title",
            active=True,
            languages="en,fr",
            vendor_id="VENDOR1",
            requires_double_optin=True,
        )
        data = {
            "country": "US",
            "lang": "en",
            "newsletters": "slug",
            "email": self.email,
        }
        upsert_user(SUBSCRIBE, data)
        update_data = data.copy()
        update_data["newsletters"] = {}  # Gets stripped since it's already subscribed to.
        ctms_mock.update.assert_called_with(user_data, update_data)
        confirm_mock.delay.assert_called()

    def test_send_confirm_optin_false_not_double_opt_in(
        self,
        get_user_mock,
        ctms_mock,
        confirm_mock,
    ):
        """
        Re-subscribing to a newsletter should not send a confirm email if the user is not already
        confirmed but the newsletter does not require double opt-in.
        """
        user_data = self.get_user_data.copy()
        user_data["optin"] = False
        user_data["newsletters"] = ["slug"]
        get_user_mock.return_value = user_data
        models.Newsletter.objects.create(
            slug="slug",
            title="title",
            active=True,
            languages="en,fr",
            vendor_id="VENDOR1",
            requires_double_optin=False,
        )
        data = {
            "country": "US",
            "lang": "en",
            "newsletters": "slug",
            "email": self.email,
        }
        upsert_user(SUBSCRIBE, data)
        update_data = data.copy()
        update_data["newsletters"] = {}  # Gets stripped since it's already subscribed to.
        ctms_mock.update.assert_called_with(user_data, update_data)
        confirm_mock.delay.assert_not_called()

    def test_new_subscription_with_ctms_conflict(
        self,
        get_user_mock,
        ctms_mock,
        confirm_mock,
    ):
        """Test when CTMS returns an error for a new contact"""
        get_user_mock.return_value = None  # Does not exist yet
        ctms_mock.add.return_value = None  # Conflict on create
        models.Newsletter.objects.create(
            slug="slug",
            title="title",
            active=True,
            languages="en,fr",
            vendor_id="VENDOR1",
            requires_double_optin=True,
        )
        data = {
            "country": "US",
            "lang": "en",
            "newsletters": "slug",
            "email": self.email,
        }
        upsert_user(SUBSCRIBE, data)
        update_data = data.copy()
        update_data["newsletters"] = {"slug": True}
        update_data["token"] = ANY
        ctms_mock.add.assert_called_with(update_data)
        confirm_mock.delay.assert_called_with(self.email, ANY, "en", "moz", None)

    def test_new_user_subscribes_to_mofo_newsletter(
        self,
        get_user_mock,
        ctms_mock,
        confirm_mock,
    ):
        """Subscribing to a MoFo-relevant newsletter makes the new user
        mofo-relevant."""
        get_user_mock.return_value = None  # Does not exist yet
        email_id = str(uuid4())
        ctms_mock.add.return_value = {"email": {"email_id": email_id}}
        models.Newsletter.objects.create(
            slug="mozilla-foundation",
            title="The Mozilla Foundation News",
            active=True,
            languages="en,fr",
            vendor_id="VENDOR1",
            requires_double_optin=False,
            is_mofo=True,
        )
        data = {
            "country": "US",
            "lang": "en",
            "newsletters": "mozilla-foundation",
            "email": self.email,
        }
        upsert_user(SUBSCRIBE, data)
        update_data = data.copy()
        update_data["newsletters"] = {"mozilla-foundation": True}
        update_data["mofo_relevant"] = True
        update_data["optin"] = True
        update_data["token"] = ANY
        ctms_mock.add.assert_called_with(update_data)
        update_data["email_id"] = email_id
        confirm_mock.delay.assert_not_called()

    def test_existing_user_subscribes_to_mofo_newsletter(
        self,
        get_user_mock,
        ctms_mock,
        confirm_mock,
    ):
        """Subscribing to a MoFo-relevant newsletter makes the user mofo-relevant."""
        user_data = self.get_user_data.copy()
        get_user_mock.return_value = user_data
        models.Newsletter.objects.create(
            slug="mozilla-foundation",
            title="The Mozilla Foundation News",
            active=True,
            languages="en,fr",
            vendor_id="VENDOR1",
            requires_double_optin=False,
            is_mofo=True,
        )
        data = {
            "country": "US",
            "lang": "en",
            "newsletters": "mozilla-foundation",
            "email": self.email,
        }
        upsert_user(SUBSCRIBE, data)
        update_data = data.copy()
        update_data["newsletters"] = {"mozilla-foundation": True}
        update_data["mofo_relevant"] = True
        update_data["optin"] = True
        ctms_mock.update.assert_called_with(user_data, update_data)
        confirm_mock.delay.assert_not_called()

    def test_existing_mofo_user_subscribes_to_mofo_newsletter(
        self,
        get_user_mock,
        ctms_mock,
        confirm_mock,
    ):
        """If a user is already MoFo-relevant, a subscription does not set it again."""
        user_data = self.get_user_data.copy()
        user_data["mofo_relevant"] = True
        get_user_mock.return_value = user_data
        models.Newsletter.objects.create(
            slug="mozilla-foundation",
            title="The Mozilla Foundation News",
            active=True,
            languages="en,fr",
            vendor_id="VENDOR1",
            requires_double_optin=False,
            is_mofo=True,
        )
        data = {
            "country": "US",
            "lang": "en",
            "newsletters": "mozilla-foundation",
            "email": self.email,
        }
        upsert_user(SUBSCRIBE, data)
        update_data = data.copy()
        update_data["newsletters"] = {"mozilla-foundation": True}
        update_data["optin"] = True
        ctms_mock.update.assert_called_with(user_data, update_data)
        confirm_mock.delay.assert_not_called()

    @patch("basket.news.tasks.send_acoustic_tx_messages")
    def test_send_transactional_old(self, acoustic_mock, get_user_mock, ctms_mock, confirm_mock):
        """Subscribing to a transactional should send a transactional email"""
        get_user_mock.return_value = None  # Does not exist yet
        data = {
            "country": "US",
            "lang": "en",
            "newsletters": "download-foo",
            "email": self.email,
        }
        with patch("basket.news.tasks.get_transactional_message_ids") as get_transactional_message_ids:
            get_transactional_message_ids.return_value = ["download-foo"]
            upsert_user(SUBSCRIBE, data)
            acoustic_mock.assert_called_with("dude@example.com", "en", ["download-foo"])
            ctms_mock.update.assert_not_called()

    @patch("basket.news.tasks.send_tx_messages")
    def test_send_transactional(self, braze_mock, get_user_mock, ctms_mock, confirm_mock):
        """Subscribing to a transactional should send a transactional email"""
        get_user_mock.return_value = None  # Does not exist yet
        data = {
            "country": "US",
            "lang": "en",
            "newsletters": "download-foo",
            "email": self.email,
        }
        with patch("basket.news.models.BrazeTxEmailMessage.objects.get_tx_message_ids") as get_tx_message_ids:
            get_tx_message_ids.return_value = ["download-foo"]
            upsert_user(SUBSCRIBE, data)
            braze_mock.assert_called_with("dude@example.com", "en", ["download-foo"])
            assert braze_mock.called
            ctms_mock.update.assert_not_called()

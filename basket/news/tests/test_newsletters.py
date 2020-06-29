# -*- coding: utf8 -*-

from django.test import TestCase

from basket.news import newsletters, utils
from basket.news.models import Newsletter, NewsletterGroup, LocalizedSMSMessage


class TestSMSMessageCache(TestCase):
    def setUp(self):
        newsletters.clear_sms_cache()
        LocalizedSMSMessage.objects.create(
            message_id="the-dude",
            vendor_id="YOURE_NOT_WRONG_WALTER",
            country="us",
            language="de",
        )
        LocalizedSMSMessage.objects.create(
            message_id="the-walrus",
            vendor_id="SHUTUP_DONNIE",
            country="gb",
            language="en-GB",
        )

    def test_all_messages(self):
        """Messages returned should be all of the ones in the DB."""

        self.assertEqual(
            newsletters.get_sms_messages(),
            {
                "the-dude-us-de": "YOURE_NOT_WRONG_WALTER",
                "the-walrus-gb-en-gb": "SHUTUP_DONNIE",
            },
        )


class TestNewsletterUtils(TestCase):
    def setUp(self):
        self.newsies = [
            Newsletter.objects.create(
                slug="bowling",
                title="Bowling, Man",
                vendor_id="BOWLING",
                languages="en",
            ),
            Newsletter.objects.create(
                slug="surfing",
                title="Surfing, Man",
                vendor_id="SURFING",
                languages="en",
            ),
            Newsletter.objects.create(
                slug="extorting",
                title="Beginning Nihilism",
                vendor_id="EXTORTING",
                languages="en",
            ),
            Newsletter.objects.create(
                slug="papers",
                title="Just papers, personal papers",
                vendor_id="CREEDENCE",
                languages="en",
                private=True,
            ),
        ]
        self.groupies = [
            NewsletterGroup.objects.create(
                slug="bowling", title="Bowling in Groups", active=True,
            ),
            NewsletterGroup.objects.create(
                slug="abiding", title="Be like The Dude", active=True,
            ),
            NewsletterGroup.objects.create(
                slug="failing", title="The Bums Lost!", active=False,
            ),
        ]
        self.groupies[0].newsletters.add(self.newsies[1], self.newsies[2])

    def test_newseltter_private_slugs(self):
        self.assertEqual(newsletters.newsletter_private_slugs(), ["papers"])

    def test_newsletter_slugs(self):
        self.assertEqual(
            set(newsletters.newsletter_slugs()),
            {"bowling", "surfing", "extorting", "papers"},
        )

    def test_newsletter_group_slugs(self):
        self.assertEqual(
            set(newsletters.newsletter_group_slugs()), {"bowling", "abiding"},
        )

    def test_newsletter_and_group_slugs(self):
        self.assertEqual(
            set(newsletters.newsletter_and_group_slugs()),
            {"bowling", "abiding", "surfing", "extorting", "papers"},
        )

    def test_newsletter_group_newsletter_slugs(self):
        self.assertEqual(
            set(newsletters.newsletter_group_newsletter_slugs("bowling")),
            {"extorting", "surfing"},
        )

    def test_parse_newsletters_for_groups(self):
        """If newsletter slug is a group for SUBSCRIBE, expand to group's newsletters."""
        subs = utils.parse_newsletters(utils.SUBSCRIBE, ["bowling"], list())
        self.assertTrue(subs["surfing"])
        self.assertTrue(subs["extorting"])

    def test_parse_newsletters_not_groups_set(self):
        """If newsletter slug is a group for SET mode, don't expand to group's newsletters."""
        subs = utils.parse_newsletters(utils.SET, ["bowling"], list())
        self.assertDictEqual(subs, {"bowling": True})

    def test_parse_newsletters_not_groups_unsubscribe(self):
        """If newsletter slug is a group for SET mode, don't expand to group's newsletters."""
        subs = utils.parse_newsletters(
            utils.UNSUBSCRIBE, ["bowling"], ["bowling", "surfing", "extorting"],
        )
        self.assertDictEqual(subs, {"bowling": False})

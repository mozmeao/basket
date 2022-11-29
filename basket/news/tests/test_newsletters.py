# -*- coding: utf8 -*-

from django.test import TestCase

from basket.news import newsletters, utils
from basket.news.models import Newsletter, NewsletterGroup


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
                slug="bowling",
                title="Bowling in Groups",
                active=True,
            ),
            NewsletterGroup.objects.create(
                slug="abiding",
                title="Be like The Dude",
                active=True,
            ),
            NewsletterGroup.objects.create(
                slug="failing",
                title="The Bums Lost!",
                active=False,
            ),
        ]
        self.groupies[0].newsletters.add(self.newsies[1], self.newsies[2])

    def test_newsletter_private_slugs(self):
        self.assertEqual(newsletters.newsletter_private_slugs(), ["papers"])

    def test_newsletter_slugs(self):
        self.assertEqual(
            set(newsletters.newsletter_slugs()),
            {"bowling", "surfing", "extorting", "papers"},
        )

    def test_newsletter_group_slugs(self):
        self.assertEqual(
            set(newsletters.newsletter_group_slugs()),
            {"bowling", "abiding"},
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
            utils.UNSUBSCRIBE,
            ["bowling"],
            ["bowling", "surfing", "extorting"],
        )
        self.assertDictEqual(subs, {"bowling": False})

    def test_parse_newsletters_private_with_set(self):
        """If newsletter is private for SET mode, that newsletter should be removed."""
        subs = utils.parse_newsletters(utils.SET, ["bowling", "papers"], list())
        self.assertDictEqual(subs, {"bowling": True})

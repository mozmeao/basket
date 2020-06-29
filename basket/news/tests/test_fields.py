from django.core.exceptions import ValidationError
from django.test import TestCase

from mock import call, Mock, patch

from basket.news.fields import CommaSeparatedEmailField


class CommaSeparatedEmailFieldTests(TestCase):
    def setUp(self):
        self.field = CommaSeparatedEmailField(blank=True)

    def test_validate(self):
        """
        Validate should run the email validator on all non-empty emails
        in the list.
        """
        with patch("basket.news.fields.validate_email") as validate_email:
            instance = Mock()
            self.field.attname = "blah"
            instance.blah = "  foo@example.com   ,bar@example.com   "
            self.field.pre_save(instance, False)
            validate_email.assert_has_calls([call("foo@example.com"), call("bar@example.com")])

            validate_email.reset_mock()
            instance.blah = "foo@example.com"
            self.field.pre_save(instance, False)
            validate_email.assert_has_calls([call("foo@example.com")])

            validate_email.reset_mock()
            instance.blah = ""
            self.field.pre_save(instance, False)
            self.assertFalse(validate_email.called)

    def test_invalid_email(self):
        instance = Mock()
        self.field.attname = "blah"
        instance.blah = "the.dude"
        with self.assertRaises(ValidationError):
            self.field.pre_save(instance, False)

    def test_pre_save(self):
        """pre_save should remove unnecessary whitespace and commas."""
        instance = Mock()
        self.field.attname = "blah"

        # Basic
        instance.blah = "bob@example.com,larry@example.com"
        self.assertEqual(self.field.pre_save(instance, False), "bob@example.com,larry@example.com")

        # Excess whitespace
        instance.blah = "   bob@example.com ,larry@example.com    "
        self.assertEqual(self.field.pre_save(instance, False), "bob@example.com,larry@example.com")

        # Extra commas
        instance.blah = "bob@example.com  ,,,, larry@example.com "
        self.assertEqual(self.field.pre_save(instance, False), "bob@example.com,larry@example.com")

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
        with patch('basket.news.fields.validate_email') as validate_email:
            self.field.validate('  foo@example.com   ,bar@example.com   ', None)
            validate_email.assert_has_calls([
                call('foo@example.com'),
                call('bar@example.com'),
            ])

            validate_email.reset_mock()
            self.field.validate('foo@example.com', None)
            validate_email.assert_has_calls([
                call('foo@example.com'),
            ])

            validate_email.reset_mock()
            self.field.validate('', None)
            self.assertFalse(validate_email.called)

    def test_pre_save(self):
        """pre_save should remove unnecessary whitespace and commas."""
        instance = Mock()
        self.field.attname = 'blah'

        # Basic
        instance.blah = 'bob@example.com,larry@example.com'
        self.assertEqual(self.field.pre_save(instance, False),
                         'bob@example.com,larry@example.com')

        # Excess whitespace
        instance.blah = '   bob@example.com ,larry@example.com    '
        self.assertEqual(self.field.pre_save(instance, False),
                         'bob@example.com,larry@example.com')

        # Extra commas
        instance.blah = 'bob@example.com  ,,,, larry@example.com '
        self.assertEqual(self.field.pre_save(instance, False),
                         'bob@example.com,larry@example.com')

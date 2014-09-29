from django.test import TestCase

from news.fields import CommaSeparatedEmailField


class CommaSeparatedEmailFieldTests(TestCase):
    def setUp(self):
        self.field = CommaSeparatedEmailField()

    def test_to_python(self):
        # List
        self.assertEqual(self.field.to_python(['a@example.com', 'b@example.com']),
                         ['a@example.com', 'b@example.com'])

        # None
        self.assertEqual(self.field.to_python(None), [])

        # String
        self.assertEqual(self.field.to_python('bob@example.com,phil@example.com'),
                         ['bob@example.com', 'phil@example.com'])

        # String with whitespace
        self.assertEqual(self.field.to_python('  a@example.com, b@example.com   '),
                         ['a@example.com', 'b@example.com'])

from django.core.exceptions import ValidationError

import pytest

from basket.base.forms import EmailListField


class TestEmailListField:
    def setup_method(self):
        self.field = EmailListField()

    def test_to_python_empty(self):
        assert self.field.to_python("") == []

    def test_to_python_single_email(self):
        assert self.field.to_python("test@example.com") == ["test@example.com"]

    def test_to_python_multiple_emails(self):
        value = "test1@example.com\ntest2@example.com\n"
        assert self.field.to_python(value) == ["test1@example.com", "test2@example.com"]

    def test_to_python_with_whitespace(self):
        value = "  test1@example.com  \n  test2@example.com  \n"
        assert self.field.to_python(value) == ["test1@example.com", "test2@example.com"]

    def test_to_python_with_empty(self):
        value = "  test1@example.com  \n\n  test2@example.com  \n"
        assert self.field.to_python(value) == ["test1@example.com", "test2@example.com"]

    def test_validate_invalid_emails(self):
        value = ["test1@example.com", "invalid-email"]
        with pytest.raises(ValidationError) as excinfo:
            self.field.validate(value)
        assert "Invalid email: invalid-email" in str(excinfo.value)

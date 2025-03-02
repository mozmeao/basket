from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import validate_email


class EmailListField(forms.Field):
    def to_python(self, value):
        """Normalize data to a list of strings."""
        if not value:
            return []

        return [email.strip() for email in value.splitlines() if email.strip()]

    def validate(self, value):
        """Check if value consists only of valid emails."""
        super().validate(value)
        errors = []
        for email in value:
            try:
                validate_email(email)
            except ValidationError:
                errors.append(f"Invalid email: {email}")
        if errors:
            raise ValidationError(errors)


class EmailListForm(forms.Form):
    emails = EmailListField(
        widget=forms.Textarea(attrs={"rows": 10, "placeholder": "Enter emails separated by newlines"}),
        required=True,
        help_text="Enter one email per line",
    )


class EmailForm(forms.Form):
    email = forms.EmailField()

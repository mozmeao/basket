from django.core.validators import validate_email
from django.db import models
from django.forms import TextInput

from product_details import product_details


class CommaSeparatedEmailField(models.TextField):
    """TextField that stores a comma-separated list of emails."""
    __metaclass__ = models.SubfieldBase

    def validate(self, value, model_instance):
        super(CommaSeparatedEmailField, self).validate(value, model_instance)

        # Validate that all non-empty emails are valid.
        for email in value.split(','):
            if email:
                validate_email(email.strip())

    def pre_save(self, model_instance, add):
        """Remove whitespace and excess commas."""
        emails = getattr(model_instance, self.attname).split(',')
        return ','.join(email.strip() for email in emails if email)

    def formfield(self, **kwargs):
        kwargs['widget'] = TextInput(attrs={'style': 'width: 400px'})
        return super(CommaSeparatedEmailField, self).formfield(**kwargs)


ENGLISH_LANGUAGE_CHOICES = sorted(
    [(key, u'{0} ({1})'.format(key, value['English']))
     for key, value in product_details.languages.items()]
)


class LocaleField(models.CharField):
    description = 'CharField for storing a locale code.'

    def __init__(self, *args, **kwargs):
        defaults = {
            'max_length': 32,
            'choices': ENGLISH_LANGUAGE_CHOICES,
        }
        for key, value in defaults.items():
            kwargs.setdefault(key, value)

        return super(LocaleField, self).__init__(*args, **kwargs)

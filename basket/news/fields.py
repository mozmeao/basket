from django.core.validators import validate_email
from django.db import models
from django.forms import TextInput

from product_details import product_details

from basket.news.country_codes import SFDC_COUNTRIES


def parse_emails(emails_string):
    emails = []
    for email in emails_string.split(','):
        email = email.strip()
        if email:
            validate_email(email)
            emails.append(email)

    return emails


class CommaSeparatedEmailField(models.TextField):
    """TextField that stores a comma-separated list of emails."""
    def pre_save(self, model_instance, add):
        """Remove whitespace and excess commas."""
        emails = getattr(model_instance, self.attname)
        emails = ','.join(parse_emails(emails))
        setattr(model_instance, self.attname, emails)
        return emails

    def formfield(self, **kwargs):
        kwargs['widget'] = TextInput(attrs={'style': 'width: 400px'})
        return super(CommaSeparatedEmailField, self).formfield(**kwargs)


ENGLISH_LANGUAGE_CHOICES = sorted(
    [(key, '{0} ({1})'.format(key, value['English']))
     for key, value in product_details.languages.items()]
)
COUNTRY_CHOICES = sorted(
    [(key, '{0} ({1})'.format(key, value))
     for key, value in SFDC_COUNTRIES.items()]
)


class CountryField(models.CharField):
    description = 'CharField for storing a country code.'

    def __init__(self, *args, **kwargs):
        defaults = {
            'max_length': 3,
            'choices': COUNTRY_CHOICES,
        }
        for key, value in defaults.items():
            kwargs.setdefault(key, value)

        return super(CountryField, self).__init__(*args, **kwargs)


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

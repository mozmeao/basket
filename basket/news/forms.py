import re

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

from basket.news.country_codes import SFDC_COUNTRIES
from basket.news.newsletters import newsletter_field_choices
from basket.news.utils import parse_newsletters_csv, process_email, LANG_RE


FORMATS = (('H', 'HTML'), ('T', 'Text'))
SOURCE_URL_RE = re.compile(r'^https?://')


class EmailForm(forms.Form):
    """Form to validate email addresses"""
    email = forms.EmailField()


class EmailField(forms.CharField):
    """EmailField with better validation and value cleaning"""
    def to_python(self, value):
        value = super(EmailField, self).to_python(value)
        email = process_email(value)
        if not email:
            raise ValidationError('Enter a valid email address.', 'invalid')

        return email


class NewslettersField(forms.MultipleChoiceField):
    """
    Django form field that validates the newsletter IDs are valid

    * Accepts single newsletter IDs in multiple fields, and/or
      a comma separated list of newsletter IDs in a single field.
    * Validates each individual newsletter ID.
    * Includes newsletter group IDs.
    """
    def __init__(self, required=True, widget=None, label=None, initial=None,
                 help_text='', *args, **kwargs):
        super(NewslettersField, self).__init__(newsletter_field_choices, required, widget, label,
                                               initial, help_text, *args, **kwargs)

    def to_python(self, value):
        value = super(NewslettersField, self).to_python(value)
        full_list = []
        for v in value:
            full_list.extend(parse_newsletters_csv(v))

        return full_list


def country_choices():
    """Upper and Lower case country codes"""
    return SFDC_COUNTRIES.items() + [(code.upper(), name) for code, name in SFDC_COUNTRIES.iteritems()]


UTC_DATETIME_FORMATS = ['%Y-%m-%dT%H:%M:%SZ']


class CommonVoiceForm(forms.Form):
    email = EmailField()
    days_interval = forms.IntegerField(required=False)
    created_at = forms.DateTimeField(input_formats=UTC_DATETIME_FORMATS, required=False)
    goal_reached_at = forms.DateTimeField(input_formats=UTC_DATETIME_FORMATS, required=False)
    first_contribution_date = forms.DateTimeField(input_formats=UTC_DATETIME_FORMATS, required=False)


class SubscribeForm(forms.Form):
    email = EmailField()
    newsletters = NewslettersField()
    privacy = forms.BooleanField()
    fmt = forms.ChoiceField(required=False, choices=FORMATS)
    source_url = forms.CharField(required=False)
    first_name = forms.CharField(required=False)
    last_name = forms.CharField(required=False)
    country = forms.ChoiceField(required=False, choices=country_choices)
    lang = forms.CharField(required=False, validators=[RegexValidator(regex=LANG_RE)])

    def clean_source_url(self):
        source_url = self.cleaned_data['source_url']
        if source_url:
            if SOURCE_URL_RE.match(source_url):
                return source_url

        return ''

    def clean_country(self):
        country = self.cleaned_data['country']
        if country:
            return country.lower()

        return country


class UpdateUserMeta(forms.Form):
    source_url = forms.CharField(required=False)
    first_name = forms.CharField(required=False)
    last_name = forms.CharField(required=False)
    country = forms.ChoiceField(required=False, choices=country_choices)
    lang = forms.CharField(required=False, validators=[RegexValidator(regex=LANG_RE)])

    def clean_country(self):
        country = self.cleaned_data['country']
        if country:
            return country.lower()

        return country

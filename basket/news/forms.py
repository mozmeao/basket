from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from product_details import product_details

from basket.news.newsletters import newsletter_field_choices
from basket.news.utils import parse_newsletters_csv, process_email, LANG_RE


FORMATS = (('H', 'HTML'), ('T', 'Text'))


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
    regions = product_details.get_regions('en-US')
    return regions.iteritems()


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

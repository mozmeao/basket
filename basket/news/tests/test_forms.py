from mock import patch

from basket.news import forms


@patch.object(forms, 'process_email')
def test_email_validation(email_mock):
    email_mock.return_value = None
    form = forms.SubscribeForm({
        'newsletters': ['dude'],
        'email': 'dude@example.com',
        'privacy': 'true',
    })
    form.fields['newsletters'].choices = (('dude', 'dude'), ('walter', 'walter'))
    assert not form.is_valid()
    assert 'email' in form.errors

    email_mock.return_value = 'dude@example.com'
    form = forms.SubscribeForm({
        'newsletters': ['dude'],
        'email': 'dude@example.com',
        'privacy': 'true',
    })
    form.fields['newsletters'].choices = (('dude', 'dude'), ('walter', 'walter'))
    assert form.is_valid(), form.errors

    # should result in whatever email process_email returns
    email_mock.return_value = 'walter@example.com'
    form = forms.SubscribeForm({
        'newsletters': ['dude'],
        'email': 'dude@example.com',
        'privacy': 'true',
    })
    form.fields['newsletters'].choices = (('dude', 'dude'), ('walter', 'walter'))
    assert form.is_valid(), form.errors
    assert form.cleaned_data['email'] == 'walter@example.com'


@patch.object(forms, 'process_email', return_value='dude@example.com')
def test_newsletters_validation(email_mock):
    # comma separated in just one field
    form = forms.SubscribeForm({
        'newsletters': ['dude, walter'],
        'email': 'dude@example.com',
        'privacy': 'true',
    })
    form.fields['newsletters'].choices = (('dude', 'dude'), ('walter', 'walter'))
    assert form.is_valid(), form.errors
    assert form.cleaned_data['newsletters'] == ['dude', 'walter']

    # separate fields
    form = forms.SubscribeForm({
        'newsletters': ['dude', 'walter'],
        'email': 'dude@example.com',
        'privacy': 'true',
    })
    form.fields['newsletters'].choices = (('dude', 'dude'), ('walter', 'walter'))
    assert form.is_valid(), form.errors
    assert form.cleaned_data['newsletters'] == ['dude', 'walter']

    # combo of comma separated and non
    form = forms.SubscribeForm({
        'newsletters': ['dude', 'walter,donnie'],
        'email': 'dude@example.com',
        'privacy': 'true',
    })
    form.fields['newsletters'].choices = (('dude', 'dude'),
                                          ('walter', 'walter'),
                                          ('donnie', 'donnie'))
    assert form.is_valid(), form.errors
    assert form.cleaned_data['newsletters'] == ['dude', 'walter', 'donnie']

    # invalid newsletter
    form = forms.SubscribeForm({
        'newsletters': ['dude, walter'],
        'email': 'dude@example.com',
        'privacy': 'true',
    })
    form.fields['newsletters'].choices = (('dude', 'dude'),)
    assert not form.is_valid()
    assert 'newsletters' in form.errors


@patch.object(forms, 'process_email', return_value='dude@example.com')
def test_privacy_required(email_mock):
    form = forms.SubscribeForm({
        'newsletters': ['dude, walter'],
        'email': 'dude@example.com',
    })
    form.fields['newsletters'].choices = (('dude', 'dude'),)
    assert not form.is_valid()
    assert 'privacy' in form.errors

    form = forms.SubscribeForm({
        'newsletters': ['dude, walter'],
        'email': 'dude@example.com',
        'privacy': 'false',
    })
    form.fields['newsletters'].choices = (('dude', 'dude'),)
    assert not form.is_valid()
    assert 'privacy' in form.errors

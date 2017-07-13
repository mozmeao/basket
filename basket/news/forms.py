from django import forms


class EmailForm(forms.Form):
    """Form to validate email addresses"""
    email = forms.EmailField()

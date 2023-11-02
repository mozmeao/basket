from django import forms

from basket.petition.models import Petition


class PetitionForm(forms.ModelForm):
    class Meta:
        model = Petition
        fields = ["name", "email", "title", "affiliation"]

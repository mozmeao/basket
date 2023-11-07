from django import forms

from basket.petition.models import Petition


class PetitionForm(forms.ModelForm):
    title = forms.CharField(required=True)
    affiliation = forms.CharField(required=True)

    class Meta:
        model = Petition
        fields = ["name", "email", "title", "affiliation"]

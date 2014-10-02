from django.core.validators import validate_email
from django.db import models

from south.modelsinspector import add_introspection_rules


class CommaSeparatedEmailField(models.TextField):
    """TextField that stores a comma-separated list of emails."""
    __metaclass__ = models.SubfieldBase

    def validate(self, value, model_instance):
        super(CommaSeparatedEmailField, self).validate(value, model_instance)
        for email in value:
            validate_email(email)

    def to_python(self, value):
        if isinstance(value, list):
            return value
        elif value is None:
            return []
        else:
            return [email.strip() for email in value.split(',')]

    def get_prep_value(self, value):
        return ','.join(value)


add_introspection_rules([], ['^news\.fields\.CommaSeparatedEmailField'])

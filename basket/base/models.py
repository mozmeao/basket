from django.db import models


class DSARPermissions(models.Model):
    class Meta:
        managed = False  # Disable database table creation.
        default_permissions = ()  # Disable default permissions.
        permissions = (("dsar_access", "DSAR access"),)

    def __str__(self) -> str:
        return "DSARPermissions"

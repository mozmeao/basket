from django.db import migrations


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="DSARPermissions",
            fields=[],
            options={
                "permissions": (("dsar_access", "DSAR access"),),
                "managed": False,
                "default_permissions": (),
            },
        ),
    ]

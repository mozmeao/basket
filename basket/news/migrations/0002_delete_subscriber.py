from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("news", "0001_initial"),
    ]

    operations = [
        migrations.DeleteModel(name="Subscriber"),
    ]

# Generated by Django 3.2.16 on 2023-01-25 15:02

from django.db import migrations, models


def set_waitlist_field(apps, schema_editor):
    """
    Instead of hard-coding which newsletters are waitlists,
    we now set a flag.
    """
    Newsletter = apps.get_model("news", "Newsletter")
    for newsletter in Newsletter.objects.all():
        if newsletter.slug.endswith("-waitlist"):
            newsletter.is_waitlist = True
            newsletter.save()


class Migration(migrations.Migration):
    dependencies = [
        ("news", "0025_auto_20220308_1803"),
    ]

    operations = [
        migrations.AddField(
            model_name="newsletter",
            name="is_waitlist",
            field=models.BooleanField(
                default=False,
                help_text="True if the newsletter is a waiting list. A waitlist can have additional arbitrary fields.",
            ),
        ),
        migrations.RunPython(set_waitlist_field),
    ]

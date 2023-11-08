import codecs
import csv
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_datetime

from basket.petition.models import Petition


class Command(BaseCommand):
    help = "Import signatures from a CSV file"  # noqa: A003

    def add_arguments(self, parser):
        parser.add_argument("csv_file", type=str, help="Path to CSV file")

    def handle(self, *args, **options):
        csv_file = options["csv_file"]

        with codecs.open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader)  # skip header

            count = 0
            for row in reader:
                if len(row) != 8:
                    raise CommandError("Invalid row: %s" % row)

                name, affiliation, email, title, created, tag, _, notes = (f.strip() for f in row)

                if name and (affiliation or email):
                    created = parse_datetime(created)
                    if not email:
                        email = "not-provided@null.com"
                    vip = tag == "VIP"

                    try:
                        Petition.objects.create(
                            name=name,
                            email=email,
                            title=title,
                            affiliation=affiliation,
                            created=created,
                            user_agent="Imported from CSV",
                            token=uuid.uuid4(),
                            approved=True,
                            vip=vip,
                        )
                    except Exception as e:
                        print(f"Error importing row: {row}: {e}")  # noqa: T201

                    count += 1

            print(f"Imported {count} signatures")  # noqa: T201

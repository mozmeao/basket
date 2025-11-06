import json
import sys
import time

from django.core.management.base import BaseCommand, CommandError

import pandas as pd
from google.cloud import storage

from basket.news.backends.braze import braze


class Command(BaseCommand):
    help = "Migrator utility to fetch external_ids from a Parquet file in GCS and migrate them to updated UUIDs."

    def add_arguments(self, parser):
        parser.add_argument("--project", type=str, required=False, help="Project ID")
        parser.add_argument("--bucket", type=str, required=True, help="GCS Storage Bucket")
        parser.add_argument("--prefix", type=str, required=True, help="GCS Storage Prefix")
        parser.add_argument("--file", type=str, required=True, help="Name of file to migrate")
        parser.add_argument(
            "--start_timestamp",
            type=str,
            required=False,
            help="create_timestamp to start from",
        )
        parser.add_argument(
            "--chunk_size",
            type=int,
            required=False,
            default=50,
            help="Number of records per migration batch, 50 max",
        )

    def handle(self, **options):
        project = options.get("project")
        bucket = options["bucket"]
        prefix = options["prefix"]
        file_name = options["file"]
        start_timestamp = options.get("start_timestamp")
        chunk_size = options["chunk_size"]
        try:
            self.process_and_migrate_parquet_file(project, bucket, prefix, file_name, start_timestamp, chunk_size)
        except Exception as err:
            raise CommandError(f"Error processing Parquet file: {str(err)}") from err

    def process_and_migrate_parquet_file(self, project, bucket, prefix, file_name, start_timestamp, chunk_size):
        client = storage.Client(project=project)
        blob = client.bucket(bucket).blob(f"{prefix}/{file_name}")
        if not blob.exists():
            raise CommandError(f"File '{file_name}' not found in bucket '{bucket}' with prefix '{prefix}'")
        df = self.read_parquet_blob(blob)
        if start_timestamp and "create_timestamp" in df.columns:
            df = df[df["create_timestamp"] >= start_timestamp]
        migrations = self.build_migrations(df)

        for i in range(0, len(migrations), chunk_size):
            chunk = migrations[i : i + chunk_size]
            braze_fxa_alias_chunk = self.strip_for_braze_fxa_alias(chunk)
            braze_migration_chunk = self.strip_for_braze_migration(chunk)
            try:
                if braze_fxa_alias_chunk:
                    braze.interface.add_aliases(braze_fxa_alias_chunk)

                migrate_response = braze.interface.migrate_external_id(braze_migration_chunk)

                if not migrate_response["braze_collected_response"]["external_ids"]:
                    # If no external_ids are migrated we assume we are done.
                    self.stdout.write(self.style.SUCCESS(f"Migration complete. Ended on email_id {chunk[-1]['current_external_id']}."))
                    sys.exit(0)

                time.sleep(0.07)
            except Exception as e:
                failure = {
                    "current_external_id": self.mask(chunk[0]["current_external_id"]),
                    "new_external_id": self.mask(chunk[0]["new_external_id"]),
                    "create_timestamp": str(chunk[0].get("create_timestamp", "")),
                    "reason": str(e),
                }
                self.stdout.write(self.style.ERROR(json.dumps(failure, indent=2)))
                raise CommandError("Migration failed. Process terminated error.") from None

    def strip_for_braze_migration(self, chunk):
        return [
            {
                "current_external_id": item["current_external_id"],
                "new_external_id": item["new_external_id"],
            }
            for item in chunk
        ]

    def strip_for_braze_fxa_alias(self, chunk):
        return [
            {
                "external_id": item["current_external_id"],
                "alias_name": "fxa_id",
                "alias_label": item["fxa_id"],
            }
            for item in chunk
            if item.get("fxa_id")
        ]

    def mask(self, external_id):
        parts = str(external_id).split("-")
        return "-".join(["***"] * 3 + parts[3:])

    def read_parquet_blob(self, blob):
        data = blob.download_as_bytes()
        return pd.read_parquet(pd.io.common.BytesIO(data))

    def build_migrations(self, df):
        return [
            {
                "current_external_id": row.email_id,
                "new_external_id": row.basket_token,
                "create_timestamp": getattr(row, "create_timestamp", ""),
                "fxa_id": getattr(row, "fxa_id", ""),
            }
            for row in df.itertuples(index=False)
        ]

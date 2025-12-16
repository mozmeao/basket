import logging
import tempfile
import time

from django.core.management.base import BaseCommand, CommandError

import pyarrow.parquet as pq
import sentry_sdk
from google.cloud import storage

from basket.base.rq import get_queue
from basket.news.backends.braze import braze
from basket.news.management.commands.alias_migration.lib import (
    build_alias_operations_from_dataframe,
    create_batched_chunks,
    fake_add_aliases,
    mask,
)

log = logging.getLogger(__name__)


def process_migration_batch(
    batch,
    batch_index,
    file_name,
    use_fake_braze=False,
):
    """
    RQ job function to process a batch of chunks.
    batch is a list of chunks, where each chunk is a list of migration items.
    """
    try:
        processed_count = 0

        for chunk in batch:
            if use_fake_braze:
                fake_add_aliases(chunk)
            else:
                braze.interface.add_aliases(chunk)
            time.sleep(0.003)
            processed_count += len(chunk)

        log.info(f"Successfully processed batch (batch index {batch_index}) with {len(batch)} chunks, {processed_count} total items")

    except Exception as e:
        first_external_id = mask(batch[0][0]["external_id"])
        message = (f"Batch starting with external_id={first_external_id} from file {file_name} has failed.",)
        sentry_sdk.capture_exception(
            e,
            extra={"message": message},
        )
        log.error(message)


class Command(BaseCommand):
    help = "Migrator utility to fetch external_ids from a Parquet file in GCS and aliases to them in Braze."

    def add_arguments(self, parser):
        parser.add_argument("--project", type=str, required=False, help="Project ID")
        parser.add_argument("--bucket", type=str, required=True, help="GCS Storage Bucket")
        parser.add_argument("--files", type=str, required=True, help="Comma separated list of files to migrate")
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
        parser.add_argument(
            "--batch-size",
            type=int,
            required=False,
            default=100,
            help="Number of chunks to be processed in a single job by a worker",
        )
        parser.add_argument(
            "--use-fake-braze",
            action="store_true",
            help="Use a fake Braze call instead of actually hitting Braze (for testing)",
        )

    def handle(self, **options):
        project = options.get("project")
        bucket = options["bucket"]
        files = options["files"].split(",")
        start_timestamp = options.get("start_timestamp")
        chunk_size = options["chunk_size"]
        batch_size = options["batch_size"]
        use_fake_braze = options["use_fake_braze"]

        try:
            for file in files:
                self.process_and_migrate_parquet_file(
                    project,
                    bucket,
                    file,
                    start_timestamp,
                    chunk_size,
                    batch_size,
                    use_fake_braze,
                )
        except Exception as err:
            raise CommandError(f"Error processing Parquet file: {str(err)}") from err

    def process_and_migrate_parquet_file(
        self,
        project,
        bucket,
        file,
        start_timestamp,
        chunk_size,
        batch_size,
        use_fake_braze,
    ):
        client = storage.Client(project=project)
        blob = client.bucket(bucket).blob(file)
        if not blob.exists():
            raise CommandError(f"File '{file}' not found in bucket '{bucket}'")

        queue = get_queue()
        previous_job = None

        for df in self.read_parquet_blob(blob, chunk_size, batch_size):
            if start_timestamp and "create_timestamp" in df.columns:
                df = df[df["create_timestamp"] >= start_timestamp]
            alias_operations = build_alias_operations_from_dataframe(df)
            batches = create_batched_chunks(
                alias_operations,
                batch_size,
                chunk_size,
            )

            for batch_index, batch in enumerate(batches):
                total_items_in_batch = sum(len(chunk) for chunk in batch)

                # Create job with dependency on previous job so they execute sequentially
                if previous_job is None:
                    job = queue.enqueue(
                        process_migration_batch,
                        batch,
                        batch_index,
                        file,
                        use_fake_braze,
                        job_timeout="30m",  # Increased timeout
                    )
                else:
                    job = queue.enqueue(
                        process_migration_batch,
                        batch,
                        batch_index,
                        file,
                        use_fake_braze,
                        depends_on=previous_job,
                        job_timeout="30m",
                    )

                previous_job = job

                self.stdout.write(f"Queued job {job.id} for file {file}, batch {batch_index + 1}: {len(batch)} chunks, {total_items_in_batch} items")

    def read_parquet_blob(self, blob, chunk_size, batch_size):
        with tempfile.NamedTemporaryFile() as tmp_file:
            blob.download_to_filename(tmp_file.name)

            parquet_file = pq.ParquetFile(tmp_file.name)
            for batch in parquet_file.iter_batches(batch_size=chunk_size * batch_size):
                df_chunk = batch.to_pandas()
                yield df_chunk

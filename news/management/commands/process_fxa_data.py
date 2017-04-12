from __future__ import print_function, unicode_literals

from email.utils import formatdate

from django.conf import settings
from django.core.cache import cache
from django.core.management import BaseCommand, CommandError

import babis
import boto3
from apscheduler.schedulers.blocking import BlockingScheduler
from django_statsd.clients import statsd
from pathlib2 import Path
from pytz import utc
from raven.contrib.django.raven_compat.models import client as sentry_client

from news.backends.sfmc import sfmc, NewsletterException


TMP = Path('/tmp')
BUCKET_DIR = 'fxa-last-active-timestamp/data'
DATA_PATH = TMP.joinpath(BUCKET_DIR)
FXA_IDS = {}
FILE_DONE_KEY = 'fxa_activity:completed:%s'
TWO_WEEKS = 60 * 60 * 24 * 14
schedule = BlockingScheduler(timezone=utc)


def _fxa_id_key(fxa_id):
    return 'fxa_activity:%s' % fxa_id


def get_fxa_time(fxa_id):
    fxatime = FXA_IDS.get(fxa_id)
    if fxatime is None:
        fxatime = cache.get(_fxa_id_key(fxa_id))
        if fxatime:
            FXA_IDS[fxa_id] = fxatime

    return fxatime or 0


def set_fxa_time(fxa_id, fxa_time):
    try:
        sfmc.upsert_row(settings.FXA_SFMC_DE, {
            'FXA_ID': fxa_id,
            'Timestamp': formatdate(timeval=fxa_time, usegmt=True),
        })
    except NewsletterException:
        sentry_client.captureException()
        # try again later
        return

    FXA_IDS[fxa_id] = fxa_time
    cache.set(_fxa_id_key(fxa_id), fxa_time, timeout=TWO_WEEKS)


def file_is_done(pathobj):
    return bool(cache.get(FILE_DONE_KEY % pathobj.name))


def set_file_done(pathobj):
    # cache done state for 2 weeks. files stay in s3 bucket for 1 week
    cache.set(FILE_DONE_KEY % pathobj.name, 1, timeout=TWO_WEEKS)


def update_fxa_data(current_timestamps):
    """Store the updated timestamps in a local dict, the cache, and SFMC."""
    update_count = 0
    print('attempting to update %s fxa timestamps' % len(current_timestamps))
    for fxaid, timestamp in current_timestamps.iteritems():
        curr_ts = get_fxa_time(fxaid)
        if timestamp > curr_ts:
            update_count += 1
            set_fxa_time(fxaid, timestamp)

    print('updated %s fxa timestamps' % update_count)
    statsd.gauge('process_fxa_data.updates', update_count)


def download_fxa_files():
    s3 = boto3.resource('s3',
                        aws_access_key_id=settings.FXA_ACCESS_KEY_ID,
                        aws_secret_access_key=settings.FXA_SECRET_ACCESS_KEY)
    bucket = s3.Bucket(settings.FXA_S3_BUCKET)
    for obj in bucket.objects.filter(Prefix=BUCKET_DIR):
        print('found %s in s3 bucket' % obj.key)
        tmp_path = TMP.joinpath(obj.key)
        if not tmp_path.name.endswith('.csv'):
            continue

        if file_is_done(tmp_path):
            continue

        if not tmp_path.exists():
            print('getting ' + obj.key)
            print('size is %s' % obj.size)
            tmp_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                bucket.download_file(obj.key, str(tmp_path))
                print('downloaded %s' % tmp_path)
            except Exception:
                # something went wrong, delete file
                print('bad things happened. deleting %s' % tmp_path)
                tmp_path.unlink()


def get_fxa_data():
    all_fxa_times = {}
    data_files = DATA_PATH.glob('*.csv')
    for tmp_path in sorted(data_files):
        if file_is_done(tmp_path):
            continue

        print('loading data from %s' % tmp_path)
        # collect all of the latest timestamps from all files in a dict first
        # to ensure that we have the minimum data set to compare against SFMC
        with tmp_path.open() as fxafile:
            file_count = 0
            for line in fxafile:
                file_count += 1
                fxaid, timestamp = line.strip().split(',')
                curr_ts = all_fxa_times.get(fxaid, 0)
                timestamp = int(timestamp)
                if timestamp > curr_ts:
                    all_fxa_times[fxaid] = timestamp

            if file_count < 1000000:
                # if there were fewer than 1M rows we probably got a truncated file
                # try again later (typically they contain 20M)
                print('possibly truncated file: %s' % tmp_path)
            else:
                set_file_done(tmp_path)

            # done with file either way
            tmp_path.unlink()

    return all_fxa_times


@schedule.scheduled_job('cron', id='process_fxa_data', hour=1, minute=0, max_instances=1)
@babis.decorator(ping_before=settings.FXA_SNITCH_URL, fail_silenty=True)
def main():
    download_fxa_files()
    update_fxa_data(get_fxa_data())


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('--cron', action='store_true', default=False,
                            help='Run the cron schedule instead of just once')

    def handle(self, *args, **options):
        if not all(getattr(settings, name) for name in ['FXA_ACCESS_KEY_ID',
                                                        'FXA_SECRET_ACCESS_KEY',
                                                        'FXA_S3_BUCKET']):
            raise CommandError('FXA S3 Bucket access not configured')

        if options['cron']:
            print('cron schedule starting')
            schedule.start()
        else:
            main()

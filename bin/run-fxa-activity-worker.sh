#!/bin/bash -ex

exec python manage.py process_fxa_data --cron

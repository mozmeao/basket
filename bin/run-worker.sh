#!/bin/bash -ex

NEW_RELIC_CONFIG_FILE=newrelic.ini newrelic-admin run-program \
python manage.py rqworker --max-jobs "${RQ_MAX_JOBS:-5000}" --with-scheduler

#!/bin/bash -ex

NEW_RELIC_CONFIG_FILE=newrelic.ini newrelic-admin run-program \
python manage.py rqworker --with-scheduler

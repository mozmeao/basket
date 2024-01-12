#!/bin/bash -ex

echo "$GIT_SHA" > static/revision.txt
NEW_RELIC_CONFIG_FILE=newrelic.ini newrelic-admin run-program \
    uwsgi --ini /app/bin/uwsgi.ini

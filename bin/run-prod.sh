#!/bin/bash -ex

echo "$GIT_SHA" > static/revision.txt
NEW_RELIC_CONFIG_FILE=newrelic.ini newrelic-admin run-program \
granian \
    --interface wsgi \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --no-ws \
    --workers "${WSGI_NUM_WORKERS:-8}" \
    basket.wsgi:application

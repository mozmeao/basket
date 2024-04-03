#!/bin/bash -ex

function run-gunicorn () {
    if [[ -z "$NEW_RELIC_LICENSE_KEY" ]]; then
        exec gunicorn "$@"
    else
        export NEW_RELIC_CONFIG_FILE=newrelic.ini
        exec newrelic-admin run-program gunicorn "$@"
    fi
}

echo "$GIT_SHA" > static/revision.txt

run-gunicorn basket.wsgi:application --config basket/wsgi_config.py

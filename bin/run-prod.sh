#!/bin/bash -ex

echo "$GIT_SHA" > static/revision.txt
exec NEW_RELIC_CONFIG_FILE=newrelic.ini newrelic-admin run-program \
gunicorn basket.wsgi --bind "0.0.0.0:${PORT:-8000}" \
                     --workers "${WSGI_NUM_WORKERS:-8}" \
                     --worker-class "${WSGI_WORKER_CLASS:-meinheld.gmeinheld.MeinheldWorker}" \
                     --log-level "${WSGI_LOG_LEVEL:-info}" \
                     --error-logfile - \
                     --access-logfile -

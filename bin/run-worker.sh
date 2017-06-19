#!/bin/bash -ex

exec newrelic-admin run-program celery -A news worker \
                                       -P "${CELERY_POOL:-prefork}" \
                                       -l "${CELERY_LOG_LEVEL:-warning}" \
                                       -c "${CELERY_NUM_WORKERS:-4}"
                                       -Q celery,snitch

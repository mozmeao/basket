#!/bin/bash

exec newrelic-admin run-program celery -A news worker \
                                       -l "${CELERY_LOG_LEVEL:-warning}" \
                                       -c "${CELERY_NUM_WORKERS:-4}"

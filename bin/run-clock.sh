#!/bin/bash -ex

exec celery -A news beat -l "${CELERY_LOG_LEVEL:-warning}"

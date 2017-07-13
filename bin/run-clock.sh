#!/bin/bash -ex

exec celery -A basket.news beat -l "${CELERY_LOG_LEVEL:-warning}"

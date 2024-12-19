#!/bin/bash -ex

python manage.py migrate --noinput

granian \
    --interface wsgi \
    --host "0.0.0.0" \
    --port "8000" \
    --no-ws \
    --workers "1" \
    --threads "1" \
    --log-level "${GRANIAN_LOG_LEVEL:-debug}" \
    --access-log \
    --reload \
    basket.wsgi:application

#!/bin/bash -ex

python manage.py rqworker --max-jobs "${RQ_MAX_JOBS:-5000}" --with-scheduler

#!/bin/bash

set -exo pipefail

ruff check basket/
black --check basket/
urlwait
python manage.py makemigrations | grep "No changes detected"
python manage.py migrate --noinput
py.test basket \
  --cov-config=.coveragerc \
  --cov-report=html \
  --cov-report=term-missing \
  --cov-report=xml:python_coverage/coverage.xml \
  --cov=.

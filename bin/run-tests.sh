#!/bin/bash

set -exo pipefail

flake8 basket
urlwait
python manage.py makemigrations | grep "No changes detected"
bin/post-deploy.sh
py.test --junitxml=test-results/test-results.xml basket

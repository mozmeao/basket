#!/bin/bash

set -exo pipefail

flake8 basket
bin/post-deploy.sh
py.test --junitxml=test-results/test-results.xml basket

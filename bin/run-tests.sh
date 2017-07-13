#!/bin/bash

flake8 basket
urlwait
bin/post-deploy.sh
py.test --junitxml=test-results/test-results.xml basket

#!/bin/bash

flake8 news
urlwait
bin/post-deploy.sh
py.test --junitxml=test-results/test-results.xml news

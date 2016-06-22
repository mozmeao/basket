#!/bin/bash

urlwait
bin/post-deploy.sh
py.test --junitxml=test-results/test-results.xml news

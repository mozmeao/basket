#!/bin/bash

set -ex

urlwait
bin/run-common.sh

./manage.py runserver 0.0.0.0:8000

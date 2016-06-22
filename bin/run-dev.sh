#!/bin/bash

set -ex

urlwait
bin/post-deploy.sh
./manage.py runserver 0.0.0.0:8000

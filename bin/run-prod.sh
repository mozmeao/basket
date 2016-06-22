#!/bin/bash

echo "$GIT_SHA" > static/revision.txt
exec gunicorn wsgi.app --config wsgi/config.py

#!/bin/bash

# need to do this here because docker build has no env
python manage.py collectstatic --noinput
python manage.py migrate --noinput

exec gunicorn wsgi:application -b 0.0.0.0:8000 -w 2 --log-file -

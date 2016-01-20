#!/bin/bash

# need to do this here because docker build has no env
python manage.py collectstatic --noinput

READ_ONLY_MODE=$(echo "$READ_ONLY_MODE" | tr '[:upper:]' '[:lower:]')
if [[ "$READ_ONLY_MODE" != "true" ]]; then
    python manage.py migrate --noinput
fi

echo "$GIT_SHA" > static/revision.txt

exec gunicorn wsgi:application -b 0.0.0.0:8000 -w 2 --log-file -

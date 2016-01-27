#!/bin/bash

READ_ONLY_MODE=$(echo "$READ_ONLY_MODE" | tr '[:upper:]' '[:lower:]')

if [[ "$READ_ONLY_MODE" != "true" ]]; then
    python manage.py migrate --noinput
fi

echo "$GIT_SHA" > static/revision.txt

exec gunicorn wsgi.app --config wsgi/config.py

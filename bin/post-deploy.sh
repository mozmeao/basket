#!/bin/bash

READ_ONLY_MODE=$(echo "$READ_ONLY_MODE" | tr '[:upper:]' '[:lower:]')

if [[ "$READ_ONLY_MODE" != "true" ]]; then
    python manage.py migrate --noinput
fi

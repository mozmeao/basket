#!/bin/bash -ex

echo "$GIT_SHA" > static/revision.txt

# Granian recommends containerized apps use the defaults of workers=1, blocking-threads=1.
# The backgpressure defaults to backlog (1024) / workers (1), but should be adjusted to match the
# number of database connections when configured for databases.

# Set the various GRANIAN_* environment variables to configure Granian, notably:
# - GRANIAN_PORT
# - GRANIAN_WORKERS
# - GRANIAN_THREADS
# - GRANIAN_BLOCKING_THREADS
# - GRANIAN_BACKPRESSURE
# - GRANIAN_LOG_LEVEL
granian \
    --interface wsgi \
    --host "0.0.0.0" \
    --no-ws \
    basket.wsgi:application

web: bin/run-prod.sh
worker: newrelic-admin run-program celery -A news worker -l info -c 4
clock: celery -A news beat -l info

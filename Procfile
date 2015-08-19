web: gunicorn wsgi:application --log-file -
worker: celery -A news worker -l info -c 1

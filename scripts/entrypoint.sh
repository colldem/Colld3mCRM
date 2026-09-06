#!/bin/sh
set -eu
python manage.py migrate --noinput
python manage.py collectstatic --noinput
exec gunicorn config.wsgi:application --bind 0.0.0.0:8080 --workers 2 --threads 2 --timeout 60 --access-logfile - --error-logfile -

#!/bin/sh
set -eu
# A single-host Docker install has one container, so it may as well migrate and
# collect on the way up. Kubernetes runs several: migrations belong to a Job that
# runs once per release, and the static files are already in the image. Both
# steps are therefore switchable, and both default to the Compose behaviour.
if [ "${CRM_RUN_MIGRATIONS:-1}" = "1" ]; then
  python manage.py migrate --noinput
fi
if [ "${CRM_COLLECTSTATIC:-1}" = "1" ]; then
  python manage.py collectstatic --noinput
fi
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${CRM_GUNICORN_PORT:-8080}" \
  --workers "${CRM_GUNICORN_WORKERS:-2}" \
  --threads "${CRM_GUNICORN_THREADS:-2}" \
  --timeout "${CRM_GUNICORN_TIMEOUT:-60}" \
  --access-logfile - --error-logfile -

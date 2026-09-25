#!/bin/sh
# The crm-worker loop: every background command in turn, then a pause.
#
# Each command runs under `timeout`, so one that hangs (an IMAP or SMTP server
# that never answers) is stopped after WORKER_JOB_TIMEOUT_SECONDS and the others
# still run; the command records the stop as a failure (management/tracked.py).
# `nice` keeps the jobs behind the web requests when they compete for the CPU.
# The heartbeat file is touched before every command; the container healthcheck
# fails when it goes stale, i.e. when the loop itself has stopped moving.
set -u
JOBS="extend_recurrences complete_past_meetings send_notifications fetch_mail run_automations deliver_webhooks
deactivate_inactive_users purge_audit_log apply_retention find_duplicates refresh_analytics"
while true; do
  for job in $JOBS; do
    touch /tmp/worker-heartbeat
    timeout "${WORKER_JOB_TIMEOUT_SECONDS:-600}" nice -n 10 python manage.py "$job" \
      || echo "worker: $job failed or was stopped after ${WORKER_JOB_TIMEOUT_SECONDS:-600} s" >&2
  done
  touch /tmp/worker-heartbeat
  sleep "${WORKER_INTERVAL_SECONDS:-300}"
done

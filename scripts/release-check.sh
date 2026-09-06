#!/bin/sh
set -eu
PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ]; then
  if command -v python >/dev/null 2>&1; then PYTHON_BIN=python; else PYTHON_BIN=python3; fi
fi
"$PYTHON_BIN" manage.py makemigrations --check --dry-run
"$PYTHON_BIN" manage.py test contacts
DJANGO_DEBUG=false \
DJANGO_SECRET_KEY="deployment-check-0123456789abcdefghijklmnopqrstuvwxyz-ABCDEFGHIJKLMNOPQRSTUVWXYZ" \
DJANGO_ALLOWED_HOSTS="crm.example.test" \
CRM_SETUP_TOKEN="deployment-check-setup-token" \
"$PYTHON_BIN" manage.py check --deploy
"$PYTHON_BIN" -c "import json; json.load(open('deploy/tailscale/serve.json', encoding='utf-8'))"

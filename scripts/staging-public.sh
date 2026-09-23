#!/bin/sh
# Put a staging instance on the public internet through Tailscale Funnel, or
# take it back off. Run on the host, or through the runner that deploys there
# (.github/workflows/regitra-staging-public.yml) when nobody can reach the box.
#
#   sh scripts/staging-public.sh on  [APP_DIR]
#   sh scripts/staging-public.sh off [APP_DIR]
#
# Publishing is two statements in the instance's .env, because one line should
# not be enough to expose a copy of production: the serve file, and
# CRM_STAGING_PUBLIC=1. scripts/deploy-staging.sh refuses the deploy unless both
# are present. This script writes both together, or removes both together.
#
# What it will not do: touch anything that is not a staging instance. Production
# is published deliberately and through its own serve.json; it is not this
# script's business, and the guard below is what keeps a mistyped path harmless.
#
# Before turning this on, read "Publishing a staging instance" in
# docs/DEPLOYMENT.md — in particular that sanitising the copy does not replace
# password hashes.
set -eu

MODE="${1:?usage: staging-public.sh on|off [APP_DIR]}"
APP="${2:-${CRM_STAGING_DIR:-/volume1/docker/crm-regitra-staging}}"
ENV_FILE="$APP/.env"

[ -f "$ENV_FILE" ] || { echo "FATAL: no $ENV_FILE"; exit 1; }

# --- refuse anything that is not an isolated copy ------------------------
grep -q '^CRM_ENVIRONMENT=staging$' "$ENV_FILE" || {
  echo "FATAL: $ENV_FILE is not CRM_ENVIRONMENT=staging — refusing"; exit 1; }
grep -q '^COMPOSE_FILE=.*compose\.staging\.yaml' "$ENV_FILE" || {
  echo "FATAL: $ENV_FILE COMPOSE_FILE does not include compose.staging.yaml"; exit 1; }

# --- rewrite the two lines together -------------------------------------
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
grep -v -e '^TS_SERVE_CONFIG=' -e '^CRM_STAGING_PUBLIC=' "$ENV_FILE" > "$tmp"

case "$MODE" in
  on)
    printf 'TS_SERVE_CONFIG=/config/serve-staging-funnel.json\nCRM_STAGING_PUBLIC=1\n' >> "$tmp"
    ;;
  off)
    printf 'TS_SERVE_CONFIG=/config/serve-staging.json\n' >> "$tmp"
    ;;
  *)
    echo "FATAL: mode must be 'on' or 'off', not '$MODE'"; exit 1 ;;
esac

cat "$tmp" > "$ENV_FILE"          # keep the existing file, and its mode
chmod 600 "$ENV_FILE"

# --- apply ---------------------------------------------------------------
cd "$APP"
# TS_SERVE_CONFIG is read by the Tailscale container when it starts, so that one
# has to be recreated rather than merely left running.
docker compose up -d --force-recreate crm-tailscale
docker compose up -d

if [ "$MODE" = on ]; then
  echo ">>> PUBLIC: this instance is now served on the open internet."
  echo "    Change the administrator's password on it now — sanitising the copy"
  echo "    replaces usernames but not password hashes."
else
  echo ">>> tailnet only: the instance is off the public internet."
fi
grep -e '^TS_SERVE_CONFIG=' -e '^CRM_STAGING_PUBLIC=' -e '^CRM_DOMAIN=' "$ENV_FILE"

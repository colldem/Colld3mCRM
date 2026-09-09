# Deployment

The CRM ships as a Docker Compose project. It runs on anything that runs Docker —
a VPS, a home server, a NAS — and needs no account with any third party.

- [Quick start](#quick-start)
- [Choosing how it is exposed](#choosing-how-it-is-exposed)
  - [A. Behind your own reverse proxy](#a-behind-your-own-reverse-proxy)
  - [B. Your own domain, certificates handled for you](#b-your-own-domain-certificates-handled-for-you)
  - [C. A private Tailscale network](#c-a-private-tailscale-network)
- [First run](#first-run)
- [Upgrading](#upgrading)
- [Backups and restore](#backups-and-restore)
- [A second, isolated copy for testing](#a-second-isolated-copy-for-testing)
- [Automated deployment](#automated-deployment)
- [Security notes](#security-notes)

## Quick start

Requires Docker with the Compose plugin. The base file works on any recent
version; the two overlays below use `!reset`, which needs **Compose v2.24 or
newer** (`docker compose version`).

```sh
git clone https://github.com/colldem/Colld3mCRM.git crm
cd crm
cp .env.example .env
```

Edit `.env` and set the four required values — the file explains how to generate
each one:

| Variable | What it is |
|---|---|
| `POSTGRES_PASSWORD` | database password, any long random string |
| `DJANGO_SECRET_KEY` | signs sessions and tokens |
| `CRM_SETUP_TOKEN` | one-time token that unlocks `/setup/` to create the first admin |
| `CRM_SECRETS_KEY` | encrypts integration passwords stored in the database |

Then:

```sh
docker compose up -d
```

The CRM is on <http://127.0.0.1:8080>. The database schema is created
automatically on first start.

Note that this is **on the machine you started it on, and nowhere else**. Two
settings do that on purpose, and both are the first thing people trip over:

- `CRM_BIND_IP=127.0.0.1` means the port is not published to the network. To
  reach it from another machine while testing, set `CRM_BIND_IP=0.0.0.0` — but
  only on a trusted network, since the app speaks plain HTTP.
- `DJANGO_ALLOWED_HOSTS` lists the names the app answers to. Reach it by any
  other name or IP and Django replies **400 Bad Request** rather than serving
  the page. Add the name you actually use, e.g.
  `DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.50`.

For anything beyond a local trial, use one of the three options below instead.

`CRM_SECRETS_KEY` is the one value you cannot regenerate later: lose it and the
SMTP, IMAP and Entra passwords saved through the Settings UI become unreadable.
Keep a copy somewhere safe, outside the server.

## Choosing how it is exposed

Out of the box the app listens on `127.0.0.1:8080` only — deliberately, since it
speaks plain HTTP. Pick one of the three ways below to put it in front of users.
The choice is one line in `.env`.

### A. Behind your own reverse proxy

If you already run nginx, Traefik, HAProxy or similar, change nothing in
Compose. Point your proxy at the published port and set:

```sh
CRM_BIND_IP=127.0.0.1
CRM_PORT=8080
DJANGO_ALLOWED_HOSTS=crm.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://crm.example.com
DJANGO_FORCE_HTTPS=true
CRM_BASE_URL=https://crm.example.com
```

Your proxy must pass `X-Forwarded-Proto`; the app already trusts that header to
decide whether a request arrived over HTTPS. An nginx location block:

```nginx
location / {
    proxy_pass         http://127.0.0.1:8080;
    proxy_set_header   Host              $host;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
    client_max_body_size 64m;
}
```

### B. Your own domain, certificates handled for you

Use the Caddy overlay if you do not already have a proxy. Caddy obtains and
renews a Let's Encrypt certificate on its own.

Requirements: a DNS record for your domain pointing at this host, and ports 80
and 443 reachable from the internet (Let's Encrypt validates over port 80).

```sh
COMPOSE_FILE=compose.yaml:compose.caddy.yaml
CRM_DOMAIN=crm.example.com
CRM_ACME_EMAIL=admin@example.com
DJANGO_ALLOWED_HOSTS=crm.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://crm.example.com
DJANGO_FORCE_HTTPS=true
CRM_BASE_URL=https://crm.example.com
```

Then `docker compose up -d` — with `COMPOSE_FILE` set, the ordinary commands use
the overlay, so there are no `-f` flags to remember. Certificates live in
`runtime/caddy/`; keep that directory across upgrades.

### C. A private Tailscale network

Reach the CRM from your own devices without exposing it to the internet at all.
Create an auth key in the Tailscale admin console (*Settings → Keys*), then:

```sh
COMPOSE_FILE=compose.yaml:compose.tailscale.yaml
TS_AUTHKEY=tskey-auth-...
TS_HOSTNAME=crm
TS_CERT_DOMAIN=crm.your-tailnet.ts.net
DJANGO_ALLOWED_HOSTS=crm.your-tailnet.ts.net
DJANGO_CSRF_TRUSTED_ORIGINS=https://crm.your-tailnet.ts.net
DJANGO_FORCE_HTTPS=true
CRM_BASE_URL=https://crm.your-tailnet.ts.net
```

Tailscale terminates HTTPS itself, so there is no certificate work.

`deploy/tailscale/serve.json` also enables **Funnel**, which publishes the CRM to
the public internet on top of the private network. That is a deliberate choice,
not a default worth keeping by accident: if you want the CRM reachable only from
your own devices, delete the `AllowFunnel` line, or point `TS_SERVE_CONFIG` at
`/config/serve-staging.json`, which omits it.

## First run

1. Open the CRM and go to `/setup/`.
2. Enter the `CRM_SETUP_TOKEN` from `.env` and create the first administrator.
3. The setup page disables itself once a user exists.
4. Clear `CRM_SETUP_TOKEN` from `.env` and restart: `docker compose up -d crm-web`.
5. If you used a Tailscale auth key, revoke it in the admin console — it has done
   its job, and the node is already authenticated.

Everything else — users, roles, teams, custom fields, email, incoming mail,
single sign-on — is configured in **Settings** inside the app.

## Upgrading

```sh
git pull
docker compose build --pull
docker compose up -d
docker compose exec crm-web python manage.py migrate --check
```

Migrations run automatically at start; `migrate --check` afterwards confirms
none were missed. Take a backup first (below).

## Backups and restore

The `crm-backup` service dumps the database on a timer to `runtime/backups/`,
keeping `BACKUP_KEEP` files (default 14, daily). Attachments live in
`runtime/media/`; back that up with your normal file backups.

Take one now:

```sh
docker compose exec -T crm-db pg_dump -U crm -d crm -Fc > crm-$(date +%F).dump
```

Restore into a running stack:

```sh
docker compose stop crm-web crm-worker
docker compose exec -T crm-db pg_restore --clean --if-exists --no-owner \
  --no-privileges -U crm -d crm < crm-2026-01-31.dump
docker compose up -d
```

Users can also download a complete ZIP — every record, attachments and restore
instructions — from *Settings → Data export*.

Two things worth doing before you put real contacts in: copy `runtime/backups/`
somewhere off this machine on a schedule (RAID is not a backup), and actually
perform a restore once to confirm the dumps are usable. A restore is only as good
as its test — *Settings → Documentation* in the app has the procedure.

## A second, isolated copy for testing

You can run a second instance holding a copy of live data, to try changes against
realistic records. Because that copy contains real personal data and real
credentials, set `CRM_ENVIRONMENT` to anything other than `production`:

```sh
CRM_ENVIRONMENT=staging
```

That single switch makes the app refuse to touch the outside world, whatever the
copied database says: SMTP, IMAP and Entra return an inert configuration, and
webhooks are neither queued nor sent. A red banner names the tier on every page,
including sign-in. It lives in the environment rather than the database on
purpose — reloading the data cannot switch it back on.

Two more layers are worth having:

```sh
docker compose exec crm-web python manage.py sanitize_staging
```

clears those settings from the copied data itself and deletes API tokens (it
refuses to run on production), and `compose.staging.yaml` holds `crm-worker` and
`crm-backup` at zero replicas so nothing runs on a timer against the clone.

A full second instance, in its own directory with its own `.env`:

```sh
COMPOSE_FILE=compose.yaml:compose.tailscale.yaml:compose.staging.yaml
CRM_ENVIRONMENT=staging
TS_SERVE_CONFIG=/config/serve-staging.json   # no Funnel: private, unlike production
```

`scripts/refresh-staging.sh` reloads it from production; it streams a read-only
`pg_dump` straight into the copy and then runs `sanitize_staging`. Set
`CRM_APP_DIR` and `CRM_STAGING_DIR` to your two directories.

## Automated deployment

`.github/workflows/` contains the pipeline this project uses: `ci.yml` (lint,
tests, image build on every push and pull request), `deploy-staging.yml` (every
push to `main`) and `deploy.yml` (a `v*.*.*` tag). Both deploy jobs run on a
self-hosted runner on the target host — see [`deploy/runner/README.md`](../deploy/runner/README.md).

A fork sets its own paths and URLs as repository variables rather than editing
the workflows: `CRM_APP_DIR`, `CRM_STAGING_DIR`, `CRM_PROD_URL`,
`CRM_STAGING_URL`.

None of this is required. `scripts/deploy.sh` does the same work over SSH, and
`docker compose build --pull && docker compose up -d` is always enough.

## Security notes

- Keep `.env` out of version control (it already is) and readable only by its
  owner: `chmod 600 .env`.
- Do not publish the app's own port to the internet. It speaks plain HTTP;
  something in front must terminate TLS.
- The app rate-limits and locks out repeated failed sign-ins (django-axes),
  hashes passwords with Argon2, and sets `Secure` cookies once
  `DJANGO_FORCE_HTTPS=true`.
- Self-hosted CI runners have access to the Docker socket, which is equivalent to
  root on the host. Use them only with a private repository.
- If you enable Tailscale Funnel, the CRM is reachable by anyone on the internet.
  Know that you have chosen it.

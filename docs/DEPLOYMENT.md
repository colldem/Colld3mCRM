# Deployment

The CRM ships as a Docker Compose project. It runs on anything that runs Docker —
a VPS, a home server, a NAS — and needs no account with any third party.

> Running it on **Kubernetes** instead? The same image, packaged as a Helm
> chart: **[KUBERNETES.md](KUBERNETES.md)**. Nothing on this page changes.

- [Quick start](#quick-start)
- [Choosing how it is exposed](#choosing-how-it-is-exposed)
  - [A. Behind your own reverse proxy](#a-behind-your-own-reverse-proxy)
  - [B. Your own domain, certificates handled for you](#b-your-own-domain-certificates-handled-for-you)
  - [C. A private Tailscale network](#c-a-private-tailscale-network)
- [First run](#first-run)
- [The other settings](#the-other-settings)
- [Upgrading](#upgrading)
- [Backups and restore](#backups-and-restore)
- [A second, isolated copy for testing](#a-second-isolated-copy-for-testing)
- [Automated deployment](#automated-deployment)
- [Security notes](#security-notes)
- [Kubernetes](KUBERNETES.md)

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
# The proxy's address as the app sees it (same host: loopback).
CRM_TRUSTED_PROXIES=127.0.0.1/32
```

Your proxy must pass `X-Forwarded-Proto`; the app already trusts that header to
decide whether a request arrived over HTTPS. An nginx location block:

```nginx
location / {
    proxy_pass         http://127.0.0.1:8080;
    proxy_set_header   Host              $host;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
    client_max_body_size 12m;
    proxy_read_timeout   90s;
}
```

A proxy on another machine: publish on that interface only (`CRM_BIND_IP=<app VM
address>`), firewall the port to the proxy, and set `CRM_TRUSTED_PROXIES` to the
proxy's address. The organisational deployment guide — network flows, sizing,
upgrade and rollback — is [DIEGIMAS-ORGANIZACIJOJE.md](DIEGIMAS-ORGANIZACIJOJE.md).

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

## The other settings

Nothing here needs touching for a normal install — every one of them already has
the right default. `.env.example` carries them all with comments; this table is
the summary.

**Behaviour**

| Variable | Default | What it does |
|---|---|---|
| `CRM_EXTRA_APPS` | empty | comma-separated Django apps installed beside the CRM and added to `INSTALLED_APPS`, so a deployment can add one without patching settings |
| `CRM_ENVIRONMENT` | `production` | anything else marks the instance an isolated copy: e-mail, IMAP, Entra and webhooks are forced off and a banner names the tier |
| `DJANGO_SESSION_IDLE_MINUTES` | `480` | idle timeout before a session expires |
| `CRM_DJANGO_ADMIN` | `false` | `true` mounts Django's `/admin/` for superusers only. It edits records outside the CRM's audit trail and permissions, so leave it off unless a one-off technical fix needs it |
| `CRM_TRUSTED_PROXIES` | *(empty; overlays set it)* | CIDR list of reverse proxies whose `X-Forwarded-For` is believed. The client address in the audit trail and the sign-in lockout comes from it; without it every user behind one proxy shares the proxy's address — five failed sign-ins by anyone would lock everyone out. Read right-to-left, skipping trusted hops, so a client cannot spoof it |
| `CRM_METRICS_TOKEN` | *(empty)* | enables `/metrics` (Prometheus text format) for requests with `Authorization: Bearer <token>`; see *Monitoring* |
| `CRM_CLAMAV_HOST` | *(empty)* | clamd host for malware scanning of every upload (attachments, e-mail attachments, avatars, import and translation files); `compose.clamav.yaml` runs one and sets it. Empty disables scanning |
| `CRM_CLAMAV_PORT`, `CRM_CLAMAV_TIMEOUT` | `3310`, `30` | clamd TCP port and per-file timeout in seconds |
| `CRM_CLAMAV_REQUIRED` | `true` | while the scanner is unreachable: `true` refuses uploads, `false` accepts them unscanned; both log to `crm.security` |
| `CRM_CSP_REPORT_ONLY` | `false` | `true` sends the Content-Security-Policy as `Content-Security-Policy-Report-Only` — violations show in the browser console instead of being blocked; use only while checking a new reverse proxy or browser extension setup |
| `CRM_LOG_FORMAT` | `json` (`text` with `DJANGO_DEBUG=true`) | `json` writes one JSON object per line to stdout — application, security and Gunicorn access logs — for a SIEM; `text` is for reading by eye. See *Logs* below |
| `CRM_LOG_LEVEL` | `INFO` | root log level |
| `CRM_API_RATE_LIMIT` | `120` | JSON API requests allowed per token per minute (counted in the database, so shared by every process and replica); `0` disables the limit |
| `CRM_BREAK_GLASS_USERS` | *(empty)* | comma-separated usernames still allowed a local password when SSO-only sign-in is on (Settings → Prisijungimas); empty means active superusers only |
| `WORKER_INTERVAL_SECONDS` | `300` | how often `crm-worker` runs the background commands |
| `BACKUP_KEEP` / `BACKUP_INTERVAL_SECONDS` | `14` / `86400` | how many dumps `crm-backup` keeps, and how often it takes one |

**Uploaded files**

| Variable | Default | What it does |
|---|---|---|
| `CRM_MEDIA_BACKEND` | `filesystem` | `filesystem` keeps attachments in `runtime/media`; `s3` puts them in S3-compatible object storage |
| `CRM_S3_BUCKET` | — | bucket name, with `s3` |
| `CRM_S3_ENDPOINT` | — | e.g. `https://minio.example.com`; leave empty for AWS |
| `CRM_S3_REGION` | — | region, where the provider needs one |
| `CRM_S3_ACCESS_KEY` / `CRM_S3_SECRET_KEY` | — | credentials for the bucket |
| `CRM_S3_ADDRESSING` | `path` | `path` for MinIO and most self-hosted gateways, `virtual` for AWS S3 |

One host needs none of this: the default keeps files on disk. Object storage is
what you need once **more than one web process** serves the app, because each one
otherwise has its own disk — see [KUBERNETES.md](KUBERNETES.md).

**Container start-up** (read by `scripts/entrypoint.sh`)

| Variable | Default | What it does |
|---|---|---|
| `CRM_RUN_MIGRATIONS` | `1` | run `migrate` before starting. Kubernetes sets `0`: migrations run once per release, in a Job |
| `CRM_COLLECTSTATIC` | `1` | run `collectstatic` before starting. `0` when the static files are already baked into the image |
| `CRM_GUNICORN_PORT` | `8080` | port gunicorn binds |
| `CRM_GUNICORN_KEEPALIVE` | `75` | seconds an idle keep-alive connection stays open; keep it above the reverse proxy's upstream keep-alive so the proxy never reuses a connection gunicorn is closing |
| `CRM_GUNICORN_WORKERS` | `2` | worker processes |
| `CRM_GUNICORN_THREADS` | `2` | threads per worker |
| `CRM_GUNICORN_TIMEOUT` | `60` | seconds before a stuck worker is killed |

Raise the two gunicorn numbers only if the host has the cores and memory for it;
each worker is a full copy of the app.

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

The `crm-backup` service (image built from `deploy/backup/Dockerfile`) writes one
**backup set** per `BACKUP_INTERVAL_SECONDS` (default daily) to `runtime/backups/`
and keeps the newest `BACKUP_KEEP` (default 14):

| File | Content |
|---|---|
| `db-<UTC timestamp>.dump.age` | `pg_dump` custom format, encrypted |
| `media-<timestamp>.tar.gz.age` | uploaded files, encrypted |
| `SHA256SUMS-<timestamp>` | checksums of both |
| `manifest-<timestamp>.json` | what the set is |
| `last-success` | time of the last complete set; the container turns *unhealthy* when it is older than two intervals |

**Encryption.** Generate an [age](https://age-encryption.org) key pair *off* the
CRM host and keep the private key in the organisation's secret store:

```sh
docker compose run --rm --no-deps --entrypoint age-keygen crm-backup > crm-backup-key.txt
grep 'public key' crm-backup-key.txt      # age1...  -> BACKUP_AGE_RECIPIENTS
```

Put the public key(s) in `.env` as `BACKUP_AGE_RECIPIENTS` (space separated — add a
second key for a colleague or the DR vault) or in `runtime/backup-config/age-recipients.txt`,
and set `BACKUP_REQUIRE_ENCRYPTION=true` so the service refuses to write plain
backups. The CRM host can create backups but cannot read them. Without recipients
the sets are plain `.dump` / `.tar.gz` and every run logs a warning. The
pre-deploy dumps `scripts/deploy.sh` takes are encrypted with the same recipients.

**Off-host copy.** RAID is not a backup. Set `BACKUP_REMOTE` to an
[rclone](https://rclone.org) destination (`s3:bucket/crm`, `sftp:backup/crm`, …),
put its `rclone.conf` in `runtime/backup-config/`, and each set is copied there;
copies older than `BACKUP_REMOTE_KEEP_DAYS` (default 30) are pruned. A failed copy
fails the run, so the health check shows it.

| Variable | Default | Meaning |
|---|---|---|
| `BACKUP_KEEP` | `14` | sets kept on the host |
| `BACKUP_INTERVAL_SECONDS` | `86400` | time between sets |
| `BACKUP_AGE_RECIPIENTS` | *(empty)* | age public keys to encrypt for |
| `BACKUP_REQUIRE_ENCRYPTION` | `false` | `true` refuses to run without recipients |
| `BACKUP_REMOTE` | *(empty)* | rclone destination for the off-host copy |
| `BACKUP_REMOTE_KEEP_DAYS` | `30` | age after which remote copies are deleted |

Take a set now: `docker compose run --rm -e BACKUP_ONCE=true crm-backup`.

**Restore** — verifies checksums, stops the app, decrypts inside a container (no
plaintext on the host disk), restores the database in one transaction (a failed
restore changes nothing), replaces the uploaded files, starts the CRM and prints
record counts:

```sh
bash scripts/restore.sh \
  --db runtime/backups/db-20260913-020000.dump.age \
  --media runtime/backups/media-20260913-020000.tar.gz.age \
  --identity /secure/crm-backup-key.txt
```

**Tested on every change.** The `backup-restore` CI job builds the stack, creates
a contact with an attachment, takes an encrypted set, deletes the database and the
uploads, checks that a tampered dump is refused, restores, and verifies the contact
and the file content. Still restore once on your own infrastructure — a drill proves
the procedure, not your storage.

Recovery point: at most one `BACKUP_INTERVAL_SECONDS` (24 h by default; shorten it,
or rely on the database platform's point-in-time recovery). Recovery time: minutes
for a typical CRM database — measure it in your drill.

Kubernetes: the chart uses an external PostgreSQL and S3 storage, so backups there
are the platform's (database PITR, bucket versioning); this service is Compose-only.

Users can also download a complete ZIP — every record, attachments and restore
instructions — from *Settings → Data export*.

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
`pg_dump` straight into the copy and then runs `sanitize_staging`, which clears
the integration credentials and **anonymises the personal data** — names, contact
details, texts, attachment files, users; incoming mail, the audit trail and logs
are deleted — while keeping counts, links and dates (`--keep-personal-data` skips
it). `--with-media` copies attachments before that step. Set
`CRM_APP_DIR` and `CRM_STAGING_DIR` to your two directories.

## Automated deployment

`.github/workflows/` contains the pipeline this project uses: `ci.yml` (lint,
tests, image build on every push and pull request; security checks — `pip-audit`
for known CVEs in dependencies, `bandit` static analysis, a Trivy scan of the
image — and CycloneDX SBOMs of the Python dependencies and of the image,
downloadable as run artifacts; run the first two locally with
`scripts/security-check.sh`), `deploy-staging.yml` (every
push to `main`) and `deploy.yml` (a `v*.*.*` tag). Both deploy jobs run on a
self-hosted runner on the target host — see [`deploy/runner/README.md`](../deploy/runner/README.md).

A fork sets its own paths and URLs as repository variables rather than editing
the workflows: `CRM_APP_DIR`, `CRM_STAGING_DIR`, `CRM_PROD_URL`,
`CRM_STAGING_URL`.

None of this is required. `scripts/deploy.sh` does the same work over SSH, and
`docker compose build --pull && docker compose up -d` is always enough.

## Monitoring

| Endpoint | Use |
|---|---|
| `/health/live` | the process answers — liveness probe |
| `/health/ready` | the database answers — readiness probe, load balancer check |
| `/metrics` | Prometheus scrape, with `CRM_METRICS_TOKEN` as bearer token |

`/metrics` is computed from the database at scrape time, so any web process gives
the same answer; request rates and latencies come from the reverse proxy or
ingress. Scrape config:

```yaml
- job_name: crm
  scheme: https
  metrics_path: /metrics
  authorization: {credentials: "<CRM_METRICS_TOKEN>"}
  static_configs: [{targets: ["crm.example.com"]}]
```

| Metric | Suggested alert |
|---|---|
| `crm_database_up`, `crm_clamav_up` | `== 0` for 5 minutes |
| `crm_job_last_success_timestamp_seconds{job}` | older than 30 minutes for `send_notifications`, `fetch_mail`, `deliver_webhooks`, `run_automations`; older than 26 hours for the daily ones — the worker has stopped |
| `crm_job_last_failure_timestamp_seconds{job}` | newer than the last success |
| `crm_login_failures_24h{reason="locked_out"}` | above your baseline — password guessing |
| `crm_read_only_refusals_24h` | above 0 — someone probing beyond their role |
| `crm_api_tokens{state="expiring_14d"}` | above 0 — an integration is about to break |
| `crm_webhook_deliveries_pending` | growing — a receiving system is down |
| `crm_info{version,environment}` | informational |

The backup container has its own health check (last successful set), visible to
the Docker or orchestrator monitoring.

## Malware scanning

Add `compose.clamav.yaml` to `COMPOSE_FILE`. It runs ClamAV (signatures updated by
the container itself, cached in `runtime/clamav`, ~1.5 GB RAM) and points the web
and worker containers at it. Every uploaded file is streamed to it before it is
stored or parsed; an infected file is refused, audited (`target_type=upload`,
`detail.signature`) and logged as `event=upload.malware`. An organisation that
already runs clamd sets `CRM_CLAMAV_HOST` instead. CI checks the integration against
a real ClamAV with the EICAR test file.

## Logs

Every container writes to stdout; collect it with the platform's log shipper
(Docker logging driver, Fluent Bit, Promtail, the SIEM agent). With
`CRM_LOG_FORMAT=json` each line is one JSON object:

| Field | Meaning |
|---|---|
| `ts`, `level`, `logger`, `message` | always present; `ts` is UTC ISO 8601 |
| `request_id` | the request's id — the incoming `X-Request-ID` when a proxy sets one, otherwise generated — also returned in the `X-Request-ID` response header and stored in the audit trail (`detail.request_id`) |
| `event` | on `crm.security` lines: `audit.<action>` for every audit row (`login`, `login_failed`, `logout`, `create`, `update`, `archive`, `delete`, `merge`, `import`, `export`, `setting` …) |
| `action`, `actor_id`, `target_type`, `target_id`, `field`, `ip`, `reason` | the structured part of a security event: ids and types only, never names or field values |
| `exception` | stack trace, when there is one |

Useful alerts: `event=audit.login_failed` with `reason=locked_out` (brute force),
`reason=directory` (sign-in refused by group mapping), `target_type=access`
(a reader tried to change data), `logger=django.security.*` (rejected tokens,
disallowed hosts, CSRF failures) and any `level=ERROR`.

The audit trail itself (Settings → Žurnalas) is append-only: the application
refuses to change or delete rows and, on PostgreSQL, a trigger refuses it in the
database too. Only the retention purge (`purge_audit_log`, run by the worker;
retention set on that page, 0 = forever, otherwise at least 180 days) removes
rows, and it records that it did. The page exports the filtered trail as CSV.
A database superuser can still bypass the trigger — ship the JSON stream to the
SIEM for a copy nobody on the CRM host can alter.

Gunicorn's access log uses the same shape (`logger=gunicorn.access`) and records
the path without its query string, which can carry search terms.

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

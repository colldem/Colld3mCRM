# Colld3m CRM

A self-hosted CRM for people, companies, the relationships between them, and the
history of working with them — contact history, files, reminders and tasks. It
runs in the browser, ships as a Docker Compose project, and depends on no
third-party service.

The interface is available in Lithuanian and English.

```sh
git clone https://github.com/colldem/Colld3mCRM.git crm && cd crm
cp .env.example .env      # fill in four values, the file explains each
docker compose up -d      # http://127.0.0.1:8080
```

Then open `/setup/` and create the first administrator. Putting it on your own
domain with HTTPS, or on a private network, is one line in `.env` —
see **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**.

Current version: see [`VERSION`](VERSION). User and administrator documentation
lives inside the app: **Settings → Documentation**.

## Features

- **Records.** People, companies and the links between them; multiple phone
  numbers, emails, addresses and URLs per record. Tags, categories and custom
  fields. Duplicate detection and merging. Archive with restore.
- **Lists.** Search, advanced filters, saved filters, sorting, selectable
  columns, pagination. Bulk actions on a selection: assign tags, categories or an
  owner, set a custom field, add a co-owner, create a task or log an activity,
  archive and restore.
- **Record pages.** Inline editing of every field, communication history, file
  attachments, reminders and comments.
- **Dashboard and analytics.** Agenda, overdue reminders, the week's activity;
  relationship care, communication, reminder follow-through and database growth,
  charted as inline SVG with no external libraries.
- **Calendar.** Day, week and month views, recurring reminders, and an `.ics`
  subscription URL for Google, Outlook or Apple Calendar.
- **Tasks.** Assign work to a colleague with a priority and a due date.
- **Email.** Notifications for an upcoming event, a morning digest and a newly
  assigned task. Incoming mail from an IMAP mailbox is attached to the matching
  contact automatically.
- **Automation.** Rules of the form *when a contact has gone quiet / has no
  owner / a reminder is overdue → notify, assign, create a task or add a tag*,
  evaluated in the background.
- **Integration.** A JSON REST API at `/api/v1/` with bearer tokens, and outgoing
  webhooks signed with HMAC-SHA256.
- **Access control.** Roles (administrator / all records / own records only), a
  role-permission table, teams, and per-record visibility. Sign-in rate limiting
  and lockout. Microsoft Entra ID (OIDC) single sign-on alongside local accounts.
  A full audit log.
- **Import and export.** CSV and XLSX contact import, CSV export, and a complete
  ZIP backup.

Email, incoming mail and Entra sign-on are switched on and configured in the
Settings UI without restarting anything. Their passwords are encrypted in the
database with `CRM_SECRETS_KEY` from `.env`.

## Environments

`CRM_ENVIRONMENT` names the tier. Anything other than `production` marks the
instance as an isolated copy — typically one restored from a production dump, so
holding real personal data. There, SMTP, IMAP, Entra and webhooks are forced off
regardless of what the database says, and a red banner names the tier on every
page. The switch lives in the environment, not the database, so reloading the
data cannot turn it back on.

That makes a **development → staging → production** flow practical:
`compose.staging.yaml` runs a second instance against a copy of live data, and
`scripts/refresh-staging.sh` reloads it. See
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md#a-second-isolated-copy-for-testing).

## Built with

Python 3.13 · Django 5.2 LTS · PostgreSQL 17 (SQLite for local development) ·
Gunicorn · WhiteNoise · django-axes · Argon2 · mozilla-django-oidc · cryptography ·
AdminLTE 4 and Bootstrap 5, vendored locally. Charts are hand-generated SVG with
no charting library. Background work runs in a `crm-worker` container. Optional
Caddy or Tailscale overlays handle HTTPS.

Architecture notes: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Development

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python manage.py migrate
PYTHON_BIN=.venv/bin/python sh scripts/release-check.sh
```

`release-check.sh` runs `makemigrations --check`, the full test suite and
`manage.py check --deploy`. To serve locally:

```sh
DJANGO_DEBUG=true .venv/bin/python manage.py runserver 127.0.0.1:8765
```

`.github/workflows/ci.yml` runs ruff, the same release check and a Docker image
smoke test on every push and pull request.

## Licence

No licence has been chosen yet, so default copyright applies: the code is
readable here, but not licensed for reuse. Open an issue if you would like that
to change.

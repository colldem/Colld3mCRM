# Running Colld3m CRM on Kubernetes

The CRM ships as a Docker Compose project for a single host, and as a Helm chart
for a cluster. Both run the same image and the same code — what differs is who
runs the migrations, where uploaded files live, and how the background commands
are scheduled.

If you only want one machine, stay with [DEPLOYMENT.md](DEPLOYMENT.md). Nothing
here changes that setup.

---

## What is different from Compose

| | Compose (one host) | Kubernetes |
|---|---|---|
| Image | built on the host, tagged `crm-web:X.Y.Z` | pulled from a registry (GHCR by default) |
| Migrations | every container start (`CRM_RUN_MIGRATIONS=1`) | once per release, in a Job |
| Static files | collected on start | baked into the image at build |
| Uploaded files | `runtime/media` on disk | S3-compatible object storage |
| Background jobs | one `crm-worker` container looping | five `CronJob`s |
| Database | the `crm-db` container | an external PostgreSQL you already run |
| HTTPS | Caddy or Tailscale overlay | nginx Ingress |

Sessions, sign-in rate limiting and the editable-translations mechanism were
already safe across processes, and nothing in the app uses a local-memory cache,
so **no Redis or shared cache is needed**.

---

## Before you start

You need:

1. A cluster with an **nginx Ingress controller** and a way to get a certificate
   (cert-manager, or a certificate your platform issues).
2. A **PostgreSQL 17** database, plus a user and an empty database. The chart
   deliberately ships no database: use what your platform already runs and backs
   up.
3. An **S3-compatible bucket** for uploaded files (MinIO, Ceph RGW, AWS S3 …)
   and a key pair that can read and write it.
4. Two generated secrets:

   ```sh
   # Django's signing key
   python -c "import secrets; print(secrets.token_urlsafe(64))"
   # The key that encrypts integration passwords stored in the database
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

   > **`CRM_SECRETS_KEY` must never change.** SMTP, IMAP and Entra passwords
   > entered in Settings are encrypted with it. Replace it and they stop
   > decrypting, and everyone has to type them in again.

---

## The image

Tagging a release (`git tag v0.76.0 && git push origin v0.76.0`) runs
`.github/workflows/publish-image.yml`, which builds and pushes:

```
ghcr.io/colldem/crm-web:0.76.0
ghcr.io/colldem/crm-web:latest
```

The workflow refuses to publish if the tag and the `VERSION` file disagree.

If the cluster cannot reach GHCR, mirror the image into your own registry and
point `image.repository` at it:

```sh
docker pull ghcr.io/colldem/crm-web:0.76.0
docker tag  ghcr.io/colldem/crm-web:0.76.0 registry.internal/crm-web:0.76.0
docker push registry.internal/crm-web:0.76.0
```

A private registry also needs `image.pullSecrets`.

---

## Installing

Write a values file — keep it out of Git if it holds secrets, or better, put the
secrets in a `Secret` of your own and point `existingSecret` at it.

`crm-values.yaml`:

```yaml
image:
  repository: ghcr.io/colldem/crm-web
  tag: "0.76.0"

replicaCount: 2

ingress:
  host: crm.regitra.lt
  className: nginx
  tls:
    enabled: true
    secretName: crm-tls

database:
  host: postgres.databases.svc.cluster.local
  name: crm
  user: crm

env:
  CRM_ENVIRONMENT: production
  CRM_MEDIA_BACKEND: s3
  CRM_S3_BUCKET: crm-media
  CRM_S3_ENDPOINT: https://minio.regitra.lt
  CRM_S3_ADDRESSING: path

# Better: create this Secret yourself and set existingSecret instead.
secrets:
  djangoSecretKey: "…"
  crmSecretsKey: "…"
  databasePassword: "…"
  s3AccessKey: "…"
  s3SecretKey: "…"
  setupToken: "one-time-token-for-the-first-admin"
```

Then:

```sh
kubectl create namespace crm
helm upgrade --install crm deploy/helm/crm -n crm -f crm-values.yaml
kubectl -n crm rollout status deploy/crm
```

Helm runs the migration Job **before** the new pods start, so an upgrade that
cannot migrate never puts a broken release in front of users.

### The first administrator

With `secrets.setupToken` set, open `https://<host>/setup/`, enter the token and
create the account. Then remove the token:

```sh
helm upgrade crm deploy/helm/crm -n crm -f crm-values.yaml --set secrets.setupToken=""
```

---

## Bringing your own Secret

Preferred, and required if you use External Secrets or Vault:

```sh
kubectl -n crm create secret generic crm-secrets \
  --from-literal=DJANGO_SECRET_KEY='…' \
  --from-literal=CRM_SECRETS_KEY='…' \
  --from-literal=DB_PASSWORD='…' \
  --from-literal=CRM_S3_ACCESS_KEY='…' \
  --from-literal=CRM_S3_SECRET_KEY='…'
```

```yaml
existingSecret: crm-secrets
```

The chart then creates no Secret of its own and reads every credential from
yours.

---

## What the chart creates

| Object | Why |
|---|---|
| `Deployment` (web) | gunicorn, `replicaCount` pods, `CRM_RUN_MIGRATIONS=0` |
| `Job` (migrate) | Helm `pre-install,pre-upgrade` hook, once per release |
| `CronJob` × 5 | `send_notifications`, `fetch_mail`, `deliver_webhooks`, `run_automations`, `extend_recurrences` |
| `Service` | ClusterIP on port 80 → container 8080 |
| `Ingress` | nginx, TLS, 12 MB body limit so a 10 MB import fits |
| `ConfigMap` | non-secret settings; the pods roll when it changes |
| `Secret` | only when `existingSecret` is empty; kept across upgrades |
| `HorizontalPodAutoscaler` | only when `autoscaling.enabled` |

### Probes

`/health/live` says the process is alive; `/health/ready` also reaches the
database, so it is what gates traffic. A `startupProbe` gives a cold pod up to a
minute before the liveness probe starts counting.

### Background jobs

The Compose setup runs one container looping through five management commands.
Here each is its own `CronJob` with `concurrencyPolicy: Forbid`: the commands
claim work with database flags rather than a lock, so two overlapping runs would
do the same work twice. Adjust the schedules under `worker.jobs`, or switch the
lot off with `worker.enabled=false` if something else drives them.

---

## Upgrading

```sh
helm upgrade crm deploy/helm/crm -n crm -f crm-values.yaml --set image.tag=0.76.0
```

Because the pods roll while the old ones still serve, a migration must work
against **both** the old and the new code for the length of the rollout. Adding
columns and tables is safe; dropping or renaming one needs two releases — add
the new shape first, deploy, then remove the old in the next release.

Back the database up before an upgrade, the same as on the NAS. If your operator
does not do it, take one by hand:

```sh
kubectl -n crm run pgdump --rm -i --restart=Never --image=postgres:17 -- \
  pg_dump -h "$DB_HOST" -U crm -d crm -Fc > crm-$(date +%F).dump
```

---

## A second, isolated copy

Set `CRM_ENVIRONMENT` to anything other than `production` and the instance
refuses to send e-mail, fetch IMAP, talk to Entra or fire webhooks, and paints a
banner naming the tier on every page — even if the database says otherwise,
because the switch lives in the environment. That makes a staging release from a
copy of live data safe:

```sh
helm upgrade --install crm-staging deploy/helm/crm -n crm-staging \
  -f crm-values.yaml \
  --set env.CRM_ENVIRONMENT=staging \
  --set ingress.host=crm-staging.regitra.lt \
  --set database.name=crm_staging \
  --set env.CRM_S3_BUCKET=crm-media-staging \
  --set replicaCount=1 --set worker.enabled=false
```

Run `manage.py sanitize_staging` against the copy to clear stored credentials
and disable webhooks in the data itself:

```sh
kubectl -n crm-staging exec deploy/crm-staging -- python manage.py sanitize_staging
```

---

## Troubleshooting

**The migration Job fails and the release rolls back.** That is the design — the
old pods keep serving. Read it:

```sh
kubectl -n crm logs job/crm-migrate-<revision>
```

**Pods never become ready.** `/health/ready` checks the database; usually the
host, credentials or a network policy are wrong:

```sh
kubectl -n crm logs deploy/crm
kubectl -n crm exec deploy/crm -- python manage.py check --database default
```

**Uploads vanish, or a file 404s from one pod and not another.**
`CRM_MEDIA_BACKEND` is still `filesystem`, so each pod has its own disk. Set it
to `s3`.

**Stored SMTP or IMAP passwords stopped working.** `CRM_SECRETS_KEY` changed.
Restore the old value; if it is gone, re-enter the passwords in Settings.

**A 413 on import.** The nginx body limit. Raise
`ingress.annotations."nginx\.ingress\.kubernetes\.io/proxy-body-size"`.

**Static files 404.** The image is built with `DJANGO_DEBUG=false` so WhiteNoise
writes its manifest; a hand-built image without that produces exactly this. The
build fails loudly if the manifest is missing, so check how the image was made.

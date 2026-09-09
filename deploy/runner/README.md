# CRM deploy runner (self-hosted GitHub Actions)

A single ephemeral runner on the NAS that runs the `deploy` job of
`.github/workflows/deploy.yml`. It needs the Docker socket (to build and start
the app) and the app directory `/volume1/docker/crm`.

## One-time setup

1. **Create a fine-grained PAT** — GitHub → *Settings → Developer settings →
   Fine-grained tokens* → *Generate new token*:
   - Resource owner: your account
   - Repository access: *Only select repositories* → `Colld3mCRM`
   - Permissions: **Administration → Read and write**, **Actions → Read**
   - Short expiry (e.g. 90 days); set a calendar reminder to rotate.

2. **Configure and pin the image**

   `/volume1/docker/crm-runner` on the NAS is already provisioned: `compose.yaml`,
   a `.env` (mode 600) with `REPO_URL` and the verified `DOCKER_GID=121`, and
   `RUNNER_IMAGE` pinned to the pulled digest. Only the token is missing — put
   the PAT from step 1 on the `ACCESS_TOKEN=` line, replacing the placeholder.

   To re-pin the image later (do this when you rotate the PAT — `.env` never
   leaves the NAS, so Dependabot cannot bump it):
   ```sh
   cd /volume1/docker/crm-runner
   docker compose pull
   docker inspect --format '{{index .RepoDigests 0}}' $(docker compose config --images)
   # put that name@sha256:... into RUNNER_IMAGE in .env
   ```

3. **Start it**
   ```sh
   docker compose up -d
   docker compose logs -f          # expect "Listening for Jobs"
   ```
   The runner appears under GitHub → *Settings → Actions → Runners* with the
   label `crm-nas`.

4. **Protect the environment** — GitHub → *Settings → Environments* → **New
   environment** `production`:
   - *Required reviewers*: yourself
   - *Deployment branches and tags*: **Selected** → add tag rule `v*`
   This is the approval gate: every deploy waits for your click.

5. **Harden Actions** — GitHub → *Settings → Actions → General*:
   - *Fork pull request workflows from outside collaborators*: **Require approval
     for all external contributors**
   - Self-hosted runners are only usable by workflows in this private repo; never
     enable them for a public fork of it.

## Deploying

- **Normal**: `git tag v0.52.0 && git push origin v0.52.0` → CI-equivalent checks
  run → you approve `production` → the runner deploys (backup → build → up →
  health check).
- **Manual / rollback**: GitHub → *Actions → Deploy → Run workflow*, enter a tag
  or SHA.
- **Rollback the data too**: restore the matching `pre-<version>-<ts>.dump` from
  `/volume1/docker/crm/` (procedure: in-app docs → *Kopijos ir atkūrimas*).

## Security notes

The runner can control the Docker daemon (≈ root on the NAS) and holds a PAT.
Mitigations: private repo only, ephemeral runner, `no-new-privileges`, the
`deploy` job is not PR-triggerable and is gated by environment approval, and
`deploy.yml` uses only first-party actions. Rotate the PAT on schedule.

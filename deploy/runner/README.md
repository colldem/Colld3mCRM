# CRM deploy runner (self-hosted GitHub Actions)

A single ephemeral runner on the NAS that runs the `deploy` job of
`.github/workflows/deploy.yml`. It needs the Docker socket (to build and start
the app) and the app directory `/opt/crm`.

## One-time setup

1. **Create a fine-grained PAT** — GitHub → *Settings → Developer settings →
   Fine-grained tokens* → *Generate new token*:
   - Resource owner: your account
   - Repository access: *Only select repositories* → `Colld3mCRM`
   - Permissions: **Administration → Read and write**, **Actions → Read**
   - Short expiry (e.g. 90 days); set a calendar reminder to rotate.

2. **Configure and pin the image**

   `/opt/crm-runner` on the NAS is already provisioned: `compose.yaml`,
   a `.env` (mode 600) with `REPO_URL` and the verified `DOCKER_GID=121`, and
   `RUNNER_IMAGE` pinned to the pulled digest. Only the token is missing — put
   the PAT from step 1 on the `ACCESS_TOKEN=` line, replacing the placeholder.

   To re-pin the image later (do this when you rotate the PAT — `.env` never
   leaves the NAS, so Dependabot cannot bump it):
   ```sh
   cd /opt/crm-runner
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

4. **Restrict the environment** — GitHub → *Settings → Environments* →
   `Production`, and again for `Staging`:
   - *Deployment branches and tags*: **Selected** → add tag rule `v*`

   There is no approval button: *Required reviewers* needs a paid plan on a
   private repository, and on a public one it is not the control that matters
   here anyway. What makes a release deliberate is that only someone with write
   access can push the tag.

5. **Harden Actions** — GitHub → *Settings → Actions → General* →
   *Fork pull request workflows from outside collaborators*: **Require approval
   for all outside collaborators**. On a public repository this is the setting
   that keeps a stranger's pull request off this machine. See *Security notes*.

## Deploying

- **Normal**: `git tag v0.52.0 && git push origin v0.52.0` → CI-equivalent checks
  run → the runner deploys (backup → build → up →
  health check).
- **Manual / rollback**: GitHub → *Actions → Deploy → Run workflow*, enter a tag
  or SHA.
- **Rollback the data too**: restore the matching `pre-<version>-<ts>.dump` from
  `/opt/crm/` (procedure: in-app docs → *Kopijos ir atkūrimas*).

## Security notes

**This runner can control the Docker daemon, which is equivalent to root on the
host, and it holds a PAT.** The repository is public, which GitHub explicitly
warns against for self-hosted runners: a pull request from a fork carries its own
copy of the workflow files, so without a gate someone could point a job at this
machine and run whatever they liked on it.

What stands between a stranger and that:

- **Fork pull requests require approval.** Set *Settings → Actions → General →
  Fork pull request workflows from outside collaborators* to **Require approval
  for all outside collaborators**. This is the load-bearing one — nothing from a
  fork runs at all until you click approve. Check it after any Actions settings
  change.
- The deploy jobs trigger only on a tag push, a push to `main`, or
  `workflow_dispatch`, all of which need write access, and each is additionally
  guarded by `if: github.repository == ... && github.event_name != 'pull_request'`.
- `ci.yml`, the only workflow a pull request can reach, runs on GitHub-hosted
  runners, never this one.
- The runner is ephemeral (it re-registers between jobs), runs with
  `no-new-privileges`, and mounts only the two app directories.
- The workflows use first-party actions only.

Rotate the PAT on schedule, and re-pin `RUNNER_IMAGE` when you do.

If you would rather not accept this risk at all, delete the two deploy workflows
and run `scripts/deploy.sh` over SSH instead; nothing else depends on the runner.

# Regitros staging aplinka

Antra staging instancija šalia viešosios. Abi laiko produkcijos duomenų kopiją,
abi izoliuotos (`CRM_ENVIRONMENT=staging`), bet tai — Regitros versija:
registrų kolona, asmens kodas, paieška su pagrindu ir prieigos seansai.

| | Vieša staging | Regitros staging |
| --- | --- | --- |
| Šaka | `main` | `regitra` |
| Katalogas NAS | `/volume1/docker/crm-staging` | `/volume1/docker/crm-regitra-staging` |
| Compose projektas | `crm-staging` | `crm-regitra-staging` |
| Diegia | `deploy-staging.yml` | `deploy-regitra-staging.yml` |

Viena kitos jos neliečia: visi duomenys (`runtime/postgres`, `runtime/media`,
`runtime/tailscale-state`) guli po instancijos katalogu, o projekto vardas
skiria konteinerius. Bendri lieka tik host'o portai — todėl žemiau jie kiti.

## Greičiausias kelias: be terminalo

NAS'e jau sukasi GitHub Actions runner'is, kuris ten ir diegia. Juo galima
atlikti ir sąranką — terminalo nereikia.

**1. Leisti runner'iui matyti naują katalogą.** NAS'o Docker programoje
atidarykite projektą `crm-runner`, jo `compose.yaml` prie `volumes` pridėkite

```yaml
      - /volume1/docker/crm-regitra-staging:/volume1/docker/crm-regitra-staging
```

ir perkurkite projektą. Katalogą Docker susikurs pats — jo kurti nereikia.
(Repozitorijoje `deploy/runner/compose.yaml` ta eilutė jau yra; NAS'e gyvenantis
failas atskiras, todėl jį reikia pataisyti ranka.)

**2. Jei turite Tailscale raktą** — GitHub → Settings → Secrets and variables →
Actions → Secrets → `REGITRA_STAGING_TS_AUTHKEY`. Neprivaloma: be jo `.env`
bus sukurtas su tuščiu `TS_AUTHKEY`, kurį įrašysite vėliau.

**3. GitHub → Actions → „Set up Regitra staging" → Run workflow**, įveskite
savo tailnet domeną (pvz. `tailb8493f.ts.net`). Jis sukurs `.env` su naujai
sugeneruotais raktais ir žurnale parodys, ką dar nustatyti.

Esamo `.env` jis neperrašo, tad paleisti antrą kartą nepavojinga.

## Tas pats iš terminalo

NAS'e, CRM kataloge:

```bash
sh scripts/setup-regitra-staging.sh <jūsų-tailnet>.ts.net
```

Jis sukuria katalogą, sugeneruoja `DJANGO_SECRET_KEY`, `CRM_SECRETS_KEY` ir
`POSTGRES_PASSWORD`, surašo `.env` (teisės 600) ir atspausdina, kuriuos du
GitHub kintamuosius dar reikia nustatyti. Esamo `.env` jis neperrašo.
Tailscale rakto paprašys arba jį galima paduoti per `TS_AUTHKEY`.

Toliau — kas tame `.env` atsiranda ir ką reiškia, jei norite daryti rankomis.

## Ką reikia padaryti NAS'e (vieną kartą)

**1. Katalogas ir `.env`.**

```bash
sudo mkdir -p /volume1/docker/crm-regitra-staging
sudo chown "$USER" /volume1/docker/crm-regitra-staging
cd /volume1/docker/crm-regitra-staging
```

Sukurkite `.env`:

```sh
COMPOSE_FILE=compose.yaml:compose.tailscale.yaml:compose.staging.yaml:compose.regitra-staging.yaml
COMPOSE_PROJECT_NAME=crm-regitra-staging
CRM_FLAVOUR=regitra
CRM_ENVIRONMENT=staging

# Tailscale: atskiras mazgas, atskiras vardas.
TS_AUTHKEY=tskey-auth-...
TS_HOSTNAME=crm-regitra-staging
TS_CERT_DOMAIN=crm-regitra-staging.<jūsų-tailnet>.ts.net
TS_SERVE_CONFIG=/config/serve-staging.json

CRM_DOMAIN=crm-regitra-staging.<jūsų-tailnet>.ts.net
DJANGO_ALLOWED_HOSTS=crm-regitra-staging.<jūsų-tailnet>.ts.net,localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=https://crm-regitra-staging.<jūsų-tailnet>.ts.net
CRM_BASE_URL=https://crm-regitra-staging.<jūsų-tailnet>.ts.net

# Kiti portai nei viešoji staging — jie vieninteliai bendri.
CRM_PORT=8082
CRM_LAN_PORT=18083

# Savi raktai. NEKOPIJUOKITE iš kitos instancijos.
DJANGO_SECRET_KEY=<naujas>
CRM_SECRETS_KEY=<naujas>
POSTGRES_PASSWORD=<naujas>
```

Naujus raktus sugeneruoti:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(64))'                      # DJANGO_SECRET_KEY
python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'  # CRM_SECRETS_KEY
```

**2. GitHub repozitorijos kintamieji** (Settings → Secrets and variables →
Actions → Variables):

| Kintamasis | Reikšmė |
| --- | --- |
| `CRM_REGITRA_STAGING_DIR` | `/volume1/docker/crm-regitra-staging` — **neprivaloma**, tai numatytoji reikšmė workflow faile |
| `CRM_REGITRA_STAGING_URL` | `https://crm-regitra-staging.<tailnet>.ts.net` — neprivaloma, tik nuoroda GitHub aplinkoje |

Nustačius `CRM_REGITRA_STAGING_DIR` neteisingai, diegimas **nutrūks** —
`scripts/deploy-staging.sh` reikalauja, kad tikslinio katalogo `.env` turėtų
`CRM_FLAVOUR=regitra`, tad viešoji staging nebus perrašyta per klaidą.

**3. GitHub aplinka** (Settings → Environments): sukurti `Regitra staging`.
Apsaugos taisyklių jai nereikia.

**4. Pirmas paleidimas.** Įkėlus bet ką į `regitra` šaką, „Deploy Regitra
staging" nusideploy'ins pats. Arba rankiniu būdu iš NAS:

```bash
cd /volume1/docker/crm-regitra-staging
docker compose build --pull && docker compose up -d
```

**5. Duomenys.** `scripts/refresh-staging.sh` nukopijuoja produkcijos bazę ir
pats paleidžia `manage.py sanitize_staging`. Nurodykite šį katalogą:

```bash
CRM_APP_DIR=/volume1/docker/crm \
CRM_STAGING_DIR=/volume1/docker/crm-regitra-staging \
  sh /volume1/docker/crm-regitra-staging/scripts/refresh-staging.sh
```

Skriptas atsisako dirbti, jei nurodytas katalogas nėra staging
(`CRM_ENVIRONMENT=staging`), o produkcijoje tik skaito (`pg_dump`).

## Ko tikėtis

- Prisijungimai tie patys kaip produkcijoje (duomenų kopija).
- El. paštas, IMAP, Entra ir webhook'ai išjungti — `CRM_ENVIRONMENT=staging`.
- `crm-worker` ir `crm-backup` nepaleisti (0 replikų) — niekas neveikia pagal
  laikmatį ant kopijuotų duomenų.
- Registrų blokai užpildyti pavyzdiniais duomenimis (`CRM_DEMO_BLOCKS=1` ateina
  iš `compose.staging.yaml`), pažymėtais prierašu.
- Viršuje — geltona juosta, sakanti, kad tai izoliuota kopija.

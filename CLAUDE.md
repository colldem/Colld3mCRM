# Colld3m CRM — darbo taisyklės

Django 5.2 CRM (kontaktai, įmonės, veiklos, priminimai). Produkcija: UGREEN NAS
Docker, pasiekiama per Tailscale HTTPS (`https://crm.example.com`).
GitHub: `github.com/colldem/Colld3mCRM`. **Ši šaka — `regitra`**, Regitros
versija; bendrinis produktas gyvena `main`. Iš `main` imti tik `cherry-pick`,
niekada `merge` — žr. `docs/REGITRA-SAKA.md`.

## Taisyklės KIEKVIENAM pakeitimui

1. **Tik konkreti funkcija.** Kodas rašomas tik tai užduočiai. Jokio
   „papildomo" refaktorinimo, jokių nesusijusių pataisymų tame pačiame diff'e.
   Prieš baigiant — peržiūrėti diff'ą ir patikrinti, ar kiekviena eilutė
   priklauso šiai funkcijai. Nereikalingas senas kodas (dead code, nebenaudojami
   vertimai ir pan.), atsiradęs dėl pakeitimo, pašalinamas.
2. **Testai.** Paleisti visą patikrą ir įsitikinti, kad viskas žalia:
   ```bash
   PYTHON_BIN=.venv/bin/python sh scripts/release-check.sh
   ```
   (leidžia `makemigrations --check`, visus testus ir `manage.py check --deploy`) **ir**
   `PYTHON_BIN=.venv/bin/python sh scripts/security-check.sh` (pip-audit, bandit) — commit tik abiem praėjus.
   Naujai logikai — pridėti testą į `tests/test_contacts.py` ar `tests/test_theme.py`.
3. **Patikra naršyklėje.** Paleisti lokalų serverį ir realiai patikrinti
   pakeitimą naršyklėje (LT ir, jei liečia sąsają, EN; desktop ir mobilus vaizdas):
   ```bash
   DJANGO_DEBUG=true .venv/bin/python manage.py runserver 127.0.0.1:8765
   ```
   Lokalus adminas: `dev` / `devlocalpass123` (tik lokali SQLite, ne produkcija).
4. **GitHub.** `git push` į `main` iškart po commit'o — CI (`.github/workflows/ci.yml`:
   ruff, `release-check.sh`, Docker image + smoke) turi būti žalias. Commit žinutė
   `fix:` / `feat:` / `chore:` stiliumi, glausta, apie tą vieną pakeitimą.
5. **Diegimas.** Kiekvienas push į `main` automatiškai nusideploy'ina į
   **staging** (`https://crm-staging.example.com`, `deploy-staging.yml` →
   `scripts/deploy-staging.sh`) — ten realių produkcijos duomenų kopija, bet
   `CRM_ENVIRONMENT=staging` išjungia el. paštą, IMAP, Entra ir webhook'us, ir
   nėra `crm-worker`. Duomenis atnaujinti: `scripts/refresh-staging.sh` (rankiniu
   būdu ant NAS). Į produkciją — tik po patikros staging'e.
   Jei keitėsi funkcionalumas — bumpinti `VERSION` ir
   `image: crm-web:X.Y.Z` bei `crm-backup:X.Y.Z` `compose.yaml`. Diegimas: `git tag vX.Y.Z && git push
   origin vX.Y.Z` → GitHub Actions „Deploy" praeina patikras → runner ant NAS
   daro backup → build → `up -d` → health check. Patvirtinimo mygtuko **nėra**
   („Required reviewers" reikalauja mokamo plano privačiam repo), tad sąmoningas
   veiksmas yra pati žymos įkėlimas. Rankinis atsarginis kelias:
   `scripts/deploy.sh` arba `docker compose build --pull && up -d`. Perdangos
   parenkamos per `COMPOSE_FILE` NAS `.env` faile. Patikrinti: `crm-db`,
   `crm-web`, `crm-worker` healthy, `/health/ready` = `ready`.
6. **Dokumentacija.** Jei pakeitimas prideda ar keičia funkciją, matomą
   naudotojui (naują langą, mygtuką, nustatymą, prieigos taisyklę), tame
   pačiame pakeitime atnaujinti in-app žinyną `templates/settings/documentation.html`
   ir, jei keičiasi funkcijų sąrašas ar priklausomybės — `README.md` bei šio
   failo „Struktūra" sąrašą. Versijos numeris žinyne imamas iš `VERSION`.

## Aplinka

- `.venv/` — Python 3.12, priklausomybės iš `requirements.txt` + `django-axes`.
- Lokaliai DB = SQLite (`db.sqlite3`, gitignore). Produkcijoje = PostgreSQL.
- Vertimai: `locale/en/LC_MESSAGES/*.po`; perkompiliuoti `.mo`:
  `msgfmt locale/en/LC_MESSAGES/djangojs.po -o locale/en/LC_MESSAGES/djangojs.mo`
- Statiniai failai turi `?v=YYYYMMDD` cache-buster'į `templates/base.html` —
  keičiant `static/css/*` ar `static/js/*` bumpinti atitinkamą reikšmę.

## Struktūra

- `contacts/models.py` — Person, Company, PersonCompanyLink, Activity,
  Attachment, Reminder, Tag, Category, SavedFilter, UserProfile, Team,
  RolePermissions, AuditLog, CustomField, CustomValue, DuplicateSettings,
  SystemSettings, IncomingMail, AutomationRule, AutomationLog, ApiToken, Webhook, WebhookDelivery, Translation, DuplicateException, DirectoryGroupMapping.
- `contacts/views.py` — pagrindiniai puslapiai; `analytics_views.py` —
  darbastalis, analitikos apžvalga (`analytics_overview`) ir 5 detalios skiltys;
  `calendar_views.py` — kalendorius;
  `detail_editing.py` / `inline_views.py` — AJAX laukų redagavimas;
  `duplicates.py` / `merging.py` — dublikatai; `filters.py` — sąrašų filtrai;
  `permissions.py` — rolės (admin / vadovas / visi / savi / skaitytojas), teisės (`CAPABILITIES`,
  paaiškinimai `CAPABILITY_HINTS`) ir įrašų matomumas;
  `middleware.py` `ReadOnlyRoleMiddleware` — skaitytojui atmeta redagavimo puslapius ir rašymus;
  `middleware.py` `SecurityHeadersMiddleware` — CSP su nonce (`{{ csp_nonce }}` ant įterptinių `<script>`),
  Permissions-Policy; įterptinių `on*=` tvarkytojų nenaudoti — `static/js/behaviors.js` (`data-confirm`, `data-autosubmit`, `data-row-href`);
  `record_access.py` + `record_access_views.py` — kam, kokiu pagrindu ir kiek laiko
  įrašas yra sąraše, ir paieškos su pagrindu puslapis (`/paieska/`)
  (`RecordAccess`, `grant` / `touch` / `take_into_work` / `live_for` / `find`; žr.
  `docs/REGITRA-PRIEIGA.md`);
  `record_blocks.py` — kortelės vidurinės kolonos blokai (Regitros integracijos
  sąlyčio taškas; `register_block`, žr. `docs/REGITRA-INTEGRACIJA.md`);
  `record_blocks_demo.py` — tų blokų pavyzdiniai duomenys (`CRM_DEMO_BLOCKS=1`,
  tik ne produkcijoje); `validators.py` — asmens kodo tikrinimas;
  `personal_code.py` — asmens kodo uždengimas kortelėje (`cover`) ir atidengimas
  su įrašu žurnale (`AuditLog.PERSONAL_CODE`);
  `menu.py` — asmeninė šoninė juosta (branduolys / naudotojo nuorodos / „Daugiau“ klostė;
  konfigūracija `UserProfile.menu_config`); `charts.py` — SVG grafikai
  (`stacked_bars`, `grouped_bars`, `line_series`, `donut`, `donut_multi`, `sparkline`);
  `notifications.py` + `management/commands/send_notifications.py` — el. pašto pranešimai;
  `recurrence.py` + `management/commands/extend_recurrences.py` — pasikartojantys priminimai;
  `ical.py` — .ics kalendoriaus srautas; atskiro priminimų sąrašo puslapio nėra —
  priminimai gyvena varpelyje (`reminder_live.py`), kalendoriuje ir kortelėse;
  varpelio atidarymas žymi juos skaitytais (`reminder_mark_read`); `sanitizers.py` — `safe_url` / `csv_safe`;
  `mailfetch.py` + `management/commands/fetch_mail.py` — IMAP gautų laiškų prisegimas;
  `oidc.py` — OIDC prisijungimo backend'as (Entra ID arba AD FS; iss/aud/exp/tid tikrinimas), view'ai,
  `LocalAccountBackend` (vien SSO režimas, avarinės paskyros `CRM_BREAK_GLASS_USERS`) ir
  `DirectorySessionRefresh` middleware (katalogo sesijos pakartotinis tikrinimas);
  `directory.py` — AD grupių susiejimas su rolėmis ir komandomis, taikomas kiekvieno prisijungimo metu;
  `integrations.py` — efektyvi SMTP/IMAP/OIDC konfigūracija (DB + `.env` fallback);
  izoliacija: kai `CRM_ENVIRONMENT` ≠ `production`, visi trys akcesoriai grąžina
  inertišką konfigūraciją, o `webhooks.emit`/`post_once` atsisako siųsti — kad
  iš produkcijos atkurta kopija neveiktų realiame pasaulyje
  (`manage.py sanitize_staging` išvalo tai ir pačiuose duomenyse);
  `crypto.py` — integracijų slaptažodžių šifravimas (`CRM_SECRETS_KEY`);
  `antivirus.py` — ClamAV (clamd INSTREAM) visų įkeliamų failų tikrinimas; `compose.clamav.yaml` — ClamAV perdanga;
  `privacy.py` — duomenų subjekto eksportas (ZIP) ir ištrynimas su žurnalo nuasmeninimu; `anonymize.py` — staging nuasmeninimas;
  `observability.py` — JSON žurnalai (`CRM_LOG_FORMAT`), `X-Request-ID`, `crm.security` įvykiai (audito veidrodis be asmens duomenų);
  `automation.py` + `management/commands/run_automations.py` — „kai X → daryk Y" taisyklės;
  `api.py` + `api_urls.py` — rankomis rašytas JSON REST API (`/api/v1/`);
  `webhooks.py` + `management/commands/deliver_webhooks.py` — išeinantys webhookai (signalai + worker);
  `translations.py` + `middleware.py` — redaguojami sąsajos vertimai (CSV eksportas/importas
  per Nustatymai → Vertimai; override'ai DB, įrašomi tiesiai į Django katalogą veikiant,
  middleware sinchronizuoja procesus per versijos žymą).
- Foninius darbus (`extend_recurrences`, `send_notifications`, `fetch_mail`,
  `run_automations`, `deliver_webhooks`, `deactivate_inactive_users` — `accounts.py`, `purge_audit_log` — `audit.py`, `apply_retention` — `privacy.py`) vykdo `crm-worker` paslauga `compose.yaml` (ciklas kas
  `WORKER_INTERVAL_SECONDS` s).
- `templates/` — Django šablonai; `static/` — CSS/JS + `vendor/adminlte`.
  Vienas kortelių apvalkalas visame produkte — `.dash-card` (+ `.dash-grid`,
  `.dash-card-head`, `.kpi-card`); kortelės antraštė visada `--fs-md`/700.
- `.github/workflows/` — `ci.yml` (push/PR), `deploy-staging.yml` (push į `main`),
  `deploy.yml` (tag `v*`), abu `runs-on: self-hosted crm-nas`.
  `scripts/backup.sh` (crm-backup image, `deploy/backup/Dockerfile`) — šifruotos kopijos; `scripts/restore.sh` — atkūrimas
  (CI `backup-restore` darbas atlieka avarinio atkūrimo pratybas); `scripts/security-check.sh` — pip-audit + bandit (CI `security` darbas; Trivy ir SBOM — `image` darbe);
  `scripts/deploy.sh` / `deploy-staging.sh` — diegimas; `refresh-staging.sh` —
  produkcijos duomenų kopija į staging. `compose.staging.yaml` — staging stack'as
  (be `crm-worker`, `serve-staging.json` be Funnel).
  `deploy/runner/` — self-hosted runner konteineris (`README.md` — sąranka).
- `docs/paketas/` — dokumentų paketas organizacijai (LT); `04-duomenu-zodynas.md` generuojamas
  `manage.py data_dictionary` — pridėjus modelį ar lauką, klasifikuoti `contacts/data_dictionary.py` ir pergeneruoti.
- `docs/DIEGIMAS-ORGANIZACIJOJE.md` — organizacinis diegimas: tinklo srautai, proxy, resursai (CI `load`), atnaujinimo ir rollback runbook.
- `docs/ORACLE.md` — Oracle suderinamumo patikros rezultatai (CI `oracle-compatibility`, tik ataskaita).
  Naujame kode vengti `.distinct()`/`annotate(Count)` ant modelių su `TextField` — žr. ten.
- `docs/REGITRA-SAKA.md` — šios šakos santykis su `main` ir kas joje yra papildomai.
- `docs/REGITRA-STAGING.md` — antra staging instancija šiai šakai
  (`compose.regitra-staging.yaml`, `deploy-regitra-staging.yml`,
  `scripts/setup-regitra-staging.sh` + `setup-regitra-staging.yml` — sąranka NAS'e
  be terminalo, per runner'į); push į `regitra`
  nusideploy'ina ten, viešosios staging neliečia.
- `docs/REGITRA-PRIEIGA.md` — paieška su pagrindu, prieigos galiojimas ir rolės.
- `docs/REGITRA-INTEGRACIJA.md` — Regitros dalis atskirame repozitorijuje ir keturios
  aplinkos (CRM prod/staging, Regitra prod/staging).
- `docs/INTEGRACIJOS.md` — integracijų kanalai; `reporting` schema (migracija 0051) ir `create_reporting_role`
  — tik skaitymo prieiga DWH; keičiant modelius, kurių laukai yra rodiniuose, atnaujinti rodinius nauja migracija.
- `docs/DEPLOYMENT.md` — bendrinė diegimo procedūra (bet kuris Docker hostas,
  nuosavas domenas per Caddy, Tailscale) ir visų aplinkos kintamųjų lentelės;
  prieš diegimą būtina DB ir `runtime/media` atsarginė kopija.
- `docs/ARCHITECTURE.md` § „Kur ką pridėti" — kur dedamas naujas puslapis,
  nustatymų skiltis, meniu punktas, teisė, laukas, foninis darbas, grafikas,
  stilius ar vertimas. Pridėjus naują aplinkos kintamąjį — įrašyti į
  `.env.example` **ir** `docs/DEPLOYMENT.md` lentelę.
- `deploy/helm/crm/` — Helm chart'as Kubernetes'ui (web Deployment, migracijų Job
  kaip `pre-upgrade` hook, 9 CronJob'ai vietoj `crm-worker`, nginx Ingress;
  DB ir failų saugykla — išorinės). Instrukcija: `docs/KUBERNETES.md`.
  Atvaizdas į GHCR keliamas `publish-image.yml` uždėjus `v*` žymą.

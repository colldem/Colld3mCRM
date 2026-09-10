# Colld3m CRM — architektūros aprašymas

Šis dokumentas apibendrina, iš ko sudaryta CRM, kaip komponentai jungiasi ir
kokiais principais parašytas kodas. Kasdienio darbo ir diegimo instrukcijos yra
atskirai: programoje **Nustatymai → Dokumentacija**, `README.md` ir
`docs/DEPLOYMENT.md`.

---

## 1. Kas tai ir kam

Vienos komandos CRM: bendrame registre tvarkomi kontaktiniai asmenys, įmonės, jų
ryšiai, bendravimo istorija, failai ir priminimai. Produkcija — vienas UGREEN NAS,
Docker Compose, prieiga per Tailscale HTTPS. Vienas realus naudotojas šiuo metu,
bet duomenų modelis ir teisės paruoštos kelioms paskyroms ir komandoms.

Sąmoningi apribojimai: nėra automatinių atsarginių kopijų su šifravimu, nėra
el. paštu siunčiamo slaptažodžio atkūrimo. Sąsajoje visi matomi įrašai yra ir
redaguojami; „tik skaityti" prieiga yra tik per API raktą.

---

## 2. Technologijų rietuvė

| Sluoksnis | Technologija | Vaidmuo |
|---|---|---|
| Kalba | Python 3.13 (prod), 3.12 (lokalus `.venv`) | — |
| Karkasas | Django 5.2 | MTV, ORM, auth, admin, i18n, migracijos |
| DB | PostgreSQL 17 (prod) / SQLite (lokaliai, testai) | `DB_HOST` aplinkos kintamasis perjungia |
| WSGI serveris | Gunicorn (2 workeriai × 2 gijos, 60 s timeout) | `config.wsgi:application` |
| Statiniai failai | WhiteNoise + `CompressedManifestStaticFilesStorage` (prod) | hash'uoti failai, gzip/br, be atskiro Nginx |
| DB draiveris | `psycopg` 3 (binary) | — |
| Slaptažodžiai | Argon2 (`argon2-cffi`), min. 12 simbolių, 4 validatoriai | `PASSWORD_HASHERS` |
| Prisijungimų ribojimas | `django-axes` 8 | 5 klaidos → 30 min blokada pagal (username, ip), HTTP 429 |
| SSO (neprivalomas) | `mozilla-django-oidc` | Microsoft Entra ID prisijungimas, įjungiamas Nustatymuose |
| REST API | rankomis rašytas JSON (`contacts/api.py`), be DRF | `/api/v1/`, „Bearer" token'ai, ta pati matomumo apsauga |
| El. paštas | Django SMTP backend + `imaplib` (gauti laiškai) | konfigūruojama Nustatymuose; be jos — laiškai į žurnalą, IMAP išjungtas |
| Paslaptys | `cryptography` (Fernet) | Nustatymuose suvesti integracijų slaptažodžiai šifruojami raktu `CRM_SECRETS_KEY` |
| Importas | `openpyxl` | XLSX skaitymas; CSV — standartinė biblioteka |
| Sąsaja | AdminLTE 4 + Bootstrap 5, **įdiegti vietoje** `static/vendor/adminlte/` | uždaras tinklas — jokių CDN |
| Grafikai | rankomis generuojamas inline SVG (`contacts/charts.py`) | jokios chart bibliotekos |
| Tinklas / TLS | Tailscale konteineris + Tailscale Serve (`deploy/tailscale/serve.json`) | HTTPS terminacija, `crm-web` dalijasi tinklu su `crm-tailscale` |

Priklausomybės fiksuotos `requirements.txt` (tikslios versijos), Python bazinis
image — pinuotas pagal SHA `Dockerfile`.

---

## 3. Katalogų sandara

```
config/            Django projektas
  settings.py      viena byla, konfigūruojama aplinkos kintamaisiais
  urls.py          šakninis URL žemėlapis (admin, auth, setup, health, PWA)
  wsgi.py
contacts/          vienintelė programa (app)
  models.py        visi modeliai
  views.py         pagrindiniai puslapiai ir CRUD
  analytics_views.py   darbastalis + analitikos apžvalga ir detalūs puslapiai
  calendar_views.py    kalendorius ir įvykių API
  charts.py        SVG grafikų geometrija
  menu.py          šoninis meniu: privalomi punktai, naudotojo nuorodos, „Daugiau"
  permissions.py   rolės, teisių lentelė, įrašų matomumo Q filtrai
  detail_editing.py / inline_views.py   inline (AJAX) laukų redagavimas
  duplicates.py / merging.py            dublikatų aptikimas ir sujungimas
  filters.py       sąrašų filtrų logika
  forms.py         Django formos
  custom_fields.py dinaminių laukų apdorojimas
  audit.py         AuditLog rašymo pagalbininkas
  signals.py       m2m limitas (≤3), prisijungimo/atsijungimo audit
  context_processors.py  priminimų skaičius, profilis, teisės, sistemos nustatymai
  reminder_live.py / reminder_queries.py  priminimų snapshot ir užklausos
  notifications.py  el. pašto pranešimų kūrimas ir siuntimas
  recurrence.py     pasikartojančių priminimų materializavimas
  ical.py           .ics kalendoriaus srautas (be bibliotekos)
  mailfetch.py      IMAP gautų laiškų parsisiuntimas ir priskyrimas
  oidc.py           Microsoft Entra ID (OIDC) backend'as + gate'inti view'ai
  integrations.py   efektyvi SMTP / IMAP / OIDC konfigūracija (DB + .env fallback)
  crypto.py         integracijų slaptažodžių šifravimas (Fernet, CRM_SECRETS_KEY)
  sanitizers.py     safe_url / csv_safe
  automation.py     „kai X -> daryk Y" taisyklės (H2)
  api.py / api_urls.py  rankomis rašytas JSON REST API (H3), /api/v1/
  webhooks.py       išeinantys webhookai (H4): emit() signaluose, worker POST’ina
  translations.py / middleware.py  redaguojami sąsajos vertimai (DB override'ai
                    įrašomi į gyvą gettext katalogą; middleware sinchronizuoja procesus)
  templatetags/crm_format.py  šablonų filtrai (record_tone, record_initials, short_since …)
  management/commands/  send_notifications, extend_recurrences, fetch_mail, run_automations, deliver_webhooks, ensure_admin, sanitize_staging
  migrations/      migracijos
templates/         serverio pusėje renderinami šablonai (be JS karkaso)
static/            css/ (app.css — žetonai ir bazė, theme.css — komponentai),
                   js/ (progresyvus enhancement), vendor/adminlte
locale/en/         .po / .mo (šaltinis — lietuviški msgid)
tests/             test_contacts.py, test_theme.py (~270 iš viso)
scripts/           entrypoint.sh, backup.sh, release-check.sh, deploy*.sh, refresh-staging.sh
deploy/tailscale/  serve.json          deploy/caddy/   Caddyfile
deploy/runner/     self-hosted CI runner konteineris
deploy/helm/crm/   Helm chart'as Kubernetes klasteriui (žr. docs/KUBERNETES.md)
docs/              ši byla, DEPLOYMENT.md, KUBERNETES.md, REMAINING-WORK.md
```

---

## 4. Užklausos kelias

```
Naršyklė ─HTTPS─▶ Tailscale (Serve, TLS terminacija, tik tailnet arba Funnel)
                     │  (crm-web veikia crm-tailscale tinklo vardų erdvėje)
                     ▼
                 Gunicorn :8080
                     ▼
   SecurityMiddleware → WhiteNoise → Session → Locale → Common → CSRF
   → Auth → Messages → XFrameOptions → Axes
                     ▼
                 config.urls → contacts.urls → view
                     ▼
        ORM (PostgreSQL, CONN_MAX_AGE=60) + Django šablonai
```

- `SECURE_PROXY_SSL_HEADER` leidžia Django atpažinti HTTPS už Tailscale proxy.
- `SECURE_REDIRECT_EXEMPT = ^health/` — sveikatos taškai atsako be HTTPS
  peradresavimo (konteinerio healthcheck kviečia per `http://127.0.0.1:8080`).
- `RUNNING_TESTS` išjungia WhiteNoise, saugius slapukus ir HTTPS redirect'ą, kad
  Django testinis klientas veiktų.

---

## 5. Duomenų modelis

**Įrašai ir rekvizitai**
- `Company`, `Person` — paveldi `RecordDetailsModel` (bendri rekvizitai) ir
  `TimestampedModel` (`created_at`/`updated_at`). Turi `owner`, papildomus
  atsakingus, `favourite`, minkštą trynimą (`deleted_at` — „archyvas").
- `PersonCompanyLink` — asmens ↔ įmonių M:N su pagrindinės įmonės požymiu ir pareigomis.
- `PhoneNumber`, `EmailAddress`, `PostalAddress`, `WebLink` — daugiareikšmiai,
  susieti su `Person` (įmonei atitinkami laukai yra tiesiai `Company`).

**Klasifikatoriai**
- `Tag`, `Category` — bendri; stabili spalva pagal ID; M:N su įrašais, ≤3 vienam
  įrašui (užtikrina `signals.enforce_three_item_limit`).
- `CustomField` + `CustomValue` — administratoriaus apibrėžti dinaminiai laukai
  (tekstas, data, sąrašas, kelių reikšmių sąrašas) kontaktams ir/ar įmonėms.

**Istorija**
- `Activity` — istorijos įrašas (pastaba / skambutis / el. laiškas / susitikimas /
  užduotis), susietas su `Person` arba `Company`.
- `Attachment` — `Activity` priedas; atsisiuntimas per autentifikuotą view su
  archyvo patikra.
- `Reminder` — priminimas, gali būti susietas su `Person`, `Company` arba niekuo;
  `due_at`, `end_at`, perskaitymo ir užbaigimo laikai; naudojamas ir kalendoriuje.

**Prieiga ir konfigūracija**
- `UserProfile` — 1:1 su `auth.User`: rolė (`admin` / `member` / `restricted`),
  įrašų matomumas (`all` / `team` / `own`), kalba, laiko zona, nuotrauka.
- `Team` — narių grupė su savo matomumu (`all` / `team`).
- `RolePermissions` — ne-administratorių rolių teisių lentelė (saugoma reikšmė
  gožia `_CAPABILITY_DEFAULTS`).
- `SavedFilter` — naudotojo vardinis sąrašo filtras.
- `DuplicateSettings`, `SystemSettings` — vienaeilės konfigūracijos.
- `AuditLog` — veiksmų žurnalas (aktorius, veiksmas, taikinio tipas/ID/etiketė,
  laukas, sena/nauja reikšmė, IP, kelias).
- `IncomingMail` — nepriskirtas IMAP laiškas (rankiniam priskyrimui).
- `AutomationRule` + `AutomationLog` — foninės „kai X → daryk Y" taisyklės ir jų
  veiksmų žurnalas (idempotencijos raktas).
- `ApiToken` — REST API „Bearer" raktas (saugoma tik sha256; scope read / read_write).
- `Webhook` + `WebhookDelivery` — išeinantys HTTP hookai ir jų pristatymo eilė
  (HMAC parašas, backoff, auto-išjungimas).

---

## 6. Teisės ir įrašų matomumas

Trys lygiai, visi `contacts/permissions.py`:

1. **Rolė** (`role_of`, `is_admin`). Administratorius — viskas. Ne-administratoriai
   turi galimybių rinkinį (`CAPABILITIES`: importas, eksportas, archyvavimas,
   dublikatų sujungimas, masiniai veiksmai, atsakingo keitimas, dinaminiai laukai,
   klasifikatoriai, žurnalas). Numatytieji `_CAPABILITY_DEFAULTS`, redaguojami
   Nustatymai → Rolės ir teisės (`RolePermissions`).
2. **Įrašų matomumas** — `visible_people()`, `visible_companies()`,
   `visible_reminders()` grąžina queryset'ą, apribotą `Q` filtru pagal
   `record_visibility`: `all` (viskas), `team` (savo + komandos draugų sukurti/atsakingi),
   `own` (tik savo). Analitika ir sąrašai visada eina per šias funkcijas.
3. **Django `is_staff` / `is_superuser`** — atskiri, reikalingi tik `/admin/`.

Teisės tikrinamos view lygyje (`_require_capability`) ir šablonuose per
`crm_permissions` context processor (`crm_caps.*`, `is_crm_admin`).

---

## 7. Sąsajos principai

- **Serverio pusėje renderinta.** Jokio SPA/React. Puslapis = Django šablonas.
- **Progresyvus enhancement.** `static/js/*.js` — nedideli, be karkaso: inline
  laukų redagavimas, popover meniu, kalendoriaus tempimas, paieškos pasiūlymai.
  Be JS lieka veikianti pagrindinė funkcija.
- **AdminLTE 4 + Bootstrap 5 įdiegti vietoje** (`static/vendor/adminlte/`) — uždaras
  tinklas, CDN nepasiekiamas. Ta pati priežastis: grafikai — rankomis dėliojamas
  SVG (`charts.py` + `templates/analytics/_chart.html`), be bibliotekų.
- **Dizaino žetonai** `static/css/app.css :root`: `--fs-*` (tipografijos skalė
  11–28), tarpų ritmas 2/4/6/8/10/12/16/20/24/32, `--radius* ` (4/6/8/pill),
  `--control-h*` (32/40/48). Nauji CSS dydžiai turi taikytis prie šių — žr.
  testus `tests/test_theme.py`.
- **Statinių cache-busting.** `templates/base.html` `?v=YYYYMMDD<raidė>` +
  ManifestStaticFilesStorage hash'as. Keičiant `static/css|js` — bumpinti `?v=`.
- **PWA.** `manifest.webmanifest` + `sw.js` (minimalus service worker).

---

## 8. Internacionalizacija

- Numatyta kalba `lt`; palaikoma `lt` / `en`. Šaltinio `msgid` — **lietuviški**;
  `locale/en/LC_MESSAGES/django.po` verčia į anglų.
- `LocaleMiddleware` + kalbos slapukas; naudotojo pasirinkimas saugomas ir
  `UserProfile.language`.
- Modulio lygio verčiamos eilutės — `gettext_lazy` (kad kalba neužstrigtų importo
  metu). SVG koordinatėse — `{% localize off %}` (dešimtainis taškas, ne lokalės kablelis).

---

## 9. Sauga

- Visi CRM langai — `login_required`. Setup langas (`/setup/`) veikia tik kol nėra
  nė vieno naudotojo ir su `CRM_SETUP_TOKEN`.
- Argon2, min. 12 simbolių, panašumo/dažnumo/skaitmenų validatoriai.
- `django-axes`: 5 klaidos → 30 min blokada (username+IP), 429.
- REST API (`/api/v1/`): „Bearer" token'ai (DB saugo tik `sha256`), CSRF-exempt
  (be slapukų), scope `read` / `read_write`, veikia su token kūrėjo matomumu ir
  teisėmis; panaikinami Nustatymuose. Nėra dažnio ribojimo (tailnet vidinis).
- Webhooks: adresai admino konfigūruojami (tik `http`/`https`), paslaptis DB
  šifruota, kūnas pasirašomas HMAC-SHA256. SSRF ribojimas: atmetami loopback ir
  link-local (debesų metadata) taikiniai, peradresavimai neseklojami; DNS
  rebinding lieka likutine rizika (admino atsakomybė). Payload'e gali būti bet
  kurio įrašo duomenys — endpoint'as turi būti patikimas.
- Neprivalomas Microsoft Entra ID (OIDC) prisijungimas, įjungiamas Nustatymai →
  Prisijungimas: `contacts.oidc.EntraOIDCBackend` susieja pagal el. paštą su esama
  aktyvia paskyra; naujų nekuria, kol neįjungtas atskiras jungiklis. Plumbing'as
  visada įkeltas, `EntraRequestView`/`EntraCallbackView` grąžina 404, kol
  `oidc_config().usable` yra `False`; endpoint'ai ir client id/secret imami iš DB
  per užklausą (`get_settings` override). Vietinis prisijungimas lieka.
- Integracijų slaptažodžiai (SMTP / IMAP / Entra secret) suvedami Nustatymuose ir
  DB saugomi šifruoti (`Fernet`, `enc:v1:` prefiksas). Raktas `CRM_SECRETS_KEY` —
  tik `.env`; be jo neslapti laukai veikia, slaptažodžių išsaugoti negalima.
  Formos laukai write-only (pateikus tuščią — lieka esamas). `pg_dump` ir ZIP
  eksportas neša tik neatšifruojamą tekstą.
- CSRF įjungta; `HttpOnly` + `SameSite=Lax` sesijos slapukai; idle timeout
  (`SESSION_COOKIE_AGE`, numatyta 480 min, `SESSION_SAVE_EVERY_REQUEST`).
- `DJANGO_FORCE_HTTPS=true` (prod): saugūs slapukai, `SECURE_SSL_REDIRECT`, HSTS.
- `X_FRAME_OPTIONS=DENY`, `SECURE_CONTENT_TYPE_NOSNIFF`, `Referrer-Policy=same-origin`.
- Konteineriai: `no-new-privileges:true`, `crm-web` veikia ne-root naudotoju `crm`.
- Failų atsisiuntimas — autentifikuotas, tikrina, ar įrašas neArchyvuotas.

---

## 10. Diegimo topologija (Docker Compose)

| Servisas | Image | Paskirtis | Nuolatinis tomas |
|---|---|---|---|
| `crm-db` | `postgres:17` | duomenų bazė | `runtime/postgres` |
| `crm-backup` | `postgres:17` | periodinis `pg_dump` (`scripts/backup.sh`) | `runtime/backups` |
| `crm-tailscale` | `tailscale/tailscale` | TLS/tinklas, Tailscale Serve | `runtime/tailscale-state` |
| `crm-web` | `crm-web:X.Y.Z` (vietinis build) | Django + Gunicorn | `runtime/media` |
| `crm-worker` | `crm-web:X.Y.Z` (tas pats image) | foninis ciklas: `extend_recurrences`, `send_notifications`, `fetch_mail`, `run_automations`, `deliver_webhooks` | `runtime/media` |

- `crm-web` naudoja `network_mode: service:crm-tailscale` — dalijasi Tailscale
  konteinerio tinklu, todėl klausosi `:8080` už Tailscale Serve.
- `crm-worker` sukasi `while true; do … ; sleep ${WORKER_INTERVAL_SECONDS:-300}; done`;
  komandos nekenksmingai nieko nedaro, kol integracijos neįjungtos Nustatymuose.
- Bendri env kintamieji laikomi `compose.yaml` YAML anchor'e `x-crm-env` ir
  įtraukiami į `crm-web` bei `crm-worker`.
- `entrypoint.sh`: `migrate --noinput` → `collectstatic --noinput` → gunicorn.
  Abu žingsnius galima išjungti (`CRM_RUN_MIGRATIONS=0`, `CRM_COLLECTSTATIC=0`),
  o gunicorno parametrai imami iš `CRM_GUNICORN_PORT/WORKERS/THREADS/TIMEOUT`.
  Visos numatytosios reikšmės atitinka ankstesnį elgesį, tad Compose diegimui
  nieko nustatinėti nereikia — jungikliai skirti klasteriui.
- Įkelti failai: `CRM_MEDIA_BACKEND=filesystem` (numatyta) rašo į `runtime/media`;
  `s3` perjungia į `django-storages` S3 backend'ą (`CRM_S3_BUCKET`, `_ENDPOINT`,
  `_REGION`, `_ACCESS_KEY`, `_SECRET_KEY`, `_ADDRESSING`). Daugiau nei vienam
  web procesui reikia antrojo — pod'o diskas yra jo paties.
- Healthcheck: `crm-web` — `GET /health/ready`; `crm-db` — `pg_isready`.
- Funkcinis pakeitimas → `VERSION` + `compose.yaml` `image:` tag'as bumpinami kartu.
- `.env` (negitinamas) laiko `POSTGRES_PASSWORD`, `DJANGO_SECRET_KEY`,
  `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `DJANGO_FORCE_HTTPS`,
  `TS_AUTHKEY`, `CRM_SETUP_TOKEN`, `CRM_SECRETS_KEY`, `CRM_BASE_URL`, taip pat
  neprivalomus `EMAIL_*`, `IMAP_*`, `OIDC_*` fallback'us (žr. `.env.example`).

### Kubernetes (alternatyva)

Tas pats atvaizdas veikia klasteryje per `deploy/helm/crm/`. Skiriasi tik tai, kas
ką daro: migracijos — vienas `Job` per leidimą (Helm `pre-upgrade` hook'as, todėl
nepavykusi migracija neišleidžia naujo kodo), statiniai failai įkepti į atvaizdą
(`Dockerfile` leidžia `collectstatic` su `DJANGO_DEBUG=false` ir tikrina, ar
atsirado `staticfiles.json`), įkelti failai — S3, o `crm-worker` ciklą pakeičia
penki `CronJob`'ai su `concurrencyPolicy: Forbid`. DB ir failų saugykla —
išorinės. Sesijos, `django-axes` ir vertimų override'ai jau buvo saugūs keliems
procesams, todėl Redis ar bendro cache nereikia. Pilna instrukcija —
`docs/KUBERNETES.md`.

---

## 11. Atsarginės kopijos

Nėra vieno perkeliamo failo. Pilna kopija = PostgreSQL `pg_dump -Fc` +
`runtime/media` + `runtime/tailscale-state` + `.env` + `compose.yaml` +
`deploy/tailscale/serve.json`. `crm-backup` daro periodinį DB dump'ą į
`runtime/backups`; kopija laikoma patikima tik atkūrus atskiroje aplinkoje
(procedūra — žinyne, tema „Kopijos ir atkūrimas").

---

## 12. Testai ir kokybės vartai

- `scripts/release-check.sh`: `makemigrations --check --dry-run` → visi testai →
  `check --deploy` (su prod-panašiais env) → `serve.json` JSON patikra.
- ~270 testų `tests/`. `test_theme.py` sergsti dizaino žetonų skalę, CSS
  taisyklių korektiškumą (pvz. kad selektorius vienoje byloje apibrėžtas vieną
  kartą) ir diegimo paruoštumą (`Dockerfile`, Helm chart'as).
- **CI** (`.github/workflows/ci.yml`, push/PR į `main`): `ruff check`,
  `release-check.sh`, Docker image build + `/health/ready` smoke, `chart` job'as
  (`helm lint` + `helm template`).
- **Staging** (`deploy-staging.yml`): kiekvienas push į `main` automatiškai
  diegiamas į staging (`CRM_ENVIRONMENT=staging`, be `crm-worker`).
- **CD** (`.github/workflows/deploy.yml`): paleidžiama version tag'u `vX.Y.Z`
  (arba rankiniu `workflow_dispatch`). `verify` job'as GitHub runner'yje pakartoja
  patikras; `deploy` job'as `runs-on: [self-hosted, crm-nas]` (ephemeral runner
  konteineris ant NAS, `deploy/runner/`). Atskiro patvirtinimo mygtuko nėra —
  sąmoningas veiksmas yra pati žymos įkėlimas. `scripts/deploy.sh`: backup →
  `rsync` šaltinį į `/opt/crm` → `compose build --pull` → `up -d` → sveikatos
  patikra. Ta pati žyma paleidžia ir `publish-image.yml`, kuris sudeda atvaizdą į
  GHCR (klasteriui); jis atsisako publikuoti, jei žyma nesutampa su `VERSION`.
- Kiekvienam pakeitimui: minimalus diff, žalias `release-check`, patikra
  naršyklėje (LT/EN, desktop/mobile). Žr. `CLAUDE.md`.

---

## 13. Kur ką pridėti

Trumpas žemėlapis: „noriu pridėti X" → kuriuos failus liesti. Visais atvejais
galioja `CLAUDE.md` taisyklės (minimalus diff, žalias `release-check.sh`, patikra
naršyklėje, in-app žinyno atnaujinimas).

**Naują puslapį.** View → `contacts/views.py` (arba teminė byla:
`analytics_views.py`, `calendar_views.py`); `@login_required`, sąrašai visada per
`visible_people()` / `visible_companies()` / `visible_reminders()`. Maršrutas →
`contacts/urls.py` (vardas be prefikso, kviečiama kaip `contacts:vardas`).
Šablonas → `templates/…`, `{% extends "base.html" %}`. Jei puslapis turi būti
pasiekiamas iš šoninio meniu — `contacts/menu.py` `_PAGES` (ir `OPTIONAL_KEYS`,
jei naudotojas turi galėti jį susiskleisti). Testas → `tests/test_contacts.py`.

**Nustatymų skiltį.** View grąžina `settings_section` kontekste; šablonas
`{% extends "settings/layout.html" %}` su `{% block settings_content %}`; nuoroda
— `templates/settings/layout.html` atitinkamoje grupėje, apgaubta teisės sąlyga
(`{% if is_crm_admin %}` arba `{% if crm_caps.can_… %}`). Į atskirą puslapį
neišeinama — visas turinys renderinamas nustatymų karkase (žr. „Importas /
eksportas").

**Meniu punktą naudotojui.** Nauji punktai aprašomi `contacts/menu.py`
(`_PAGES` puslapiams, `ACTIONS` veiksmams); ką naudotojas pasirinko, saugoma
`UserProfile.menu_config` JSON lauke, redaguojama Nustatymai → Mano meniu
(`contacts/forms.py` `MenuForm`). Punktų niekada netrinamas — nepasirinkti
nukeliauja į „Daugiau" foldą.

**Naują teisę (capability).** `contacts/permissions.py`: eilutė į `CAPABILITIES`
(raktas + verčiama etiketė) ir numatytos reikšmės į `_CAPABILITY_DEFAULTS` abiem
rolėms. View gale — `_require_capability(request, "can_…")`; šablone —
`{% if crm_caps.can_… %}`. Nustatymai → Rolės ir teisės lentelę generuoja pats
`CAPABILITIES`, tad ten keisti nieko nereikia.

**Lauką modelyje.** `contacts/models.py` → `makemigrations` → forma
`contacts/forms.py` → kortelės šablonas (`templates/contacts/_detail_layout.html`).
Jei laukas turi būti rodomas sąraše — stulpelio raktas įrašomas į
`contacts/views.py` sąrašo `allowed_columns`/`default_columns` ir į sąrašo
šabloną; jei filtruojamas — `contacts/filters.py`. Adminui pakanka dinaminio
lauko (Nustatymai → Dinaminiai laukai) — modelio keisti nereikia.

**Foninį darbą.** `contacts/management/commands/<vardas>.py`, idempotentiškas
(darbas pasiimamas DB žyma, ne užraktu — komanda gali būti paleista antrą kartą).
Į ciklą įtraukiama `compose.yaml` `crm-worker` komandoje ir, klasteriui,
`deploy/helm/crm/values.yaml` `worker.jobs` sąraše.

**Grafiką.** `contacts/charts.py` grąžina geometriją (`stacked_bars`,
`grouped_bars`, `line_series`, `donut`, `donut_multi`, `sparkline`,
`share_rows`); šablonas ją renderina inline SVG. Bibliotekų nenaudojame.
**Koordinatės privalo būti `{% localize off %}` viduje** — lietuvių lokalė
`68.83` išveda kaip `68,83` ir SVG sugriūva.

**Stilių.** Žetonai (spalvos, tipografijos skalė, tarpai, valdiklių aukščiai) —
`static/css/app.css :root`; ten pat tik bazinė elementų tipografija, sugrupuota
pagal komponentą (bylos pradžioje aprašyta tvarka). Komponentų taisyklės —
`static/css/theme.css`. Naujos reikšmės imamos iš žetonų skalės;
`tests/test_theme.py` neleidžia įvesti naujų dydžių už jos ribų ir reikalauja, kad
tas pats selektorius vienoje byloje būtų apibrėžtas vieną kartą. Pakeitus
`static/css` ar `static/js` — bumpinti `?v=` `templates/base.html`.

**Vertimą.** Šaltinio tekstas rašomas **lietuviškai** (`{% translate '…' %}` /
`gettext`), anglų vertimas ranka dedamas į `locale/en/LC_MESSAGES/django.po` (JS
eilutės — `djangojs.po`) ir perkompiliuojamas `msgfmt`. **`makemessages` šiame
projekte neleidžiama** — ji perkelia esamus vertimus į `#~` pasenusius. Jau
įdiegtos sąsajos formuluotes naudotojas gali persivadinti Nustatymai → Vertimai,
nekeičiant kodo.

**Dokumentaciją.** Naudotojui matomas pakeitimas → `templates/settings/documentation.html`
tame pačiame diff'e. Funkcijų sąrašas ar priklausomybės → `README.md`. Sandara ar
diegimas → ši byla, `docs/DEPLOYMENT.md`, `docs/KUBERNETES.md`. Naujas aplinkos
kintamasis → `.env.example` **ir** `docs/DEPLOYMENT.md` lentelė.

---

## 14. Ką dar planuojama

„G" skyriaus darbai (`docs/REMAINING-WORK.md`) įgyvendinti: analitika, užduočių
priskyrimas kolegoms, el. pašto pranešimai, pasikartojantys įvykiai, `.ics`
prenumerata, Microsoft Entra ID prisijungimas, gautų el. laiškų prisegimas.
Trys pastarosios (SMTP, IMAP, Entra) įjungiamos ir konfigūruojamos Nustatymų
languose be konteinerio perkrovimo.
Sąmoningai atmesta: sandoriai/piltuvėlis, dvipusė kalendoriaus sinchronizacija,
grafinis ryšių medis.

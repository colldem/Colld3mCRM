# Diegimas organizacijos infrastruktūroje

Kaip CRM įdiegti organizacijos serveryje (VM su Docker Compose) už organizacijos
reverse proxy arba Kubernetes klasteryje, kokie tinklo srautai reikalingi, kiek
resursų reikia ir kaip saugiai atnaujinti bei atšaukti atnaujinimą.
Visų kintamųjų aprašai — [DEPLOYMENT.md](DEPLOYMENT.md); Kubernetes — [KUBERNETES.md](KUBERNETES.md);
integracijos — [INTEGRACIJOS.md](INTEGRACIJOS.md).

## 1. Tikslinė architektūra (VM + Compose)

```
Darbuotojo naršyklė
   │ HTTPS 443 (organizacijos sertifikatas)
   ▼
Organizacijos reverse proxy / WAF ── TLS, X-Forwarded-For/Proto, 12 MB kūnas
   │ HTTP 8080 (tik iš proxy adreso)
   ▼
CRM VM ─ Docker Compose ─────────────────────────────────────────────────────┐
│ crm-init (vienkartinis) → crm-web (Gunicorn) ─┬─ crm-db (PostgreSQL 17)   │
│ crm-worker (foniniai darbai) ─────────────────┘   └ runtime/postgres       │
│ crm-backup (age šifruotos kopijos) → runtime/backups ─→ rclone (neprivaloma)│
│ crm-clamav (neprivaloma, compose.clamav.yaml)                               │
└──────────────────────────────────────────────────────────────────────────────┘
      │ OIDC 443 → Entra ID / AD FS      │ SMTP 587 / IMAP 993 (neprivaloma)
      │ stdout JSON → SIEM agentas        │ /metrics ← Prometheus
```

`COMPOSE_FILE=compose.yaml:compose.clamav.yaml` (be Tailscale ir Caddy perdangų —
jų vaidmenį atlieka organizacijos proxy). Organizacijos PostgreSQL serveris vietoje
`crm-db` — nustatykite `DB_HOST` ir nenaudokite `crm-db`/`crm-backup` (tada kopijos
yra DB platformos).

## 2. Tinklo srautai

| Iš | Į | Prievadas | Paskirtis | Būtina |
|---|---|---|---|---|
| Naudotojų tinklas | reverse proxy | TCP 443 | CRM naudojimas | taip |
| reverse proxy | CRM VM | TCP 8080 (`CRM_BIND_IP`, `CRM_PORT`) | programa | taip |
| CRM VM | Entra ID `login.microsoftonline.com`, `graph.microsoft.com` arba AD FS | TCP 443 | prisijungimas (OIDC), sesijos pertikrinimas | jei SSO |
| CRM VM | SMTP relay | TCP 587 (STARTTLS) arba 465 | pranešimai el. paštu | jei pranešimai |
| CRM VM | IMAP serveris | TCP 993 | laiškų priskyrimas kontaktams | jei IMAP |
| CRM VM | kopijų saugykla (S3 / SFTP) | TCP 443 / 22 | kopija už serverio ribų | rekomenduojama |
| CRM VM | ClamAV veidrodis `database.clamav.net` arba vidinis | TCP 443 | antivirusinių parašų atnaujinimas | jei ClamAV |
| CRM VM | webhook gavėjai | TCP 443 | įvykių siuntimas | jei webhook'ai |
| Prometheus | reverse proxy → `/metrics` | TCP 443 | stebėsena | rekomenduojama |
| Stebėsena (Zabbix, Uptime Kuma …) | reverse proxy → `/health/ready`, `/health/jobs` | TCP 443 | pasiekiamumas ir foniniai darbai (200 = gerai, 503 = problema) | rekomenduojama |
| SIEM agentas (VM) | SIEM | pagal SIEM | žurnalai | rekomenduojama |
| DWH | CRM VM PostgreSQL | TCP 5432 (tik jei publikuojama) | `reporting` schema | jei DWH |
| Administratoriai | CRM VM | TCP 22 | priežiūra | taip |

Visi kiti įeinantys srautai uždaromi. Konteinerių tarpusavio srautai lieka Docker
tinkle ir į išorę neatveriami.

## 3. Reverse proxy reikalavimai

- TLS su organizacijos sertifikatu; HTTP → HTTPS peradresavimas; HSTS gali dėti proxy arba CRM (`DJANGO_FORCE_HTTPS=true`).
- Antraštės: `Host` (originalus), `X-Forwarded-Proto: https`, `X-Forwarded-For` (pridedant kliento adresą), `X-Request-ID` (neprivaloma — CRM jį perims į žurnalus ir auditą).
- `CRM_TRUSTED_PROXIES` = proxy adresas(-ai), kaip jį mato CRM VM. **Be to** visi naudotojai CRM atrodys kaip vienas IP: blokavimas po 5 klaidų paliestų visus, o žurnale nebūtų tikrų adresų.
- Užklausos kūnas iki **12 MB** (importas ir priedai iki 10 MB); atsakymo laukimas ≥ 90 s.
- Upstream keep-alive trumpesnis nei `CRM_GUNICORN_KEEPALIVE` (75 s).
- HTML suspaudimas (gzip/br) proxy lygmenyje sumažina puslapius kelis kartus.
- WAF taisyklės neturi blokuoti `POST` su CSRF žetonu, `multipart/form-data` ir JSON `/api/v1/`.

`.env` gamybinė dalis:

```sh
CRM_BIND_IP=<CRM VM adresas proxy tinkle>
DJANGO_ALLOWED_HOSTS=crm.imone.lt
DJANGO_CSRF_TRUSTED_ORIGINS=https://crm.imone.lt
DJANGO_FORCE_HTTPS=true
CRM_BASE_URL=https://crm.imone.lt
CRM_TRUSTED_PROXIES=<proxy adresas>/32
CRM_ENVIRONMENT=production
BACKUP_AGE_RECIPIENTS=age1...            # viešasis raktas; privatus — slaptažodžių saugykloje
BACKUP_REQUIRE_ENCRYPTION=true
BACKUP_REMOTE=<rclone paskirtis>
CRM_METRICS_TOKEN=<atsitiktinis>
CRM_BREAK_GLASS_USERS=<avarinė paskyra>
COMPOSE_FILE=compose.yaml:compose.clamav.yaml
```

Po pirmo paleidimo Nustatymuose: prisijungimas per katalogą, AD grupių susiejimas,
„Tik organizacijos prisijungimas", neaktyvių paskyrų terminas, žurnalo ir asmens
duomenų saugojimo terminai.

## 4. Resursai (apkrovos testo rezultatai)

CI darbas `load` kiekvieno pakeitimo metu: produkcinis image, PostgreSQL, 5 000
kontaktų, 1 000 įmonių, 15 000 veiklų, 2 500 priminimų; **50 vienu metu dirbančių
naudotojų** (1–4 s tarp veiksmų: sąrašai, kortelės, paieška, darbastalis,
kalendorius, analitika, įrašų kūrimas); web konteineris apribotas **2 vCPU, 1 GB**,
numatyti Gunicorn nustatymai (2 procesai × 2 gijos).

| Rodiklis | Rezultatas (2026-09-13) |
|---|---|
| Užklausos per 3 min. | 2 763 (≈15 per s) |
| Klaidos | 0 |
| Mediana / 95 procentilis | 0,86 s / 1,7 s |
| Web atmintis | ~190 MB |
| Riba | web procesorius (2 vCPU išnaudoti); DB ~50–75 % vieno branduolio |

Slenksčiai CI (build krenta, jei viršijami): klaidos < 1 %, p95 < 2 s.
Testo metu rasti ir ištaisyti: varpelis generavo visus priminimus kiekviename
puslapyje, N+1 užklausos, sąrašų agregatai visam sąrašui, keep-alive lenktynės.

| Naudojimas | vCPU | RAM | Gunicorn (`CRM_GUNICORN_WORKERS`/`THREADS`) | Diskas |
|---|---|---|---|---|
| Pilotas, iki ~30 aktyvių naudotojų | 2 | 4 GB (+1,5 GB su ClamAV) | 2 / 2 | 20 GB + kopijos |
| Iki ~100 aktyvių naudotojų | 4 | 8 GB | 4 / 2 | 40 GB + kopijos |
| Daugiau arba aukštas pasiekiamumas | Kubernetes, 2+ web replikos, išorinis PostgreSQL ir S3 | | | |

„Aktyvus" — tuo pačiu metu dirbantis naudotojas; registruotų naudotojų gali būti
keliskart daugiau. Kopijų vieta ≈ DB dydis × `BACKUP_KEEP` + failai.

## 5. Atnaujinimas (runbook)

**Prieš:** perskaityti pakeitimų sąrašą (`git log v<dabartinė>..v<nauja>`),
patikrinti, ar yra migracijų (`git diff --stat v<dabartinė>..v<nauja> -- contacts/migrations`),
suderinti langą, jei migracijos didelės.

1. **Staging.** Nauja versija automatiškai diegiama į staging (`main`); patikrinti
   pagrindinius scenarijus su nuasmenintais produkcijos duomenimis.
2. **Kopija dabar:** `docker compose run --rm -e BACKUP_ONCE=true crm-backup`; užsirašyti rinkinio laiką.
3. **Diegimas:** `git fetch --tags && git checkout v<nauja>` → `docker compose build --pull` → `docker compose up -d`
   (arba `scripts/deploy.sh`, kuris pats padaro kopiją, sukuria image, paleidžia ir patikrina).
4. **Patikra (5 min.):**
   - `docker compose ps` — `crm-db`, `crm-web`, `crm-worker`, `crm-backup` *healthy*, `crm-init` *exited 0*;
   - `curl https://crm.imone.lt/health/ready` → `ready`;
   - `docker compose exec crm-web python manage.py migrate --check`;
   - prisijungti per katalogą, atidaryti sąrašą, kortelę, sukurti bandomąjį įrašą ir jį archyvuoti;
   - `/metrics`: `crm_database_up 1`, `crm_info{version="<nauja>"}`; žurnale nėra `level=ERROR`.
5. Pranešti naudotojams; stebėti `crm_login_failures_24h` ir klaidas pirmą valandą.

## 6. Atšaukimas (rollback)

| Situacija | Veiksmas |
|---|---|
| Nauja versija neprasideda arba nepraeina patikros, **migracijų nebuvo** | `git checkout v<ankstesnė>` → `docker compose build` → `docker compose up -d` |
| Nepavyko, **migracijos buvo pritaikytos** | sustabdyti, grąžinti ankstesnę versiją **ir** atkurti DB iš 2 žingsnio kopijos: `bash scripts/restore.sh --db runtime/backups/db-<laikas>.dump.age --identity <raktas>` (failai nekeičiami — `--media` nereikia) |
| Klaida pastebėta po kelių valandų darbo | įvertinti: taisymas pirmyn (naujas leidimas) paprastai geriau nei atkūrimas, nes atkūrimas prarastų tarpinius įrašus; jei būtina — atkurti ir pranešti, kurio laikotarpio įrašus reikia suvesti iš naujo |
| Kubernetes | `helm rollback crm <revizija>`; jei migracijos buvo — DB atkūrimas platformos priemonėmis (PITR iki diegimo laiko) |

Django migracijos paprastai nėra atgaliniu būdu suderinamos, todėl „ankstesnė
versija + nauja schema" nėra palaikoma kombinacija — su migracijomis rollback
visada reiškia ir DB atkūrimą.

## 7. Pirmo diegimo kontrolinis sąrašas

- [ ] VM, DNS, sertifikatas, proxy taisyklė, ugniasienės taisyklės (2 skyrius)
- [ ] `.env` (3 skyrius), `chmod 600 .env`; `CRM_SECRETS_KEY`, `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD` sugeneruoti ir išsaugoti slaptažodžių saugykloje
- [ ] age raktų pora sukurta ne CRM serveryje, privatus raktas saugykloje
- [ ] `docker compose up -d`, `/setup/` — avarinis administratorius (vardas `CRM_BREAK_GLASS_USERS`)
- [ ] Entra programos registracija / AD FS taisyklė, grupių susiejimas, bandomosios paskyros, „Patikrinti žetoną"
- [ ] „Tik organizacijos prisijungimas", sesijos pertikrinimas, neaktyvių paskyrų terminas
- [ ] SMTP / IMAP (jei reikia), saugojimo terminai, `CRM_METRICS_TOKEN`, SIEM surinkimas, Prometheus taisyklės
- [ ] Pirmoji kopija ir **atkūrimo pratybos** atskiroje VM; išmatuotas RTO
- [ ] Staging aplinka su `CRM_ENVIRONMENT=staging` ir `refresh-staging.sh`

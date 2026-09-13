# Pasirengimas diegimui organizacijoje — būklė ir veiksmų planas

Darbinis dokumentas. Sudarytas 2026-09-13, versija 0.77.1, commit `6c82da6`.
Tikslas: paruošti CRM pristatymui organizacijos infrastruktūros ir saugos
skyriams. Po kiekvieno atlikto punkto žymima būsena; pabaigoje — revizija.

Žymėjimas: ✅ padaryta · 🟡 iš dalies · ❌ nėra · ⏳ vykdoma

---

## A. Kas jau yra (patikrinta kode)

| Sritis | Būklė | Kur |
|---|---|---|
| Testai ir CI | ✅ 611 testų (SQLite **ir PostgreSQL**), ruff, `makemigrations --check`, `check --deploy`, image smoke test, Helm lint | `ci.yml`, `release-check.sh` |
| Priklausomybių atnaujinimai | ✅ Dependabot: pip, GitHub Actions, Docker; Django laikomas 5.2 LTS | `.github/dependabot.yml` |
| Fiksuotos versijos | ✅ `requirements.txt` tikslios versijos, bazinis image ir Postgres pagal SHA | `Dockerfile`, `compose.yaml` |
| Konteinerio sauga | ✅ ne root naudotojas, `no-new-privileges`; Helm `runAsNonRoot` | `Dockerfile`, `values.yaml` |
| Slaptažodžiai | ✅ Argon2, min. 12 simb., validatoriai | `settings.py` |
| Prisijungimų ribojimas | ✅ django-axes 5 klaidos / 30 min, pagal IP ir naudotoją | `settings.py` |
| SSO | ✅ Entra ID arba AD FS (OIDC); žetono iss/aud/exp/tid tikrinimas; tapatybė pririšta prie oid/sub | `oidc.py` |
| AD grupės → rolės | ✅ grupių susiejimas su rolėmis ir komandomis, taikomas kiekvieno prisijungimo metu; žetono tikrinimo įrankis | `directory.py` |
| Sesijos | ✅ HttpOnly, SameSite, Secure (su HTTPS), slankus neaktyvumo langas | `settings.py` |
| HTTP antraštės | ✅ CSP su nonce, Permissions-Policy, HSTS, X-Frame DENY, nosniff, Referrer-Policy, X-Request-ID | `middleware.py` |
| Rolės ir matomumas | ✅ admin / visi / tik savi, teisių lentelė, komandos | `permissions.py` |
| „Tik skaityti" | ✅ rolė „Skaitytojas", užtikrinta serveryje | `middleware.py` |
| Auditas | ✅ nekeičiamas (programa + PostgreSQL trigeris), saugojimo terminas, CSV eksportas, SIEM srautas | `audit.py`, `AuditLog` |
| API raktai | ✅ sha256, scope, atšaukimas, galiojimo terminas, užklausų ribojimas (429) | `api.py` |
| Webhook'ai | ✅ HMAC-SHA256, pristatymų žurnalas 30 d. | `webhooks.py` |
| Paslaptys DB | ✅ Fernet (`CRM_SECRETS_KEY`) | `crypto.py` |
| Priedai | ✅ dydis, tipas, ClamAV visiems įkeliamiems failams (tikrinta su tikru ClamAV) | `antivirus.py` |
| Atsarginės kopijos | ✅ age šifravimas, SHA256SUMS, būsenos patikra, kopija už hosto ribų (rclone), pre-deploy dump'ai šifruojami | `backup.sh`, `deploy/backup` |
| Atkūrimas | ✅ `restore.sh` + avarinio atkūrimo pratybos CI kiekvieno pakeitimo metu | `restore.sh`, `ci.yml` |
| Failų katalogo teisės | ✅ fiksuotas UID 10001, `crm-init`, paleidimo patikra, Helm fsGroup | `compose.yaml` |
| Aplinkų izoliacija | ✅ ne-production aplinkoje SMTP/IMAP/Entra/webhook'ai priverstinai išjungti | `integrations.py` |
| Staging duomenys | ✅ nuasmeninami (struktūra išlieka) | `anonymize.py` |
| Žurnalai (logging) | ✅ JSON į stdout (programa, `crm.security`, Gunicorn), request-id, be asmens duomenų | `observability.py` |
| Stebėsena | ✅ health, `/metrics` (Prometheus), foninių darbų heartbeat, įspėjimų pavyzdžiai | `metrics.py` |
| Asmens duomenų saugojimo terminai | ✅ archyvuoti įrašai, gauti laiškai, auditas — su peržiūra | `privacy.py` |
| Duomenų subjekto teisės | ✅ vieno asmens ZIP eksportas ir ištrynimas su žurnalo nuasmeninimu | `privacy.py` |
| Naudotojų išjungimas | ✅ AD išjungtas → atjungiamas per ≤15 min.; neaktyvūs išjungiami automatiškai; katalogo naudotojai be vietinio slaptažodžio | `oidc.py`, `accounts.py` |
| Vien SSO režimas | ✅ su avarinėmis paskyromis (`CRM_BREAK_GLASS_USERS`) | `oidc.py` |
| Pažeidžiamumų skenavimas | ✅ pip-audit, bandit, Trivy CI (žr. 5 etapą) | `ci.yml`, `security-check.sh` |
| SBOM | ✅ CycloneDX (Python + image), GHCR atestacijos | `ci.yml`, `publish-image.yml` |
| Kubernetes | ✅ Helm chart; read-only root, seccomp, PDB, NetworkPolicy, kubeconform; ištaisytas Service selektorius | `deploy/helm` |
| Našumas | ✅ apkrovos testas CI (50 naudotojų, 5 000 kontaktų): p95 1,7 s, 0 klaidų; ištaisyti N+1 ir varpelis | `scripts/loadtest` |
| Kliento IP už proxy | ✅ `CRM_TRUSTED_PROXIES`; ištaisyta: blokavimas palietė visus už proxy | `audit.py` |
| Integracijos / DWH | ✅ `reporting` schema, tik skaitymo rolė, `INTEGRACIJOS.md` | migracija 0051 |
| Oracle | 🟡 migracijos praeina, 515/644 testų; darbų įvertinimas `ORACLE.md` | CI `oracle-compatibility` |
| Dokumentacija | 🟡 techninė EN/LT gera; **nėra saugumo aprašo, duomenų žodyno, DAPV, priežiūros modelio** | `docs/` |

---

## B. Veiksmų planas

Dydis: S — iki pusdienio, M — ~1 diena, L — kelios dienos.
Kiekvienas kodo punktas = atskiras commit pagal `CLAUDE.md` taisykles
(testai, patikra naršyklėje, in-app žinynas, push).

### 1 etapas — Prieiga ir tapatybė (AD) — ✅ atlikta 2026-09-13

| # | Darbas | Būsena |
|---|---|---|
| 1.0 | **AD grupės → rolės ir komandos** (Entra ID arba AD FS), stipriausia rolė, be grupės neįleidžiama, žetono tikrinimo įrankis, AD žymos ir užraktai Naudotojų/Komandų languose | ✅ |
| 1.0a | OIDC sustiprinimas: iss/aud/exp/tid tikrinimas, „common" draudimas, tapatybė pagal oid/sub, grupių „overage" atmetimas | ✅ |
| 1.1 | **Vien SSO režimas** su avarinėmis paskyromis; vietinės sesijos baigiamos | ✅ |
| 1.1a | **Sesijos pakartotinis tikrinimas** kas N min. (`prompt=none`): AD išjungtas ar iš grupės pašalintas naudotojas atjungiamas | ✅ |
| 1.2 | **Neaktyvių paskyrų išjungimas** po N d., grąžinimas per AD; katalogo naudotojams vietinis slaptažodis neleidžiamas | ✅ |
| 1.3 | **„Skaitytojo" rolė**, užtikrinta serveryje (middleware), API tik skaitymui | ✅ |
| 1.4 | **API raktai**: galiojimo terminas, užklausų ribojimas (429, Retry-After) | ✅ |

> Rastos ir ištaisytos klaidos, kurios būtų sutrukdžiusios tikram Entra prisijungimui:
> neteisingi authorize/token (`/oauth2/` trūko), JWKS ir userinfo adresai; nesėkmingo
> prisijungimo nukreipimas į neegzistuojantį adresą.
>
> **Neišbandyta su tikra aplinka** (nėra Regitros duomenų): reikės Entra programos
> registracijos arba AD FS taisyklės, grupių lauko žetone ir bandomųjų paskyrų.
> Klausimai infrastruktūrai — 7.10.

### 2 etapas — Žurnalai ir auditas — ✅ atlikta 2026-09-13

| # | Darbas | Būsena |
|---|---|---|
| 2.1 | **JSON žurnalai SIEM'ui**: programa, `crm.security` (kiekvienas audito įvykis, blokados), Gunicorn access log be query string; `X-Request-ID` visur ir audito įrašuose | ✅ |
| 2.2 | **Auditas**: įrašų pakeisti/ištrinti negalima (modelis + PostgreSQL trigeris), saugojimo terminas (≥180 d.) su kasdieniu valymu, CSV eksportas | ✅ |
| 2.3 | **CSP** su nonce, be įterptinių tvarkytojų (`behaviors.js`), `Permissions-Policy`, report-only jungiklis | ✅ |
| 2.4 | **CI testai su PostgreSQL** (produkcijos DB variklis) | ✅ |

> Žinomas apribojimas: DB superuser gali apeiti trigerį — nekeičiama kopija turi būti SIEM'e.
> Gunicorn paleidimo pranešimai (kelios eilutės starto metu) lieka tekstiniai.

### 3 etapas — Asmens duomenys (BDAR) — ✅ atlikta 2026-09-13

| # | Darbas | Būsena |
|---|---|---|
| 3.1 | **Staging nuasmeninimas** pagal nutylėjimą (`--keep-personal-data` išimčiai); priedai kopijuojami prieš valymą | ✅ |
| 3.2 | **Saugojimo terminai**: archyvuoti kontaktai/įmonės, gauti laiškai; kasdienis `apply_retention` su peržiūra ir `--dry-run` | ✅ |
| 3.3 | **Duomenų subjekto užklausos**: ZIP eksportas (15, 20 str.), ištrynimas (17 str.) su failais, laiškais ir žurnalo nuasmeninimu (PostgreSQL trigeris leidžia keisti tik vertes) | ✅ |

> Žinomi apribojimai: atsarginėse kopijose ištrinti duomenys lieka iki kopijų galiojimo pabaigos;
> įmonė kaip duomenų subjektas (individuali veikla) — tik per saugojimo terminą, ne per užklausų langą.

### 4 etapas — Kopijos ir atkūrimas — ✅ atlikta 2026-09-13

| # | Darbas | Būsena |
|---|---|---|
| 4.1 | **Šifruotos kopijos** (age viešuoju raktu, `BACKUP_REQUIRE_ENCRYPTION`), SHA256SUMS, manifestas, sveikatos patikra pagal paskutinę sėkmingą kopiją | ✅ |
| 4.2 | **`scripts/restore.sh`** (sumų patikra, iššifravimas konteineryje, viena transakcija, failai, patikra) + **CI avarinio atkūrimo pratybos** | ✅ |
| 4.3 | **Kopija už hosto ribų** per rclone (S3, SFTP, …) su senų kopijų valymu | ✅ |
| 4.4 | Rastas ir ištaisytas diegimo trūkumas: `runtime/media` teisės naujame hoste (UID 10001, `crm-init`) | ✅ |

> RPO — vienas kopijavimo intervalas (numatyta 24 val.); RTO matuoti pratybose organizacijos infrastruktūroje.
> Kubernetes atveju kopijos — platformos (DB PITR, S3 versijos).

### 5 etapas — Tiekimo grandinė ir CI

| # | Darbas | Dydis | Būsena |
|---|---|---|---|
| 5.1 | `pip-audit` CI (priklausomybių CVE) | S | ✅ radinių nėra |
| 5.2 | `bandit` statinė kodo saugumo analizė | S | ✅ 8 radiniai peržiūrėti, realių spragų nėra; `rich_text` XSS regresijos testai |
| 5.3 | Trivy image skenavimas CI | S | ✅ rado 2 HIGH (libpcre2) — pataisyta Dockerfile; PostgreSQL image skenuojamas informaciniu režimu |
| 5.4 | SBOM (CycloneDX) kaip leidimo artefaktas + licencijų sąrašas | S | ✅ Python ir image SBOM CI artefaktai; GHCR image su SBOM ir provenance atestacijomis |
| 5.5 | Priedų antivirusinis skenavimas per ClamAV (neprivaloma, įjungiama env) | M | ✅ visi įkėlimo keliai; CI su tikru ClamAV |

> Žinomas apribojimas: oficialus `postgres:17.11-bookworm` (naujausias) turi
> neištaisytų upstream CVE (libpcre2, `gosu` Go stdlib). Keičiama tik atnaujinus
> digest, kai upstream išleis; organizacijos nuosavas PostgreSQL šios rizikos neturi.

### 6 etapas — Diegimas organizacijos infrastruktūroje — ✅ atlikta 2026-09-13

| # | Darbas | Būsena |
|---|---|---|
| 6.1 | Helm: read-only root + `/tmp` emptyDir, seccomp, be SA žetono, PDB, NetworkPolicy, darbų resursai; **ištaisyta**: Service siuntė srautą į CronJob podus; kubeconform ir read-only paleidimas CI | ✅ |
| 6.2 | Diegimas už organizacijos proxy, tinklo srautai, `.env` — `DIEGIMAS-ORGANIZACIJOJE.md`; **ištaisyta**: axes blokavimas ir auditas už proxy (`CRM_TRUSTED_PROXIES`) | ✅ |
| 6.3 | Apkrovos testas CI su slenksčiais; **ištaisyta**: varpelis (visi priminimai kiekviename puslapyje), N+1, sąrašų agregatai, keep-alive; resursų rekomendacijos | ✅ |
| 6.4 | `/metrics` (Prometheus) su žetonu, foninių darbų heartbeat, įspėjimų lentelė | ✅ |
| 6.5 | Atnaujinimo ir atšaukimo runbook | ✅ |
| 6.6 | Oracle suderinamumo patikra CI; **ištaisyta**: unikalus indeksas ant teksto (lūžtų ir PostgreSQL); likę darbai ir įvertinimas `ORACLE.md` | ✅ (patikra) |
| 6.7 | Integracijų aprašas, `reporting` schema ir tik skaitymo rolė (tikrinta PostgreSQL) | ✅ |

### 7 etapas — Dokumentų paketas (LT) — ✅ atlikta 2026-09-13 (`docs/paketas/`)

| # | Dokumentas | Būsena |
|---|---|---|
| 7.1 | `01-sistemos-aprasas.md` | ✅ |
| 7.2 | `02-architektura-ir-schemos.md` (Mermaid: loginė, prisijungimas, aplinkos, duomenų srautai) | ✅ |
| 7.3 | `03-saugumo-priemones.md` (priemonė → įgyvendinimas → patikra → organizacijos dalis) | ✅ |
| 7.4 | `04-duomenu-zodynas.md` — **generuojamas iš kodo**, testai neleidžia pasenti | ✅ |
| 7.5 | `05-dapv-juodrastis.md` (su [ORGANIZACIJA]/[DAP] laukais) | ✅ |
| 7.6 | `06-kopijavimo-ir-atkurimo-planas.md` (RPO/RTO, raktai, pratybos) | ✅ |
| 7.7 | `07-prieziura-ir-perdavimas.md` (RACI, apimtis, perdavimo planas, incidentai) | ✅ |
| 7.8 | `08-pilotinis-projektas.md` (etapai, sėkmės kriterijai, išėjimas) | ✅ |
| 7.9 | `09-apribojimai-ir-rizikos.md` (rizikų registras) | ✅ |
| 7.10 | `10-klausimai.md` (užsakovui, infrastruktūrai, tapatybei, saugai, DAP, pirkimams) | ✅ |

> Rengiant dokumentus rasta ir įgyvendinta: kalendoriaus prenumeratos nuorodų išjungimo nustatymas.

### 8 etapas — Tik jūs (ne kodas)

| # | Klausimas | Būsena |
|---|---|---|
| 8.1 | Verslo užsakovas — padalinys ir atsakingas asmuo | ❌ |
| 8.2 | Autorių teisės: kodas kurtas darbo ar asmeniniu laiku; MIT licencijos patvirtinimas | ❌ |
| 8.3 | Interesų konfliktas, jei vėliau būtų mokama priežiūra | ❌ |
| 8.4 | Pirminė konsultacija su DAP | ❌ |
| 8.5 | Poreikio aprašas (problema, naudotojų skaičius, nauda) | ❌ |

---

## C. Revizija (pildoma pabaigus)

- [ ] Visi A lentelės ❌ ir 🟡 punktai arba padaryti, arba sąmoningai įrašyti į 7.9 kaip žinomi apribojimai
- [ ] `release-check.sh` žalias, CI žalias, skenavimai be kritinių radinių
- [ ] Atkūrimas iš šifruotos kopijos išbandytas
- [ ] Dokumentų paketas 7.1–7.10 baigtas ir suderintas su kodu
- [ ] Kiekvienam 4.1–4.4 klausimui iš pasirengimo plano yra atsakymas arba nuoroda

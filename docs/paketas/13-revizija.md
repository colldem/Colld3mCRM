# 13. Revizija prieš pristatymą (2026-09-13)

Peržiūrėta iš organizacijos IT saugos ir infrastruktūros specialisto pozicijos:
ar kiekvienam tikėtinam klausimui yra atsakymas, ar atsakymas atitinka kodą ir
ar yra įrodymas (testas, CI, dokumentas).

## 1. Revizijos metu rasta ir ištaisyta

| Radinys | Rizika | Ištaisyta |
|---|---|---|
| Django `/admin/` pasiekiamas kiekvienam CRM administratoriui (`is_staff`) | įrašų keitimas apeinant auditą ir CRM teises | išjungtas pagal nutylėjimą; `CRM_DJANGO_ADMIN=true` — tik superuser |
| Su tikra DB be `DJANGO_SECRET_KEY` būtų naudotas viešai žinomas dev raktas, `DEBUG` pagal nutylėjimą įjungtas | sesijų klastojimas, klaidų detalės | su `DB_HOST` `DEBUG` išjungtas, be rakto procesas nestartuoja |
| Profilio nuotraukos tipas imtas iš naršyklės / failo vardo | HTML failas, pavadintas `.png`, galėjo būti atvaizduojamas | tikrinamas failo parašas; kita — atsisiunčiama kaip `octet-stream` |
| Webhook'ų SSRF | vidinių adresų užklausos | jau buvo: loopback, link-local, nukreipimai blokuojami; DNS rebinding — priimta rizika (tik administratorius) |

Visi trys taisymai su regresijos testais; CI 9/9 žali.

## 2. Pradinių klausimų atitikmenys

| Klausimas (pirminis pasirengimo planas) | Atsakymas | Įrodymas |
|---|---|---|
| Kas sistemos savininkas? | **atvira — jūsų** (8.1) | šablonas 00 |
| Kas prižiūrės, jei kūrėjas išeis? | perdavimo planas, RACI, 4–8 val./mėn. | 07 |
| Kodėl ne esami įrankiai? | **atvira — užsakovo** | šablonas 00, 6 sk. |
| Kaina, pirkimai, licencija | 0 € licencijos; MIT; komponentų licencijos | 11, 00 |
| Technologijos, resursai | Django 5.2 LTS, PostgreSQL 17; 2 vCPU pilotui, 4 vCPU iki ~100 aktyvių | 01, DIEGIMAS 4 sk., CI `load` |
| Ar veikia be interneto / išorinių paslaugų | taip (be CDN) | 01 |
| Skaliavimas, Kubernetes | Helm, replikos, S3, sustiprinti podai | KUBERNETES, CI `chart` |
| Organizacijos PostgreSQL / Oracle | `DB_HOST`; Oracle — išmatuota, 1,5–2,5 d. | ORACLE, CI `oracle-compatibility` |
| Atnaujinimai ir rollback | runbook | DIEGIMAS 5–6 sk. |
| Stebėsena, žurnalai, SIEM | JSON žurnalai, `/metrics`, heartbeat | DEPLOYMENT „Logs", „Monitoring" |
| Pažeidžiamumų valdymas, SBOM | pip-audit, bandit, Trivy, CodeQL, Dependabot, CycloneDX | CI `security`, `image` |
| Prisijungimas, MFA | Entra ID / AD FS; MFA — organizacijos IdP | 03, CI testai |
| Teisės pagal AD grupes | grupė → rolė ir komandos; pertikrinimas ≤15 min. | 02 (2.2), testai |
| „Tik skaityti" | Skaitytojo rolė, užtikrinta serveryje | testai |
| Auditas ir jo nekeičiamumas | pilnas žurnalas, DB trigeris, CSV, terminas | 03 (3.4), PostgreSQL testai |
| Šifravimas | TLS; paslaptys Fernet; kopijos age; disko — organizacijos | 03 (3.2) |
| Kopijos, RPO/RTO, atkūrimas | šifruotos kopijos, kopija už serverio, atkūrimo pratybos | 06, CI `backup-restore` |
| Failų įkėlimas ir antivirusas | ClamAV visiems keliams | CI `clamav` |
| Įsiskverbimo testas | **nėra — rekomenduojamas pilote** | 09 K2, 08 |
| Asmens duomenys, DAPV | žodynas iš kodo, DAPV juodraštis | 04, 05 |
| Saugojimo terminai, subjektų teisės | automatiniai terminai; ZIP eksportas; ištrynimas | testai |
| Tikri duomenys testinėje aplinkoje | nuasmeninama automatiškai | testai |
| Duomenys už ES | ne (išskyrus organizacijos Entra ID) | 05 |
| Integracijos su kitomis sistemomis | API, webhook'ai, `reporting` schema | INTEGRACIJOS |
| Tinklo srautai, proxy reikalavimai | lentelė ir reikalavimai | DIEGIMAS 2–3 sk. |
| Autorių teisės, interesų konfliktas | **atvira — jūsų** (8.2, 8.3) | šablonas 11 |

## 3. Atviri punktai prieš susitikimą

| # | Kas | Kieno | Ar blokuoja susitikimą |
|---|---|---|---|
| A1 | Užsakovas ir poreikio aprašas (00) | jūsų | **taip** — be jo pokalbis būna apie technologiją, ne poreikį |
| A2 | Autorystės situacija (11, 2 ir 5 sk.) | jūsų, teisininkas | ne, bet paklaus |
| A3 | Pirminė DAP konsultacija | jūsų | ne |
| A4 | Produkcijos diegimas (`v0.77.0` → nauja versija) | sutarta vėliau | ne (demonstracija — staging) |
| A5 | Programos žinyno papildymai (kontrolinio sąrašo D skyrius) | sutarta vėliau | ne |

## 4. Po susitikimo (priklauso nuo organizacijos atsakymų)

| # | Kas | Kada |
|---|---|---|
| B1 | Įsiskverbimo testas ir / ar kodo auditas | pilotas, 2 etapas |
| B2 | Tikras prisijungimas su organizacijos Entra ID / AD FS, grupės, bandomosios paskyros | pilotas, 1 etapas |
| B3 | Oracle darbai (tik jei politika reikalauja) | pagal sprendimą |
| B4 | Atkūrimo pratybos organizacijos infrastruktūroje, RTO matavimas | pilotas, 3 etapas |
| B5 | `.env` reikšmės pagal 10 dokumento atsakymus | parengimas |

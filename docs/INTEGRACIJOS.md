# Integracijos su kitomis sistemomis

Kaip CRM keičiasi duomenimis su organizacijos sistemomis ir kodėl būtent taip.
Pagrindinė taisyklė: **jokia sistema nerašo į kitos sistemos lenteles ir neskaito
jų tiesiogiai**. Kiekvienas kanalas turi savo tapatybę, teises, žurnalą ir
galiojimo terminą.

## 1. Kanalų apžvalga

| Kryptis | Kanalas | Kam tinka | Apsauga | Kur aprašyta |
|---|---|---|---|---|
| Kitos sistemos → CRM (rašo) | **REST API** `/api/v1/` | svetainės formos, kitų sistemų įrašų kūrimas | `Bearer` raktas, sha256 DB'je, scope skaityti / skaityti ir keisti, galiojimo terminas (30–365 d.), 120 užkl./min, kūrėjo teisės ir matomumas, auditas | Nustatymai → Dokumentacija „REST API" |
| CRM → kitos sistemos (įvykiai) | **Webhook'ai** | sinchronizacija beveik realiu laiku | HTTPS, `X-CRM-Signature: sha256=HMAC`, pakartojimai, pristatymų žurnalas 30 d.; staging aplinkoje išjungti | tas pats |
| Kitos sistemos ← CRM (skaito) | **REST API** (tik skaitymo raktas) | nedideli kiekiai, konkretūs įrašai | kaip aukščiau | tas pats |
| DWH / BI ← CRM | **`reporting` schema** PostgreSQL + tik skaitymo rolė | ataskaitos, analitika, Oracle DWH | atskira rolė, tik `SELECT` rodiniams, `default_transaction_read_only`, be laisvo teksto ir slaptų lentelių | 3 skyrius |
| Tapatybė | **Entra ID / AD FS (OIDC)** | prisijungimas, rolės pagal AD grupes | žetono parašas, iss/aud/exp/tid, grupių susiejimas, sesijos pertikrinimas | `docs/DEPLOYMENT.md`, dokumentacija „Prisijungimas per organizacijos katalogą" |
| El. paštas | **SMTP** (siuntimas), **IMAP** (gauti laiškai) | pranešimai, laiškų prisegimas prie kontaktų | TLS, slaptažodžiai šifruoti DB'je | dokumentacija „El. pašto pranešimai" |
| Sauga | **JSON žurnalai** stdout → SIEM | incidentų stebėsena | be asmens duomenų, `request_id` | `docs/DEPLOYMENT.md` „Logs" |
| Stebėsena | **`/metrics`** (Prometheus) | sveikata, foniniai darbai, saugumo rodikliai | `Bearer` žetonas | `docs/DEPLOYMENT.md` „Monitoring" |
| Kopijos | **rclone** → S3 / SFTP / … | kopija už serverio ribų | age šifravimas prieš išsiunčiant | `docs/DEPLOYMENT.md` „Backups" |
| Antivirusas | **clamd** (TCP 3310) | įkeliamų failų tikrinimas | failas neišsaugomas be patikros | `docs/DEPLOYMENT.md` „Malware scanning" |

## 2. REST API ir webhook'ai

- Endpoint'ai: `GET /me`; `GET/POST /contacts`, `GET/PATCH/DELETE /contacts/<id>`
  (DELETE = archyvavimas); tas pats `/companies`; `GET/POST /activities`;
  `GET/POST /reminders`. Puslapiavimas `?limit` (≤100) ir `?offset`, `X-Total-Count`.
- Priminimas API'je yra kalendoriaus įvykis: `kind` (`reminder` / `call` / `meeting`),
  `description`, `meeting_url` ir `end_at` — ir skaitant, ir kuriant. Nežinomas
  `kind` tampa `reminder`, `meeting_url` išsaugomas tik susitikimui, o `end_at`
  anksčiau už `due_at` atmetamas (400).
- Kiekvienai integracijai — **atskiras raktas** su aiškiu pavadinimu (pvz.
  „Svetainės forma"), minimaliu scope ir trumpiausiu tinkamu galiojimu. Raktas
  veikia su jį sukūrusio naudotojo teisėmis, todėl integracijoms verta sukurti
  techninį naudotoją su tinkama role (pvz. „Naudotojas (tik savi įrašai)" arba
  „Skaitytojas").
- Besibaigiantys raktai matomi Nustatymai → API ir webhookai bei metrikoje
  `crm_api_tokens{state="expiring_14d"}`.
- Webhook'ų įvykiai: `contact.created|updated|archived`, `company.created|updated|archived`,
  `activity.created`, `reminder.created|completed`. Gavėjas turi patikrinti
  `X-CRM-Signature` (HMAC-SHA256 su webhook'o paslaptimi) ir atsakyti 2xx.

## 3. Ataskaitos ir duomenų saugykla (DWH)

CRM duomenų bazėje (PostgreSQL) yra schema `reporting` su rodiniais:

| Rodinys | Stulpeliai |
|---|---|
| `reporting.people` | id, first_name, last_name, job_title, favourite, owner_id, created_by_id, created_at, updated_at, archived_at |
| `reporting.companies` | id, name, company_code, vat_code, city, owner_id, created_by_id, created_at, updated_at, archived_at |
| `reporting.person_companies` | person_id, company_id, role, is_primary |
| `reporting.activities` | id, person_id, company_id, activity_type, created_by_id, created_at, archived_at |
| `reporting.reminders` | id, person_id, company_id, kind, due_at, end_at, completed_at, priority, created_by_id, assigned_to_id, created_at, archived_at |
| `reporting.tags`, `person_tags`, `company_tags` | žymos ir jų ryšiai |
| `reporting.categories`, `person_categories`, `company_categories` | kategorijos ir jų ryšiai |
| `reporting.users` | id, username, first_name, last_name, is_active, role |
| `reporting.teams`, `team_members` | komandos |

Sujungti dublikatai (`merged_into`) į rodinius nepatenka. **Nėra**: laisvo teksto
(aprašymų, veiklų ir priminimų tekstų), telefonų, el. paštų, adresų, failų,
slaptažodžių hash'ų, sesijų, API raktų, integracijų paslapčių, audito žurnalo.
Jei ataskaitai reikia daugiau — naujas rodinys naujoje migracijoje, suderinus su DAP.

Rolės sukūrimas (arba slaptažodžio keitimas):

```sh
docker compose exec -e REPORTING_PASSWORD='<ilgas slaptažodis>' crm-web \
  python manage.py create_reporting_role --name crm_reporting
```

Rolė gali tik prisijungti ir `SELECT` iš `reporting` schemos; bet kokia užklausa į
programos lenteles grąžina „permission denied", o rašymas neįmanomas. Tai
tikrinama CI su tikru PostgreSQL. Tinklo lygiu PostgreSQL prievadą (5432) atverkite
tik DWH serveriui.

**Oracle aplinkoje** DWH prie šios schemos jungiasi įprastais būdais: Oracle
Database Gateway for ODBC / `DB link` per PostgreSQL ODBC tvarkyklę, Oracle Data
Integrator arba GoldenGate su PostgreSQL šaltiniu, arba bet kuris ETL įrankis per
JDBC. Visais atvejais naudojama `crm_reporting` rolė.

## 4. Duomenys iš kitų sistemų į CRM

Jei CRM turi gauti duomenis iš organizacijos sistemų (pvz. įmonių ar klientų
sąrašą), eilės tvarka pagal pageidaujamumą:

1. **Šaltinio sistema kviečia CRM REST API** (arba jos integracijų platforma — ESB,
   API gateway): CRM tikrina teises, rašo auditą, siunčia webhook'us.
2. **Periodinis failų eksportas** (CSV/XLSX) → CRM importas: stulpelių priskyrimas,
   peržiūra prieš įrašant, dublikatų tvarkymas, antivirusinė patikra.
3. **Sinchronizavimo komanda CRM pusėje**, skaitanti šaltinio sistemos *rodinį* per
   tik skaitymo prieigą (Oracle — `oracledb` tvarkyklė be Oracle kliento). Kuriama
   pagal konkretų poreikį: laukų atitikimas, dažnis, konfliktų taisyklės.

Nenaudojama: tiesioginis rašymas į CRM lenteles ar CRM rašymas į kitų sistemų
lenteles — apeina teises, auditą ir patikras.

## 5. Klausimai integracijų derinimui

- Su kuriomis sistemomis CRM keisis duomenimis, kokia kryptimi, kaip dažnai, kokie laukai?
- Koks organizacijos integracijų standartas (ESB, API gateway, failų mainai)?
- Kur yra DWH, kokiu įrankiu jis pasiima duomenis, iš kokio adreso jungsis prie 5432?
- Ar reikia laisvo teksto ataskaitose (reikalingas DAP sutikimas)?
- Kas yra kiekvienos integracijos savininkas ir kas atnaujina raktus prieš jiems pasibaigiant?

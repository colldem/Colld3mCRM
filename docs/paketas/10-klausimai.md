# 10. Klausimai infrastruktūrai, saugai, DAP ir užsakovui

Atsakymai virsta galutiniais reikalavimais ir `.env` / Nustatymų reikšmėmis.
Nuorodos rodo, kur atsakymas bus panaudotas.

## 10.1 Užsakovas (sistemos savininkas)

| # | Klausimas | Kam reikia |
|---|---|---|
| U1 | Kuris padalinys yra sistemos savininkas ir kas atsakingas asmuo? | 07 RACI, 05 DAPV |
| U2 | Kokią problemą sprendžiame, kiek naudotojų pilote ir vėliau? | 08, resursai |
| U3 | Kokius duomenis vesime ir kokius — ne (instrukcija dėl laisvo teksto)? | 05 R7 |
| U4 | Kokios rolės reikalingos (administratoriai, visi įrašai, savi įrašai, skaitytojai) ir kas tvirtina priskyrimą? | AD grupės |
| U5 | Kiek laiko saugoti archyvuotus įrašus ir gautus laiškus? | Nustatymai → Duomenų apsauga |
| U6 | Ar reikia el. pašto pranešimų, IMAP laiškų priskyrimo, kalendoriaus prenumeratos? | integracijos |

## 10.2 Infrastruktūra

| # | Klausimas | Kam reikia |
|---|---|---|
| I1 | Ar leidžiama PostgreSQL? Ar yra bendras PostgreSQL serveris, ar DB veikia kartu su CRM? Ar politika reikalauja Oracle? | `DB_HOST`, `docs/ORACLE.md` |
| I2 | Ar naudojami konteineriai (Docker / Podman / Kubernetes / OpenShift), ar tik VM? Kokia OS? | diegimo variantas |
| I3 | VM parametrai (vCPU, RAM, diskas) ir kur ji stovi (tinklo zona) | DIEGIMAS-ORGANIZACIJOJE 4 sk. |
| I4 | Koks reverse proxy / WAF, koks jo adresas CRM VM atžvilgiu, kas išduoda sertifikatą, koks domenas? | `CRM_TRUSTED_PROXIES`, `DJANGO_ALLOWED_HOSTS`, `CRM_BASE_URL` |
| I5 | Ar proxy perduoda `X-Forwarded-For`, `X-Forwarded-Proto`, leidžia 12 MB kūną, keep-alive < 75 s? | proxy konfigūracija |
| I6 | Kaip gaunamos ugniasienės taisyklės 2 skyriaus srautams? | tinklas |
| I7 | Kur siųsti kopijas už serverio ribų (S3, SFTP, NAS), kas saugo age privatų raktą ir `.env` paslaptis? | `BACKUP_REMOTE`, 06 |
| I8 | Koks standartinis RPO/RTO ir kopijų saugojimas? Ar DB platforma turi PITR? | `BACKUP_INTERVAL_SECONDS`, `BACKUP_KEEP` |
| I9 | Ar yra organizacijos clamd, ar naudoti `compose.clamav.yaml`? Ar leidžiama pasiekti `database.clamav.net`, ar yra vidinis veidrodis? | `CRM_CLAMAV_HOST` |
| I10 | Koks SMTP relay (adresas, prievadas, autentifikacija, siuntėjo adresas)? IMAP dėžutė? | Nustatymai → El. paštas, Gauti laiškai |
| I11 | Kaip diegiami atnaujinimai (CAB, langai), ar CI veiks organizacijos Git sistemoje? | 07, runbook |
| I12 | Ar reikia staging aplinkos atskiroje VM? | `compose.staging.yaml` |

## 10.3 Tapatybė (AD / Entra ID / AD FS)

| # | Klausimas | Kam reikia |
|---|---|---|
| T1 | AD sinchronizuojamas į Entra ID ar naudojamas AD FS? | Nustatymai → Prisijungimas |
| T2 | Kas registruoja programą (redirect URI `https://<domenas>/oidc/callback/`), kas perduoda client ID / secret? | `oidc_*` |
| T3 | Ar į ID žetoną bus įtraukiamos grupės (Entra: „Groups assigned to the application"; AD FS: taisyklė ir lauko pavadinimas)? Object ID ar pavadinimai? | `oidc_groups_claim`, susiejimas |
| T4 | Kokie CRM grupių pavadinimai / ID (pvz. `CRM-Admins`, `CRM-Users`, `CRM-Own`, `CRM-Readers`, komandų grupės) ir kas jų savininkai? | Katalogo grupės |
| T5 | Ar taikoma MFA ir sąlyginė prieiga CRM programai? | 03 |
| T6 | Kas gauna avarinę vietinę paskyrą ir kur saugomas jos slaptažodis? | `CRM_BREAK_GLASS_USERS` |
| T7 | 2–3 bandomosios paskyros skirtingose grupėse pilotui | pilotas 1 etapas |

## 10.4 IT sauga

| # | Klausimas | Kam reikia |
|---|---|---|
| S1 | Koks naujos sistemos priėmimo procesas / klausimynas? Kokia sistemos kategorija? | 03, 09 |
| S2 | Ar reikalingas įsiskverbimo testas ir/ar kodo auditas, kas jį atlieka, iki kada? | pilotas 2 etapas |
| S3 | Koks SIEM, kaip surenkami konteinerių stdout žurnalai, kokios įspėjimų taisyklės? | DEPLOYMENT „Logs" |
| S4 | Ar Prometheus / kita stebėsena skaitys `/metrics`? | `CRM_METRICS_TOKEN` |
| S5 | Pažeidžiamumų valdymo tvarka (kaip greitai diegti kritinius atnaujinimus)? | 07 |
| S6 | Ar leidžiami image iš Docker Hub (postgres, clamav), ar reikia vidinio registro? | image šaltiniai |
| S7 | Kas turi DB superuser prieigą ir kaip ji kontroliuojama? | 09 S1 |

## 10.5 Duomenų apsaugos pareigūnas (DAP)

| # | Klausimas | Kam reikia |
|---|---|---|
| P1 | Ar DAPV privalomas? Teisinis pagrindas kontaktų tvarkymui? | 05 |
| P2 | Saugojimo terminai: aktyvūs, archyvuoti įrašai, laiškai, audito žurnalas, kopijos? | Nustatymai |
| P3 | Duomenų subjektų užklausų procedūra ir atsakingi? | Duomenų apsauga |
| P4 | Privatumo pranešimas kontaktams? | 05 |
| P5 | Ar leidžiama `reporting` schema DWH, ar reikia laisvo teksto ataskaitose? | INTEGRACIJOS |
| P6 | Ar leidžiami tikri duomenys testinėje aplinkoje (numatytai — ne, nuasmeninama)? | staging |

## 10.6 Integracijos ir pirkimai

| # | Klausimas | Kam reikia |
|---|---|---|
| A1 | Su kuriomis sistemomis keistis duomenimis, kokia kryptimi, kaip dažnai, kokie laukai? Integracijų standartas (ESB, API gateway)? | INTEGRACIJOS 5 sk. |
| A2 | Autorių teisės ir licencija (MIT) — ar reikia rašytinio patvirtinimo? | teisininkai |
| A3 | Priežiūros forma (darbo pareigos / sutartis), interesų konflikto deklaracija, jei taikoma? | 07 |

# 1. Sistemos aprašas

## Paskirtis

Colld3m CRM — organizacijos vidinė ryšių su klientais ir partneriais valdymo
sistema. Joje tvarkomi kontaktiniai asmenys, įmonės ir jų ryšiai, bendravimo
istorija (pastabos, skambučiai, susitikimai, laiškai), prisegti failai,
priminimai ir užduotys, kalendorius bei analitika.

Sistema **nėra** valstybės registras ir nesijungia prie organizacijos registrų ar
kitų informacinių sistemų duomenų bazių. Keitimasis duomenimis — tik per
kontroliuojamus kanalus (REST API, webhook'ai, tik skaitymo ataskaitų schema),
kurie įjungiami atskirai.

## Pagrindinės funkcijos

| Sritis | Funkcijos |
|---|---|
| Įrašai | Asmenys, įmonės, ryšiai; keli telefonai, el. paštai, adresai; žymos, kategorijos, papildomi laukai; dublikatų paieška ir sujungimas; archyvas |
| Darbas | Sąrašai su filtrais ir masiniais veiksmais; kortelės su istorija, failais, priminimais; kalendorius (.ics prenumerata); užduočių priskyrimas; el. pašto pranešimai; IMAP laiškų priskyrimas; automatikos taisyklės |
| Analitika | Darbastalis, ryšių priežiūra, komunikacija, priminimų vykdymas, augimas |
| Prieiga | Prisijungimas per organizacijos katalogą (Entra ID / AD FS) su rolėmis pagal AD grupes; rolės Administratorius / Naudotojas (visi įrašai) / Naudotojas (savi įrašai) / Skaitytojas; komandos ir įrašų matomumas |
| Duomenų apsauga | Duomenų subjekto eksportas ir ištrynimas; saugojimo terminai; nuasmeninta testinė aplinka; nekeičiamas audito žurnalas |
| Integracijos | REST API, webhook'ai, `reporting` schema DWH, SMTP/IMAP, JSON žurnalai SIEM, Prometheus metrikos |
| Eksploatacija | Šifruotos atsarginės kopijos su automatinėmis atkūrimo pratybomis; antivirusinis failų tikrinimas; staging aplinka |

Sąsaja — lietuvių ir anglų kalbomis, veikia naršyklėje (kompiuteryje ir telefone),
be išorinių CDN ar trečiųjų šalių paslaugų.

## Technologijos

| Sluoksnis | Technologija |
|---|---|
| Programa | Python 3.13, Django 5.2 LTS (palaikoma iki 2028-04), Gunicorn |
| Duomenų bazė | PostgreSQL 17 (Oracle — žr. `docs/ORACLE.md`) |
| Sąsaja | Serverio pusėje generuojamas HTML, AdminLTE 4 / Bootstrap 5 (vietoje), be JS karkaso |
| Tapatybė | OpenID Connect (`mozilla-django-oidc`): Microsoft Entra ID arba AD FS |
| Diegimas | Docker Compose (VM) arba Kubernetes (Helm) |
| Priedai | ClamAV (antivirusas), age (kopijų šifravimas), rclone (kopijos už serverio ribų) |
| Licencija | MIT (atvirasis kodas) |

## Kokybė ir patikra

Kiekvienas pakeitimas automatiškai tikrinamas (GitHub Actions): 655 automatiniai
testai su SQLite ir PostgreSQL, statinė kodo saugumo analizė (bandit),
priklausomybių pažeidžiamumai (pip-audit), konteinerių pažeidžiamumai (Trivy),
komponentų sąrašas (SBOM, CycloneDX), Helm chart schemų validacija, avarinio
atkūrimo pratybos, antiviruso integracija su tikru ClamAV, apkrovos testas
(50 vienu metu dirbančių naudotojų) ir Oracle suderinamumo ataskaita.
Pakeitimai pirmiausia automatiškai diegiami į staging aplinką.

## Dokumentų paketas

| # | Dokumentas |
|---|---|
| 01 | Sistemos aprašas (šis) |
| 02 | [Architektūra ir schemos](02-architektura-ir-schemos.md) |
| 03 | [Saugumo priemonės](03-saugumo-priemones.md) |
| 04 | [Duomenų žodynas](04-duomenu-zodynas.md) |
| 05 | [DAPV juodraštis](05-dapv-juodrastis.md) |
| 06 | [Kopijavimo ir atkūrimo planas](06-kopijavimo-ir-atkurimo-planas.md) |
| 07 | [Priežiūros ir perdavimo modelis](07-prieziura-ir-perdavimas.md) |
| 08 | [Pilotinis projektas](08-pilotinis-projektas.md) |
| 09 | [Žinomi apribojimai ir rizikos](09-apribojimai-ir-rizikos.md) |
| 10 | [Klausimai infrastruktūrai, saugai ir DAP](10-klausimai.md) |

Techniniai priedai: [DIEGIMAS-ORGANIZACIJOJE.md](../DIEGIMAS-ORGANIZACIJOJE.md),
[DEPLOYMENT.md](../DEPLOYMENT.md), [KUBERNETES.md](../KUBERNETES.md),
[INTEGRACIJOS.md](../INTEGRACIJOS.md), [ORACLE.md](../ORACLE.md),
[ARCHITECTURE.md](../ARCHITECTURE.md).

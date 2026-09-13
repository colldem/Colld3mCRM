# 6. Kopijavimo ir atkūrimo planas

## 6.1 Tikslai

| Rodiklis | Numatyta | Kaip keisti |
|---|---|---|
| **RPO** (didžiausias duomenų praradimas) | ≤ 24 val. | `BACKUP_INTERVAL_SECONDS` (pvz. 21600 = 6 val.) arba DB platformos PITR |
| **RTO** (atkūrimo trukmė) | tikslas ≤ 2 val. nuo sprendimo atkurti | išmatuoti pratybose (6.6); techninis atkūrimas su bandomaisiais duomenimis — kelios minutės |
| Kopijų saugojimas serveryje | 14 rinkinių | `BACKUP_KEEP` |
| Kopijų saugojimas už serverio ribų | 30 d. | `BACKUP_REMOTE_KEEP_DAYS` |

## 6.2 Apimtis

| Kas | Kaip kopijuojama | Pastaba |
|---|---|---|
| Duomenų bazė | `pg_dump` (custom formatas) kas intervalą; prieš kiekvieną diegimą — papildomai | apima auditą, nustatymus, šifruotas integracijų paslaptis |
| Priedų failai (`runtime/media`) | `tar.gz` tame pačiame rinkinyje | |
| `.env` (paslaptys) | **ne** kopijose — organizacijos slaptažodžių saugykloje | be `CRM_SECRETS_KEY` integracijų slaptažodžiai neiššifruojami |
| age privatus raktas | **ne** serveryje — slaptažodžių saugykloje, bent 2 atsakingi asmenys | be jo kopijų atkurti neįmanoma |
| Konfigūracija (`compose*.yaml`, `deploy/`) | Git repozitorija | |
| Kubernetes variantas | DB platformos kopijos (PITR), S3 versijos | `crm-backup` naudojamas tik su Compose |

## 6.3 Apsauga

- Kiekvienas rinkinys šifruojamas **age** viešuoju raktu (ar keliais — antras
  raktas DR saugyklai); `BACKUP_REQUIRE_ENCRYPTION=true` neleidžia rašyti
  nešifruotų kopijų. CRM serveris kopijas kurti gali, bet perskaityti — ne.
- SHA-256 sumos kiekvienam rinkiniui; atkūrimas sustoja, jei failas pakeistas.
- Kopija už serverio ribų per rclone (S3 / SFTP / …) — jau užšifruota.
- Rakto rotacija: sukurti naują porą, pridėti naują viešąjį raktą prie
  `BACKUP_AGE_RECIPIENTS`, po `BACKUP_REMOTE_KEEP_DAYS` pašalinti senąjį;
  seną privatų raktą saugoti, kol yra juo užšifruotų kopijų.

## 6.4 Stebėsena

- `crm-backup` konteineris *unhealthy*, jei per du intervalus (+1 val.) nėra sėkmingo rinkinio (`last-success`).
- Kiekvienas rinkinys — JSON žurnalo įrašas (`logger=crm.backup`); klaidos — `level=ERROR` (įspėjimas SIEM'e).
- Nepavykęs kopijos siuntimas už serverio ribų laikomas nesėkme.

## 6.5 Atkūrimo procedūra

1. Sprendimas atkurti (sistemos savininkas + IT), incidento registravimas.
2. Pasirinkti rinkinį (`manifest-<laikas>.json`), gauti privatų raktą iš saugyklos.
3. `bash scripts/restore.sh --db runtime/backups/db-<laikas>.dump.age --media runtime/backups/media-<laikas>.tar.gz.age --identity <raktas>`
   — patikrina sumas, sustabdo programą, iššifruoja konteineryje, atkuria DB viena
   transakcija, pakeičia failus, paleidžia ir parodo įrašų skaičių.
4. Patikra: prisijungimas, sąrašas, kortelė, priedo atsisiuntimas, `/health/ready`, žurnale nėra klaidų.
5. Pranešti naudotojams, nuo kurio laiko duomenis reikia suvesti iš naujo (RPO langas).
6. Jei po kopijos buvo įvykdyti duomenų subjektų ištrynimai — pakartoti juos (žr. ištrynimų žurnalą: `detail.reason=data_subject_erasure`).
7. Užregistruoti trukmę (RTO) ir pastabas.

Visiškas serverio praradimas: nauja VM pagal [DIEGIMAS-ORGANIZACIJOJE.md](../DIEGIMAS-ORGANIZACIJOJE.md) 7 skyrių
→ `.env` iš saugyklos → kopijos iš saugyklos už serverio ribų → 3–7 žingsniai.

## 6.6 Pratybos

| Kas | Kada | Kas atlieka |
|---|---|---|
| Automatinės pratybos (šifruota kopija → duomenų praradimas → sugadinto failo atmetimas → atkūrimas → turinio patikra) | kiekvieno kodo pakeitimo metu (CI `backup-restore`) | automatiškai |
| Atkūrimas organizacijos infrastruktūroje į atskirą VM iš kopijų saugyklos | pilotui pradedant, vėliau kas ketvirtį | IT administratorius |
| Rakto pasiekiamumo patikra (privatus raktas randamas ir tinka) | kas pusmetį | du atsakingi asmenys |

## 6.7 Atsakomybės

| Veikla | Atsakingas |
|---|---|
| Kopijų veikimo stebėsena | IT administratorius **[ORGANIZACIJA]** |
| Kopijų saugykla už serverio ribų | infrastruktūra **[ORGANIZACIJA]** |
| age raktų ir `.env` saugojimas | IT saugos atsakingas **[ORGANIZACIJA]** |
| Sprendimas atkurti | sistemos savininkas **[ORGANIZACIJA]** |
| Pratybos ir jų protokolas | IT administratorius |

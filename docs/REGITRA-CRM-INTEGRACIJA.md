# Regitros klientų DB („CRM“) integracija ir didelių kiekių pasirengimas — užrašai

Būsena: **atidėta, grįžti vėliau** (aptarta 2026-09-13). Tai ne sprendimas, o
surinkta informacija ir įvertinimas tolesniam darbui.

## 1. Kas yra Regitros „CRM“ (iš Confluence / Jira)

- Oracle **klientų duomenų bazė** („CRM, sms, email, asmenų registras“), dev/test/prod aplinkos.
- Schemos: `CLIENT_DB.NOTIFICATIONS` (pranešimai, grupuojami `common_group_id`),
  `SMSIS.MESSAGE_REGISTRY` (SMS), `EMAILIS.MESSAGES` (laiškai su tekstu),
  `WEBIS.MESSAGE_REGISTRY` (sistemų užklausos, XML). Confluence „SELECTAI“.
- `EMAILIS.MESSAGES` planuojama papildyti `SYSTEM_ID`, `REFERENCE_ID` (Jira CZ-3706).
- Oracle **APEX „CRM“ aplikacija**; kontaktų (tel., el. pašto) taisymas **pagal asmens kodą**
  kiekvienoje sistemoje (ORATECH-399, -415, -515, -511).
- Kontaktai laikomi atskirai eKETRIS / VEPP / e.regitra ir nesisinchronizuoja (PRJ-457).
- Kitos sistemos ima „aktualius (validuotus)“ kontaktus iš CRM (IPP įmokos grąžinimo reikalavimai).
- CRM PROD serveryje diegiamas **ORDS** (SITD-496) — galimas REST kelias integracijai.
- SMS per Tele2 API (PRJ-433), „SMS lenta“ (MVP-36); darbai su NetCode.

Išvada: Regitros „CRM“ — kontaktų ir pranešimų registras (šaltinis). Mūsų CRM būtų
darbo sluoksnis ant jo, ne pakaitalas. Raktas — **asmens kodas** → reikia peržiūrėti DAPV ir rizikas.

## 2. Poreikis (naudotojo žodžiais)

- Į CRM pasipildyti asmenis ir įmones iš Regitros „CRM“ su kontaktiniais duomenimis.
- Kortelėje matyti, kas kam buvo siųsta (SMS, laiškai su tekstais).
- Mastas: nežinomas, prielaida **500–800 tūkst.** įrašų; klientai grįžta periodiškai.
- Galimos integracijos su klientų aptarnavimo sistemomis (rodyti CRM duomenis).
- Tikėtina, kad push nebus — CRM turės pati periodiškai imti (GET): SMS, laiškai, kontaktų atnaujinimai.
- Reikės sisteminių laukų kortelėje ir papildomų dinaminių laukų.
- ~50 vienu metu dirbančių naudotojų.

## 3. Dabartinio kodo apribojimai dideliems kiekiams (patikrinta kode)

| Vieta | Problema |
|---|---|
| `duplicates.find_person_duplicates` (kiekvienas išsaugojimas) | įkelia **visus** asmenis į atmintį — lūžtų pirmiausia |
| `duplicates.all_person_duplicate_pairs` | visi asmenys į atmintį |
| `filters.py` paieška | `icontains` per 11 laukų su jungtimis + `distinct` — pilni skenavimai |
| Sąrašai | pilnas `COUNT` kiekvienam puslapiui; dinaminių laukų filtrai per EAV (`CustomValue`) |
| Analitika / darbastalis | ~45 skaičiavimų per visą DB |
| Kortelė | pagal PK greita; reikės veiklų / pranešimų puslapiavimo |
| Modelis | nėra asmens kodo, išorinio ID, šaltinio sistemos, „validuota nuo“, sinchronizavimo laiko |
| Importas | CSV per naršyklę iki 10 MB — netinka |

Apkrovos testas CI buvo su 5 000 kontaktų. PostgreSQL pati 800 tūkst. asmenų ir ~10 mln.
pranešimų atlaiko; keisti reikia užklausas. Grubus įvertinimas: **1,5–3 sav.**

### Išmatuota su 800 tūkst. (0 etapas, 2026-09-24)

800 000 asmenų, 200 000 įmonių, 2,4 mln. veiklų, 400 000 priminimų, ~1 % dublikatų;
DB 1,2 GB. Kiekvienas puslapis atskirai, vienas naudotojas (`scripts/loadtest/probe.py`),
PostgreSQL 16, Gunicorn 2 × 2, 4 vCPU be atminties ribos; užklausos riba 120 s.
Tas pats CI: **Actions → „Load — large volume"** (`load-large.yml`, 2 vCPU / 1 GB).

| Puslapis | 5 000 | 800 000 |
|---|---|---|
| Darbastalis | 0,21 s | 2,5 s |
| Kontaktų sąrašas (1 ir 2000 psl.) | 0,12 s | 1,3 s |
| Paieška kontaktų sąraše | 0,11 s | 8,3 s |
| Paieškos pasiūlymai / globali paieška | 0,11 / 0,13 s | 21,5 / 21,9 s |
| Įmonių sąrašas su filtru | 0,04 s | 0,8 s |
| Kontakto kortelė | 0,10 s | 6,8 s |
| Analitika | 0,31 s | **> 120 s (klaida)** |
| Naujo asmens forma (visos įmonės kaip žymimieji langeliai) | 0,25 s | 37 s |
| Dublikatų tikrinimas išsaugant | 0,58 s | **139 s** |
| Dublikatų sąrašas | 1,4 s | **> 150 s** |

Web proceso atmintis pakilo iki **6,6 GB** (dublikatai) — 1 GB konteineryje procesas būtų nužudytas.
Analitika: `COUNT` su `person_id IN (visi asmenys) OR company_id IN (...)` — 800 tūkst. id netelpa į
`work_mem`, PostgreSQL tikrina kiekvieną veiklą per visą asmenų sąrašą (valandos).

### 1 etapas — dublikatai (0.84.0)

Tikrinimas išsaugant ieško per indeksus (`match_key` — `LOWER(TRIM(...))`, telefonų `digits`),
peržiūros sąrašą sudaro foninis `find_duplicates` (`crm-worker` kas ciklą, K8s CronJob kas 5 min.)
į `DuplicateCandidate`; puslapis tik skaito, puslapiuoja po 50 ir tikrina matomumą `EXISTS` per porą.

| Matavimas (800 tūkst.) | Prieš | Po |
|---|---|---|
| Dublikatų tikrinimas išsaugant | 139 s | 0,03 s |
| Dublikatų sąrašas | > 150 s | 1,6 s |
| Web proceso atmintis (dublikatai) | 6,6 GB | nepastebima |
| Foninė patikra `find_duplicates` | — | 11 s, 87 MB, 16 136 porų |
| Migracija 0057 (telefonų skaitmenų užpildymas) | — | ~2 min. |

### 2 etapas — paieška ir sąrašai (0.85.0)

Filtrai: susijusios lentelės — `pk IN (… UNION …)` vietoj `JOIN` + `DISTINCT` visiems stulpeliams;
`pg_trgm` GIN indeksai ant `UPPER(col)` (migracija 0058, ~25 s su 800 tūkst.). Įmonių pasirinkimas —
paieškos laukelis (`company_lookup`), ne visos įmonės puslapyje. Analitikos veiklų matomumas —
`visible_activities` (jungtis, ne `IN (800 tūkst.)`).

| Matavimas (800 tūkst.) | 1 etapo pabaigoje | Po 2 etapo |
|---|---|---|
| Kontaktų sąrašas | 1,3 s | 0,9 s |
| Paieška kontaktų sąraše | 8,8 s | 0,8 s |
| Paieškos pasiūlymai / globali paieška | 23 / 24 s | 0,2 / 0,9 s |
| Kontakto kortelė | 7,2 s | 0,75 s |
| Naujo asmens forma | 40 s | 0,75 s |
| Įmonių paieška valdiklyje | — | 0,01 s |
| Analitika | > 120 s (klaida) | 44 s (3 etapas) |

Liko ~0,5–0,9 s kiekviename puslapyje — varpelis; bandomuosiuose duomenyse kiekvienas naudotojas turi
~20 tūkst. atvirų priminimų (nerealu), todėl tai matuojama atskirai.

### 3 etapas — analitika (0.86.0)

Skaičiuojama DB (`GROUP BY` savaitei / mėnesiui, `EXISTS` / `NOT EXISTS`, vidurkis per subužklausą), ne
Python cikle per visas eilutes. Apžvalgos ir komunikacijos sunkioji dalis saugoma `AnalyticsSnapshot`:
visų įrašų matomumui ją kas ~20 min. perskaičiuoja `refresh_analytics` (su 800 tūkst. — 17 s), kitiems —
pirmą kartą atidarius, galioja 30 min.

| Matavimas (800 tūkst.) | Prieš | Po |
|---|---|---|
| Analitikos apžvalga | > 120 s (klaida), po 2 etapo 52 s | 2,7 s (pirmą kartą be išankstinio — ~11 s) |
| Komunikacija | 58 s | 1,0 s (pirmą kartą — ~8 s) |
| Ryšių priežiūra | 13 s | 3,5 s |
| Bazė ir augimas | 13 s | 2,3 s |
| Web proceso atmintis per visą matavimą | 635 MB | 85 MB |

### 5 etapas — kortelės istorijos puslapiavimas (0.87.0)

Kortelės skirtukuose (Visi / Komentarai / Failai) — 50 naujausių, skaičiai iš DB, „Rodyti senesnius“
prideda po 50 (iki 1000). Asmuo su 5 000 veiklų ir 300 failų: kortelė 3,4 s → 1,2 s, įmonė 4,1 s → 1,2 s
(likusi dalis — bendras puslapio karkasas).

## 4. Siūloma kryptis

- **Integracija:** 1) ORDS tik skaitymo REST („pakitę nuo X“, „asmens pranešimai“), CRM worker
  traukia pokyčiais, porcijomis; 2) atsarginis — tik skaitymo Oracle rodinys + `oracledb`;
  3) AQ / GoldenGate — brangiausia.
- **Asmenys:** ne visi iš karto — lengvas identifikatorių indeksas pokyčiais arba įkėlimas pagal
  poreikį; neaktyvūs valomi saugojimo terminais.
- **Pranešimai:** archyvo nekopijuoti; kortelėje rodyti gyvai iš API su puslapiavimu.
- **Laukai:** sisteminiai — tikri stulpeliai su indeksais (asmens kodas šifruotas / hash paieškai,
  `external_id` pagal šaltinį, šaltinis, validuota nuo, sutikimai, sinchronizuota); filtruojami
  dinaminiai — stulpeliai arba JSONB su indeksu, ne EAV.
- **Paieška:** PostgreSQL pilno teksto + `pg_trgm`; dublikatai per indeksą; paginacija be pilno `COUNT`;
  analitika iš anksto suskaičiuota.

## 5. Kitas žingsnis (kai grįšime)

1. ~~Didelių kiekių matavimas~~ — atlikta (§3, `load-large.yml`).
2. Mastelio etapai, po kiekvieno — pakartotinis `load-large.yml`:
   1) ~~dublikatai~~ — atlikta (0.84.0, §3);
   2) ~~paieška ir sąrašai~~ — atlikta (0.85.0, §3);
   3) ~~darbastalis ir analitika~~ — atlikta (0.86.0, §3);
   4) sisteminiai laukai ir didelis importas porcijomis;
   5) ~~kortelės veiklų puslapiavimas~~ — atlikta (0.87.0, §3);
   6) foninių darbų priežiūra ir stebėsena:
      - A. savaiminis atsistatymas — kiekvienam `crm-worker` darbui laiko riba (pakibęs nutraukiamas,
        kiti vyksta), konteinerio sveikatos patikra (ciklas baigtas per ~20 min., kitaip paleidžiamas iš
        naujo), `crm-worker` CPU/atminties ribos ir žemesnis prioritetas, `statement_timeout` DB užklausoms;
      - B. matomumas CRM — Nustatymai → Sistemos būklė (kiekvieno darbo paskutinė sėkmė / klaida / būsena),
        raudona juosta administratoriui, kai darbas vėluoja ar krenta, `/health/jobs` išorinei stebėsenai;
      - C. pranešimai į išorę — NAS: Uptime Kuma (`/health/ready`, `/health/jobs` → el. paštas / Telegram /
        Teams); organizacijoje: `/metrics` + `docs/DEPLOYMENT.md` įspėjimų taisyklės į Prometheus / Zabbix.
3. Integracijos prototipas su netikru ORDS stiliaus API.

## 6. Klausimai Regitros Oracle / CRM komandai

1. Tikri kiekiai: asmenys, įmonės, pranešimai per metus, kiek su tekstais?
2. Ar yra `date_modified` / pokyčių žyma asmenims, kontaktams, pranešimams?
3. Ar ORDS gali pateikti tik skaitymo REST endpoint'us; kas juos kurtų (Regitra, NetCode, kartu)?
4. Kuris kontaktas „teisingas“, kai eKETRIS / VEPP / e.regitra skiriasi; ar CRM tik rodo, ar ir taiso?
5. Kurios klientų aptarnavimo sistemos turėtų rodyti CRM duomenis; ar reikia API iš CRM pusės?
6. Ar DAP leidžia asmens kodą CRM ir kokiam tikslui?

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
pranešimų atlaiko; keisti reikia užklausas. Grubus įvertinimas: **1,5–3 sav.** (neišmatuota).

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

1. Didelių kiekių testas CI: 800 tūkst. asmenų, 200 tūkst. įmonių, ~10 mln. pranešimų, 50 naudotojų — tikri skaičiai.
2. Mastelio etapas pagal rezultatus (paieška, dublikatai, sąrašai, analitika, sisteminiai laukai, kortelės puslapiavimas).
3. Integracijos prototipas su netikru ORDS stiliaus API.

## 6. Klausimai Regitros Oracle / CRM komandai

1. Tikri kiekiai: asmenys, įmonės, pranešimai per metus, kiek su tekstais?
2. Ar yra `date_modified` / pokyčių žyma asmenims, kontaktams, pranešimams?
3. Ar ORDS gali pateikti tik skaitymo REST endpoint'us; kas juos kurtų (Regitra, NetCode, kartu)?
4. Kuris kontaktas „teisingas“, kai eKETRIS / VEPP / e.regitra skiriasi; ar CRM tik rodo, ar ir taiso?
5. Kurios klientų aptarnavimo sistemos turėtų rodyti CRM duomenis; ar reikia API iš CRM pusės?
6. Ar DAP leidžia asmens kodą CRM ir kokiam tikslui?

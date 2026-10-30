# Įgyvendinimo planas: CRM paruošimas integracijoms

Būsena: **programuotojo peržiūra 2026-10-30**. Pagrindas —
`docs/REIKALAVIMAI-INTEGRACIJOMS.md` (analitiko dokumentas, toliau — RI).
Teiginiai sutikrinti su kodu: `main` 388ffd4, `regitra` 09d5e0e.

Šis dokumentas: (1) pastabos analitikui — kas RI netikslu ar praleista;
(2) sprendimai, be kurių negalima pradėti; (3) etapai ir konkrečios užduotys
su failais, testais, priėmimu ir apimtimi.

Apimties žymėjimas: **S** ≤ 1 d., **M** 2–3 d., **L** 4–5 d. (vienas programuotojas,
įskaitant testus, naršyklės patikrą, žinyną ir vertimus pagal `CLAUDE.md`).

---

## 1. Verdiktas

RI kryptis teisinga: adapteris + bandomasis serveris, gyvi duomenys nesaugomi,
paslaugų faktai saugomi, CRM savo API kontraktas skambučiams. Dauguma FR
įgyvendinami taip, kaip parašyta.

Tačiau RI **nepastebėjo dviejų dalykų `regitra` šakoje**, kurie keičia
etapo 0 apimtį ir rolių modelį (K1, K2). Be jų sprendimo pradėti etapų 1–3
negalima — kitaip tas pats darbas bus daromas du kartus skirtingais modeliais.

---

## 2. Pastabos analitikui

| # | Svarba | Kas | Kur RI | Ką daryti |
|---|---|---|---|---|
| K1 | Blokuojanti | `regitra` šaka nėra „atsilikusi“, ji **išsiskyrusi**: 41 savas commit'as, 56 `main` commit'ai neperimti. Migracijos `0056`–`0062` abiejose šakose turi **tuos pačius numerius ir skirtingą turinį**. Asmens kodas — **dvi schemos**: `regitra` — `Person.personal_code` atviru tekstu (`CharField(11)`), `main` — `personal_code_encrypted` + `personal_code_hash` (`identity.py`). Regitros staging DB jau pritaikiusi `regitra` migracijas. | T01, §2 | T01 skaidyti į E0-01…E0-04: inventorius, asmens kodo schemos suvienijimas su duomenų migracija, migracijų grafo perstatymas, pavijimas. |
| K2 | Blokuojanti | `regitra` šakoje yra **prieigos modelis „paieška su pagrindu“** (`RecordAccess`, `record_access.py`, `docs/REGITRA-PRIEIGA.md`). Visą bazę mato tik administratorius ir vadovas; kiti mato tik **aktyvius** įrašus, atvertus su užfiksuota priežastimi (iki dienos pabaigos, ilgiau — su priminimu, veikla ar „Imu į darbą“). RI jo nemini. | T09–T12, T17, T18 | Prieštaravimai: T12 duoda visoms trims grupėms „visi įrašai“; T09/T10/T11 specialistui su „savo aktyvūs“ grąžintų tuščią suvestinę ir eksportą; T16–T18 skambutis turi pats suteikti prieigą su pagrindu „Kliento kreipimasis“. Reikia savininko sprendimo S2. |
| K3 | Svarbi | Commit'as `daed7b7` („revert: take the registry column out of the public CRM“) — savininkas sąmoningai išėmė registrų koloną iš `main` kaip specializuotos versijos dalį. Vėliau `main` vis tiek gavo asmens kodą ir `contacts/regitra.py`. FR-01.1 (blokų jungtis į `main`) tam sprendimui neprieštarauja, nes jungtis generinė, be Regitros specifikos. Bet tai reikia **patvirtinti aiškiai**. | T01 FR-01.1 | Sprendimas S1 kartu su Q1. |
| K4 | Svarbi | Asinchroninis krovimas `main` jau yra: `static/js/regitra.js` + `views.person_regitra` (`/contacts/<pk>/regitra/<kind>/`). Teiginys „loader kviečiamas sinchroniškai“ teisingas tik `regitra` šakos `record_blocks()`. | T02, §2 | T02 = apibendrinti esamą `main` mechanizmą blokams, ne kurti nuo nulio. Apimtis mažesnė. |
| K5 | Svarbi (sauga) | `ApiToken` veikia **kūrėjo teisėmis** (docstring: „Acts with its creator's visibility and capabilities“). Raktus kuria tik administratorius, todėl skambučių centro raktas turėtų administratoriaus matomumą ir visas teises, įskaitant asmens kodų peržiūrą. Rakto galiojimas — iki 365 d. | T14 FR-14.4, T16 | Paslaugų paskyra: raktas susiejamas su sisteminiu naudotoju, kuris turi tik reikiamas teises (E3-04). Rotacijos procedūra — `docs/INTEGRACIJOS.md`. |
| K6 | Svarbi (esama klaida) | `merging.py:125`: jei **abu** sujungiami asmenys turi `external_id`, šaltinio ID lieka archyvuotame įraše. Sinchronizacija tada atnaujins archyvuotą kortelę, o ne paliktą. | T03 FR-03.4 | Sutvarkyti E0-08: konfliktas → sujungimas atmetamas su paaiškinimu. |
| K7 | Smulki | FR-05.4 (paieška pagal `company_code`) **jau įgyvendinta**: `filters.py:180`, `views.py:2451`. | T05 | Išbraukti. |
| K8 | Svarbi | FR-06.6 neturi duomenų modelio. `PhoneNumber` / `EmailAddress` / `PostalAddress` neturi `source` lauko. `Company.phone` ir `Company.email` — po vieną lauką, ne sąrašas: įmonei „šaltinio + savi papildomi“ be modelio keitimo neįmanomas. | T06 | Asmeniui — `source` laukas trims kontaktų modeliams. Įmonei — šaltinio laukai tik skaitomi visiškai, CRM papildomi duomenys — dinaminiuose laukuose (E1-05). |
| K9 | Svarbi | FR-11.6 eksporto kelių sąrašas neišsamus. Dar yra: `analytics_views.py:302` (darbastalio sąrašų CSV), `settings_data_export` (pilna kopija, tik administratorius), `privacy.export_person` (subjekto eksportas). | T11 | Riba ir auditas — ir analitikos CSV. Pilna kopija ir subjekto eksportas — be ribos, bet su auditu (jau yra). |
| K10 | Smulki | FR-16.6: riba dabar globali `CRM_API_RATE_LIMIT`. Per raktą — nėra. | T16 | `ApiToken.rate_limit` (null = globali) — E3-04. |
| K11 | Svarbi (diegimas) | FR-14.1 `occurred_at` 2,4 mln. eilučių: `AddField` su numatytąja reikšme PostgreSQL perrašo lentelę su užraktu. Ordering keitimas paliečia `_feed_context`, analitiką, API, `reporting` rodinius. | T14 | Trys migracijos: nullable stulpelis → užpildymas porcijomis → `NOT NULL`. Indeksai `(person, occurred_at)` ir `(company, occurred_at)` — `AddIndexConcurrently` (`atomic = False`). Regresija visiems keturiems vartotojams. |
| K12 | Svarbi (verslas) | FR-08.3: faktas be kortelės **praleidžiamas**. Tada suvestinė vėl nepilna — būtent to užsakovas norėjo išvengti (verslo sprendimas 8). | T08 | `ServiceRecord` saugo `subject_source` + `subject_external_id`; FK prijungiamas, kai kortelė atsiranda (sinchronizacija ar vėlesnis praėjimas). Suvestinė skaičiuoja faktus, ne korteles. |
| K13 | Smulki | FR-21.3 tikslai p95 absoliutūs, o `load-large.yml` p95 svyruoja 0,4–1,6 s pagal runner'į. | T21 | Lyginti A/B tame pačiame lange (`main` ir šaka iš eilės), tikslą formuluoti kaip „ne blogiau nei +20 % nuo `main`“ ir absoliutų — kaip orientyrą. |
| K14 | Smulki | FR-04.5 „ištrynimas → archyvas“ + `archived_retention_days` → po termino kortelė su CRM istorija ištrinama visam laikui. | T04 | Užrašyti žinyne; DAP sprendimas (Q4 išplėsti). |

---

## 3. Sprendimai prieš pradedant

| # | Sprendimas | Kas | Blokuoja |
|---|---|---|---|
| S1 | Regitros dalis — atskiras repozitorijus ar `regitra/` programėlė šiame (RI Q1)? Ar generinė blokų jungtis eina į `main` (K3)? **Siūlymas:** jungtis — į `main`; Regitros programėlė — `regitra/` kataloge šiame repozitorijuje, įjungiama `CRM_EXTRA_APPS`; `regitra` šaka panaikinama po E0-04. Viena šaka — vienas CI, vienas pavijimas mažiau. | Savininkas | E0-02…E0-07 |
| S2 | Prieigos modelis trims grupėms (K2). **Siūlymas:** KAC — „savo aktyvūs“; skambutis (E3-05, E3-06) automatiškai suteikia prieigą su pagrindu „Kliento kreipimasis“. Klientų patirties specialistai — „visi įrašai“ (analizė ir eksportas be to neįmanomi), kortelės atvėrimas fiksuojamas žurnale. Raštų komanda — „savo aktyvūs“, pagrindas „Dokumentų tvarkymas“. | Savininkas, DAP | E2-06, E3-05, E3-06 |
| S3 | Regitros staging DB: atkurti iš naujo po migracijų perstatymo (paprasčiau) ar migruoti esamą (`migrate --fake` planas)? **Siūlymas:** atkurti iš naujo (`refresh-staging.sh` + `sanitize_staging`), nes ten jau buvo atviru tekstu saugomi asmens kodai. | Savininkas | E0-03 |
| S4 | RI Q2–Q8 lieka galioti; jie blokuoja tik atskiras užduotis (nurodyta prie jų). | — | — |

**Ką galima pradėti iškart, nelaukiant S1–S3:** E0-01, E0-08, E2-04, E3-07.

---

## 4. Etapai

| Etapas | Tikslas | Užduotys | Apimtis | Pabaigos kriterijus |
|---|---|---|---|---|
| 0 | Viena kodo bazė, blokų jungtis, išoriniai ID | E0-01…E0-08 | ~25 d. | `regitra` šakos nebereikia; kortelė su blokais kraunasi asinchroniškai; `Company` ir `ExternalLink` turi išorinius ID |
| 1 | Regitros klientų DB: sinchronizacija ir blokai | E1-01…E1-07 | ~22 d. | Su bandomuoju serveriu sinchronizuojami asmenys, įmonės, ryšiai; 18 blokų rodo duomenis |
| 2 | Paslaugos, suvestinė, eksportas, rolės | E2-01…E2-08 | ~27 d. | Paslaugų suvestinė ir filtras veikia 5 mln. faktų; eksportas pagal filtrą su riba; trys profiliai |
| 3 | Skambučių centras | E3-01…E3-08 | ~22 d. | `POST /api/v1/calls` ir `calls/pop` veikia su `fake_call_center.py`; OpenAPI paruoštas tiekėjui |
| 4 | DocLogix | E4-01…E4-02 | ~7 d. | Raštų blokas ir susiejimas veikia su `fake_doclogix_api.py` |
| 5 | Tikri prijungimai | I1…I3 | priklauso nuo API | Realūs adapteriai, testinės aplinkos |

Iš viso etapai 0–4: **~100 darbo dienų** vienam programuotojui. Etapai 2 ir 3
po etapo 1 gali eiti lygiagrečiai, jei programuotojai du (jie liečia skirtingus
modulius; bendras tik `permissions.py` — derinti per E2-06).

Kiekviena užduotis = vienas commit'as ir push į `main` pagal `CLAUDE.md` (testai,
`release-check.sh`, `security-check.sh`, naršyklė LT/EN desktop ir mobilus,
žinynas, vertimai, `data_dictionary.py`, kai yra naujas laukas).

---

## 5. Užduotys

### Etapas 0 — pamatai

#### E0-01. `regitra` šakos inventorius · S · be priklausomybių
- 41 šakos commit'ą suskirstyti į tris grupes: (a) jau turi atitikmenį `main`;
  (b) bendrinė, turi eiti į `main`; (c) Regitros specifika.
  Pradinis vertinimas: (a) slaptažodžio atkūrimas, klaidų puslapiai, mygtukų skalė,
  leidimo workflow; (c) `RecordAccess`, paieška su pagrindu, blokai, prekės ženklas,
  Regitros staging; (b) neaiškūs — `manager` rolė, komandos vadovai, nesėkmingos paieškos
  žurnalas.
- Kiekvienai migracijai `0056`–`0062` (`regitra`) — ką ji daro ir ar `main` turi atitikmenį.
- Rezultatas: `docs/REGITRA-SAKA-INVENTORIUS.md` (atlikta 2026-10-30).
- **Priėmimas:** kiekvienas commit'as ir migracija turi sprendimą (perkelti / atmesti / jau yra).

#### E0-02. Asmens kodo schemos suvienijimas · M · E0-01, S1, S3
- `regitra` šakoje pereiti prie `main` modelio: `identity.py`, `personal_code_encrypted`,
  `personal_code_hash`, `personal_code_type`.
- Duomenų migracija: atviras `personal_code` → `identity.assign()` (šifruoti + hash) →
  stulpelis pašalinamas.
- `contacts/validators.py` (šimtmečio skaitmuo, gimimo data, kontrolinis skaitmuo) palyginti
  su `identity.normalize()` / `_checksum()`; ko trūksta `main` — perkelti į `identity.py`
  atskiru commit'u į `main`.
- Paieška su pagrindu (`record_access_views.py`) — per `personal_code_hash`, POST, ne URL.
- **Testai:** migracija iš atviro teksto; paieška pagal kodą; kodas nepatenka į žurnalus.
- **Priėmimas:** `grep personal_code ` šakoje rodo tik `main` laukus; DB nėra atviro teksto stulpelio.

#### E0-03. Migracijų grafo perstatymas · L · E0-02
- Kartu — plėtinio taškai `main` programėlei: `Team.leads`, matomumų ir žurnalo veiksmų
  registrai (`REGITRA-SAKA-INVENTORIUS.md` M2–M4).
- Šakos migracijos, kurios lieka (pagal E0-01), perrašomos ant `main` `0062_content_page`
  viršaus kaip `0063+`. Pasikartojantys `alter_auditlog_action` sujungiami į vieną.
- Jei S1 = atskira programėlė: Regitros modeliai (`RecordAccess`) — `regitra/migrations/`.
- Regitros staging — pagal S3.
- **Priėmimas:** `makemigrations --check` švarus; tuščia DB → `migrate` be klaidų; staging atkurtas.

#### E0-04. Pavijimas ir šakos uždarymas · L · E0-03
- `git merge main` į `regitra` (ne `cherry-pick`: 56 commit'ai). Konfliktai sprendžiami
  pagal E0-01 lentelę. Po to — `regitra/` programėlė (jei S1) ir šakos panaikinimas.
- Abi konfigūracijos (`CRM_EXTRA_APPS` tuščias ir su `regitra`) — CI matrica `ci.yml`.
- `deploy-regitra-staging.yml` — iš `main` su Regitros perdanga.
- **Priėmimas:** visi testai žali abiem konfigūracijomis; Regitros staging veikia iš `main`.

#### E0-05. Generinė blokų jungtis `main` · M · E0-04 · RI T01 FR-01.1–01.3
- `contacts/record_blocks.py` be `_PLACEHOLDERS`; `RolePermissions.blocks`;
  `permissions.can_see_block`; Nustatymai → Registrų blokai (`templates/settings/record_blocks.html`).
- Vidurinis stulpelis `_detail_layout.html` rodomas tik jei yra matomas blokas.
- **Testai:** be registruotų blokų kortelė nepakitusi (snapshot); rolės matomumas.

#### E0-06. Asinchroninis blokų krovimas · L · E0-05 · RI T02 (pataisyta K4)
- Apibendrinti `static/js/regitra.js` → `static/js/blocks.js`; `views.person_regitra` →
  `GET /contacts/<pk>/blocks/<key>/`, `GET /companies/<pk>/blocks/<key>/`, `?offset=`.
- Kontraktas `loader(record, offset) -> {"items", "has_more", "columns"}`;
  `BlockUnavailable(message)`; `CRM_BLOCK_TIMEOUT_SECONDS` (5) — į `.env.example` ir
  `docs/DEPLOYMENT.md`.
- Būsenos: krauna / tuščia / klaida / neprijungta / duomenys. Suskleisti nekraunami;
  išskleidimas — `UserProfile.layout_config`.
- **Testai:** įrašo ir bloko matomumas (403/404); laiko riba; klaida → ne 500, `request_id`
  žurnale; puslapiavimas; suskleistas nekraunamas.
- **Priėmimas:** loader'is su 3 s vėlavimu nekeičia kortelės laiko.

#### E0-07. Regitros skilčių perkėlimas į blokus · M · E0-06 · RI T01 FR-01.4, 01.6
- `contacts/regitra.py`, `_regitra_rows.html`, `regitra.js` → `regitra` programėlė,
  trys rūšys registruojamos `register_block`.
- `can_view_regitra` → blokų matomumas; duomenų migracija perkelia esamas reikšmes į
  `RolePermissions.blocks`; teisė pašalinama (`permissions.py`, vertimai, žinynas).
- **Priėmimas:** `main` be `regitra` programėlės neturi Regitros kodo
  (`grep -ri regitra contacts/` — tik dokumentacija).

#### E0-08. Išoriniai identifikatoriai · M · be priklausomybių · RI T03 + K6
- `Company.external_source`, `external_id`, `synced_at` + `unique_company_external_id`.
- `ExternalLink` (RI FR-03.2) + `contacts/external_ids.py` (`find_record`, `link`, `unlink`, auditas).
- `merging.py`: abu turi skirtingą tos pačios sistemos ID → `MergeConflict` su paaiškinimu;
  `ExternalLink` perkeliami. Tas pats įmonėms.
- API objektuose — `external_source`, `external_id`. Kortelės „Tapatybė“ — „Susieta su“
  (`can_view_personal_code` arba administratorius).
- `data_dictionary.py`, `04-duomenu-zodynas.md`; jei laukai `reporting` rodiniuose — nauja migracija.
- **Testai:** unikalumas, `CheckConstraint` (lygiai vienas FK), sujungimo konfliktas, auditas, API.

### Etapas 1 — Regitros klientų DB

#### E1-01. Sinchronizacijos karkasas · L · E0-08 · RI T04 FR-04.1–04.3, 04.6, 04.7, 04.9, 04.10
- `contacts/sync/source.py` (`ChangeSource`, `ChangeBatch`), `SyncState` modelis,
  `management/commands/sync_external.py` (`--source`, `--entity`, `--full`), `tracked` + `JobStopped`.
- Registracija: `jobs.py`, `scripts/worker.sh`, Helm `cronjobs.yaml` + `values.yaml`.
- `CRM_SYNC_BATCH_SIZE` — `.env.example`, `docs/DEPLOYMENT.md`.
- Porcija = transakcija; žymeklis įrašomas tik po sėkmės; auditas — suvestinė porcijai.
- Nustatymai → Sistemos būklė: lentelė pagal `(source, entity)`.
- **Testai:** žymeklis; lūžis porcijos viduryje → kartojama ta pati porcija; „neprijungta“ ≠ klaida.

#### E1-02. Bandomasis pokyčių šaltinis · M · E1-01 · RI FR-04.8
- `scripts/fake_regitra_api.py`: `/persons/changes`, `/companies/changes`,
  `/person-companies/changes`, `/services/changes`, `/service-types` (ORDS formatas,
  `since`, `limit`, `offset`). Deterministinė sėkla; pakeitimai ir ištrynimai pagal laiką.
- `regitra` programėlėje — `OrdsChangeSource` (tas pats klientas vėliau eis į tikrą ORDS).

#### E1-03. Asmenų sinchronizacija · M · E1-02 · RI FR-04.4, 04.5
- `upsert` per `bulk_import` (raktas, neperšifruoti nepakitusio kodo); nerasta pagal ID,
  rasta pagal `personal_code_hash` → prijungiama; `delete` → `deleted_at` + auditas.
- **Priėmimas (RI):** 100 tūkst. pradinis; antras paleidimas — 0 atnaujinimų; nutrauktas tęsiasi.

#### E1-04. Įmonės ir ryšiai · M · E1-03 · RI T05 (be FR-05.4, K7)
- `entity="company"` (prijungimas pagal `company_code`), `entity="person_company"`;
  `PersonCompanyLink.source` (numatytai `crm`), sinchronizacija liečia tik savo `source`.
- `manage.py import_companies` (CSV porcijomis kaip `import_people`).
- **Testai:** rankinis ryšys išlieka; šaltinio ryšio pašalinimas.

#### E1-05. Šaltinio valdomi laukai · L · E1-03 · RI T06 + K8
- `SOURCE_OWNED_FIELDS` registras (bendrinis CRM — tuščias, `regitra` programėlė pildo).
- `PhoneNumber`, `EmailAddress`, `PostalAddress` + `source` (numatytai `crm`).
- Serverio pusės draudimas: `forms.py`, `detail_editing.py`, `inline_views.py`, `api.py` PATCH,
  masiniai veiksmai, `bulk_import` / naršyklės importas. Viena funkcija `source_locked(record, field)`.
- UI: ženklelis „Iš Regitros“, „Sinchronizuota: prieš 2 val.“.
- **Testai:** kiekvienam keliui — šaltinio laukas nekeičiamas, CRM laukas keičiamas.

#### E1-06. ORDS klientas ir 18 blokų · L · E0-07, E1-02 · RI T07
- `regitra/ords.py`: kolekcijos formatas, laiko riba, `X-Request-ID`, 1 pakartojimas,
  OAuth2 client credentials / Basic (`CRM_REGITRA_API_*`).
- 18 loader'ių; laukų aprašai — viename faile `regitra/columns.py`.
- SMS blokas: numeris užmaskuotas (paskutiniai 3), pilnas tekstas išskleidžiamas.
- `fake_regitra_api.py` — visos 18 rūšių.
- **Priėmimas:** išjungus bandomąjį serverį — „Regitra šiuo metu nepasiekiama“, kortelė veikia.

#### E1-07. Sinchronizacijos ir blokų našumas · S · E1-04, E1-06 · RI T21 dalis
- `scripts/loadtest/probe.py`: sinchronizacijos 100 tūkst. trukmė; kortelė su 18 blokų
  (1–3 s vėlavimas). A/B su `main` (K13).

### Etapas 2 — paslaugos, suvestinė, eksportas, rolės

#### E2-01. Paslaugų faktai · L · E1-01 · RI T08 + K12 · Q4, Q7
- `ServiceType`, `ServiceRecord` (RI FR-08.2) + `subject_source`, `subject_external_id`
  (indeksuotas); FK `person` / `company` null, kol kortelės nėra.
- Sinchronizacija `entity="service"` ir `"service_type"`; prijungimo praėjimas po asmenų
  ir įmonių porcijos (užpildo FK pagal `subject_external_id`).
- `service_records_retention_months` (36) → `apply_retention`; `privacy.py` eksportas ir ištrynimas.
- Nustatymai → Paslaugos (jei šaltinis neteikia klasifikatoriaus).
- `seed.py` — ~3 faktai asmeniui per metus.
- **Priėmimas:** 2,4 mln. faktų; faktai be kortelės saugomi ir vėliau prijungiami.

#### E2-02. Kortelės blokas „Neseniai suteiktos paslaugos“ · S · E2-01, E0-06 · RI FR-08.5
- Blokas iš DB per E0-06 kontraktą (ne gyvai). **Priėmimas:** ≤ 0,2 s.

#### E2-03. Filtras „gavo / negavo paslaugą“ · M · E2-01 · RI T10
- `filters.py`: `pk IN (SELECT person_id FROM … WHERE …)` / `NOT IN`; `SavedFilter`;
  stulpelis „Paskutinė paslauga“.
- **Priėmimas:** 800 tūkst. bazėje ≤ 1,5 s.

#### E2-04. Eksportas pagal filtrą, riba, teisė · L · be priklausomybių · RI T11 + K9 · Q2
- `contacts_export` / `companies_export`: pažymėtos → jos; kitaip — `filters.py` rezultatas
  (tas pats kodas kaip sąrašas). Viena funkcija `export_queryset(request, scope)`.
- `SystemSettings.export_row_limit` (500); teisė `can_export_unlimited`.
- Riba ir auditas — ir `analytics_views.py:302`.
- `AuditLog.detail`: filtras (be 11 skaitmenų sekų), stulpeliai, eilutės, šaltinis.
- `StreamingHttpResponse` > 5000 eilučių; `.iterator(chunk_size=2000)`.
- **Testai:** filtras taikomas; riba; teisė; žurnalas; 100 tūkst. — atmintis < 200 MB.

#### E2-05. Paslaugų suvestinė · L · E2-01, E2-03, E2-04 · RI T09
- Analitika → Paslaugos (`analytics_views.py`), `can_view_service_analytics`.
- Filtrai URL'e; KPI (gavėjai, suteikimai, palyginimas); lentelė; `charts.stacked_bars`;
  skaičius → sąrašas (50/psl.); eksportas per E2-04; „Atidaryti kaip sąrašą“ → E2-03 filtras.
- Matomumas per `EXISTS` į `visible_people` / `visible_companies`.
- **Priėmimas:** skaičiai = tiesioginė SQL; sąrašas ir eksportas sutampa.

#### E2-06. Rolių profiliai · L · S2, E0-04 · RI T12 (pataisyta K2) · Q8
- `RoleProfile`, `UserProfile.role_profile`, `DirectoryGroupMapping.role_profile`.
- `has_capability()` — profilis prieš rolę; matomumas — pagal `base_role` ir S2
  (įskaitant „savo aktyvūs“ iš `RecordAccess`).
- Duomenų migracija — trys profiliai pagal S2.
- **Testai:** kiekvienam profiliui leidžiami ir draudžiami veiksmai (UI ir serveris);
  AD grupė priskiria profilį.

#### E2-07. Žyma „Nesiųsti apklausų“ · M · E2-04 · RI T13 · Q3
- Pradėti tik po DAP atsakymo Q3.

#### E2-08. Našumo regresija · M · E2-05 · RI T21
- `seed.py` 5 mln. `ServiceRecord`, 200 tipų; `probe.py` — suvestinė, sąrašas, filtras.
  Rezultatai — `docs/REGITRA-CRM-INTEGRACIJA.md` §3.

### Etapas 3 — skambučių centras

#### E3-01. Veiklos išplėtimas · L · E0-08 · RI T14 FR-14.1, 14.2, 14.6, 14.7 + K11
- Migracijos: `occurred_at` nullable → užpildymas porcijomis (`RunPython`, po 50 tūkst.) →
  `NOT NULL`; `source`, `external_id` + dalinis unikalumas; indeksai `AddIndexConcurrently`.
- Rikiavimas pagal `occurred_at`: `_feed_context`, analitika, API, `reporting` rodiniai (nauja migracija).
- Išorinės veiklos neredaguojamos / netrinamos (serveris ir UI).
- **Priėmimas:** 2,4 mln. migracija < 5 min. be lentelės užrakto; esami duomenys rodomi taip pat.

#### E3-02. Skambučio duomenys · M · E3-01, E3-03 · RI FR-14.3, 14.5 · Q5
- `CallDetails`; laiko juostos atvaizdas; `can_view_call_recordings`.

#### E3-03. Skambučių temos · M · E3-01 · RI T15
- `CallTopic`, `PUT /api/v1/call-topics`, nežinoma tema, Nustatymai → Skambučių temos.

#### E3-04. Paslaugų paskyros API raktams · M · E2-06 · K5, K10
- `ApiToken.acts_as` (FK į sisteminį naudotoją, null = kūrėjas); migracija sukuria
  neaktyvų „Skambučių centras“ (`set_unusable_password`, negali prisijungti), jo profilis —
  tik `calls`, `call-topics`, kortelės paieška; be `can_view_personal_code`.
- `ApiToken.rate_limit`; rotacijos procedūra `docs/INTEGRACIJOS.md`.
- **Testai:** raktas su `acts_as` negauna kūrėjo teisių; riba per raktą.

#### E3-05. `POST /api/v1/calls` ir automatinis asmens sukūrimas · L · E3-02, E3-03, E3-04 · RI T16, T17
- Kontraktas RI FR-16.1–16.5; `Person.created_via`; prijungimas sinchronizacijoje (FR-17.2).
- Pagal S2: skambutis suteikia `RecordAccess` operatoriui (pagal `agent.id` → naudotojas),
  pagrindas „Kliento kreipimasis“.
- **Testai (RI):** patvirtinta / ne / pakartota / nauja tema / įmonė / klaidingi duomenys;
  asmens kodas nepatenka į jokį žurnalą (tikrinama žurnalų išvestis).

#### E3-06. `calls/pop` ir tapatybės juosta · M · E3-05 · RI T18 FR-18.1–18.4
- `CallPop` modelis (token, 2 val.), juosta žalia / geltona; pagal S2 — prieigos suteikimas.

#### E3-07. Mygtukas „Perskambinti“ · S · be priklausomybių · RI FR-18.5
- Kortelės antraštėje; `Reminder(kind=call)` (`KIND_CALL` jau yra); greiti laikai;
  tekstas iš paskutinio skambučio temos (kai bus E3-02; iki tol — tuščias).

#### E3-08. Bandomasis skambučių centras ir kontrakto dokumentas · M · E3-05 · RI FR-16.7, 16.8
- `scripts/fake_call_center.py`; OpenAPI aprašas (`docs/api/openapi.yaml` — dabar jo nėra);
  `docs/INTEGRACIJOS.md` skyrius „Skambučių centras“.

### Etapas 4 — DocLogix

#### E4-01. Raštų blokas · L · E0-06, E0-08 · RI T19
- `contacts/documents.py` (`DocumentSource`), blokas pirmas viduriniame stulpelyje,
  `can_view_documents`, `scripts/fake_doclogix_api.py` (su bendravardžiais).

#### E4-02. Susiejimas „pasiūlyti → patvirtinti“ · M · E4-01 · RI T20
- Normalizavimas (teisinė forma, kabutės, diakritikai), iki 10 kandidatų, `ExternalLink(method="manual")`,
  atsiejimas su `data-confirm`, auditas.

### Etapas 5 — tikri prijungimai (laukia API)

| ID | Darbas | Reikia |
|---|---|---|
| I1 | `OrdsChangeSource` ir 18 loader'ių — tikri endpoint'ai ir laukai; `SOURCE_OWNED_FIELDS` sąrašas | Regitros API aprašas, testinė aplinka, Q6, Q7 |
| I2 | API raktas platformai, `rate_limit`, platformos pusės kvietimai | Platformos pasirinkimas |
| I3 | Tikras `DocumentSource` | DocLogix API prieiga |

---

## 6. Pasirengimas pradėti

| Ką | Būsena |
|---|---|
| Aplinka (`.venv`, `release-check.sh`, `security-check.sh`) | Veikia, abu žali (2026-10-30) |
| Užduotys be sprendimų: E0-01, E0-08, E2-04, E3-07 | Galima pradėti iškart |
| Etapas 0 (E0-02…E0-07) | Laukia S1 ir S3 |
| E2-06, E3-05, E3-06 | Laukia S2 |
| E2-01 | Q4 ir Q7 gali pakeisti laukus; pradėti galima su numatytomis reikšmėmis |
| E2-07 | Laukia Q3 (DAP) |

Rekomenduojama pradžia: **E0-01 → E0-08 → E2-04 → E3-07**, lygiagrečiai gaunant
S1–S3 atsakymus.

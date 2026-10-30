# Sisteminiai reikalavimai: CRM paruošimas integracijoms

Būsena: **suderinta su užsakovu 2026-10-30** (verslo analizės interviu).
Skirta programuotojams. Kiekviena užduotis (`T01`…`T21`) — atskiras, savarankiškai
įgyvendinamas ir testuojamas pakeitimas pagal `CLAUDE.md` taisykles.

Tikslas — **dabar, be jokių realių integracijų**, paruošti CRM taip, kad
prijungiant Regitros klientų DB, skambučių centrą ir DocLogix liktų parašyti tik
adapterį (HTTP klientą ir laukų susiejimą). Visa kita — modeliai, sąsaja, teisės,
auditas, foniniai darbai, API kontraktai, bandomieji serveriai — padaroma iš anksto.

---

## 1. Kontekstas

### 1.1 Naudotojų grupės

| Grupė | Ką daro CRM | Ko reikia |
|---|---|---|
| **KAC** (Klientų aptarnavimo centras, skambučių centras) | Skambučio metu atsidaro kortelę, žiūri istoriją ir Regitros duomenis; kartais susikuria priminimą perskambinti | Greita kortelė, matyti, ar tapatybė patvirtinta; skambučiai automatiškai istorijoje |
| **Klientų patirties specialistai** | Žiūri asmens / įmonės istoriją, paslaugas, SMS; filtruoja ir eksportuoja sąrašus apklausoms, analizei | Paslaugų suvestinė pagal laikotarpį, filtrai pagal paslaugą, eksportas be ribos |
| **Raštų (dokumentų valdymo) komanda** | Tikrina, kokie raštai asmeniui / įmonei siųsti ir gauti | DocLogix raštų sąrašas kortelėje su nuoroda; procesas lieka DocLogix |

### 1.2 Suderinti verslo sprendimai

1. **Prioritetai:** (1) Regitros klientų DB sinchronizacija ir duomenys kortelėje →
   (2) paslaugų suvestinė ir eksportas → (3) skambučių centras → (4) DocLogix.
2. **Skambučių platforma keisis** (Genesys → Genesys Cloud arba kitas sprendimas):
   CRM pusė turi būti **nepriklausoma nuo platformos** — CRM apibrėžia savo API kontraktą.
3. **Į CRM patenka tik patvirtintos tapatybės skambučiai** (Smart-ID / Mobile-ID
   skambučio metu). Neidentifikuoti skambučiai lieka skambučių platformoje.
4. **Kiekvienas patvirtintas skambutis registruojamas automatiškai**, operatorius nesprendžia.
5. **Operatorius gali atidaryti kortelę ir nepatvirtinus tapatybės**; ką atskleisti,
   lemia instrukcija, ne sistema — bet CRM turi aiškiai rodyti patvirtinimo būseną.
6. **Skambučių temos** gyvena skambučių platformoje; CRM jas perima, savo sąrašo nekuria.
7. **Skambučių statistika** (kreipiniai pagal temą, operatorių apkrova) — skambučių
   platformos ataskaitose, ne CRM.
8. **Paslaugų suvestinės šaltinis — Regitros DB „suteiktos paslaugos“**, ne skambučių
   centras (tik taip duomenys pilni: padalinys, e. paslaugos, telefonas). Paslaugos
   saugomos CRM kaip faktai su data, kad veiktų filtrai ir laikotarpiai.
9. **Kiti Regitros duomenys** (transporto priemonės, numeriai, įgaliojimai, SMS ir kt.)
   rodomi gyvai ir CRM nesaugomi.
10. **Patvirtintas asmuo, kurio CRM nėra**, sukuriamas automatiškai; nepatvirtintas — ne.
11. **Eksportas be patvirtinimo mechanizmo:** valdomas rolių teisėmis — riba eilutėms
    ir atskira teisė eksportuoti be ribos. Kiekvienas eksportas — žurnale.
12. **DocLogix neturi asmens / įmonės kodo lauko** — susiejama pagal pavadinimą,
    principu „sistema pasiūlo, žmogus patvirtina“, patvirtinta jungtis įsimenama.
13. **Raštai:** tik sąrašas (data, numeris, tema, kryptis, būsena, nuoroda į DocLogix);
    terminų, priminimų ir dokumento peržiūros CRM nereikia.
14. **Įmonė gali būti ir klientas, ir partneris** — sprendžiama esamomis kategorijomis
    ir žymomis, naujos funkcijos nereikia.

---

## 2. Dabartinė būsena (patikrinta kode, `main` b26d457, `regitra` 09d5e0e)

| Sritis | Yra | Trūksta |
|---|---|---|
| Asmens identifikatoriai | `Person.personal_code_*` (šifruotas + `personal_code_hash`), `external_source` + `external_id` (unikalūs), `synced_at` | — |
| Įmonės identifikatoriai | `Company.company_code`, `vat_code` (indeksuoti) | `external_source`, `external_id`, `synced_at` |
| Didelis įkėlimas | `bulk_import.py` + `import_people` — **tik asmenys, tik CSV** | Įmonės, asmens–įmonės ryšiai, traukimas iš API pokyčiais, sinchronizacijos būsena |
| Regitros duomenys kortelėje | `main`: `contacts/regitra.py` — 3 rūšys (paslaugos, vizitai, prašymai) gyvai iš ORDS, `scripts/fake_regitra_api.py`. `regitra` šaka: `contacts/record_blocks.py` — 18 tuščių blokų, `register_block()` jungtis, matomumas pagal rolę (`RolePermissions.blocks`) | Abu keliai išsiskyrę; blokų `loader` kviečiamas **sinchroniškai** renderinant kortelę (18 gyvų užklausų iš eilės = kortelės laikas) |
| Šakos | `regitra` šaka **55 commit'ais atsilikusi** nuo `main` (paskutinis pavijimas 2026-09-23) | Pavijimas |
| Veiklos (istorija) | `Activity`: tipas (note/call/email/meeting/task), tekstas, `created_by`, `message_id` (IMAP dedup) | Įvykio laikas (`occurred_at`), šaltinis, išorinis ID (idempotentiškumas), skambučio duomenys, tema |
| API | `/api/v1/`: contacts, contacts/lookup, companies, activities (GET/POST), reminders; raktai `read` / `read_write` | Skambučio priėmimo endpoint'as, temų klasifikatorius |
| Eksportas | Teisė `can_export`; auditas: kas, kada, failas, eilučių skaičius | Riba; teisė be ribos; filtras ir stulpeliai žurnale. Eksportas iš sąrašo — tik pažymėtos eilutės, `GET` — **visa matoma bazė**, aktyvus filtras neįvertinamas |
| Rolės | 5 fiksuotos rolės + teisių lentelė rolei | Profiliai KAC / specialistams / raštams. „Tik savi įrašai“ pagal nutylėjimą turi `can_delete` ir `can_export` |
| Našumas 800 tūkst. | Kortelė 0,75 s, paieška 0,8 s, asmens kodu 0,5 s, analitika 2,7 s | Paslaugų faktų (milijonai eilučių) ir asinchroninių blokų matavimas |
| Sutikimai | Nėra | Žyma „Nesiųsti apklausų“ |

---

## 3. Architektūros principai (galioja visoms užduotims)

**A1. Bendrinis CRM ir Regitros sluoksnis.** Laikomasi `docs/REGITRA-INTEGRACIJA.md`
(`regitra` šaka) principo: bendrinis CRM turi **generinius mechanizmus**
(blokų jungtis, išorinių ID susiejimas, sinchronizacijos karkasas, paslaugų faktai,
skambučio įrašo API, dokumentų blokas). Regitrai specifiški dalykai — blokų sąrašas,
ORDS laukų susiejimas, DocLogix adapteris — Regitros sluoksnyje (programėlė
`regitra`, įjungiama `CRM_EXTRA_APPS`). Bendrinis CRM niekur neimportuoja `regitra`.

**A2. Adapteris + bandomasis serveris.** Kiekviena integracija turi:
- Python sąsają (`Protocol`), nuo kurios priklauso CRM logika;
- realų adapterį (rašomas, kai bus API aprašas);
- **bandomąjį serverį** `scripts/fake_<sistema>_api.py` (kaip `fake_regitra_api.py`),
  kuris grąžina tikėtino formato duomenis — lokaliai, CI ir staging.
Prijungimas = realaus adapterio parašymas + `.env` reikšmės. Jokių kitų pakeitimų.

**A3. Konfigūracija.** Kiekvienai integracijai: `CRM_<SISTEMA>_API_URL`, autentifikacija,
`..._TIMEOUT_SECONDS`. Tuščias URL = integracija išjungta, sąsaja rodo
„neprijungta“, niekas nelūžta. Nauji kintamieji — į `.env.example` ir `docs/DEPLOYMENT.md`.

**A4. Aplinkų izoliacija.** Staging (`CRM_ENVIRONMENT≠production`) jungiasi tik prie
išorinių sistemų **testinių** aplinkų (atskiri URL `.env`). Išeinantys siuntimai, jei
atsirastų, staging — išjungti kaip `integrations.py`.

**A5. Asmens kodas** niekada nepatenka į URL, žurnalus, audito tekstą, klaidų
pranešimus, webhook'us (kaip dabar `identity.py`). Susiejimas — per `personal_code_hash`.

**A6. Atsparumas.** Išorinė sistema nepasiekiama → atitinkamas blokas rodo
„<Sistema> šiuo metu nepasiekiama“, likusi kortelė veikia. Laiko riba kiekvienai
užklausai. Foniniai darbai kartoja su atidėjimu, klaidos matomos `jobs.py`
(Nustatymai → Sistemos būklė, `/health/jobs`, `/metrics`).

**A7. Užklausos DB, ne Python cikle** (`CLAUDE.md`, `docs/ORACLE.md`): filtrai —
`pk IN (SELECT …)`, be `JOIN` + `DISTINCT`; vengti `.distinct()` / `annotate(Count)`
ant modelių su `TextField`.

**A8. Užbaigtumo apibrėžimas (kiekvienai užduočiai):** testai `tests/`;
`release-check.sh` ir `security-check.sh` žali; patikra naršyklėje LT/EN,
desktop ir mobilus; vertimai `locale/en`; `templates/settings/documentation.html`;
naujas modelis / laukas — klasifikuotas `contacts/data_dictionary.py` ir
pergeneruotas `docs/paketas/04-duomenu-zodynas.md`; `CLAUDE.md` „Struktūra“, jei
atsirado naujas modulis.

---

## 4. Užduočių apžvalga

Žymėjimas: **Dabar** — galima pilnai padaryti be integracijų;
**Dalinai** — CRM pusė dabar, prijungimas vėliau; **Laukia** — reikia išorinės sistemos API.

| ID | Užduotis | Etapas | Galima | Priklauso nuo |
|---|---|---|---|---|
| T01 | `regitra` šakos pavijimas ir blokų jungties perkėlimas į `main` | 0 | Dabar | — |
| T02 | Asinchroninis registrų blokų krovimas | 0 | Dabar | T01 |
| T03 | Išorinių identifikatorių modelis | 0 | Dabar | — |
| T04 | Sinchronizacijos karkasas | 1 | Dabar | T03 |
| T05 | Įmonių ir ryšių sinchronizacija | 1 | Dabar | T04 |
| T06 | Šaltinio valdomi laukai kortelėje | 1 | Dabar | T04 |
| T07 | ORDS klientas ir Regitros blokų loader'iai | 1 | Dalinai | T01, T02 |
| T08 | Paslaugų klasifikatorius ir paslaugų faktai | 1 | Dabar | T04 |
| T09 | Paslaugų suvestinė | 2 | Dabar | T08 |
| T10 | Sąrašų filtras „gavo paslaugą“ | 2 | Dabar | T08 |
| T11 | Eksportas: aktyvus filtras, riba, teisė, auditas | 2 | Dabar | — |
| T12 | Rolių profiliai trims grupėms | 2 | Dabar | — |
| T13 | Žyma „Nesiųsti apklausų“ | 2 | Dabar (laukia DAP sprendimo) | T11 |
| T14 | Veiklos išplėtimas išoriniams įvykiams ir skambučio duomenims | 3 | Dabar | T03 |
| T15 | Skambučių temų klasifikatorius | 3 | Dabar | T14 |
| T16 | Skambučio įrašo priėmimo API | 3 | Dalinai | T14, T15 |
| T17 | Automatinis asmens sukūrimas iš patvirtinto skambučio | 3 | Dabar | T16 |
| T18 | Kortelė iš skambučio: tapatybės žyma ir „Perskambinti“ | 3 | Dalinai | T16 |
| T19 | Raštų blokas su dokumentų šaltinio adapteriu | 4 | Dalinai | T02, T03 |
| T20 | Raštų susiejimas „pasiūlyti → patvirtinti“ | 4 | Dalinai | T19 |
| T21 | Našumo regresija su paslaugų faktais ir blokais | 1–2 | Dabar | T02, T08, T09 |
| I1 | Realus Regitros ORDS adapteris (pokyčiai, blokai) | 1 | Laukia | Regitros API aprašas |
| I2 | Skambučių platformos pusės integracija | 3 | Laukia | Platformos pasirinkimas |
| I3 | Realus DocLogix adapteris | 4 | Laukia | DocLogix API prieiga |

Rekomenduojama tvarka: T01 → T03 → T02 → T04 → T05/T06/T08 → T07 → T11 → T09/T10 →
T12 → T13 → T21 → T14 → T15 → T16 → T17 → T18 → T19 → T20.

---

## 5. Užduotys

### T01. `regitra` šakos pavijimas ir blokų jungties perkėlimas į `main`

**Kodėl.** Šiuo metu du nesuderinti keliai: `main` turi `contacts/regitra.py`
(3 rūšys gyvai), `regitra` šaka — `record_blocks.py` (18 tuščių blokų, be duomenų).
Šaka 55 commit'ais atsilikusi; kiekvienas naujas darbas daromas dukart.

**Reikalavimai.**
1. FR-01.1 `contacts/record_blocks.py` (jungtis: `register_block`, `block`,
   `block_keys`, `record_blocks`) perkeliamas į `main` **be Regitros placeholder'ių
   sąrašo** — bendrinis CRM žino tik mechanizmą.
2. FR-01.2 Blokų matomumas pagal rolę (`RolePermissions.blocks`, Nustatymai →
   Registrų blokai, `can_see_block`) perkeliamas kartu.
3. FR-01.3 Kortelės šablonas rodo vidurinį stulpelį tik jei yra bent vienas
   registruotas ir naudotojui matomas blokas; kitaip išdėstymas kaip dabar.
4. FR-01.4 18 placeholder'ių ir `contacts/regitra.py` logika (ORDS klientas, 3 rūšys)
   perkeliami į Regitros sluoksnį (`regitra` programėlė). `main` lieka be Regitrai
   specifinio kodo. **Sprendimas reikalingas iš savininko:** ar Regitros programėlė
   gyvena atskirame repozitorijuje (kaip numato `REGITRA-INTEGRACIJA.md`), ar
   `regitra/` kataloge šiame repozitorijuje, įjungiama `CRM_EXTRA_APPS`.
5. FR-01.5 `regitra` šaka pavejama iki `main`; `docs/REGITRA-SAKA.md` atnaujinamas.
6. FR-01.6 Esama teisė `can_view_regitra` pakeičiama blokų matomumu (vienas
   mechanizmas), duomenų migracija perkelia esamas reikšmes.

**Priėmimas.** Be `regitra` programėlės kortelė atrodo kaip dabar `main`. Su ja —
18 blokų, kaip staging ekrano nuotraukoje. Visi esami testai žali abiejose konfigūracijose.

---

### T02. Asinchroninis registrų blokų krovimas

**Kodėl.** `record_blocks()` kviečia kiekvieno bloko `loader` sinchroniškai. Su
gyvomis užklausomis kortelės laikas = visų blokų laikų suma; vienas lėtas registras
sulėtina visą kortelę. KAC operatoriui kortelė turi atsidaryti iš karto.

**Reikalavimai.**
1. FR-02.1 Kortelė renderinama be blokų turinio: kiekvienas blokas — antraštė ir
   krovimo būsena (skeleton).
2. FR-02.2 Naujas maršrutas `GET /contacts/<pk>/blocks/<key>/` ir
   `GET /companies/<pk>/blocks/<key>/` grąžina vieno bloko HTML fragmentą. Tikrina:
   įrašo matomumą (`visible_people` / `visible_companies`), bloko matomumą rolei.
3. FR-02.3 JS (`static/js/` naujas arba esamas modulis, be įterptinių `on*=`, CSP nonce)
   krauna blokus lygiagrečiai; **suskleisti blokai nekraunami, kol neišskleisti**.
   Išskleidimo būsena įsimenama `UserProfile.layout_config`.
4. FR-02.4 Bloko laiko riba — `CRM_BLOCK_TIMEOUT_SECONDS` (numatytai 5). Viršijus —
   būsena „Nepavyko gauti duomenų laiku“ ir mygtukas „Bandyti dar kartą“.
5. FR-02.5 Loader'is gali kelti `BlockUnavailable(message)` → rodomas pranešimas;
   bet kokia kita išimtis → bendras pranešimas, žurnale `request_id`, be asmens duomenų.
6. FR-02.6 Bloko kontraktas: `loader(record, offset=0) -> {"items": [...], "has_more": bool,
   "columns": [...]}`; „Rodyti daugiau“ kviečia tą patį maršrutą su `?offset=`.
7. FR-02.7 Būsenos: krauna / tuščia („Duomenų nėra“) / klaida / neprijungta
   (integracija išjungta) / duomenys.
8. FR-02.8 Gyvai gauti duomenys **nesaugomi** DB ir serverio talpykloje.

**Priėmimas.** Bandomasis loader'is su 3 s vėlavimu nesulėtina kortelės (kortelė
≤ 1 s 800 tūkst. bazėje). Loader'is su klaida neparodo 500. Testai: matomumas,
laiko riba, puslapiavimas, suskleistas blokas nekraunamas.

---

### T03. Išorinių identifikatorių modelis

**Kodėl.** Reikės susieti tą patį asmenį / įmonę su Regitros kliento ID, skambučių
platformos ID, DocLogix korespondento ID. `Company` neturi `external_*`, o antrinių
sistemų susiejimams vietos nėra.

**Reikalavimai.**
1. FR-03.1 `Company` gauna `external_source`, `external_id`, `synced_at` — simetriškai
   `Person`, su tokiu pat unikalumo apribojimu (`unique_company_external_id`).
2. FR-03.2 **Pagrindinis šaltinis** (Regitros klientų DB) — `external_source` /
   `external_id` pačiame įraše. **Antrinės sistemos** — naujas modelis `ExternalLink`:

   | Laukas | Tipas | Pastaba |
   |---|---|---|
   | `source` | char(32) | `doclogix`, `call_center`, … |
   | `external_id` | char(128) | ID toje sistemoje |
   | `person` / `company` | FK, null | lygiai vienas užpildytas (`CheckConstraint`) |
   | `method` | choice | `auto` (pagal kodą), `manual` (patvirtino žmogus) |
   | `linked_by` | FK User, null | kas susiejo |
   | `linked_at` | datetime | |
   | `label` | char(255) | pavadinimas išorinėje sistemoje (rodymui) |

   Unikalumas `(source, external_id)`: vienas išorinis ID — viena CRM kortelė.
3. FR-03.3 Paslaugų sluoksnis `contacts/external_ids.py`: `find_record(source, external_id)`,
   `link(record, source, external_id, method, user, label)`, `unlink(link, user)`.
   Kiekvienas `link` / `unlink` → `AuditLog` (be asmens kodo).
4. FR-03.4 Sujungiant dublikatus (`merging.py`) `ExternalLink` ir `external_*`
   perkeliami į paliekamą įrašą; konfliktas (abu turi skirtingą tos pačios sistemos ID)
   — sujungimas atmetamas su aiškiu paaiškinimu.
5. FR-03.5 Kortelės „Tapatybė“ skiltyje — sąrašas „Susieta su: Regitra (ID …),
   DocLogix (…)“; matoma tik su `can_view_personal_code` arba administratoriui.
6. FR-03.6 API asmens / įmonės objekte — `external_source`, `external_id`
   (be `ExternalLink` turinio).

**Priėmimas.** Migracija; testai: unikalumas, sujungimas, auditas, API laukai.

---

### T04. Sinchronizacijos karkasas

**Kodėl.** Asmenys ir įmonės turi būti periodiškai atnaujinami iš Regitros klientų DB
(prielaida — tik skaitymo ORDS REST su „pakitę nuo X“; push nebus). Dabar yra tik
vienkartinis CSV importas.

**Reikalavimai.**
1. FR-04.1 Sąsaja `contacts/sync/source.py`:
   ```python
   class ChangeSource(Protocol):
       name: str                       # "regitra"
       def changes(self, entity: str, cursor: str | None, limit: int) -> ChangeBatch: ...
   # ChangeBatch: items: list[dict], next_cursor: str | None, has_more: bool
   # entity: "person" | "company" | "person_company" | "service"
   ```
   Kiekvienas `item` turi `external_id`, `op` (`upsert` | `delete`), `changed_at` ir laukus.
2. FR-04.2 Modelis `SyncState`: `source`, `entity`, `cursor`, `last_started_at`,
   `last_success_at`, `last_error` (be asmens duomenų), `created`, `updated`,
   `unchanged`, `failed` (paskutinio paleidimo skaitikliai). Unikalus `(source, entity)`.
3. FR-04.3 Foninis darbas `sync_external` (`management/commands/sync_external.py`,
   registruojamas `jobs.py`, `crm-worker` ciklas, Helm CronJob): kiekvienam
   `entity` traukia porcijomis (`CRM_SYNC_BATCH_SIZE`, numatytai 1000), kiekviena
   porcija — viena transakcija; žymeklis išsaugomas tik po sėkmingos porcijos.
   Pakartotinis paleidimas po lūžio tęsia nuo paskutinio žymeklio.
4. FR-04.4 Asmenų `upsert` naudoja esamą `bulk_import` logiką (raktas
   `(external_source, external_id)`, nepakitęs kodas neperšifruojamas). Jei pagal
   `external_id` nerasta, bet randamas `personal_code_hash` (pvz., sukurtas iš
   skambučio, T17) — **prijungiama prie esamos kortelės**, ne kuriama nauja.
5. FR-04.5 `delete` iš šaltinio → kortelė **archyvuojama** (`deleted_at`), ne trinama;
   žurnale `AuditLog` su šaltiniu „Sinchronizacija: Regitra“. CRM istorija išlieka.
6. FR-04.6 Sinchronizacijos veiksmai įrašomi `AuditLog` suvestine (vienas įrašas
   porcijai: kiek sukurta / atnaujinta / archyvuota), ne kiekvienam įrašui.
7. FR-04.7 Rankinis paleidimas: `manage.py sync_external --source regitra --entity person
   [--full]` (`--full` — nuo nulio, žymeklis ignoruojamas).
8. FR-04.8 Bandomasis šaltinis: `scripts/fake_regitra_api.py` papildomas
   `GET /persons/changes?since=&limit=`, `/companies/changes`, `/person-companies/changes`,
   `/services/changes` (ORDS kolekcijos formatas). Generuoja deterministinius duomenis,
   įskaitant pakeitimus ir ištrynimus.
9. FR-04.9 Nustatymai → Sistemos būklė: kiekvienam `(source, entity)` — paskutinis
   sėkmingas paleidimas, atsilikimas, skaitikliai, paskutinė klaida.
10. FR-04.10 Staging: šaltinio URL — Regitros testinės aplinkos; jei nenustatytas,
    darbas praleidžiamas su būsena „neprijungta“, ne klaida.

**Priėmimas.** Su bandomuoju serveriu: pradinis įkėlimas 100 tūkst. asmenų;
pakartotinis be pokyčių — 0 atnaujinimų; pakeitimas / ištrynimas atsispindi;
nutrauktas darbas tęsiasi. Testai kiekvienam `op`, prijungimui pagal kodą, žymekliui.

---

### T05. Įmonių ir asmens–įmonės ryšių sinchronizacija

**Reikalavimai.**
1. FR-05.1 `entity="company"`: raktas `(external_source, external_id)`; laukai
   pavadinimas, `company_code`, `vat_code`, adresas, telefonas, el. paštas. Jei pagal
   `external_id` nerasta, bet randamas tas pats `company_code` — prijungiama.
2. FR-05.2 `entity="person_company"`: ryšys asmuo ↔ įmonė (`PersonCompanyLink`, esamas
   laukas `role` — pvz., „atstovas“, „vadovas“). Naujas laukas `PersonCompanyLink.source`
   (numatytai `crm`); šaltinio sukurti ryšiai žymimi `source="regitra"`. CRM naudotojų
   sukurti ryšiai sinchronizacijos neliečiami.
3. FR-05.3 `manage.py import_companies` — CSV porcijomis (analogiškai `import_people`),
   pradiniam įkėlimui be API.
4. FR-05.4 Įmonių paieška pagal `company_code` (globali paieška ir `company_lookup`).

**Priėmimas.** 200 tūkst. įmonių įkėlimas su bandomuoju serveriu; ryšiai matomi
kortelėse; rankiniai ryšiai išlieka po sinchronizacijos.

---

### T06. Šaltinio valdomi laukai kortelėje

**Kodėl.** Jei CRM naudotojas pakeis vardą ar telefoną, kurį valdo Regitros DB,
kitas sinchronizavimas jį perrašys — naudotojas nesupras, kodėl.

**Reikalavimai.**
1. FR-06.1 Konfigūracija, kurie laukai priklauso šaltiniui:
   `SOURCE_OWNED_FIELDS = {"regitra": {"person": [...], "company": [...]}}`
   (Regitros sluoksnis registruoja; bendrinis CRM — tuščia).
2. FR-06.2 Įrašui su `external_source`, šie laukai kortelėje ir formoje **tik skaitomi**:
   be inline redagavimo (`detail_editing.py`, `inline_views.py`), su ženkleliu
   „Iš Regitros“ ir paaiškinimu „Keičiama Regitros sistemose; CRM atnaujins automatiškai“.
3. FR-06.3 Serverio pusė atmeta tokių laukų keitimą (formos, inline, API, masiniai
   veiksmai, importas) — ne tik paslepia sąsajoje.
4. FR-06.4 Kortelėje rodoma „Sinchronizuota: prieš 2 val.“ (`synced_at`).
5. FR-06.5 CRM laukai (žymos, kategorijos, atsakingi, dinaminiai laukai, istorija)
   lieka redaguojami.
6. FR-06.6 Kontaktai: šaltinio telefonai / el. paštai žymimi kaip šaltinio, naudotojas
   gali pridėti savo papildomus (jie sinchronizacijos neliečiami).

**Priėmimas.** Testai: inline, forma, API `PATCH`, masinis veiksmas — šaltinio laukas
nekeičiamas; CRM laukas keičiamas.

---

### T07. ORDS klientas ir Regitros blokų loader'iai

**Reikalavimai (dabar).**
1. FR-07.1 Regitros sluoksnyje — vienas HTTP klientas ORDS (perkeliamas ir
   apibendrinamas iš `contacts/regitra.py`): ORDS kolekcijos formatas (`items`,
   `hasMore`, `offset`, `limit`), laiko riba, `X-Request-ID` perdavimas, 1 pakartojimas
   tinklo klaidai, autentifikacija per `.env` (`CRM_REGITRA_API_*`; numatyti ORDS
   OAuth2 client credentials ir Basic).
2. FR-07.2 Kiekvienam iš 18 blokų — loader'is pagal T02 kontraktą ir stulpelių
   aprašas (`COLUMNS`), prijungtas prie bandomojo serverio. Laukai — hipotezė, kol nėra
   Regitros schemos; laikomi **viename** konfigūracijos faile, kad pakeitimas būtų
   vienoje vietoje.
3. FR-07.3 Blokas „Išsiųsti SMS“: data ir laikas, numeris (užmaskuotas, išskyrus
   paskutinius 3 skaitmenis), siuntėjo sistema, **pilnas tekstas** (išskleidžiamas),
   būsena (išsiųsta / pristatyta / nepavyko).
4. FR-07.4 Blokas „Neseniai suteiktos paslaugos“ skaito **vietinius paslaugų faktus**
   (T08), ne gyvai.
5. FR-07.5 `fake_regitra_api.py` papildomas visais 18 blokų (dabar — 3).

**Laukia (I1).** Realūs ORDS endpoint'ai, laukų pavadinimai, autentifikacija,
testinės aplinkos adresas.

**Priėmimas.** Su bandomuoju serveriu visi 18 blokų rodo duomenis asmens ir įmonės
kortelėse pagal rūšį; išjungus serverį — „Regitra šiuo metu nepasiekiama“.

---

### T08. Paslaugų klasifikatorius ir paslaugų faktai

**Kodėl.** Paslaugų suvestinei ir filtrams reikia saugomų faktų su data, kanalu ir
padaliniu. Dinaminis laukas netinka (viena reikšmė, be datos, EAV).

**Reikalavimai.**
1. FR-08.1 Modelis `ServiceType`: `code` (unikalus), `name`, `group` (pvz.,
   „Transporto priemonės“, „Vairuotojai“), `active`, `source`. Sinchronizuojamas
   (`entity="service_type"`) arba tvarkomas Nustatymai → Paslaugos, jei šaltinis
   klasifikatoriaus neteikia.
2. FR-08.2 Modelis `ServiceRecord`:

   | Laukas | Tipas | Pastaba |
   |---|---|---|
   | `person` / `company` | FK, null | lygiai vienas (`CheckConstraint`) |
   | `service_type` | FK | |
   | `occurred_on` | date | suteikimo data |
   | `channel` | choice | `branch` (padalinys), `online`, `phone`, `other` |
   | `office` | char(120) | padalinys, tuščias jei ne `branch` |
   | `source`, `source_id` | char | unikalus `(source, source_id)` — idempotentiškumas |
   | `synced_at` | datetime | |

   Be `TextField`. Indeksai: `(service_type, occurred_on)`, `(person, occurred_on)`,
   `(company, occurred_on)`, `(occurred_on)`.
3. FR-08.3 Sinchronizacija per T04 (`entity="service"`): `upsert` / `delete`; faktas
   be atitinkamos kortelės → kortelė ieškoma pagal išorinį ID; nerasta — faktas
   praleidžiamas ir skaičiuojamas `failed` su priežastimi, žymeklis juda toliau.
4. FR-08.4 Saugojimo terminas: `SystemSettings.service_records_retention_months`
   (numatytai 36); šalinama esamu `apply_retention` darbu.
5. FR-08.5 Kortelės blokas „Neseniai suteiktos paslaugos“ — 10 naujausių faktų iš DB,
   „Rodyti daugiau“.
6. FR-08.6 Duomenų subjekto eksportas (`privacy.py`) ir ištrynimas apima `ServiceRecord`.
7. FR-08.7 `data_dictionary.py` klasifikacija; jei reikia DWH — `reporting` rodinys
   nauja migracija (`docs/INTEGRACIJOS.md`).
8. FR-08.8 Bandomieji duomenys: `fake_regitra_api.py` `/services/changes` ir
   `scripts/loadtest/seed.py` — ~3 faktai asmeniui per metus.

**Priėmimas.** 2,4 mln. faktų įkėlimas; kortelės blokas ≤ 0,2 s; subjekto eksportas
juos turi.

---

### T09. Paslaugų suvestinė

**Vieta.** Analitika → **Paslaugos** (nauja skiltis `analytics_views.py`, kortelė
apžvalgoje su nuoroda). Teisė `can_view_service_analytics` (numatytai: vadovas,
administratorius; suteikiama specialistų profiliui T12).

**Reikalavimai.**
1. FR-09.1 Filtrai: laikotarpis (šis mėnuo, praėjęs mėnuo, ketvirtis, metai,
   pasirinktinis nuo–iki); paslauga (keli pasirinkimai, grupuoti pagal `group`,
   paieška); kanalas (keli); padalinys (keli); gavėjai — asmenys / įmonės / visi.
   Filtrų būsena URL parametruose (be asmens duomenų), kad nuorodą būtų galima siųsti.
2. FR-09.2 KPI juosta: unikalių gavėjų skaičius; suteikimų skaičius; palyginimas su
   ankstesniu tokio pat ilgio laikotarpiu (%).
3. FR-09.3 Lentelė pagal paslaugą: paslauga, gavėjų skaičius, suteikimų skaičius,
   dalis pagal kanalą. Rikiuojama.
4. FR-09.4 Grafikas: suteikimai pagal mėnesį (`charts.stacked_bars` pagal kanalą).
5. FR-09.5 **Kiekvienas skaičius paspaudžiamas** → gavėjų sąrašas (iššokantis langas
   kaip darbastalyje arba atskiras puslapis, 50 eilučių puslapyje): vardas / pavadinimas,
   kodas (įmonės — rodomas; asmens — užmaskuotas), paslauga, data, kanalas, nuoroda
   į kortelę.
6. FR-09.6 Sąraše mygtukas „Eksportuoti“ — pagal T11 taisykles (riba, teisė, auditas);
   eksporte — tie patys filtrai.
7. FR-09.7 Mygtukas „Atidaryti kaip kontaktų / įmonių sąrašą“ → sąrašas su T10 filtru
   (masiniams veiksmams: žymos, kategorijos, užduotys).
8. FR-09.8 Skaičiuojama DB: `COUNT(DISTINCT person_id)` ant `ServiceRecord` (be
   `TextField`), `GROUP BY service_type`. Matomumas: gavėjai filtruojami pagal naudotojo
   matomumą (`visible_people` / `visible_companies` per `EXISTS`).
9. FR-09.9 Našumas: ≤ 3 s su 5 mln. faktų, 12 mėn. laikotarpiu, visomis paslaugomis
   (T21). Jei neviršijama — be talpyklos; jei viršijama — `AnalyticsSnapshot` pagal
   mėnesį ir paslaugą.
10. FR-09.10 Suvestinė įtraukiama į asmeninį išdėstymą (`{% layoutblock %}`).

**Priėmimas.** Skaičiai sutampa su tiesiogine SQL užklausa bandomuosiuose duomenyse;
paspaudus skaičių sąraše tiek pat eilučių; eksporte tiek pat.

---

### T10. Sąrašų filtras „gavo paslaugą“

**Reikalavimai.**
1. FR-10.1 Kontaktų ir įmonių sąrašų filtrų skydelyje — grupė „Suteiktos paslaugos“:
   paslauga (keli), laikotarpis nuo–iki, kanalas (keli), padalinys.
2. FR-10.2 Įgyvendinimas `filters.py`: `pk IN (SELECT person_id FROM service_record
   WHERE …)` — be `JOIN` ir `DISTINCT`.
3. FR-10.3 Galima neigti: „**negavo** paslaugos X laikotarpiu“ (`NOT IN`).
4. FR-10.4 Filtras išsaugomas `SavedFilter`, veikia su masiniais veiksmais ir eksportu.
5. FR-10.5 Sąrašo stulpelis „Paskutinė paslauga“ (pavadinimas, data) — pasirenkamas.

**Priėmimas.** Testai filtrų kombinacijoms; 800 tūkst. bazėje ≤ 1,5 s.

---

### T11. Eksportas: aktyvus filtras, riba, teisė, auditas

**Kodėl.** Dabar eksportuojamos tik pažymėtos eilutės arba (per `GET`) visa matoma
bazė, aktyvus filtras neįvertinamas; ribos nėra; žurnale nėra, kas tiksliai išeksportuota.

**Reikalavimai.**
1. FR-11.1 Sąrašo mygtukas „Eksportuoti“: jei pažymėta eilučių — eksportuojamos jos;
   jei ne — eksportuojamas **dabartinis filtruotas sąrašas** (visi puslapiai). Visos
   bazės eksportas be filtro — tik su FR-11.3 teise.
2. FR-11.2 `SystemSettings.export_row_limit` (numatytai 500), keičiama Nustatymai →
   Bendri nustatymai.
3. FR-11.3 Nauja teisė `can_export_unlimited` („Eksportuoti be eilučių ribos“),
   numatytai išjungta visoms rolėms, išskyrus administratorių.
4. FR-11.4 Eksportas virš ribos be teisės → neatliekamas; pranešimas: „Rezultate
   12 340 eilučių, jūsų riba — 500. Susiaurinkite filtrą arba kreipkitės į
   administratorių dėl teisės eksportuoti be ribos.“
5. FR-11.5 `AuditLog` eksporto įraše papildomai: filtro parametrai (be asmens kodo ir
   laisvos paieškos teksto, jei jame 11 skaitmenų), stulpelių sąrašas, eilučių skaičius,
   šaltinis (kontaktų sąrašas / įmonių sąrašas / paslaugų suvestinė).
6. FR-11.6 Ta pati logika — visiems eksporto keliams: kontaktai, įmonės, paslaugų
   suvestinė, API sąrašų puslapiavimas lieka atskiras (raktai turi savo ribą).
7. FR-11.7 Eksportas > 5000 eilučių generuojamas srautu (`StreamingHttpResponse`),
   kad 800 tūkst. eilučių neužpildytų atminties.

**Priėmimas.** Testai: filtras taikomas; riba; teisė; žurnalo turinys; srautas su
100 tūkst. eilučių — atmintis < 200 MB.

---

### T12. Rolių profiliai trims grupėms

**Kodėl.** Rolės fiksuotos (5) ir teisės priskiriamos rolei. KAC operatoriui,
specialistui ir raštų komandai reikia skirtingų rinkinių; dabar „Tik savi įrašai“
pagal nutylėjimą gali ir trinti, ir eksportuoti.

**Reikalavimai.**
1. FR-12.1 Naujas modelis `RoleProfile`: `name`, `base_role` (viena iš esamų —
   lemia matomumą: visi / savi / tik skaitymas), `permissions` (JSON, kaip
   `RolePermissions`), `blocks` (matomi registrų blokai), `description`.
2. FR-12.2 `UserProfile.role_profile` (FK, null). Jei nustatytas — teisės imamos iš
   profilio, matomumas iš `base_role`; jei ne — kaip dabar.
3. FR-12.3 Katalogo grupių susiejimas (`DirectoryGroupMapping`, `directory.py`) gali
   priskirti profilį.
4. FR-12.4 Duomenų migracija sukuria 3 profilius (administratorius gali keisti):

   | Teisė | KAC operatorius | Klientų patirties specialistas | Raštų komanda |
   |---|---|---|---|
   | Bazinė rolė | Naudotojas (visi įrašai) | Naudotojas (visi įrašai) | Naudotojas (visi įrašai) |
   | Kurti pastabas, priminimus | taip | taip | taip |
   | `can_export` | ne | taip | ne |
   | `can_export_unlimited` | ne | taip | ne |
   | `can_view_service_analytics` | ne | taip | ne |
   | `can_delete` | ne | ne | ne |
   | `can_import`, `can_bulk_edit` | ne | taip | ne |
   | `can_view_personal_code` | taip | taip | ne |
   | `can_view_documents` (T19) | ne | taip | taip |
   | Registrų blokai | visi | visi | Prašymai, Sutartys, Atstovai |

5. FR-12.5 Nustatymai → Naudotojai: profilio pasirinkimas; Nustatymai → Rolės ir teisės:
   profilių sąrašas, kūrimas, kopijavimas.
6. FR-12.6 Rekomendacija (savininko sprendimas): rolės „Tik savi įrašai“ numatytąsias
   `can_delete` ir `can_export` pakeisti į `False` naujiems diegimams.

**Priėmimas.** Testai kiekvienam profiliui: leidžiami ir draudžiami veiksmai
(UI ir serveris); AD grupė priskiria profilį prisijungiant.

---

### T13. Žyma „Nesiųsti apklausų“

**Būsena.** Techniškai paruošiama dabar; ar ir kaip naudoti — **DAP sprendimas**
(ar organizacija turi sutikimų / prieštaravimų registrą).

**Reikalavimai.**
1. FR-13.1 `Person` ir `Company`: `survey_opt_out` (bool), `survey_opt_out_at`,
   `survey_opt_out_source` (`crm`, `regitra`, `api`).
2. FR-13.2 Kortelėje — perjungiklis „Nesiųsti apklausų“; pakeitimas → `AuditLog`.
3. FR-13.3 Sąrašo filtras ir stulpelis.
4. FR-13.4 Eksporto lange — pasirinkimas „Eksportas apklausai“: pažymėjus, žymą turintys
   įrašai **neįtraukiami** ir parodoma, kiek jų atmesta.
5. FR-13.5 Laukas įtraukiamas į `SOURCE_OWNED_FIELDS` galimybę: jei Regitros DB ateityje
   teiks sutikimus — sinchronizuojamas.
6. FR-13.6 API asmens / įmonės objekte — `survey_opt_out`.

---

### T14. Veiklos išplėtimas išoriniams įvykiams ir skambučio duomenims

**Kodėl.** `Activity` neturi įvykio laiko, šaltinio, išorinio ID ir skambučio laukų —
skambučio įrašą reikės priimti iš platformos su tikslia data ir be dublikatų.

**Reikalavimai.**
1. FR-14.1 `Activity` nauji laukai: `occurred_at` (datetime, numatytai = `created_at`;
   duomenų migracija užpildo esamiems), `source` (char(32), numatytai `crm`),
   `external_id` (char(128), tuščias). Dalinis unikalumas `(source, external_id)`, kai
   `external_id` ≠ "".
2. FR-14.2 Laiko juosta ir skaičiavimai rikiuojami pagal `occurred_at`
   (`views._feed_context`, analitika „Paskutinis bendravimas“).
3. FR-14.3 Naujas modelis `CallDetails` (vienas su vienu su `Activity`, tik
   `activity_type="call"`):

   | Laukas | Tipas |
   |---|---|
   | `direction` | `inbound` / `outbound` |
   | `duration_seconds` | int |
   | `agent_ref`, `agent_name` | char — operatorius platformoje |
   | `queue` | char — linija / eilė |
   | `topic` | FK `CallTopic` (T15), null |
   | `identity_verified` | bool |
   | `identity_method` | `smart_id` / `mobile_id` / `other` |
   | `summary` | text ≤ 4000 — santrauka / operatoriaus pastaba |
   | `recording_url`, `transcript_url` | URL (per `sanitizers.safe_url`); CRM įrašo ir transkripto nesaugo |

4. FR-14.4 Sisteminis naudotojas integracijoms: `Activity.created_by` — specialus
   neaktyvus naudotojas „Skambučių centras“ (sukuriamas migracija, negali prisijungti),
   kad istorijoje matytųsi šaltinis, o ne API rakto kūrėjas.
5. FR-14.5 Laiko juostoje skambučio įrašas rodo: kryptį, trukmę (mm:ss), temą,
   operatorių, ženklelį „Tapatybė patvirtinta (Smart-ID)“, santrauką, nuorodas į įrašą /
   transkriptą (tik jei naudotojas turi `can_view_call_recordings` — nauja teisė).
6. FR-14.6 Išorinio šaltinio veiklos **neredaguojamos ir netrinamos** CRM naudotojų
   (galima pridėti komentarą).
7. FR-14.7 Filtras kortelės laiko juostoje: šaltinis (CRM / skambučių centras / …).

**Priėmimas.** Migracija su 2,4 mln. veiklų < 5 min.; laiko juosta ir analitika
nepakitusios esamiems duomenims; testai unikalumui ir rodymui.

---

### T15. Skambučių temų klasifikatorius

**Reikalavimai.**
1. FR-15.1 Modelis `CallTopic`: `code` (unikalus), `name`, `parent` (FK į save — IVR
   tema → operatoriaus žymė), `active`, `source`.
2. FR-15.2 API `PUT /api/v1/call-topics` (raktas `read_write`): visas sąrašas
   `[{code, name, parent_code, active}]`; neperduotos temos pažymimos `active=False`
   (ne trinamos — istorija išlieka).
3. FR-15.3 Skambutis su nežinomu temos kodu → sukuriama `CallTopic(active=False,
   name="Nežinoma tema (<kodas>)")`, skambutis priimamas.
4. FR-15.4 Nustatymai → Skambučių temos: tik skaitomas sąrašas su šaltiniu ir
   paskutinio atnaujinimo laiku.
5. FR-15.5 Kortelės laiko juostos filtras pagal temą.

---

### T16. Skambučio įrašo priėmimo API

**Kodėl.** Platforma dar nepasirinkta, todėl CRM apibrėžia savo kontraktą; bet kuri
platforma (Genesys, Genesys Cloud, kita) jį kvies per savo integracijos įrankius.

**Reikalavimai.**
1. FR-16.1 `POST /api/v1/calls`, raktas `read_write`. Kūnas:
   ```json
   {
     "call_id": "GEN-2026-000123",
     "started_at": "2026-10-30T10:42:00+02:00",
     "duration_seconds": 312,
     "direction": "inbound",
     "queue": "Vairuotojai",
     "agent": {"id": "a.jonaitis", "name": "Agnė Jonaitienė"},
     "topics": ["DRIVER_LICENCE", "DRIVER_LICENCE.REPLACEMENT"],
     "identity": {"verified": true, "method": "smart_id",
                  "personal_code": "39001010000"},
     "caller": {"first_name": "Jonas", "last_name": "Jonaitis", "phone": "+37060000000"},
     "company_code": null,
     "summary": "Klausė dėl pažymėjimo keitimo terminų.",
     "recording_url": "https://…", "transcript_url": null
   }
   ```
2. FR-16.2 Taisyklės:
   - `identity.verified` ≠ `true` → `422 {"error": "identity_not_verified"}`, **niekas
     nesaugoma**, žurnale tik `call_id` ir priežastis.
   - Asmuo randamas pagal `personal_code_hash`; nerastas → T17.
   - `company_code` perduotas ir įmonė rasta → veikla susiejama ir su įmone
     (asmuo atstovavo įmonę).
   - Pakartotas `call_id` → `200` su esamu veiklos ID (idempotentiškumas,
     `(source="call_center", external_id=call_id)`); naujas → `201`.
   - Tema: paskutinis `topics` elementas → `CallDetails.topic`; visi — veiklos tekste.
   - `activity.text` = santrauka arba „Skambutis: <tema>“, jei santraukos nėra.
3. FR-16.3 Atsakymas: `{"activity_id", "person_id", "person_created": bool, "card_url"}`.
4. FR-16.4 Validacija: datos ISO 8601 su zona; `duration_seconds` 0–86400; URL —
   `safe_url`; nežinomi laukai ignoruojami; klaidos — `400` su lauko pavadinimu,
   **be asmens kodo reikšmės**.
5. FR-16.5 Auditas: `AuditLog.CREATE` su šaltiniu „API: skambučių centras“;
   `observability` — `crm.security` įvykis be asmens duomenų.
6. FR-16.6 Esamas rakto ribojimas (120 užkl./min) — konfigūruojamas šiam raktui
   (piko metu gali būti daugiau).
7. FR-16.7 `scripts/fake_call_center.py` — siunčia N atsitiktinių patvirtintų /
   nepatvirtintų skambučių į nurodytą CRM (lokaliai ir staging testams).
8. FR-16.8 Aprašas OpenAPI ir `docs/INTEGRACIJOS.md` skyrius „Skambučių centras“ —
   dokumentas, kurį perduosime platformos tiekėjui.

**Laukia (I2).** Platformos pusė: skambučio pabaigos įvykis → `POST /api/v1/calls`.

**Priėmimas.** Testai: patvirtintas / nepatvirtintas, pakartotinis, nauja tema,
įmonė, klaidingi duomenys; asmens kodas nepatenka į jokį žurnalą (testas tikrina
žurnalų išvestį).

---

### T17. Automatinis asmens sukūrimas iš patvirtinto skambučio

**Reikalavimai.**
1. FR-17.1 T16 skambutis su patvirtinta tapatybe, asmuo nerastas → sukuriama kortelė:
   vardas, pavardė, asmens kodas (šifruotas + hash), telefonas. Naujas laukas
   `Person.created_via` (`crm` | `import` | `sync` | `call_center`, numatytai `crm`);
   čia — `call_center`, kortelėje rodoma „Sukurta iš skambučio“.
2. FR-17.2 Toks įrašas neturi `external_id`; kai jį atsiųs Regitros sinchronizacija,
   prijungiama pagal `personal_code_hash` (FR-04.4) — dublikato nėra.
3. FR-17.3 Sąraše filtras „Sukurta iš skambučio, dar nesusieta su Regitra“.
4. FR-17.4 Tapatybės nepatvirtinus asmuo **nekuriamas** (FR-16.2).

---

### T18. Kortelė iš skambučio: tapatybės žyma ir „Perskambinti“

**Reikalavimai.**
1. FR-18.1 `POST /api/v1/calls/pop` (platforma kviečia skambučio pradžioje):
   `{call_id, identity: {verified, method, personal_code?}, caller: {phone?}}` →
   `{"url": "/contacts/<id>/?call=<token>"}` arba `{"url": "/search/?call=<token>"}`,
   jei nerasta. `token` — atsitiktinis, galioja 2 val., saugomas DB (`CallPop`:
   token, call_id, verified, method, user=null, expires_at). **Asmens kodas URL
   nepatenka.**
2. FR-18.2 Kortelė su `?call=` rodo juostą viršuje:
   - patvirtinta: žalia „Vyksta skambutis · Tapatybė patvirtinta (Smart-ID) 10:42“;
   - nepatvirtinta: geltona „Vyksta skambutis · Tapatybė NEPATVIRTINTA — informaciją
     teikite pagal instrukciją“.
3. FR-18.3 Atidarius kortelę rankiniu būdu (be `?call=`), juostos nėra.
4. FR-18.4 Jei platforma nepalaiko `pop` — operatorius randa asmenį esama paieška;
   funkcija neprivaloma platformai.
5. FR-18.5 Mygtukas **„Perskambinti“** kortelės antraštėje (visoms rolėms, galinčioms
   kurti priminimus): vienas paspaudimas atidaro mažą langą su pasirinkimais „po 1 val.“,
   „šiandien 15:00“, „rytoj 9:00“, „pasirinkti“; tekstas užpildomas „Perskambinti dėl:
   <paskutinio skambučio tema>“; sukuriamas `Reminder(kind=call)` naudotojui. Tai
   veikia ir dabar, be integracijos.

**Priėmimas.** Testai: token galiojimas, pasibaigęs token — juostos nėra; abi juostos
būsenos; „Perskambinti“ sukuria teisingą priminimą.

---

### T19. Raštų blokas su dokumentų šaltinio adapteriu

**Reikalavimai.**
1. FR-19.1 Sąsaja bendriniame CRM `contacts/documents.py`:
   ```python
   class DocumentSource(Protocol):
       def by_correspondent(self, external_ids: list[str], offset: int) -> DocPage: ...
       def search_candidates(self, name: str, email: str | None, limit: int) -> list[Candidate]: ...
   # Doc: reg_no, reg_date, title, direction ("in"|"out"), status, url, correspondent_id, correspondent_name
   ```
2. FR-19.2 Blokas „Raštai“ (registruojamas `register_block`, abiem kortelėms),
   **viduriniame stulpelyje pirmas** (virš registrų blokų). Stulpeliai: data,
   registracijos numeris, tema, kryptis (gautas / išsiųstas), būsena, nuoroda
   „Atidaryti DocLogix“ (naujame skirtuke).
3. FR-19.3 Duomenys gyvai, nesaugomi (T02 kontraktas, laiko riba, „DocLogix šiuo metu
   nepasiekiamas“).
4. FR-19.4 Nauja teisė `can_view_documents`.
5. FR-19.5 `scripts/fake_doclogix_api.py` — korespondentai ir raštai, įskaitant
   bendravardžius (susiejimo testams).
6. FR-19.6 Rodomi tik **susietų** korespondentų raštai (`ExternalLink(source="doclogix")`);
   kandidatai — T20.

**Laukia (I3).** DocLogix API prieiga, autentifikacija, laukų pavadinimai.

---

### T20. Raštų susiejimas „pasiūlyti → patvirtinti“

**Reikalavimai.**
1. FR-20.1 Bloke „Raštai“ antra dalis — **„Galimai susiję (pagal pavadinimą)“**:
   DocLogix korespondentai, rasti `search_candidates` pagal normalizuotą vardą ir pavardę
   (asmeniui) arba pavadinimą be teisinės formos ir kabučių (įmonei: „UAB“, „AB“, „„ “).
   Jei turima — papildomai lyginama el. paštu. Rodoma iki 10 kandidatų su jų raštų
   skaičiumi ir paskutinio rašto data.
2. FR-20.2 Prie kandidato: „Tai šio asmens / šios įmonės“ → `ExternalLink(source=
   "doclogix", method="manual", linked_by=…)`; nuo šiol jo raštai rodomi automatiškai.
3. FR-20.3 Prie susieto korespondento: „Atsieti“ (su patvirtinimu, `data-confirm`).
4. FR-20.4 Vienas DocLogix korespondentas — tik vienai kortelei (FR-03.2); bandant
   susieti jau susietą — pranešimas su nuoroda į tą kortelę.
5. FR-20.5 Susieti / atsieti gali tik `can_view_documents` turintys naudotojai;
   kiekvienas veiksmas — `AuditLog`.
6. FR-20.6 Kandidatai nerodomi, jei jų > 10 (per bendras vardas) — rodoma „Per daug
   atitikmenų, susiekite DocLogix pusėje“ (apsauga nuo klaidingo susiejimo).
7. FR-20.7 Rekomendacija DocLogix pusei (ne CRM darbas): korespondento kortelėje
   įvesti asmens / įmonės kodo lauką; tada susiejimas taps automatinis (`method="auto"`).

**Priėmimas.** Su bandomuoju serveriu: bendravardžiai rodomi kaip kandidatai,
nesusiejami automatiškai; susiejus — raštai matomi; atsiejus — dingsta.

---

### T21. Našumo regresija su paslaugų faktais ir blokais

**Reikalavimai.**
1. FR-21.1 `scripts/loadtest/seed.py` — 5 mln. `ServiceRecord`, 200 paslaugų tipų,
   1 mln. `CallDetails`.
2. FR-21.2 `probe.py` — nauji puslapiai: paslaugų suvestinė (12 mėn., visos paslaugos),
   suvestinės sąrašas, kontaktų sąrašas su T10 filtru, kortelė su 18 blokų (bandomieji
   loader'iai su 1–3 s vėlavimu), `POST /api/v1/calls`.
3. FR-21.3 Tikslai (p95, `load-large.yml` sąlygomis): kortelė ≤ 1 s (be blokų turinio);
   suvestinė ≤ 3 s; filtruotas sąrašas ≤ 1,5 s; `POST /api/v1/calls` ≤ 0,3 s.
4. FR-21.4 Rezultatai — `docs/REGITRA-CRM-INTEGRACIJA.md` §3 nauja lentelė.

---

## 6. Laukiančios integracijos (kai bus API)

| ID | Kas | Kas reikalinga iš kitos pusės | CRM darbas |
|---|---|---|---|
| I1 | Regitros klientų DB | ORDS endpoint'ų aprašas („pakitę nuo“, 18 blokų), autentifikacija, testinė aplinka, laukų atsakomybė (kurie laukai Regitros) | Realus `ChangeSource` ir blokų loader'iai; `SOURCE_OWNED_FIELDS` sąrašas |
| I2 | Skambučių platforma | Platformos pasirinkimas; jos pusėje — skambučio pabaigos įvykis → `POST /api/v1/calls`, pasirinktinai `calls/pop` | Tik konfigūracija ir API raktas |
| I3 | DocLogix | API prieiga (paieška pagal korespondentą ir pavadinimą), autentifikacija, nuorodos į dokumentą formatas | Realus `DocumentSource` |

## 7. Atviri klausimai

| # | Klausimas | Kam | Įtakoja |
|---|---|---|---|
| Q1 | Ar Regitros programėlė — atskiras repozitorijus, ar katalogas šiame? | Savininkas | T01 |
| Q2 | Eksporto ribos dydis (siūloma 500) | Klientų patirties skyrius | T11 |
| Q3 | Ar organizacija fiksuoja apklausų sutikimus / prieštaravimus ir kur? | DAP | T13 |
| Q4 | Paslaugų faktų saugojimo terminas (siūloma 36 mėn.) | DAP | T08 |
| Q5 | Ar CRM gali turėti nuorodą į skambučio įrašą / transkriptą ir kas jį gali klausyti? | DAP, KAC | T14 |
| Q6 | Kurie asmens / įmonės laukai priklauso Regitros DB (CRM nekeičia)? | Regitros DB savininkai | T06 |
| Q7 | Ar Regitros DB teikia paslaugų klasifikatorių ir kanalą (padalinys / internetu)? | Regitros DB savininkai | T08 |
| Q8 | Rolės „Tik savi įrašai“ numatytųjų `can_delete` / `can_export` keitimas | Savininkas | T12 |

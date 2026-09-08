# CRM — likę darbai (2026-09-07)

Sudaryta peržiūrėjus visą pradinį reikalavimų pokalbį (ChatGPT „Sukurti vietinį
CRM Ziurek") ir palyginus su dabartiniu kodu (versija 0.5.0, commit `b669105`
+ „skip links" pataisa).

Žymėjimas: ✅ padaryta · 🟡 iš dalies · ❌ nepadaryta

## Eiga (šios sesijos)

- ✅ AdminLTE „skip links" pašalintos (rodėsi kaip pašalinis tekstas)
- ✅ **B1** — „Mano filtrai": pervadinti, ištrinti, numatytasis
- ✅ Varpelio ir profilio meniu užsidaro paspaudus bet kur kitur
- ✅ **B2** — greiti veiksmai ⋮ meniu: pridėti įrašą, sukurti priminimą, kopijuoti el. paštą
- ✅ **B4** — slaptažodžio keitimas: Nustatymai → Slaptažodis
- ✅ **B6** — priedų dydžio (10 MB) ir tipo (plėtinių sąrašas) tikrinimas serveryje
- ✅ **B7** — automatinis atsijungimas po 8 val. neaktyvumo (slankusis langas)
- ✅ **C1** — sąrašų UX: pažymėtų eilučių paryškinimas, „Atšaukti pasirinkimą",
  pilna puslapių navigacija (pirmas/numeruoti/paskutinis), „Paskutinis
  bendravimas" (kontaktai) ir „Adresas" (įmonės) stulpeliai
- ✅ **C2** — kortelės santrauka: paskutinis bendravimas (data · tipas · prieš N d.),
  kitas veiksmas (artimiausias priminimas), vėluojančių priminimų skaičius
- ✅ **B5** — automatinės kasdienės kopijos: `crm-backup` Compose servisas
  (`pg_dump` + media tar į `runtime/backups/`, 14 dienų saugojimas)
- ✅ **C9** — Nustatymai → Duomenų eksportas: pilnas ZIP (data.json + media + README)
- ✅ **C7** — importo peržiūra: įkėlus failą rodoma, kas bus sukurta/atnaujinta/praleista + pavyzdys, tik tada „Patvirtinti importą"
- ✅ **C8** — masinis žymos ir kategorijos priskyrimas pažymėtiems kontaktams/įmonėms (3 riba)
- ✅ **C3** — universali paieška: gyvas grupuotas išskleidimas (kontaktai/įmonės/veiklos/
  priminimai) nuo 2 simbolių + atskiras `/search/` rezultatų puslapis
- ✅ **C4** — dinaminiai laukai: Nustatymai → Dinaminiai laukai (tekstas/ilgas tekstas/
  žymimasis/vienas/keli pasirinkimai; kontaktams, įmonėms ar abiem); rodomi ir
  redaguojami (double-click) kortelėje, sąrašo stulpeliuose, filtruose ir paieškoje
- ✅ **C6** — visos 4 dalys: `owner` (atsakingas naudotojas) prie kontakto/įmonės
  (numatytai kūrėjas, keičiamas kortelėje); Nustatymai → Naudotojai (kūrimas,
  rolės, išjungimas, slaptažodžio atstatymas); **matomumo filtravimas** — rolė
  „Naudotojas (tik savi įrašai)" mato tik savo ir dar nepriskirtus įrašus
  (sąrašai, kortelės, paieška, eksportas, archyvas, priminimai, dublikatai,
  inline redagavimas, priedai); **„Atsakingas" stulpelis** (rikiuojamas),
  filtras (bet kuris / nepriskirta / naudotojas), masinis priskyrimas
  pažymėtiems (adminui ir pilnam naudotojui), „Atsakingas" stulpelis CSV
  eksporte ir importe (pagal prisijungimo vardą, el. paštą arba vardą-pavardę).
- ✅ **C5** — auditas: `AuditLog` + Nustatymai → Žurnalas (tik administratoriams),
  filtrai pagal naudotoją / veiksmą / datą. Registruojami įrašų, veiklų, priminimų,
  nustatymų, naudotojų, importo/eksporto ir prisijungimų įvykiai (sena→nauja).
- ✅ **C7** — importo vedlys: stulpelių priskyrimas (auto-atpažinimas + rankinis
  perrinkimas), „jei įrašas jau yra" pasirinkimas (atnaujinti / praleisti /
  visada naujas), klaidingos eilutės nenutraukia importo ir atsisiunčiamos
  klaidų CSV ataskaita.
- ✅ **VERSION → 0.7.0**, `image: crm-web:0.7.0`
- ✅ **C6–C10** naudotojai/rolės/atsakingi/komandos/matomumas/teisės (žr. C6, C10) →
  VERSION 0.8.0–0.12.0
- ✅ **Kortelės perdarymas pagal prototipą** (2 diegimai):
  - 1 dalis (`0.13.0`): nauji laukai `priority` (spalvotas ženkliukas), `contact_type`,
    `cooperation_start` (data), `description`, `internal_note`, `created_by` prie
    Person ir Company; visi inline redaguojami (select / date / textarea).
  - 2 dalis (`0.14.0`): naujas detalus puslapio išdėstymas `contacts/_detail_layout.html`
    (antraštė su „← Grįžti", žvaigždute, „Redaguoti/…/+Naujas priminimas"; kairė kolona:
    „Kontaktinė informacija" su kopijavimu, „Papildomi laukai" tinklelis, „Aprašymas",
    skirtukai Veiklos/Priminimai/Komentarai/Failai/Susiję įrašai; dešinė kolona:
    Organizacija/Atsakingi/Žymos/Papildoma informacija). `record_summary.html` nebenaudojamas.

---

## A. Padaryta (kontrolei)

- ✅ Asmenys, įmonės, M:N ryšiai, keli telefonai/el. paštai/adresai/URL, `tel:`/`mailto:`
- ✅ Kontaktų ir įmonių sąrašai: paieška, rikiavimas (visi stulpeliai, meniu),
  50/100 eilučių, stulpelių rodymas/slėpimas, puslapiavimas (dalinis, žr. C)
- ✅ Filtrai: kelios kategorijos/žymos, mėgstami, el. paštas, paskutinio
  bendravimo datų intervalas, aktyvių filtrų skaičius, filtrų žymos, „Išvalyti".
  Įmonių filtrai: kategorijos/žymos/miestas/datos. „Būklės" filtras pašalintas (sąmoningai).
- ✅ Inline redagavimas kortelėje (double-click), inline žymos/kategorijos sąraše,
  favourite žvaigždutė + filtras
- ✅ Veiklos istorija su tipais (pastaba/skambutis/el. laiškas/susitikimas/užduotis),
  failai ir nuotraukos, saugus atsisiuntimas, formatuojamas tekstas
- ✅ Įmonės kortelėje bendra įmonės + susietų kontaktų istorija; kontakto kortelėje — tik jo
- ✅ Priminimų centras: varpelis, „Aktyvūs" / „Visi suplanuoti", auto-atnaujinimas 30 s,
  redagavimas, „Atlikta", pakartotinio pateikimo apsauga
- ✅ Importas CSV (UTF-8) + XLSX, transakcinis, žymų/kategorijų atkūrimas be dublių;
  CSV eksportas su BOM; pažymėtų įrašų eksportas
- ✅ Dublikatų aptikimas (kūrimas, redagavimas, inline, importas), 3 lygiai,
  peržiūros puslapis, **sujungimas** (ne trynimas, `merged_into`)
- ✅ Archyvas (soft-delete) + atkūrimas; masiniai veiksmai: archyvuoti, eksportuoti
- ✅ Profilio meniu (avataras), profilio puslapis (vardas, el. paštas, kalba, laiko zona, nuotrauka)
- ✅ Žymų/kategorijų administravimas: kūrimas, pervadinimas, žymų spalvos (8), panaudojimo skaičius
- ✅ Nustatymai: kairysis meniu (Profilis / Žymos / Kategorijos / Dublikatai / Dokumentacija)
- ✅ In-app dokumentacija su temomis
- ✅ LT / EN perjungimas
- ✅ AdminLTE tema, `restart: unless-stopped`, HTTPS per Tailscale, Funnel (vieša prieiga)

---

## B. Aukštas prioritetas — ✅ visi padaryti

### B1. Išsaugoti filtrai („Mano filtrai") — ✅ padaryta
Pervadinti, ištrinti, numatytasis (pritaikomas kartą per sesiją). Bendras
`templates/filters/saved_filters.html` partial.

### B2. Greiti veiksmai sąrašo eilutėje (⋮ meniu) — ✅ padaryta
Atidaryti, Redaguoti, Pridėti komentarą (`#tab-comments`), Sukurti priminimą
(`#reminder-add`), Kopijuoti el. paštą (į iškarpinę). Įmonėms — be priminimo.

### B3. Nustatymų puslapio skiltys — ✅ (kas planuota)
- ✅ **Sistema** (`0.25.0`): numatytas sąrašo eilučių skaičius (25/50/100),
  datos formatas (ISO / d.m.Y / m/d/Y) — `SystemSettings` singleton,
  `date_format` / `datetime_format` per context processor'ą visuose `|date:`.
- ✅ **Importas** (`0.26.0`): CSV skyriklis (auto/`,`/`;`/tab) ir koduotė
  (auto → UTF-8, tada Windows-1257). LT „Excel" (cp1257 + `;`) importuojasi.
- ⏸️ Pranešimai (el. pašto priminimai, SMTP) — atidėta (žr. D skiltį).
- Archyvas kaip skiltis — palikta atskiru meniu punktu (veikia).
- Laukai (C4) ir Naudotojai/teisės (C6) — jau padaryta atskirai.

### B4. Slaptažodžio keitimas iš profilio — ✅ padaryta
Nustatymai → Slaptažodis (Django `PasswordChangeForm`, sesija išlieka).

### B5. Automatinės atsarginės kopijos — ✅ padaryta
`crm-backup` Compose servisas (`scripts/backup.sh`): `pg_dump -Fc` + `runtime/media`
tar į `runtime/backups/` kas `BACKUP_INTERVAL_SECONDS` (24 val.), palieka naujausias
`BACKUP_KEEP` (14). Vėliau galima savaitės/mėnesio rotaciją ir kopiją už NAS ribų.

### B6. Priedų serverinė validacija — ✅ padaryta
Veiklos priedai: 10 MB dydžio riba + plėtinių sąrašas (jpg/png/webp/gif/pdf/txt/
doc/docx/xls/xlsx). Netinkami failai atmetami su pranešimu, įrašas išsaugomas.

### B7. Automatinis atsijungimas po neaktyvumo — ✅ padaryta
`SESSION_COOKIE_AGE` = `DJANGO_SESSION_IDLE_MINUTES` (numatyta 480 = 8 val.) +
`SESSION_SAVE_EVERY_REQUEST` → slankusis langas nuo paskutinės užklausos.
Pastaba: atidarytas ir matomas CRM skirtukas kas 30 s atnaujina sesiją
(varpelio tikrinimas); paslėpus skirtuką ar užrakinus ekraną tikrinimas
sustoja ir sesija po 8 val. baigiasi. Griežtesnis (pele/klaviatūra pagrįstas)
neveiklumas — atskiras darbas, jei prireiks.

---

## C. Vidutinis prioritetas

### C1. Sąrašų UX likučiai — ✅ padaryta
Pažymėtų eilučių paryškinimas, „Atšaukti pasirinkimą", pilna puslapių navigacija
(bendras `templates/pagination.html`), „Paskutinis bendravimas" stulpelis
(kontaktai, rikiuojamas) ir „Adresas" stulpelis (įmonės). Abu — pasirenkami
per „Stulpeliai".

### C2. Paskutinio ir kito kontakto informacija kortelėje — ✅ padaryta
`templates/record_summary.html` kontakto ir įmonės kortelėse: paskutinis
bendravimas (data · tipas · prieš N d.), kitas veiksmas, vėluojančių priminimų
skaičius. Sąraše paskutinio bendravimo data yra kaip C1 stulpelis.

### C3. Universali paieška su grupėmis — ✅ padaryta
Viršutinės juostos paieška: gyvas išskleidžiamas sąrašas (`/search/suggest/` JSON,
`static/js/search.js`) su grupėmis Kontaktai / Įmonės / Veiklos / Priminimai nuo
2 simbolių, ir pilnas `/search/` puslapis. Failų grupė — vėliau, jei prireiks.

### C4. Dinaminiai (custom) laukai — ✅ padaryta
`CustomField` + `CustomValue`. Nustatymai → Dinaminiai laukai: kūrimas (tekstas,
ilgas tekstas, žymimasis langelis, vienas/keli pasirinkimai; kontaktams/įmonėms/abiem),
šalinimas. Reikšmės kortelėje (inline double-click), sąrašo stulpeliuose (pasirenkami),
filtruose (icontains) ir paieškoje. Vėliau galima: skaičiaus/datos tipai, stulpelio
rikiavimas, laukų tvarkos keitimas, pasirinkimo laukų filtras su reikšmių sąrašu.

### C5. Pakeitimų istorija / auditas — ✅ padaryta
`AuditLog` modelis + `contacts/audit.py` (`log(...)`, `log_change(...)`).
Nustatymai → **Žurnalas** (`/settings/audit/`, tik administratoriams): lentelė su
filtrais pagal naudotoją, veiksmą ir datų intervalą, puslapiavimas po 100, tik
skaitymas. Registruojama: kontakto/įmonės kūrimas, lauko keitimas (sena→nauja,
inline ir per formą), archyvavimas, atkūrimas, sujungimas; veiklos ir priminimų
kūrimas/keitimas/atlikimas/trynimas; priedų įkėlimas; žymų/kategorijų/dublikatų/
profilio/slaptažodžio nustatymų keitimas; dinaminio lauko kūrimas/šalinimas;
naudotojo kūrimas/rolės/išjungimo/slaptažodžio atstatymo veiksmai; CSV importas ir
eksportas; prisijungimas / atsijungimas / nepavykęs prisijungimas (per auth signalus).
Vėliau galima: įrašo „istorijos" kortelė detaliame puslapyje, eksportas į CSV,
saugojimo terminas.

**Pradinė specifikacija (2026-09-08):**
- `AuditLog` modelis: `actor` (FK user, SET_NULL), `action` (kategorija), `target_type`
  (contact / company / setting / custom_field / user / import / export / activity /
  reminder / auth), `target_id`, `target_label` (žmogui skaitomas pavadinimas),
  `field` (kuris laukas), `old_value` / `new_value` (tekstu), `detail` (JSON papildomai),
  `created_at`, `ip`.
- Registruojami įvykiai:
  - kontakto / įmonės kūrimas, trynimas (archyvavimas), atkūrimas, lauko redagavimas
    (inline ir per formą) — su sena→nauja reikšme;
  - sistemos nustatymų keitimas (dublikatai, žymos, kategorijos, profilis, sesijos t.t.)
    — kuris naudotojas, kurį nustatymą, sena→nauja;
  - dinaminio lauko sukūrimas / trynimas / pervadinimas;
  - naudotojo sukūrimas / rolės keitimas / išjungimas / slaptažodžio atstatymas;
  - importas (kiek eilučių, sukurta / atnaujinta / praleista) ir eksportas (ką, kiek);
  - priedų įkėlimas / šalinimas;
  - priminimo (veiksmo) suplanavimas, redagavimas, pažymėjimas atliktu, trynimas;
  - prisijungimas / atsijungimas / nepavykęs prisijungimas.
- **Atskira nustatymų skiltis „Žurnalas"** (`/settings/audit/`), matoma tik administratoriams.
- Filtravimas: pagal naudotoją, pagal veiksmą (action), pagal datų intervalą (nuo–iki).
  Puslapiavimas. Tik skaitymas, įrašai netrinami.

### C6. Naudotojai, rolės, teisės ir atsakingas naudotojas — ✅ padaryta (4 dalys)
Sąmoningai vėliau: komandų/skyrių hierarchija, matomumo grupės, įrašo dalijimasis
konkretiems naudotojams, teisės pagal lauką.

Dabar 1 superuser. Reikia pilno modulio. Pagrindas — konkurentų praktika
(Pipedrive „permission sets" + „visibility groups", HubSpot „users & teams" +
record owner, Teamgate rolės + savininkas, Salesforce owner + org-wide defaults).

**Naudotojų valdymas** (Nustatymai → Naudotojai, tik administratoriui):
- Sąrašas: vardas, el. paštas, rolė, būsena (aktyvus/išjungtas), paskutinis prisijungimas
- Pridėti naudotoją: vardas, el. paštas, rolė + pradinis slaptažodis (arba pakvietimo
  nuoroda el. paštu, kai bus SMTP — kol kas slaptažodis)
- Redaguoti rolę, **išjungti** (ne trinti — išsaugoma autorystė ir istorija),
  atstatyti slaptažodį
- Negalima išjungti/pažeminti paskutinio administratoriaus

**Rolės** (pradžiai 3, be hierarchijos):
| Rolė | Kontaktai/įmonės | Nustatymai | Naudotojai |
|---|---|---|---|
| Administratorius | visi (kurti/keisti/archyvuoti) | visi | valdo |
| Naudotojas | visi | tik profilis + savo filtrai | — |
| Naudotojas (tik savi) | tik kur jis atsakingas arba nepriskirta | tik profilis | — |

**Atsakingas naudotojas (owner)**:
- `owner` (FK į User, `null=True`) prie `Person` ir `Company`
- Numatytai priskiriamas kūrėjui; keičiamas kortelėje (inline) ir masiniu veiksmu
- Filtras „Atsakingas" + greitas „Mano kontaktai / Mano įmonės" (saveable kaip numatytasis)
- Stulpelis „Atsakingas" sąrašuose (kartu su C1)
- CSV eksporte/importe — stulpelis „Atsakingas" (pagal el. paštą arba vardą)

**Matomumas** (queryset lygyje, ne tik UI):
- „Tik savi" rolė: `Person/Company` sąrašai, paieška, kortelės, dublikatai, eksportas
  filtruojami `Q(owner=user) | Q(owner__isnull=True)`
- Veiklos ir priminimai seka įrašo matomumą; `created_by` išlieka
- Administratorius ir „Naudotojas" — mato viską

**Sąmoningai vėliau**: komandų/skyrių hierarchija, matomumo grupės, įrašo dalijimasis
konkretiems naudotojams, teisės pagal lauką, „org-wide default = private/public".

Įgyvendinimo dalys (atskiri diegimai):
1. `owner` laukas + migracija, numatytasis kūrėjas, rodymas/redagavimas kortelėje
2. Rolės modelis (`UserProfile.role` arba grupės) + „Naudotojai" sąrašas ir kūrimas
3. Matomumo filtrai visuose sąrašuose/paieškoje/eksporte + testai
4. Masinis „priskirti atsakingą" + „Atsakingas" filtras/stulpelis + CSV

### C7. Importo vedlys — ✅ padaryta
Peržiūra prieš importą (sukurta/atnaujinta/praleista + 8 eilučių pavyzdys, sesijoje).
**Stulpelių priskyrimas**: įkėlus failą, kiekvienam CSV/XLSX stulpeliui parenkamas
CRM laukas (auto-atpažinimas pagal antraštę + rankinis perrinkimas, `IMPORT_COLUMNS`).
**Dublikatų elgsena**: „atnaujinti esamą / praleisti / visada kurti naują"
(`_import_contact_rows(..., mode=...)`). **Klaidų ataskaita**: klaidinga eilutė
(pvz. >3 žymos) nenutraukia viso importo — įrašoma su eilutės numeriu ir
priežastimi, po importo atsisiunčiama `importo-klaidos.csv`
(`/import-export/errors.csv`). Vėliau galima: XLSX klaidų ataskaita, „sausas"
bandymas be įrašymo.

### C8. Masiniai veiksmai — ✅ padaryta
Archyvuoti, eksportuoti, **masinis žymos/kategorijos priskyrimas IR nuėmimas**
(kontaktams ir įmonėms), masinis atsakingo priskyrimas, ir **masinis dublikatų
sujungimas** („Sujungti visus" dublikatų puslapyje, `0.27.0`).

Žymas ir kategorijas dabar galima ir **ištrinti** (Nustatymai → Žymos/Kategorijos,
„Pašalinti" su patvirtinimu — nuimama nuo visų įrašų).

### C9. Pilna atsarginė kopija iš sąsajos — ✅ padaryta
Nustatymai → Duomenų eksportas (tik administratoriui): ZIP su `data.json`
(`dumpdata` — kontaktai, naudotojai, nustatymai), `media/` ir `README.txt`.

### C10. Komandos, matomumo modelis ir detalios teisės — ✅ padaryta (5 dalys, spec 2026-09-08)
**Padaryta (1 dalis):** `Person.responsibles` / `Company.responsibles` M2M; kortelės
laukas **„Atsakingi"** (double-click: pažymėti kelis, vienam radio „pagrindinis"
arba „be pagrindinio" → `owner`); „savo įrašai" visur = `owner=user OR responsibles=user`
(sąrašai, kortelė, paieška, priminimai, priedai); dublikatų sujungimas perkelia
atsakingus; CSV eksporte/importe stulpelis „Atsakingi" (`;`-atskirti vardai).

**Padaryta (2 dalis):** `Team` modelis (`name`, `visibility` = `all` / `team`,
`members` M2M). Nustatymai → **Komandos** (tik administratoriui): kurti, pervadinti,
keisti matomumą, valdyti narius, šalinti. Veiksmai žurnaluojami.

**Padaryta (3 dalis):** `UserProfile.record_visibility` (`all` / `team` / `own`,
numatyta `all`; migracija: „restricted" rolė → `own`). `record_visibility(user)` =
**griežtesnis** iš: naudotojo nustatymo, „restricted" rolės grindų (`own`) ir bet
kurios komandos su `visibility=team` (`team`). `sees_all_records` dabar = `== all`.
`visible_people` / `visible_companies` / `visible_reminders` + veiklų/priedų filtrai
perrašyti: `team` → įrašai, kurių `owner`/`responsibles` yra to paties naudotojo
komandų narys (+ nepriskirti); `own` kaip anksčiau. Nustatymai → Naudotojai:
„Matomumas" stulpelis, rodomas ir faktinis matomumas jei komanda griežtesnė.
Kortelės „Atsakingi" laukas — **multiselect dropdown** (naudotojų sąrašas) +
atskiras „Pagrindinis" dropdown.

**Padaryta (4 dalis):** „Atsakingas" filtras kontaktų/įmonių sąrašuose praplėstas:
greitas mygtukas **„Mano kontaktai" / „Mano įmonės"** (`?owner=me` = owner ARBA
responsible = aš), dropdown reikšmės **„Mano įrašai"**, **„Be atsakingo"** (nei
owner, nei responsibles) ir bet kuris naudotojas (`owner_id` ARBA responsible).
Jei filtruojama pagal naudotoją, kurio įrašų dabartinis naudotojas nemato
(matomumo ribos) — virš sąrašo rodomas paaiškinimas. Masinis „Priskirti
atsakingą" jau buvo (4 dalis, C6): priskiria/keičia `owner` pažymėtiems.

**Padaryta (5 dalis):** `RolePermissions` modelis (rolė → JSON gebėjimų žemėlapis).
`permissions.CAPABILITIES` — `can_import`, `can_export`, `can_delete`,
`can_merge_duplicates`, `can_bulk_edit`, `can_reassign_owner`,
`can_manage_custom_fields`, `can_manage_taxonomy`, `can_view_audit`. `has_capability`
(admin visada True; kitaip: išsaugota reikšmė → numatytoji pagal rolę). Numatytieji:
`member` — importas/eksportas/archyvavimas/dublikatai/masiniai/atsakingo keitimas;
`restricted` — tik eksportas. Nustatymai → **Rolės ir teisės** (matrica rolė ×
gebėjimas, tik administratoriui). Tikrinama view lygyje (`_require_capability`, 404,
inline atsakingo keitimas → 403) ir slepiama UI (nav „Importas/eksportas",
„Dinaminiai laukai", „Žymos/Kategorijos", „Žurnalas"; masinės juostos mygtukai;
import/eksport puslapio kortelės). Žurnalas ir taksonomija/dinaminiai laukai anksčiau
buvo neapsaugoti — dabar apsaugoti.

C6 išplėtimas. Konkurentų praktika: HubSpot „Teams" + „users & teams" matomumas,
Pipedrive „visibility groups", Salesforce „role hierarchy + sharing rules".

**1. Keli atsakingi naudotojai (`responsibles`)**
- `Person` / `Company`: paliekamas `owner` (FK) = **pagrindinis atsakingas**;
  pridedamas `responsibles` M2M (User) = **papildomi atsakingi**.
- Kortelėje laukas **„Atsakingi"** — double-click, galima pridėti/šalinti vieną ar
  kelis sistemos naudotojus. Pagrindinis pažymimas atskirai; „padaryti pagrindiniu".
- „Savo įrašai" visur = `Q(owner=user) | Q(responsibles=user)`.
- CSV eksporte/importe: „Atsakingi" stulpelis (`;`-atskirti prisijungimo vardai).

**2. Komandos / grupės (`Team`)**
- `Team` modelis: `name`, `visibility` (`team` / `all`, numatyta `all`).
- `TeamMembership` (User↔Team, M2M; naudotojas gali būti keliose).
- Nustatymai → **Komandos** (tik administratoriui): kurti/pervadinti/šalinti,
  pridėti/šalinti narius.

**3. Matomumo modelis (queryset lygyje)**
- `UserProfile.record_visibility`: `own` / `team` / `all` (numatyta `all`).
- Efektyvus matomumas = **griežtesnis** iš: naudotojo nustatymo IR (jei naudotojas
  komandoje) komandos `visibility`. Administratorius — visada `all`.
  - `all` → viskas
  - `team` → įrašai, kurių `owner` ar `responsibles` yra to paties naudotojo
    komandos narys (arba jis pats); + nepriskirti
  - `own` → tik `owner=user | responsibles=user` (+ nepriskirti)
- Sena rolė „Naudotojas (tik savi įrašai)" = `record_visibility=own`; „Naudotojas
  (visi)" = `all`. Rolė lieka kaip greitas presetas, bet tikras raktas — `record_visibility`.
- Veiklos, priminimai, priedai, dublikatai, eksportas — seka tą patį matomumą (kaip C6/3).

**4. Filtrai**
- „Atsakingas" filtras: greiti mygtukai **„Mano kontaktai" / „Mano įmonės"**
  (`responsibles=me OR owner=me`), pasirinkimas **bet kurio naudotojo**, ir
  **„Be atsakingo"** (nei `owner`, nei `responsibles`).
- Jei pasirinkto naudotojo įrašų matyti negalima (matomumo ribos) — prie
  „Rezultatų nerasta" rodomas paaiškinimas („Šio naudotojo įrašai jums nematomi").
- Sąrašo masinis veiksmas **„Priskirti atsakingą"** — priskiria arba pakeičia
  `owner` / prideda `responsibles` pažymėtiems įrašams (naudinga masiškai
  perimti „be atsakingo" įrašus).

**5. Detalios teisės (permission sets)**
- Naudotojo/rolės lygyje jungiami gebėjimai: `can_import`, `can_export`,
  `can_delete` (archyvuoti/trinti), `can_merge_duplicates`, `can_bulk_edit`,
  `can_manage_custom_fields`, `can_manage_taxonomy`, `can_reassign_owner`,
  `can_view_audit`.
- Nustatymai → **Rolės ir teisės**: matrica rolė × gebėjimas (administratoriui);
  arba individualūs perrašymai naudotojui.
- Tikrinama view lygyje (dekoratorius/patikra) + slepiama UI.

Įgyvendinimo dalys (atskiri diegimai, „tęsk" tvarka):
1. **Keli atsakingi** — `responsibles` M2M, kortelės laukas, „savo" = owner|responsible
   visur, CSV.
2. **Komandos** — `Team` + `TeamMembership` + Nustatymai → Komandos.
3. **Matomumo modelis** — `record_visibility`, komandos `visibility`, `visible_*`
   perrašymas, „nematoma" paaiškinimas.
4. **Filtrų politika** — „Mano" greiti mygtukai, bet kurio naudotojo pasirinkimas
   su matomumo koreliacija, masinis „priskirti atsakingą" (owner + responsibles).
5. **Detalios teisės** — gebėjimų rinkinys, rolė×teisė matrica, tikrinimas.

---

## D. Žemas prioritetas / vėliau (`0.27.0`)

- ⏸️ El. pašto priminimai — **kol kas nedarome** (naudotojo sprendimas 2026-09-08)
- ⏸️ Greiti veiksmai kortelėje (Skambinti / Rašyti …) — **nedarome**
- ⏸️ Žymų/kategorijų būsenos (aktyvi/neaktyvi, paskirtis) — **nereikia**
- ✅ PWA — `/manifest.webmanifest` + `/sw.js` (šablonai, kad `{% static %}` hash'ai
  veiktų prod), navy tema, SVG ikonos (+ maskable), „pridėti į pradinį ekraną".
- ✅ Neišsaugotų formos pakeitimų perspėjimas — `static/js/forms.js` (`beforeunload`
  ant `.data-form` / `.profile-form` / dublikatų nustatymų formos).
- ❌ Grafinis ryšių medis — paliekamas tekstinis sąrašas (pakanka).
- ✅ Mobilus vaizdas — `@media(max-width:640px)` tankio blokas; telefone
  neberezervuojama paslėptos masinių veiksmų juostos vieta virš sąrašo.
- ✅ LT/EN spragos — `sort_header` („Didėjančiai" / „Mažėjančiai"),
  `inline_choices` antraštė per `translate`, `duplicate_merge` klaidos per `gettext`.

## Saugumo pataisos (naudotojo pastebėtos, `0.27.0`)

- Įmonės kortelė rodė **visus** susietus kontaktus, jų veiklas ir priminimus bei
  „Kontaktai" skaičių neatsižvelgdama į matomumą → dabar filtruojama `visible_people`.
- CSV importas ieškojo esamo kontakto **globaliai**: naudotojas su `can_import` galėjo
  atnaujinti jam nematomą kontaktą ir per „Atsakingas" stulpelį jį pasisavinti. Dabar
  atitikmuo ieškomas tik `visible_people` ribose; nematomas atitikmuo = eilutės klaida;
  „Atsakingas" / „Atsakingi" stulpeliai ignoruojami be `can_reassign_owner` teisės.

## E. Kokybės darbai (naudotojo užsakyti 2026-09-08)

### E1. Kodo švara — nereikalingo kodo pašalinimas — ✅ (dalinai)
Atlikta (`0.21.0`):
- ištrinti nebenaudojami šablonai `templates/record_summary.html`,
  `templates/settings.html` (pakeitė `templates/settings/*`);
- pašalintos mirusios CSS klasės: `app.css` — `.detail-grid` / `.facts` /
  `.activity-column` / `.company-link` / `.composer` / `.reminder-panel` /
  `.timeline article` / `.facts-labels` / `.contact-head`; `theme.css` —
  `.record-summary*`, `.record-more*` / `.record-more-menu*`;
- `detail-editing.js` — miręs `#composer` hash-šuolis pakeistas į `#tab-comments`;
- `contact_detail` / `company_detail` konteksto valymas (`detail_fields`,
  `history`, `next_reminder_person`, `_last_activity_context` supaprastintas).
Cache-buster'iai: `app.css?v=20260908c`, `theme.css?v=20260908w`,
`detail-editing.js?v=20260908d`.

**„Mirusios" modelio dalys — išspręsta (`0.24.0`, migracija `0021`):** `Person.status`
ir `priority` / `contact_type` / `cooperation_start` / `internal_note` (Person + Company)
visai pašalinti; `RecordDetailsModel` palieka tik `description`.

### E2. Kiekvieno mygtuko / lauko patikra — ✅
Pereita per visą sąsają naršyklėje (lokalus serveris, LT + EN, desktop + mobile).

**Patikrinta ir veikia:**
- Prisijungimas; kalbos perjungimas (LT/EN); globali paieška + autocomplete.
- Kontaktų/įmonių sąrašai: filtrų skydelis (visi laukai + „Šaltinis“ custom),
  stulpelių skydelis + „Išsaugoti rodinį“, rūšiavimo antraštės, „Mano kontaktai“,
  žvaigždutė (favourite), eilutės meniu (atidaryti / redaguoti / komentaras /
  priminimas / kopijuoti el. paštą), masiniai veiksmai (žyma / kategorija /
  atsakingas / archyvuoti / eksportuoti), puslapiavimo dydis.
- Išsaugoti filtrai: išsaugoti / pervadinti / numatytasis / ištrinti.
- Kontakto/įmonės kūrimas: visi laukai (įsk. prioritetą, kontakto tipą,
  bendradarbiavimo pradžią, telefonus/el. paštus/adresus/URL), `created_by`.
- Kortelės inline redagavimas (double-click): pareigos, telefonai, el. paštai
  (keli), adresai, nuorodos, aprašymas, „Šaltinis“ (tekstas ir pasirinkimas),
  organizacija, atsakingi; „Kopijuoti nuorodą“, „Archyvuoti“ / „Atkurti“.
- Tabai (Komentarai / Priminimai / Failai); komentaro forma; priminimo pridėjimas,
  redagavimas, „Atlikta“; failo įkėlimas; žymų/kategorijų priskyrimas kortelėje.
- Dublikatų peržiūra + sujungimas.
- Nustatymai: profilis, slaptažodžio keitimas (validacija), žymos (kūrimas,
  pervadinimas, spalva), kategorijos, dinaminiai laukai (kūrimas + „Pašalinti“),
  naudotojų kūrimas, komandos (kūrimas + nariai + „Pašalinti“), rolės ir teisės,
  žurnalas + filtrai, duomenų eksportas (ZIP), dublikatų nustatymai, dokumentacija.
- Importas: CSV peržiūra + patvirtinimas; CSV eksportai (be „Būsena“ stulpelio).
- Priminimų varpelis (topbar): tabai, redagavimo nuorodos.

**Rasta ir pataisyta:**
- Dokumentacijos puslapyje buvo įrašyta pasenusi versija „CRM 0.4.0“ (dviejose
  vietose). Dabar rodoma tikroji versija iš `VERSION` failo (`crm_version`
  kontekstas). Priklausomybių versijos (Python, Django, PostgreSQL, Gunicorn,
  Tailscale) patikrintos — teisingos.

**Išspręsta po E2 (naudotojo sprendimai 2026-09-08):**
- Žymų / kategorijų trynimas — ✅ pridėta (Nustatymai + masinis „Nuimti"). Žr. C8.
- `Person.status` + `priority`/`contact_type`/`cooperation_start`/`internal_note` —
  ✅ **išmesti** (migracija `0021`, `RecordDetailsModel` palieka tik `description`).
  Pašalinta ir iš formų, `merging.py`, paieškos filtro, `detail_field.html`
  (`date`/`choice` redaktoriai, `prio-badge`), nebenaudojami vertimai.

---

## F. Kalendorius — ✅ padaryta (`0.28.0`)

Asmeninė darbotvarkė: kiekvienas naudotojas mato **tik savo sukurtus** priminimus.
- `Reminder` praplėstas: `company` FK, `end_at` (trukmė), `person` tapo neprivalomas —
  įvykis gali būti prie kontakto, prie įmonės arba be įrašo. Tie patys priminimai
  ir toliau matomi kortelėje bei varpelyje (viena sąvoka, ne dublikatas).
- `/calendar/` — **diena / savaitė / mėnuo**. Dienos ir savaitės vaizde valandų
  tinklelis, gyva „dabar" linija, persidengiantys įvykiai dedami greta.
  Praėję įvykiai blankesni.
- Paspaudus arba **patempus** laisvą laiką (15 min. žingsnis) atsidaro dialogas su
  užpildytu laiku; pasirinkus kontaktą/įmonę rodomi jos **telefonas ir adresas**
  iš kortelės. Įvykį galima redaguoti ir pašalinti.
- Kodas: `contacts/calendar_views.py`, `templates/calendar/*`, `static/js/calendar.js`.

## Būsena 2026-09-08 (`0.27.0`)

Visi A–E ir D punktai įgyvendinti. Lieka tik sąmoningai atidėti / atmesti dalykai:
el. pašto priminimai (SMTP), kortelės greiti „Skambinti / Rašyti" veiksmai,
žymų/kategorijų būsenos, grafinis ryšių medis. Naujų darbų nėra.

## Siūloma vykdymo tvarka (istorinė — visa atlikta)

1. **B1** išsaugotų filtrų pervadinimas / trynimas / numatytasis
2. **B2** greiti veiksmai eilutėje (pastaba, priminimas, kopijuoti el. paštą)
3. **B4** slaptažodžio keitimas profilyje
4. **B6** priedų dydžio/tipo validacija · **B7** idle-timeout (maži, saugumo)
5. **C1** sąrašų UX likučiai (paryškinimas, „atšaukti pasirinkimą", pilna navigacija, stulpeliai)
6. **C2** paskutinio/kito kontakto info
7. **B5 + C9** atsarginės kopijos (automatinės + eksportas iš sąsajos)
8. **C7 / C8** importo vedlys ir masinių veiksmų išplėtimas
9. **C3** universali paieška su grupėmis
10. **C6** naudotojai, rolės, atsakingas naudotojas, matomumas (4 dalys)
11. **C5** auditas · **C4** individualūs laukai
12. **D** likučiai (PWA, el. paštas, kortelės greiti veiksmai, taksonomijų būsenos)

Kiekvienas punktas — pagal `CLAUDE.md` taisykles: minimalus kodas → testai →
naršyklė → diegimas per UGREEN → GitHub.

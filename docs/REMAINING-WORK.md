# CRM — likę darbai (2026-09-07)

Sudaryta peržiūrėjus visą pradinį reikalavimų pokalbį (ChatGPT „Sukurti vietinį
CRM Ziurek") ir palyginus su dabartiniu kodu (versija 0.5.0, commit `b669105`
+ „skip links" pataisa).

Žymėjimas: ✅ padaryta · 🟡 iš dalies · ❌ nepadaryta

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

## B. Aukštas prioritetas — nepadaryta / iš dalies

### B1. Išsaugoti filtrai („Mano filtrai") — 🟡
Yra tik **sukurti + pritaikyti**. Trūksta:
- ❌ pervadinti
- ❌ ištrinti
- ❌ pažymėti numatytąjį (atidarant sąrašą pritaikomas automatiškai)
Kelias: `contacts/urls.py` (nauji maršrutai), `contacts/views.py`, `SavedFilter` jau turi modelį.

### B2. Greiti veiksmai sąrašo eilutėje (⋮ meniu) — 🟡
Dabar tik „Atidaryti" + „Redaguoti". Trūksta:
- ❌ Pridėti pastabą (greitas modalas / nuoroda į kortelę su atvira forma)
- ❌ Sukurti priminimą
- ❌ Kopijuoti el. paštą

### B3. Nustatymų puslapio skiltys — 🟡
Yra 5 skiltys. Pagal planą trūksta:
- ❌ Pranešimai (el. pašto priminimų įjungimas, SMTP)
- ❌ Sistemos nustatymai (numatytas eilučių skaičius, datos formatas)
- ❌ Importo nustatymai (koduotė, skyriklis)
- ❌ Archyvas kaip skiltis (dabar atskiras meniu punktas — galima palikti)
- ❌ Laukai (individualūs laukai — žr. C4)
- ❌ Naudotojai ir teisės (žr. C6)

### B4. Slaptažodžio keitimas iš profilio — ❌
Dabar tik per `manage.py changepassword`. Reikia formos „Mano profilis" puslapyje
(Django `PasswordChangeView` / `set_password`).

### B5. Automatinės atsarginės kopijos — ❌
Reikalauta: kasdienė PostgreSQL kopija + priedai, saugojimo terminas (pvz. 14/8/12).
Dabar kopijos daromos rankomis. Nėra `worker`/cron konteinerio.
Kelias: 4-as Compose servisas (`crm-backup`) su `pg_dump` + `runtime/media` tar pagal cron,
arba host cron `/volume1/docker/crm/backups`.

### B6. Priedų serverinė validacija — 🟡
Avatarui yra (5 MB, tik paveikslėliai). Veiklos priedams — **nėra** dydžio/tipo ribos
(`contacts/views.py:418,605`). Reikia dydžio limito ir tipų sąrašo.

### B7. Automatinis atsijungimas po neaktyvumo — ❌
Reikalauta NAS versijoje. `config/settings.py` neturi `SESSION_COOKIE_AGE` /
`SESSION_SAVE_EVERY_REQUEST` / idle-timeout.

---

## C. Vidutinis prioritetas

### C1. Sąrašų UX likučiai — 🟡
- ❌ Pažymėtų eilučių fono paryškinimas
- ❌ „Atšaukti pasirinkimą" mygtukas masinių veiksmų juostoje
- ❌ „Paskutinis bendravimas" stulpelis (kontaktai) — data yra tik filtre, ne stulpelyje
- ❌ „Miestas" stulpelis (įmonės)
- ❌ Pilna puslapių navigacija: pirmas / numeruoti / paskutinis (dabar tik „Ankstesnis/Kitas")

### C2. Paskutinio ir kito kontakto informacija kortelėje/sąraše — ❌
Reikalauta (Teamgate): „Paskutinis kontaktas", „Dienų nuo paskutinio",
„Kitas suplanuotas veiksmas", „vėluojančios užduotys". Dabar nerodoma niekur.

### C3. Universali paieška su grupėmis — ❌
Dabar `?q=` tik nukreipia į kontaktų sąrašą. Reikalauta: rezultatai grupėmis
(Asmenys / Įmonės / Veiklos / Priminimai / Failai), gyvas išskleidimas nuo 2–3 simbolių.

### C4. Individualūs (custom) laukai — ❌
Reikalauta (Teamgate + planas p.8). Nėra `CustomField` modelio. Tipai:
trumpas/ilgas tekstas, skaičius, data, taip/ne, vienas/keli pasirinkimai, URL;
paskirtis asmeniui/įmonei/abiem.

### C5. Pakeitimų istorija / auditas — ❌
Reikalauta „pradėti rinkti iš karto". Nėra: kas/kada/kurį lauką keitė, sena→nauja
reikšmė, prisijungimų istorija, importo/eksporto operacijų žurnalas, failų įkėlimai.
Yra tik `created_at`/`updated_at`/`created_by`.

### C6. Keli naudotojai, rolės, teisės — ❌
Suprojektuota „vėliau". Dabar 1 superuser. Architektūra leidžia (Django auth).

### C7. Importo vedlys — 🟡
Dabar: failas → rezultatas (sukurta/atnaujinta/praleista/galimi dubliai).
Trūksta: stulpelių susiejimo lango, duomenų peržiūros prieš importą,
klaidingų eilučių ataskaitos atsisiuntimo (CSV), pasirinkimo „praleisti / atnaujinti / naujas".

### C8. Masiniai veiksmai — išplėtimas — 🟡
Yra archyvuoti + eksportuoti. Trūksta: pridėti/šalinti žymą, keisti kategoriją,
masinis dublikatų sujungimas.

### C9. Pilna atsarginė kopija iš sąsajos (ZIP/CRM paketas su failais) — ❌
Reikalauta atskirai nuo CSV. Nustatymuose „Duomenų eksportas" → visas DB + `runtime/media`.

---

## D. Žemas prioritetas / vėliau

- ❌ El. pašto priminimai (reikia SMTP + worker; B5 ir B3 dalis)
- ❌ PWA režimas (manifest.json, service worker, „pridėti į pradinį ekraną")
- ❌ Neišsaugotų formos pakeitimų perspėjimas (`beforeunload`)
- ❌ Grafinis ryšių medis (dabar tekstinis sąrašas — pakanka)
- ❌ Veiklos tipai „Failas" ir „Sistemos pakeitimas"
- ❌ Greiti veiksmai kortelėje (Skambinti / Rašyti / Registruoti skambutį / Planuoti susitikimą)
- ❌ Žymų/kategorijų: aktyvi/neaktyvi, archyvavimas, paskirtis (kontaktams/įmonėms/abiem)
- 🟡 Mobilus vaizdas — bazinis yra, reikia tankio ir lentelių peržiūros
- 🟡 Retesni klaidų/tuščių būsenų ekranai, LT/EN spragos retose vietose

---

## Siūloma vykdymo tvarka

1. **B1** išsaugotų filtrų pervadinimas / trynimas / numatytasis
2. **B2** greiti veiksmai eilutėje (pastaba, priminimas, kopijuoti el. paštą)
3. **B4** slaptažodžio keitimas profilyje
4. **B6** priedų dydžio/tipo validacija · **B7** idle-timeout (maži, saugumo)
5. **C1** sąrašų UX likučiai (paryškinimas, „atšaukti pasirinkimą", pilna navigacija, stulpeliai)
6. **C2** paskutinio/kito kontakto info
7. **B5 + C9** atsarginės kopijos (automatinės + eksportas iš sąsajos)
8. **C7 / C8** importo vedlys ir masinių veiksmų išplėtimas
9. **C3** universali paieška su grupėmis
10. **C5** auditas · **C4** individualūs laukai · **C6** naudotojai/rolės
11. **D** likučiai (PWA, el. paštas, kortelės greiti veiksmai, taksonomijų būsenos)

Kiekvienas punktas — pagal `CLAUDE.md` taisykles: minimalus kodas → testai →
naršyklė → diegimas per UGREEN → GitHub.

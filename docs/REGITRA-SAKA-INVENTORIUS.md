# `regitra` šakos inventorius (E0-01)

Užduotis E0-01 iš `docs/IGYVENDINIMO-PLANAS.md`. Būsena **2026-10-30**:
`main` 388ffd4, `regitra` 09d5e0e, bendras protėvis `3c41a72`
(`regitra-base-0.79.0`, 2026-09-19).

Šaka turi **41 savą commit'ą**, `main` — **56**, kurių šaka neturi. Žemiau
kiekvienam šakos commit'ui ir kiekvienai migracijai — sprendimas, kuriuo
remsis E0-02…E0-05.

Grupės:
- **A — jau yra `main`.** Atitikmuo `main` istorijoje (dažnai rankinis perkėlimas,
  todėl `git cherry` jų nemato kaip vienodų). Pavijus imama `main` versija.
- **B — bendrinis, perkelti į `main`.** Pataisymas ar funkcija be Regitros
  specifikos, kurios `main` neturi. Kiekvienas — atskiras commit'as į `main`
  prieš pavijimą (E0-04), kad merge'o konfliktų būtų mažiau.
- **C — Regitros specifika.** Lieka Regitros sluoksnyje (programėlė `regitra/`
  arba atskiras repozitorijus — sprendimas S1).

Suvestinė: **A — 13, B — 8, C — 20.**

---

## 1. Commit'ai

### A — jau yra `main` (13)

| Šakos commit | Kas | `main` atitikmuo | Pastaba |
|---|---|---|---|
| `b639dc4` | Slaptažodžio atkūrimas, prisijungimo langas, vadovo (manager) rolė | `b072202` | `main` vėliau dar pataisyta `0a0befb` (atsakymo laikas neišduoda paskyros) |
| `62f2aff` | Mygtukų dydžių skalė | `cf6f080` | |
| `5416acb` | Paviršių skalė | `0e5c6e4` | |
| `01b8658` | Klaidų puslapiai | `3a408cf` | |
| `ffea85b` | Leidimas mygtuku (`release.yml`) | `ae9a71c` | |
| `d014933` | Meniu be „Daugiau“ | `f1dee2b` | |
| `d5cf042` | Priminimas kaip įvykis API ir DWH | `1ed3673` | Šakos migracija `0060` = `main` `0055` (turinys sutampa) |
| `f9a1d0e` | Staging viešinimas tik su dviem žymėmis | `e67e70f` | |
| `c269daf` | Staging viešinimas iš Actions | `ca9c30e` | |
| `ff7e13d` | Asmens kodas kortelėje užmaskuotas, peržiūra žurnale | `b7e1f7b` | **Kitas įgyvendinimas:** šaka žurnale rašo veiksmą `personal_code`, `main` — `view` su `field="personal_code"`. Imama `main` (žr. M4) |
| `4a2b746` | Staging kopija neturi tikrų asmens kodų | `main` `anonymize.py` (valo `personal_code_*`) | Kita schema; po E0-02 galioja `main` versija |
| `dbd10d7` | `127.0.0.1` būtinas `ALLOWED_HOSTS` sveikatos patikrai | `main` `HealthProbeMiddleware` | `main` išspręsta kitaip: `/health/*` atsako prieš Host tikrinimą. Šakos taisyklė nebereikalinga |
| `5f327fe` | Rolių ir blokų lentelės netilpo, be linijų | `d241eaf`, `ad161d1` | Rolių lentelė — `main`; blokų lentelės dalis eina kartu su E0-05 |

### B — bendrinis, perkelti į `main` (8)

| Šakos commit | Kas | Kodėl `main` reikia | Kur |
|---|---|---|---|
| `9209607` | Asmens kodas su neegzistuojančia gimimo data atmetamas | **Klaida `main`:** `identity.normalize()` tikrina tik kontrolinį skaitmenį. `49913011235` (99-as mėnuo), vasario 31-oji praeina | `contacts/identity.py`, testas |
| `b4ca30e` | Žurnalo lentelė nebekapoja žodžių | `main` `theme.css` tebeturi `.audit-table{table-layout:fixed}` ir fiksuotus procentus | `static/css/theme.css` |
| `afad5fd` | Teisių lentelė plačiame ekrane neišsitempia | `main` `.permissions-table` neturi `max-width` | `static/css/theme.css`, `templates/import_export.html` |
| `867e618` | Apkrovos testas: klaida ≠ lėtumas, lėtumas tikrinamas du kartus | `main` `ci.yml` „Check thresholds“ krenta nuo vieno lėto runner'io paleidimo | `.github/workflows/ci.yml`, `scripts/loadtest/thresholds.py` |
| `7debc74` | `refresh-staging.sh` randa konteinerį per compose | `main` `refresh-staging.sh:54` — fiksuotas vardas `crm-staging-crm-web-1` | `scripts/refresh-staging.sh` |
| `d89b6e9` | `refresh-staging.sh` atkuria į tuščią DB | `main` naudoja `pg_restore --clean --if-exists` — likęs stulpelis iš kitos šakos sugadina `migrate` | `scripts/refresh-staging.sh` |
| `b96d8d3` | Workflow parodo, ką Tailscale padarė su serve konfigūracija | `main` `regitra-staging-public.yml` to žingsnio neturi — Funnel atsisakymas lieka nematomas | `.github/workflows/regitra-staging-public.yml` |
| `a7e4fdf` | Registrų blokų matomumas pagal rolę | Generinė blokų jungtis — į `main` pagal S1 | **E0-05**, ne atskiras perkėlimas |

### C — Regitros specifika (20)

| Šakos commit | Kas | Sritis |
|---|---|---|
| `10da00a` | `RecordAccess`: kas, kurį įrašą, kodėl, iki kada | Prieiga su pagrindu |
| `a148d24` | Rolė lemia, ar atviras priminimas laiko įrašą sąraše (`can_keep_with_reminder`) | Prieiga su pagrindu |
| `c6e28bb` | Sąrašas = aktyvūs įrašai; matomumai `own_active`, `team_active` | Prieiga su pagrindu (vadovo rolės dalis jau `main`, A) |
| `e0930a5` | Paieška su pagrindu `/paieska/` | Prieiga su pagrindu |
| `eafd88b` | Vadovas įdeda / atima įrašą darbuotojo sąraše | Prieiga su pagrindu |
| `13dfd3d` | Kortelė rodo, kas atvėrė; žurnalas — kaip | Prieiga su pagrindu |
| `fa8ada1` | Paieškos laukas atsako tik pagal įvardytą asmenį | Prieiga su pagrindu |
| `8cdd78e` | Nesėkminga paieška žurnale (`search_miss`, be užklausos turinio) | Prieiga su pagrindu |
| `9c42237` | Komandos vadovas mato savo žmonių žurnalą | Prieiga su pagrindu (žr. M2 — `Team.leads`) |
| `866e44d` | Atskira Regitros staging instancija | Regitros staging |
| `4e7d246` | Vienos komandos staging sąranka NAS | Regitros staging |
| `6fb6a02` | Sąranka iš Actions | Regitros staging |
| `1ab0822` | Aiškus pranešimas, kai runner'is nemato katalogo | Regitros staging |
| `91a0704` | NAS keliai `/volume1/docker` | Regitros staging |
| `4f76fbd` | Numatytasis staging katalogas | Regitros staging |
| `e684511` | Perdanga nepublikuoja prievadų | Regitros staging |
| `c9b296a` | Kaip atverti instanciją internetui | Regitros staging |
| `09d5e0e` | Regitros prekės ženklas: paletė, logotipas, šriftas Barlow | Išvaizda |
| `446e8b4` | Šakos aprašas | Šakos dokumentacija |
| `6b62ebe` | Kiek šaka atsilikusi | Šakos dokumentacija |

Be to, iš bendro protėvio `3c41a72` šaka paveldi tai, ką `main` pašalino `daed7b7`:
`Person.personal_code` (atviras tekstas), `contacts/validators.py`, `record_blocks.py`
su 18 placeholder'ių, `record_blocks_demo.py`. Sprendimai: asmens kodas → E0-02,
blokų jungtis → E0-05, placeholder'iai ir demo duomenys → Regitros sluoksnis (E0-07).

---

## 2. Migracijos

`main` nuo protėvio pridėjo `0055`–`0062`; šaka — taip pat `0055`–`0062`.
Numeriai sutampa, turinys skiriasi.

| Šaka | Ką daro | `main` atitikmuo | Sprendimas |
|---|---|---|---|
| `0055_person_personal_code` | `Person.personal_code` `CharField(11)`, atviras tekstas | `0060_person_identity` (šifruotas + maiša) | **Atmesti.** E0-02: duomenų migracija į `personal_code_encrypted` / `_hash`, stulpelis šalinamas |
| `0056_team_leads_recordaccess` | `Team.leads` (M2M) + `RecordAccess` | nėra | Išlaikyti, numeris po `main` viršūnės. Vieta — žr. M2 |
| `0057_alter_directorygroupmapping_role_and_more` | Rolės su `manager` + matomumai `team_active`, `own_active` | `0056_alter_directorygroupmapping_role_and_more` (tik rolės) | **Skaidyti:** rolių dalis = `main` `0056` (atmesti); matomumų dalis — nauja migracija |
| `0058_alter_auditlog_action` | Veiksmas `access` | nėra | Sujungti su `0059`, `0062` į vieną (žr. M4) |
| `0059_alter_auditlog_action` | Veiksmas `personal_code` | `main` — `view` su `field` | **Atmesti** veiksmą; esamos eilutės → `view` (žr. M4) |
| `0060_reporting_reminder_kind` | `reporting` rodinys su priminimo rūšimi | `0055_reporting_reminder_kind` (sutampa) | **Atmesti** |
| `0061_rolepermissions_blocks` | `RolePermissions.blocks` | nėra | Į `main` per E0-05 kaip `0063` |
| `0062_alter_auditlog_action` | Veiksmas `search_miss` | nėra | Sujungti su `0058` (žr. M4) |

Šakai trūksta visų aštuonių `main` migracijų `0055`–`0062`:
`reporting_reminder_kind`, vadovo rolė, `duplicate_candidates`, `search_trigram_indexes`,
`analytics_snapshot`, `person_identity`, `userprofile_layout_config`, `content_page`.

Tikslinis grafas (jei S1 = programėlė šiame repozitorijuje):

```
main: … 0062_content_page → 0063_rolepermissions_blocks (E0-05)
                          → 0064_team_leads (M2, jei bendrinis)
                          → 0065_visibility_and_audit_registry (M3, M4)
regitra/: 0001_record_access (priklauso nuo contacts 0065)
          0002_personal_code_to_identity (E0-02, tik jei S3 = migruoti esamą DB)
```

---

## 3. Radiniai, kurie keičia E0-02…E0-05

**M1. Bendro protėvio migracija `0055_person_personal_code` `main` istorijoje
neegzistuoja** (pašalinta `daed7b7`), o Regitros staging DB ji pritaikyta.
`git merge main` paliks du `0055` mazgus su vienu tėvu (`0054_event_kind`) —
`migrate` atsisakys dirbti, kol grafas nesutvarkytas. Tai patvirtina S3 siūlymą
(atkurti staging DB iš naujo, ne migruoti).

**M2. `Team.leads` — laukas bendrinio CRM modelyje.** Jei Regitros dalis taps
atskira programėle (S1), jos migracijos negali pridėti lauko `contacts.Team`
modeliui. Variantai: (a) `Team.leads` → `main` kaip bendrinė funkcija
(komandos vadovas — prasminga ir be Regitros); (b) atskiras modelis
`regitra.TeamLead`. **Siūlymas: (a).**

**M3. Matomumai `own_active` / `team_active` — `UserProfile.record_visibility`
pasirinkimai.** Tas pats apribojimas kaip M2: programėlė negali praplėsti
`contacts` modelio `choices`. Reikia generinio plėtinio taško `main`:
`permissions.register_visibility(key, label, person_q, company_q)`, o laukas be
uždaro `choices` sąrašo (tikrinama pagal registrą). Tai ir yra mechanizmas,
kuriuo Regitros prieigos modelis prisijungia prie `visible_people()` /
`visible_companies()` nekeičiant `main` logikos.

**M4. Žurnalo veiksmai.** Šaka prideda `access`, `personal_code`, `search_miss`
į `AuditLog.ACTION_CHOICES`. `personal_code` dubliuoja `main` `view` +
`field="personal_code"` — atmetamas. `access` ir `search_miss` — per tą patį
registrą kaip M3 (`audit.register_action`), kad programėlė pridėtų savo veiksmus be
`contacts` migracijos. `AuditLog` eilutės nekeičiamos (DB trigeris, migracija 0047),
todėl esamų `personal_code` eilučių perrašyti negalima — dar viena priežastis
atkurti Regitros staging DB iš naujo (S3).

**M5. Apimties pataisa.** B grupės 7 perkėlimai (be `a7e4fdf`) yra smulkūs ir
nepriklauso nuo S1–S3 — juos galima daryti iškart, kiekvieną atskiru commit'u į
`main`. M2–M4 registrai yra nauja E0-03 dalis: E0-03 apimtis **M → L**.

---

## 4. Kitas žingsnis

1. ~~B grupė → `main`~~ — **atlikta 2026-10-30**:

   | Šakos | `main` |
   |---|---|
   | `9209607` | `c0bdcc1` |
   | `b4ca30e` | `c5ecd97` |
   | `afad5fd` | `614fa2a` (lentelė), `b320fb4` (rašyba) |
   | `867e618` | `ca45474` |
   | `7debc74` | `422b074` (be Regitros staging komentaro ir `/volume1` kelių) |
   | `d89b6e9` | `d532d52` |
   | `b96d8d3` | `d780789` |

   Pavijimo (E0-04) metu šių commit'ų konfliktuose imama `main` versija.
2. S1–S3 atsakymai → E0-02, E0-03 (su M2–M4), E0-04.

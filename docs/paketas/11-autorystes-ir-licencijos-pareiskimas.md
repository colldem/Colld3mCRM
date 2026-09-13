# Autorystės, licencijos ir komponentų pareiškimas (juodraštis)

> **Juodraštis teisininkui peržiūrėti — ne teisinė konsultacija.** Pažymėtos vietos
> `[PASIRINKTI]` priklauso nuo aplinkybių, kurias žino tik autorius ir organizacija
> (ar kodas kurtas darbo metu, ar numatytas atlygis už priežiūrą).

## 1. Programinė įranga

| | |
|---|---|
| Pavadinimas | Colld3m CRM |
| Versija | žr. `VERSION` (pareiškimo data: [ ]) |
| Šaltinio kodas | Git repozitorija [adresas], perduodama organizacijai su visa istorija |
| Licencija | MIT (failas `LICENSE`) |

## 2. Autorystė

Aš, [vardas, pavardė], pareiškiu, kad:

1. Esu programinės įrangos kūrėjas. Kodas kurtas naudojant dirbtinio intelekto
   asistentus (ChatGPT, Claude) — sugeneruotą kodą peržiūrėjau, ištestavau ir
   priėmiau kaip savo darbo dalį; programoje nėra žinomai nukopijuoto trečiųjų
   šalių kodo, išskyrus 4 skyriuje nurodytus atvirojo kodo komponentus pagal jų licencijas.
2. [PASIRINKTI]
   - **(a)** Kodas sukurtas asmeniniu laiku ir asmeninėmis priemonėmis, ne darbo
     pareigų vykdymo metu; turtinės teisės priklauso man, o organizacija programą
     naudoja pagal MIT licenciją; **arba**
   - **(b)** Kodas sukurtas vykdant darbo funkcijas; turtinės teisės priklauso
     darbdaviui pagal Lietuvos Respublikos autorių teisių ir gretutinių teisių įstatymą; **arba**
   - **(c)** Mišri situacija: [aprašyti], sprendžia teisininkas.

## 3. Licencijos reikšmė organizacijai (MIT)

- Organizacija gali naudoti, keisti, platinti ir diegti programą be mokesčio ir
  be leidimo, išsaugodama autorių teisių pranešimą ir licencijos tekstą.
- Programa teikiama „tokia, kokia yra": autorius neprisiima garantijų ir
  atsakomybės pagal licenciją. Priežiūros, atsakomybės ar paslaugų lygio
  įsipareigojimai galimi tik atskiru susitarimu (žr. 5).
- Licencija neatšaukiama organizacijos jau gautai kopijai.

## 4. Trečiųjų šalių komponentai

Pilnas sąrašas su versijomis — CycloneDX SBOM kiekvieno CI paleidimo artefaktuose
(`sbom-python`, `sbom-image`). Pagrindiniai:

| Komponentas | Licencija | Pastaba |
|---|---|---|
| Django 5.2 | BSD-3-Clause | |
| django-axes | MIT | |
| argon2-cffi | MIT | |
| Gunicorn | MIT | |
| psycopg 3 (binary) | **LGPL-3.0-only** | naudojama kaip nemodifikuota biblioteka; LGPL leidžia naudoti su bet kokios licencijos programa |
| WhiteNoise | MIT | |
| openpyxl | MIT | |
| mozilla-django-oidc | **MPL-2.0** | failų lygmens copyleft taikomas tik pačios bibliotekos failų pakeitimams; jie nedaromi |
| cryptography | Apache-2.0 arba BSD-3-Clause | |
| django-storages | BSD-3-Clause | |
| requests, josepy | Apache-2.0 | |
| AdminLTE 4, Bootstrap 5 (sąsaja) | MIT | įdiegta vietoje |
| PostgreSQL 17 (konteineris) | PostgreSQL License | atskira programa |
| ClamAV (konteineris, neprivaloma) | **GPL-2.0** | atskira programa, bendraujama per tinklo protokolą; su CRM nesusiejama |
| age, rclone (kopijų konteineris) | BSD-3-Clause, MIT | atskiros programos |

Nė vienas komponentas neįpareigoja organizacijos atskleisti CRM šaltinio kodo ar
mokėti licencijos mokesčių.

## 5. Priežiūra ir interesų konfliktas

[PASIRINKTI]
- **(a)** Priežiūrą atlieka organizacijos darbuotojai (įskaitant mane pagal darbo
  pareigas); atlygis už programą ar jos priežiūrą nenumatytas; **arba**
- **(b)** Numatomos mokamos paslaugos (diegimas, priežiūra, plėtra) — jos
  perkamos pagal organizacijos viešųjų pirkimų tvarką; aš, būdamas [darbuotojas /
  išorinis asmuo], pateikiu nešališkumo ir interesų konflikto deklaraciją ir
  nedalyvauju sprendimuose dėl tokių pirkimų.

## 6. Parašai

| | Vardas, pavardė | Parašas | Data |
|---|---|---|---|
| Autorius | [ ] | | |
| Organizacijos atstovas | [ ] | | |

# Colld3m CRM

Django CRM kontaktiniams asmenims ir įmonėms, jų ryšiams, bendravimo istorijai,
failams ir priminimams tvarkyti. Veikia naršyklėje, produkcijoje – UGREEN NAS
Docker konteineriuose, pasiekiama per Tailscale HTTPS.

Dabartinė versija: žr. [`VERSION`](VERSION). Techninė ir naudotojo dokumentacija –
programoje: **Nustatymai → Dokumentacija**.

## Funkcijos

- Autentifikacija, prisijungimų ribojimas, rolės (administratorius / visi įrašai /
  tik savi įrašai), rolių teisių lentelė, komandos ir įrašų matomumas
  (visi / komandos / savi).
- Asmenys, įmonės ir jų ryšiai; daugiareikšmiai telefonai, el. paštai, adresai, URL.
- Kontaktų ir įmonių sąrašai: paieška, išplėsti filtrai, išsaugoti filtrai,
  rikiavimas, pasirinktiniai stulpeliai, 50 / 100 eilučių puslapiavimas, masiniai
  veiksmai.
- Kontakto ir įmonės kortelės su inline redagavimu, bendravimo istorija, failais,
  priminimais ir komentarais.
- Darbastalis (darbotvarkė, vėluojantys priminimai, savaitės veiklos) ir analitika
  (ryšių priežiūra, komunikacijos, priminimų vykdymo ir bazės augimo statistika su
  SVG grafikais, sistemos naudojimas).
- Kalendorius su dienos / savaitės / mėnesio vaizdu.
- Žymos, kategorijos, dinaminiai laukai; dublikatų aptikimas ir sujungimas.
- CSV / XLSX kontaktų importas, CSV eksportas, pilna ZIP atsarginė kopija.
- Veiksmų žurnalas (audit log). LT / EN sąsaja.

Pirmoji administratoriaus paskyra sukuriama adresu `/setup/` naudojant vienkartinį
`CRM_SETUP_TOKEN`. Sukūrus pirmą naudotoją setup puslapis automatiškai išsijungia.

## Technologijos

Python 3.13 · Django 5.2 · PostgreSQL 17 (produkcijoje) / SQLite (lokaliai) ·
Gunicorn · WhiteNoise · django-axes · Argon2 · AdminLTE 4 + Bootstrap 5 (įdiegti
vietoje) · Tailscale. Grafikai – rankomis generuojamas SVG be išorinių bibliotekų.

Išsamus architektūros aprašymas: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Vietinė patikra

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
PYTHON_BIN=.venv/bin/python sh scripts/release-check.sh
```

`release-check.sh` paleidžia `makemigrations --check`, visus testus ir
`manage.py check --deploy`. Lokalus serveris:
`DJANGO_DEBUG=true .venv/bin/python manage.py runserver 127.0.0.1:8765`.

## Diegimas

Žr. [`docs/DEPLOYMENT-UGREEN.md`](docs/DEPLOYMENT-UGREEN.md). Prieš kiekvieną
diegimą būtina PostgreSQL ir `runtime/media` atsarginė kopija.

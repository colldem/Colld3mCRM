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
  rikiavimas, pasirinktiniai stulpeliai, puslapiavimas. Masiniai veiksmai:
  žymos/kategorijos/atsakingo priskyrimas, dinaminio lauko nustatymas, papildomas
  atsakingas, užduoties ar veiklos sukūrimas pažymėtiems, archyvavimas ir
  atkūrimas.
- Kontakto ir įmonės kortelės su inline redagavimu, bendravimo istorija, failais,
  priminimais ir komentarais.
- Darbastalis (darbotvarkė, vėluojantys priminimai, savaitės veiklos) ir analitika
  (ryšių priežiūra, komunikacijos, priminimų vykdymo ir bazės augimo statistika su
  SVG grafikais, sistemos naudojimas).
- Kalendorius su dienos / savaitės / mėnesio vaizdu; pasikartojantys priminimai;
  `.ics` prenumeratos nuoroda (Google / Outlook / Apple).
- Užduočių priskyrimas kolegai su prioritetu.
- El. pašto pranešimai (artėjantis įvykis, rytinė santrauka, priskirta užduotis) –
  SMTP konfigūruojamas Nustatymuose; be jo laiškai rašomi tik į žurnalą.
- Gautų el. laiškų prisegimas prie kontaktų per IMAP dėžutę.
- Prisijungimas per Microsoft Entra ID (OIDC) šalia vietinio prisijungimo.
- Žymos, kategorijos, dinaminiai laukai; dublikatų aptikimas ir sujungimas.
- CSV / XLSX kontaktų importas, CSV eksportas, pilna ZIP atsarginė kopija.
- Automatikos taisyklės („kai kontaktas nutilo / liko be atsakingo / priminimas
  vėluoja → pranešti / priskirti / sukurti užduotį / pridėti žymą"), vykdomos fone.
- REST API (`/api/v1/`, „Bearer" raktai iš Nustatymų → Integracijos) kontaktams,
  įmonėms, veikloms ir priminimams skaityti/rašyti; webhookai su HMAC parašu.
- Veiksmų žurnalas (audit log). LT / EN sąsaja.

El. paštas, gaunami laiškai ir Entra ID prisijungimas įjungiami ir suvedami
Nustatymų languose (Pranešimai / Gauti laiškai / Prisijungimas), be konteinerio
perkrovimo. Slaptažodžiai duomenų bazėje šifruojami raktu `CRM_SECRETS_KEY` iš
`.env` (žr. [`.env.example`](.env.example)).

Pirmoji administratoriaus paskyra sukuriama adresu `/setup/` naudojant vienkartinį
`CRM_SETUP_TOKEN`. Sukūrus pirmą naudotoją setup puslapis automatiškai išsijungia.

## Technologijos

Python 3.13 · Django 5.2 · PostgreSQL 17 (produkcijoje) / SQLite (lokaliai) ·
Gunicorn · WhiteNoise · django-axes · Argon2 · mozilla-django-oidc · cryptography ·
AdminLTE 4 + Bootstrap 5 (įdiegti vietoje) · Tailscale. Grafikai – rankomis
generuojamas SVG be išorinių bibliotekų. Foniniai darbai – `crm-worker` konteineris.

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

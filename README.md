# CRM 0.3.0

CRM: autentifikacija, asmenys, įmonės, jų ryšiai, kontaktų paieška, filtrai, išsaugoti filtrai, rikiavimas, pasirinktiniai stulpeliai, 50 arba 100 eilučių puslapiavimas, archyvas, kontakto kortelė, kontaktų istorijos įrašai su failais, priminimų centras ir CSV arba XLSX importas bei CSV eksportas.

Pirmoji administratoriaus paskyra sukuriama adresu `/setup/` naudojant vienkartinį `CRM_SETUP_TOKEN`. Sukūrus pirmą naudotoją setup puslapis automatiškai išsijungia.

## Vietinė patikra

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py test
```

## Ribos

Nėra atskiro „Veiklos“ puslapio. Kontaktų istorija pasiekiama tik konkretaus kontakto kortelėje. Prieš diegimą į UGREEN būtina atlikti atsarginę PostgreSQL ir `runtime/media` katalogo kopiją.

# Regitros integracija atskirame repozitorijuje

Colld3m CRM lieka bendrinis produktas. Viskas, kas specifiška Regitrai —
registrų laukai, jų modeliai, migracijos ir duomenų traukimas — gyvena atskirame
repozitorijuje ir įsidiegia į CRM kaip Django programėlė. Taip bendrinį CRM
galima vystyti toliau nieko nešakojant (`fork`), o Regitros pusę — savo tempu.

## Sąlyčio taškas

Vienintelis, ir sąmoningai siauras: kortelės vidurinė kolona.
`contacts/record_blocks.py` laiko blokų sąrašą ir eilę; CRM registruoja tik
tuščius blokus su paaiškinimu, ką juose matysime:

Blokas priklauso kontakto kortelei, įmonės kortelei arba abiem:

| Raktas | Blokas | Kortelė |
| --- | --- | --- |
| `licence` | Vairuotojo pažymėjimas | kontakto |
| `exams` | Egzaminai | kontakto |
| `vehicles` | Automobiliai | kontakto |
| `fleet` | Transporto priemonių parkas | įmonės |
| `plates` | Valstybiniai numeriai | kontakto |
| `trade_plates` | Laikinieji (prekybiniai) numeriai | įmonės |
| `statuses` | Statusai | įmonės |
| `contracts` | Sutartys | įmonės |
| `visits` | Vizitai padaliniuose | kontakto |
| `requests` | Prašymai | abi |
| `mandates` | Įgaliojimai | kontakto |
| `representatives` | Atstovai ir įgaliojimai | įmonės |
| `authenticity` | Autentiškumo patikrinimai | įmonės |
| `certificates` | Pažymos ir išrašai | kontakto |
| `services` | Neseniai suteiktos paslaugos | abi |
| `payments` | Mokėjimai ir skolos | kontakto |
| `invoices` | Mokėjimai ir sąskaitos | įmonės |
| `messages` | Išsiųsti SMS | abi |

Sąrašas sudarytas pagal regitra.lt paslaugų katalogą (2026 m. rugsėjis) ir
klientų aptarnavimo scenarijų: pirma tai, kas turi terminą ar būseną, paskui
istorija. Tai hipotezė — tikrieji laukai derinami su registro schema.

Integracija tuo pačiu raktu perima bloką, o nauju raktu — prideda savo:

```python
# regitra/apps.py
from django.apps import AppConfig


class RegitraConfig(AppConfig):
    name = "regitra"

    def ready(self):
        from contacts.record_blocks import register_block
        from .loaders import load_vehicles

        register_block("vehicles", "Automobiliai",
                       template="regitra/_vehicles.html", loader=load_vehicles)
```

`loader(record)` gauna `Person` arba `Company` ir grąžina šablono kontekstą.
CRM niekur neimportuoja `regitra` — be jos kortelė veikia lygiai taip pat.

Kitos jau esamos prieigos, kurių nereikia kurti iš naujo: `/api/v1/` REST
sluoksnis (`contacts/api.py`), webhook'ai (`contacts/webhooks.py`), automatikos
taisyklės (`contacts/automation.py`) ir dinaminiai laukai (`CustomField`)
paprastiems papildomiems laukams be savo modelio.

## Repozitorijaus struktūra

```
colld3m-regitra/
  regitra/                  # Django app: models, migrations, loaders, templates
  tests/
  requirements.txt          # pin'as: colld3m-crm @ git+…@vX.Y.Z
  compose.regitra.yaml      # perdanga virš CRM compose.yaml
  deploy/Dockerfile         # crm-web atvaizdas + pip install regitra
  .github/workflows/        # ci.yml, deploy-staging.yml, deploy.yml
  README.md
```

Diegimas: `pip install git+https://github.com/<org>/colld3m-regitra@vX.Y.Z`,
`CRM_EXTRA_APPS=regitra` (CRM pats pasiima jį į `INSTALLED_APPS`), `manage.py migrate`.

## Keturios aplinkos

Du produktai × prod/staging. Kiekvienai — savas hostname, savas Docker
stack'as ir sava duomenų bazė; jos niekuo nesidalija.

| Aplinka | Repozitorijus | `CRM_ENVIRONMENT` | Stack'as |
| --- | --- | --- | --- |
| CRM prod | Colld3mCRM | `production` | `compose.yaml` |
| CRM staging | Colld3mCRM | `staging` | `compose.yaml` + `compose.staging.yaml` |
| Regitra prod | colld3m-regitra | `production` | `compose.yaml` + `compose.regitra.yaml` |
| Regitra staging | colld3m-regitra | `staging` | visi trys |

Kiekvienos aplinkos hostname nustatomas jos `.env` faile (`CRM_DOMAIN`,
`DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `CRM_BASE_URL`) — žr.
`docs/DEPLOYMENT.md`. Tailscale `serve` konfigūracija — `deploy/serve*.json`;
staging'ui Funnel išjungtas.

Ką svarbu išlaikyti:

- **Atskiri konteinerių ir tomų vardai.** `COMPOSE_PROJECT_NAME` kiekvienai
  aplinkai skirtingas, kitaip antras stack'as perrašys pirmo duomenis.
- **Atskiri portai** ties Tailscale `serve`, jei visos keturios sukasi tame
  pačiame NAS.
- **`CRM_ENVIRONMENT=staging`** abiejose staging aplinkose — tai išjungia el.
  paštą, IMAP, Entra ir webhook'us, kad iš produkcijos atkurta kopija neveiktų
  realiame pasaulyje (`contacts/integrations.py`).
- **Atskiri `CRM_SECRETS_KEY` ir `DJANGO_SECRET_KEY`.**
- **Naudotojai keliauja su duomenimis.** `scripts/refresh-staging.sh` nukopijuoja
  produkcijos bazę į staging, todėl staginge galioja tie patys prisijungimai kaip
  produkcijoje; po kopijavimo paleidžiamas `manage.py sanitize_staging`.

## Versijavimas

Regitros repozitorijus prisisega prie CRM žymos (`v0.79.0`), o ne prie `main`.
Kėlimas į naują CRM versiją — atskiras, sąmoningas commit'as Regitros pusėje.

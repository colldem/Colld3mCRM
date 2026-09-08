# Colld3m CRM — darbo taisyklės

Django 5.2 CRM (kontaktai, įmonės, veiklos, priminimai). Produkcija: UGREEN NAS
Docker, pasiekiama per Tailscale HTTPS (`https://crm.tailb8493f.ts.net`).
GitHub: `github.com/colldem/Colld3mCRM` (`main`).

## Taisyklės KIEKVIENAM pakeitimui

1. **Tik konkreti funkcija.** Kodas rašomas tik tai užduočiai. Jokio
   „papildomo" refaktorinimo, jokių nesusijusių pataisymų tame pačiame diff'e.
   Prieš baigiant — peržiūrėti diff'ą ir patikrinti, ar kiekviena eilutė
   priklauso šiai funkcijai. Nereikalingas senas kodas (dead code, nebenaudojami
   vertimai ir pan.), atsiradęs dėl pakeitimo, pašalinamas.
2. **Testai.** Paleisti visą patikrą ir įsitikinti, kad viskas žalia:
   ```bash
   PYTHON_BIN=.venv/bin/python sh scripts/release-check.sh
   ```
   (leidžia `makemigrations --check`, 96+ testus ir `manage.py check --deploy`).
   Naujai logikai — pridėti testą į `tests/test_contacts.py` ar `tests/test_theme.py`.
3. **Patikra naršyklėje.** Paleisti lokalų serverį ir realiai patikrinti
   pakeitimą naršyklėje (LT ir, jei liečia sąsają, EN; desktop ir mobilus vaizdas):
   ```bash
   DJANGO_DEBUG=true .venv/bin/python manage.py runserver 127.0.0.1:8765
   ```
   Lokalus adminas: `dev` / `devlocalpass123` (tik lokali SQLite, ne produkcija).
4. **Diegimas į Docker.** Kodą į NAS kelia naudotojas per UGREEN programėlę,
   tada `docker compose build --pull && docker compose up -d`. Patikrinti, kad
   `crm-db`, `crm-web`, `crm-tailscale` yra healthy ir `/health/ready` = `ready`.
   Jei keitėsi funkcionalumas — bumpinti `VERSION` ir `image: crm-web:X.Y.Z`
   tag'ą `compose.yaml`.
5. **GitHub.** Tik po sėkmingo diegimo — `git push` į `main`. Commit žinutė
   `fix:` / `feat:` / `chore:` stiliumi, glausta, apie tą vieną pakeitimą.
6. **Dokumentacija.** Jei pakeitimas prideda ar keičia funkciją, matomą
   naudotojui (naują langą, mygtuką, nustatymą, prieigos taisyklę), tame
   pačiame pakeitime atnaujinti in-app žinyną `templates/settings/documentation.html`
   ir, jei keičiasi funkcijų sąrašas ar priklausomybės — `README.md` bei šio
   failo „Struktūra" sąrašą. Versijos numeris žinyne imamas iš `VERSION`.

## Aplinka

- `.venv/` — Python 3.12, priklausomybės iš `requirements.txt` + `django-axes`.
- Lokaliai DB = SQLite (`db.sqlite3`, gitignore). Produkcijoje = PostgreSQL.
- Vertimai: `locale/en/LC_MESSAGES/*.po`; perkompiliuoti `.mo`:
  `msgfmt locale/en/LC_MESSAGES/djangojs.po -o locale/en/LC_MESSAGES/djangojs.mo`
- Statiniai failai turi `?v=YYYYMMDD` cache-buster'į `templates/base.html` —
  keičiant `static/css/*` ar `static/js/*` bumpinti atitinkamą reikšmę.

## Struktūra

- `contacts/models.py` — Person, Company, PersonCompanyLink, Activity,
  Attachment, Reminder, Tag, Category, SavedFilter, UserProfile, Team,
  RolePermissions, AuditLog, CustomField, CustomValue, DuplicateSettings,
  SystemSettings.
- `contacts/views.py` — pagrindiniai puslapiai; `analytics_views.py` —
  darbastalis ir analitika; `calendar_views.py` — kalendorius;
  `detail_editing.py` / `inline_views.py` — AJAX laukų redagavimas;
  `duplicates.py` / `merging.py` — dublikatai; `filters.py` — sąrašų filtrai;
  `permissions.py` — rolės, teisės ir įrašų matomumas; `charts.py` — SVG grafikai;
  `notifications.py` + `management/commands/send_notifications.py` — el. pašto pranešimai;
  `recurrence.py` + `management/commands/extend_recurrences.py` — pasikartojantys priminimai;
  `ical.py` — .ics kalendoriaus srautas; `sanitizers.py` — `safe_url` / `csv_safe`.
- `templates/` — Django šablonai; `static/` — CSS/JS + `vendor/adminlte`.
- `docs/DEPLOYMENT-UGREEN.md` — diegimo procedūra; prieš diegimą būtina DB ir
  `runtime/media` atsarginė kopija.

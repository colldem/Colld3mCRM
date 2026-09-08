# CRM 0.4.0 diegimas UGREEN

Ši versija diegiama kaip atskiras Compose projektas. Ji nekeičia techninio projekto `crm-technical-test`, kol nėra atlikta atskira migracijos ir perjungimo procedūra.

## Privalomi `.env` laukai

- `POSTGRES_PASSWORD` - ilga atsitiktinė PostgreSQL reikšmė.
- `DJANGO_SECRET_KEY` - bent 50 atsitiktinių simbolių.
- `CRM_SETUP_TOKEN` - vienkartinis diegimo kodas.
- `DJANGO_ALLOWED_HOSTS` - tikras Tailscale DNS vardas.
- `DJANGO_CSRF_TRUSTED_ORIGINS` - tas pats vardas su `https://`.
- `TS_CERT_DOMAIN` - tas pats Tailscale DNS vardas.
- `TS_AUTHKEY` - tik pirmam Tailscale konteinerio prijungimui.

## Atnaujinimas iš ankstesnės CRM versijos

1. Sustabdyti tik CRM Compose projektą, ne kitus NAS konteinerius.
2. Sukurti PostgreSQL duomenų bazės kopiją ir nukopijuoti `runtime/media` katalogą.
3. Įkelti naują CRM katalogą į tą patį NAS projekto kelią, išsaugant `.env` ir `runtime` katalogą.
4. Paleisti `docker compose build --pull` ir `docker compose up -d`.
5. Patikrinti, kad `crm-db`, `crm-web` ir `crm-tailscale` yra healthy.
6. Patikrinti `/health/live`, `/health/ready`, prisijungimą, kontaktų sąrašą ir vieną failo įkėlimą.

## Pirmas paleidimas

1. Nukopijuoti `.env.example` į `.env` ir pakeisti visas pavyzdines reikšmes.
2. Paleisti `docker compose config --quiet`.
3. Paleisti `docker compose build --pull`.
4. Paleisti `docker compose up -d`.
5. Patikrinti `/health/live` ir `/health/ready`.
6. Atidaryti `https://<tailscale-vardas>/setup/`.
7. Įvesti `CRM_SETUP_TOKEN`, naudotojo vardą ir savo slaptažodį.
8. Sukūrus administratorių, pašalinti `CRM_SETUP_TOKEN` reikšmę iš `.env` ir perkrauti `crm-web`.
9. Atšaukti panaudotą `TS_AUTHKEY` Tailscale valdymo puslapyje.

## Atsarginės kopijos

- `crm-backup` konteineris automatiškai daro PostgreSQL (`pg_dump -Fc`) ir
  `runtime/media` kopijas į `runtime/backups/` kas `BACKUP_INTERVAL_SECONDS`
  (numatyta 24 val.), palieka naujausias `BACKUP_KEEP` (numatyta 14) kiekvieno tipo.
- Papildomai naudotojas per Nustatymai → Duomenų eksportas gali atsisiųsti
  pilną ZIP (visi duomenys + priedai + atkūrimo instrukcija).
- `runtime/backups/` periodiškai kopijuoti į išorinį diską ar kitą vietą —
  RAID nėra atsarginė kopija.

## Saugos riba

Neperkelti realių kontaktų, kol neįgyvendintas ir realiai neatliktas atsarginės kopijos atkūrimo testas. Produkcinė CRM turi būti pasiekiama tik per Tailscale HTTPS. Port forwarding maršrutizatoriuje nenaudojamas.

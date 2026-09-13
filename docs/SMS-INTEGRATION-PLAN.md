# SMS siuntimas iš CRM — poreikių analizė ir sprendimo planas

Būsena: **analizė / pasiūlymas** (kodas dar nerašytas). Data: 2026-09-13.

## 1. Poreikiai

| # | Poreikis | Kas iš to išplaukia |
|---|----------|---------------------|
| P1 | Siųsti SMS klientui tiesiai iš CRM kortelės | Mygtukas „Siųsti SMS" kontakto kortelėje, numerio pasirinkimas iš `PhoneNumber`, teksto laukas su simbolių / segmentų skaitikliu |
| P2 | Operatorius keičiamas (Tele2 dabar; Telia, Bitė — galimi) | Tiekėjo abstrakcija: vienas `send()` interfeisas, kelios realizacijos; tiekėjas parenkamas nustatymuose |
| P3 | Prisijungimo duomenys įvedami per sąsają | Nauja nustatymų skiltis „SMS", slapti laukai šifruojami (`CRM_SECRETS_KEY`), `.env` fallback — kaip SMTP/IMAP |
| P4 | Išsiųsta SMS atsiranda bendravimo istorijoje su data ir laiku | Naujas `Activity` tipas `sms` + siuntimo įrašas su būsena (eilėje / išsiųsta / pristatyta / nepavyko) |
| P5 | Pasiruošti integracijai su Regitros SMS siuntimu | Regitros pranešimų servisas — tik dar vienas tiekėjas tame pačiame interfeise |

Numanomi (nepasakyti, bet būtini) poreikiai:

- **Staging izoliacija** — staging turi produkcijos duomenų kopiją, todėl SMS ten privalo būti išjungtos taip pat, kaip dabar SMTP/IMAP/webhookai (`CRM_ISOLATED`).
- **Teisė** siųsti SMS (`can_send_sms`) ir įrašas `AuditLog`.
- **Kaina / segmentai** — lietuviškos raidės (ą, č, ę…) perjungia kodavimą į UCS-2: viena SMS = **70** simbolių (sujungtose — 67), o ne 160. Naudotojas turi matyti, kiek segmentų (ir kiek kainuos) žinutė.
- **Sutikimas** — transakcinės / aptarnavimo SMS gali būti siunčiamos, rinkodarinėms reikia išankstinio sutikimo; kortelėje reikia žymos „Nesiųsti SMS".

## 2. Kas rasta

### 2.1 CRM kodas (dabartinė būsena)

- SMS funkcionalumo **nėra** (nei modelio, nei nustatymų).
- `contacts/integrations.py` — jau yra šablonas, kurį reikia pakartoti: `EmailConfig`/`ImapConfig`/`OIDCConfig` sujungia DB + `.env` ir grąžina inertišką konfigūraciją, kai `CRM_ISOLATED`.
- `SystemSettings` (vienetinis modelis) — čia dedami integracijų laukai; slaptažodžiai šifruojami `contacts/crypto.py`.
- `Activity` tipai: `note`, `call`, `email`, `meeting`, `task` — trūksta `sms`. `created_at` jau duoda datą ir laiką istorijai.
- Foniniai darbai eina per `crm-worker` (`compose.yaml`) ir Helm CronJob'us — SMS eilės apdorojimas telpa ten pat.
- `webhooks.py` turi apsaugas (`target_is_allowed`, be redirect'ų) — tinka pavyzdžiu išeinantiems HTTP kvietimams į operatorių.

### 2.2 Operatoriai

| | Tele2 (dabartinis) | Telia | Bitė |
|---|---|---|---|
| Paslauga | „SMS verslui" / A2P SMS | Didmeninis SMS siuntimas | SMS verslui |
| Integracija | „API SMS integracija" — viešos techninės specifikacijos nėra, gaunama iš vadybininko | REST API per HTTP / SMPP | SMPP 3.4 per TCP/IP (tiesioginis prisijungimas prie SMS centro) |
| Siuntėjo vardas | Taip (alfanumerinis) | Taip, iki 11 lotyniškų simbolių be tarpų | Taip (alfanumerinis) |
| Atsakymai iš kliento | — | — | Taip (dvipusės SMS) |
| Kaina (viešai) | ~0,026 €/SMS be PVM | API planas 71,81 €/mėn. + 189 € diegimas + ~0,028 €/SMS | pagal sutartį |

Išvada: nė vieno operatoriaus API dokumentacija nėra vieša — **ją reikia gauti pagal sutartį**. Todėl CRM kode tiekėjo realizaciją reikia daryti atskirai, o visa kita (nustatymai, istorija, eilė, UI) — nuo tiekėjo nepriklausoma.

### 2.3 Regitros sistemos (Confluence / Jira)

- **Tele2 A2P SMS jau naudojamas Regitroje** — puslapis „Sutrikimo su A2P SMS paslauga registravimas" (SD erdvė): sutrikimai registruojami `tcs.lt@tele2.com`, aplinka „API / WEB". Tai reiškia, kad sutartis, siuntėjo vardas ir API prieiga su Tele2 jau egzistuoja.
- **Siuntėjo vardas** — „Regitra" („Automatinių pranešimų siuntimas", RS-00).
- **Centralizuotas SMS registras** — Oracle „CLIENT_DB" (naujas pavadinimas **CRM db**), schema `smsis`, lentelė `smsis.message_registry` (turinys, išsiuntimo data, būsena). Testinėse aplinkose SMS **nesiunčiamos**, tik registruojamos („SMS/EMAIL siuntimo testavimas").
- **Java mikroservisas `message-service`** su DB schema `MESSAGE_SERVICE` (MICRO DB) — „Integracijų sąrašas, Java". Tikėtinas centrinis pranešimų siuntimo taškas; integracijai tarp servisų naudojama Kafka ir REST per `internal-api-gateway`.
- Istoriškai: SMS siuntimas atskirtas į DB eilę (EKETRIS-184, 2017); senoji VEPP naudoja Oracle paketus `VEPP_SMS`, `VEPP_SMSQ`.
- **Verslo taisyklės (RS-00)**, kurias CRM turėtų atkartoti:
  - SMS siunčiamos tik **patvirtintais (validuotais)** telefono numeriais;
  - nesiunčiama asmenims su mirties data (`PHYSICAL_DATE_OF_DEATH is not null`);
  - priminimai ir informaciniai pranešimai — tik **07:00–19:00**; su užsakymu susiję — iš karto.
- Susiję Jira: VAIRISAPP-586, VAIRISAPP-612, VAIRISAPP-783, VAIRISAPP-784 (automatiniai pranešimai), PRJ-286 (SMS teksto pataisymas). Atskiros užduoties CRM ↔ SMS integracijai **nerasta**.

## 3. Siūlomas sprendimas

### 3.1 Architektūra

```
Kontakto kortelė ──► SmsService.queue() ──► SmsMessage (queued) + Activity(type=sms)
                                   │                (vienoje transakcijoje)
                                   ▼
               crm-worker: send_sms ──► Provider.send() ──► Tele2 / Telia / Bitė / Regitra
                                   │
                  būsena: sent / failed ◄── atsakymas
                  būsena: delivered    ◄── DLR callback arba status polling
```

**Tiekėjų interfeisas** (`contacts/sms/`):

```python
class SmsProvider:
    def send(self, to_e164: str, text: str, sender: str, ref: str) -> SendResult: ...
    def status(self, provider_id: str) -> DeliveryStatus: ...      # jei nepalaiko DLR
    def parse_callback(self, request) -> list[DeliveryStatus]: ...  # jei palaiko DLR
```

Realizacijos: `log` (dev/staging — tik įrašo, nesiunčia; atitinka Regitros testinių aplinkų elgseną), `tele2_http`, `telia_rest`, `bite_smpp`, `regitra_gateway`. Pirmiausia — `log` ir `tele2_http`.

### 3.2 Nustatymai (Nustatymai → SMS)

`SystemSettings` nauji laukai:

| Laukas | Paskirtis |
|---|---|
| `sms_enabled` | Pagrindinis jungiklis |
| `sms_provider` | `log` / `tele2` / `telia` / `bite` / `regitra` |
| `sms_api_url` | API adresas (arba SMPP host:port) |
| `sms_username` / `sms_client_id` | Prisijungimas |
| `sms_api_key` | Slaptažodis / raktas — **šifruojamas** |
| `sms_sender` | Siuntėjo vardas (validacija: ≤11 lotyniškų simbolių) |
| `sms_default_country` | Numatytas prefiksas `+370` numerių normalizavimui |
| `sms_quiet_from` / `sms_quiet_to` | Tylos langas (pvz. 19:00–07:00) |
| `sms_callback_secret` | DLR callback autentifikacijai — **šifruojamas** |

- `integrations.sms_config()` — DB + `.env` fallback (`SMS_PROVIDER`, `SMS_API_URL`, `SMS_USERNAME`, `SMS_API_KEY`, `SMS_SENDER`), grąžina `provider="log"` kai `CRM_ISOLATED`.
- Mygtukas **„Siųsti bandomąją SMS"** — patikrina prisijungimą ir parodo operatoriaus atsakymą.

### 3.3 Duomenų modelis

- `Activity.SMS = "sms"` į `TYPE_CHOICES` (su vertimu).
- Naujas `SmsMessage`:
  `activity` (OneToOne), `person`, `phone` (E.164), `text`, `encoding` (GSM-7/UCS-2), `segments`, `provider`, `provider_message_id`, `status` (`queued`/`sent`/`delivered`/`failed`/`blocked`), `error`, `queued_at`, `sent_at`, `delivered_at`, `created_by`, `idempotency_key` (unique — apsauga nuo dvigubo siuntimo, kaip `Activity.submission_token`).
- `Person.sms_opt_out` (bool) ir, jei reikia Regitros taisyklių, `PhoneNumber.verified_at`.

### 3.4 Istorija

- SMS istorijoje rodoma kaip `Activity` su ikona, tekstu, numeriu, **data ir laiku**, siuntėju (naudotoju) ir būsenos ženkliuku; nepavykus — klaidos priežastis ir „Kartoti".
- Istorijos įrašas sukuriamas iškart (statusas „eilėje"), o ne tik po sėkmės — kad nepavykęs bandymas irgi matytųsi.
- Filtre / analitikoje atsiranda tipas „SMS"; webhook įvykis `sms.sent` / `sms.failed`.

### 3.5 Pristatymo būsenos (DLR)

Du variantai, priklauso nuo operatoriaus:
1. **Callback** `POST /api/v1/sms/callback/<provider>/` su paslaptimi. Reikalauja, kad CRM būtų pasiekiamas iš interneto (produkcijoje — Tailscale Funnel / Caddy) ir kad operatorius leistų nurodyti URL.
2. **Polling** — `send_sms` darbas periodiškai klausia operatoriaus apie `sent` būsenos žinutes (tinka, jei CRM nepasiekiamas iš išorės).

### 3.6 Integracija su Regitros sistemomis — variantai

| Variantas | Aprašymas | + | − |
|---|---|---|---|
| **A. Per Regitros `message-service` (rekomenduojama)** | CRM kviečia centrinio pranešimų serviso REST API (per `internal-api-gateway`) arba publikuoja į Kafka temą; servisas siunčia per esamą Tele2 A2P ir registruoja `smsis.message_registry` | Viena sutartis, vienas siuntėjo vardas „Regitra", vienas registras ir auditas, taisyklės (validuoti numeriai, mirties data, laiko langai) taikomos centralizuotai | Reikia API kontrakto, prieigos, tinklo ryšio iš CRM hosto į vidinį tinklą |
| B. Tiesiogiai į Tele2 A2P su tais pačiais prisijungimais | CRM naudoja `tele2_http` tiekėją su Regitros Tele2 paskyra | Greita pradžia, nepriklausoma nuo Java komandos | SMS nepatenka į `smsis.message_registry`, dvi vietos siuntimui, dubliuojamos taisyklės |
| C. Rašymas tiesiai į `smsis` DB eilę | CRM įrašo eilutę į Oracle eilę | Paprasta | Nerekomenduojama: kietas susiejimas su svetima schema, jokio kontrakto, Oracle driver'is CRM'e |

Siūloma eiga: **B pradžiai (arba tik `log` tiekėjas), A — tikslinis sprendimas**. Kadangi abu yra `SmsProvider` realizacijos, perėjimas — tik nustatymo pakeitimas.

## 4. Veiksmai

### 0 etapas — paruošimas (ne kodas)

1. **Tele2**: gauti A2P SMS API techninę dokumentaciją (protokolas, autentifikacija, užklausos/atsakymo formatas, klaidų kodai, DLR, limitai, IP whitelist), testinę paskyrą / smėlio dėžę. Kontaktai — Confluence puslapyje „Sutrikimo su A2P SMS paslauga registravimas" arba per verslo vadybininką.
2. Išsiaiškinti: ar CRM naudos **esamą Regitros Tele2 paskyrą ir siuntėją „Regitra"**, ar atskirą.
3. **Telia / Bitė**: tik jei planuojama keisti — užklausti kainų ir API specifikacijų palyginimui (Telia REST/SMPP, Bitė SMPP 3.4).
4. **Regitros Java komanda** (`message-service` savininkai): ar servisas turi išorinį API / Kafka temą kitoms sistemoms; OpenAPI kontraktas; autentifikacija per `internal-api-gateway`; ar grąžina pristatymo būseną; testinė aplinka.
5. **Tinklas**: ar CRM hostas pasieks Regitros vidinį tinklą (192.168.x / 172.2x.x) arba Tele2 API iš leistino IP.
6. **Teisinis / DPO**: ar CRM SMS yra transakcinės ar ir rinkodarinės; sutikimo ir atsisakymo tvarka; saugojimo terminas SMS tekstams.
7. Sukurti Jira epiką su žemiau esančiomis užduotimis.

### 1 etapas — SMS aplinka CRM (galima daryti jau dabar)

1. `SystemSettings` SMS laukai + migracija; šifravimas per `crypto.py`.
2. `integrations.sms_config()` su `.env` fallback ir `CRM_ISOLATED` apsauga.
3. Nustatymų skiltis „SMS" (`templates/settings/…`, nuoroda `layout.html`, tik adminui) + „Siųsti bandomąją SMS".
4. `contacts/sms/` interfeisas + `log` tiekėjas.
5. `.env.example`, `docs/DEPLOYMENT.md` lentelė, in-app žinynas.
6. Testai: konfigūracijos sujungimas, staging izoliacija, slapto lauko šifravimas.

### 2 etapas — siuntimas ir istorija

1. `Activity.SMS`, `SmsMessage`, `Person.sms_opt_out` + migracijos.
2. Numerių normalizavimas į E.164 (biblioteka `phonenumbers`), GSM-7/UCS-2 ir segmentų skaičiavimas.
3. Teisė `can_send_sms` (`permissions.py`), audito įrašas.
4. Kortelėje: „Siųsti SMS" dialogas (numeris, tekstas, skaitiklis, perspėjimas apie UCS-2).
5. Valdymo komanda `send_sms` (eilė, pakartojimai su atidėjimu, tylos langas, idempotencija) → `crm-worker` ir Helm CronJob.
6. Istorijos atvaizdavimas su būsena; filtras pagal tipą; webhook įvykiai.
7. Testai: sukuriamas `Activity` su data/laiku, dvigubo siuntimo apsauga, opt-out blokavimas, staging nesiunčia.

### 3 etapas — Tele2 tiekėjas

1. `tele2` realizacija pagal gautą specifikaciją; laiko limitai (timeout), klaidų kodų atvaizdavimas.
2. DLR: callback endpoint arba polling.
3. Bandymas su testine paskyra → staging (su `log`) → produkcija su vienu vidiniu numeriu.

### 4 etapas — Regitros integracija (variantas A)

1. `regitra_gateway` tiekėjas pagal `message-service` kontraktą (REST arba Kafka).
2. Regitros taisyklės CRM pusėje (jei jų netaiko servisas): tik validuoti numeriai, mirties data, 07:00–19:00.
3. Sutikrinimas: CRM `SmsMessage` ↔ `smsis.message_registry` pagal `provider_message_id`.
4. Perjungti `sms_provider` į `regitra`, `tele2` palikti kaip atsarginį.

### 5 etapas — vėliau (pagal poreikį)

- SMS šablonai su kintamaisiais (`{vardas}`, `{data}`) — kaip Regitros pranešimų šablonuose.
- Automatikos veiksmas „Siųsti SMS" (`automation.py`).
- Masinis siuntimas pagal filtrą; gaunamos SMS (Bitė dvipusės) į istoriją.

## 5. Atviri klausimai

1. Ar CRM siuntėjas bus „Regitra", ir ar naudojama ta pati Tele2 sutartis?
2. Ar `message-service` leidžia jungtis kitoms sistemoms ir kas jo savininkas?
3. Ar CRM hostas turės tinklo prieigą prie Regitros vidinių servisų?
4. Kokios SMS rūšys bus siunčiamos (tik aptarnavimo ar ir rinkodaros)?
5. Ar reikia pristatymo būsenos realiu laiku, ar užtenka „išsiųsta / nepavyko"?
6. Kiek laiko saugoti SMS tekstus (Regitros privatumo politikos saugojimo terminai)?

## Šaltiniai

- Confluence: „SMS/EMAIL siuntimo testavimas", „Sutrikimo su A2P SMS paslauga registravimas", „Automatinių pranešimų siuntimas", „Integracijų sąrašas, Java", „Santrauka" (EKETRIS-184)
- https://tele2.lt/verslui/sprendimai-verslui/sms-verslui
- https://www.telia.lt/verslui/paslaugos/didmeniniu-ir-reklaminiu-sms-siuntimo-paslaugos
- https://www.bite.lt/verslui/paslaugos/sms

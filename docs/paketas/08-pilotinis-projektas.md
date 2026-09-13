# 8. Pilotinis projektas

## 8.1 Tikslas ir apimtis

Per ribotą laiką, su vienu padaliniu ir realiais duomenimis įsitikinti, kad CRM
(1) išsprendžia padalinio poreikį, (2) atitinka saugumo ir duomenų apsaugos
reikalavimus organizacijos infrastruktūroje ir (3) gali būti prižiūrima
organizacijos IT.

| | |
|---|---|
| Padalinys | **[ORGANIZACIJA]** |
| Naudotojai | 5–15 (per AD grupes, pvz. `CRM-Pilot-Users`, 1–2 `CRM-Pilot-Admins`) |
| Duomenys | padalinio kontaktai ir įmonės (importas iš Excel/CSV), nauja bendravimo istorija |
| Integracijos | Entra ID / AD FS — privaloma; SMTP — rekomenduojama; IMAP, API, webhook'ai, DWH — ne pilote |
| Aplinka | organizacijos VM (2 vCPU, 4–6 GB RAM su ClamAV) + staging VM arba ta pati VM su atskiru Compose projektu |
| Trukmė | ~3 mėn. naudojimo + pasiruošimas |

## 8.2 Etapai

| Etapas | Trukmė | Rezultatai | Atsakingi |
|---|---|---|---|
| 0. Derinimas | 2–4 sav. | užsakovas, DAP konsultacija ir DAPV, saugos klausimynas, sprendimas dėl DB, VM ir tinklo | savininkas, IT, sauga, DAP |
| 1. Parengimas | 1–2 sav. | VM, proxy, sertifikatas, Entra/AD FS programa, AD grupės, `.env`, kopijų saugykla, SIEM ir Prometheus | IT |
| 2. Saugumo patikra | 2–4 sav. (lygiagrečiai) | įsiskverbimo testas ir/ar kodo auditas; radinių taisymas | IT sauga, programuotojas |
| 3. Įdiegimas ir pratybos | 1 sav. | produkcinis diegimas, atkūrimo pratybos (RTO), grupių ir rolių patikra su bandomosiomis paskyromis | IT, programuotojas |
| 4. Mokymai ir importas | 1 sav. | 1 val. mokymai naudotojams, instrukcija dėl laisvo teksto; duomenų importas su peržiūra | savininkas, programuotojas |
| 5. Pilotas | 3 mėn. | kasdienis naudojimas; kas 2 sav. trumpas grįžtamasis ryšys | padalinys |
| 6. Įvertinimas | 2 sav. | ataskaita ir sprendimas: plėsti / keisti / nutraukti | savininkas, IT |

## 8.3 Sėkmės kriterijai

| Sritis | Kriterijus | Kaip matuojama |
|---|---|---|
| Naudojimas | ≥ 80 % piloto naudotojų naudoja CRM kas savaitę | audito žurnalas (prisijungimai, veiklos) |
| Vertė | kontaktų istorija randama per < 1 min.; Excel sąrašai nebenaudojami | naudotojų apklausa |
| Duomenų kokybė | < 5 % dublikatų po importo ir sujungimo | „Galimi dublikatai" |
| Pasiekiamumas | ≥ 99 % darbo valandomis | Prometheus `crm_database_up`, health |
| Našumas | p95 < 2 s realiu darbu | proxy / ingress metrikos |
| Sauga | 0 kritinių / aukštų neištaisytų radinių; 0 incidentų | pentest ataskaita, SIEM |
| Duomenų apsauga | saugojimo terminai nustatyti; subjekto užklausa įvykdyta per < 1 d. (bandymas) | DAP patikra |
| Priežiūra | atnaujinimas ir atkūrimas atlikti organizacijos IT be kūrėjo | pratybų protokolas |

## 8.4 Išėjimo strategija

Jei pilotas nutraukiamas: duomenys eksportuojami (CSV, pilnas ZIP) arba
perkeliami į kitą sistemą; VM ir kopijos sunaikinamos pagal organizacijos
tvarką; age raktai ir `.env` paslaptys atšaukiami; Entra programa ir AD grupės
pašalinamos; DAP informuojamas apie duomenų sunaikinimą.

## 8.5 Rizikos pilote

Žr. [09 — apribojimai ir rizikos](09-apribojimai-ir-rizikos.md): ypač priklausomybė
nuo vieno kūrėjo (perdavimo planas), neišbandyta su organizacijos Entra/AD FS
(1 etapas su bandomosiomis paskyromis), pentest neatliktas (2 etapas).

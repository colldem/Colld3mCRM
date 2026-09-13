# 7. Priežiūros ir perdavimo modelis

Didžiausia nekomercinės sistemos rizika — priklausomybė nuo vieno žmogaus. Šis
modelis ją mažina trimis būdais: kodas ir žinios perduodami organizacijai,
kasdienė priežiūra automatizuota, o sistema sukurta standartinėmis
technologijomis, kurias prižiūrėti gali bet kuris Python/Django programuotojas.

## 7.1 Rolės (RACI)

A — atsako, R — atlieka, C — konsultuoja, I — informuojamas.

| Veikla | Sistemos savininkas (padalinys) | IT administratorius | Programuotojas (priežiūra) | IT sauga | DAP |
|---|---|---|---|---|---|
| Prieigos suteikimas (AD grupės) | A | R | — | I | — |
| Diegimas ir atnaujinimai | I | A/R | R | C | — |
| Saugumo atnaujinimai (priklausomybės, image) | I | A | R | C | — |
| Kopijos ir atkūrimo pratybos | I | A/R | C | I | — |
| Stebėsena ir įspėjimai | I | A/R | C | C | — |
| Incidentai | I | A/R | R | R | C (asmens duomenų pažeidimai) |
| Funkcijų pakeitimai | A | C | R | C | C (jei liečia asmens duomenis) |
| Duomenų subjektų užklausos | A | R | — | — | C |
| Saugojimo terminai | A | R | — | — | C |

## 7.2 Reguliari priežiūra

| Veikla | Dažnis | Apimtis | Kaip palengvinta |
|---|---|---|---|
| Dependabot atnaujinimų peržiūra ir sujungimas | kas savaitę | 0,5–1 val. | CI patikrina kiekvieną atnaujinimą (testai, sauga, atkūrimas, apkrova) |
| Leidimas: staging → produkcija | kas mėnesį ar pagal poreikį | 1–2 val. | `deploy.sh` / versijos žyma; runbook |
| Stebėsenos ir žurnalo peržiūra | kas savaitę | 0,5 val. | `/metrics`, SIEM įspėjimai |
| Atkūrimo pratybos organizacijos aplinkoje | kas ketvirtį | 1–2 val. | `restore.sh` |
| Django LTS migracija (5.2 → 6.2 LTS) | iki 2028-04 | 2–5 d. | testų rinkinys, CI |
| PostgreSQL major versija | kas 2–3 m. | 0,5–1 d. | `pg_dump`/`restore.sh` |

**Įvertinimas:** apie **4–8 val. per mėnesį** įprastinei priežiūrai, be naujų funkcijų.

## 7.3 Perdavimo planas

| Žingsnis | Rezultatas |
|---|---|
| 1. Repozitorija perkeliama į organizacijos Git (arba organizacija gauna pilną kopiją su istorija) | kodas, CI, dokumentacija organizacijos kontrolėje |
| 2. CI paleidžiamas organizacijos CI sistemoje arba GitHub organizacijos paskyroje | tos pačios 9 patikros |
| 3. Du organizacijos IT darbuotojai — perdavimo sesijos (3 × 2 val.): architektūra ir kodas; diegimas, kopijos, atkūrimas; saugumas, katalogas, incidentai | bent du žmonės gali diegti, atkurti ir taisyti |
| 4. Bendras pirmas produkcinis diegimas ir atkūrimo pratybos | patvirtinta, kad procedūros veikia be kūrėjo |
| 5. Palaikymo laikotarpis pilotui (**[ORGANIZACIJA: forma — darbo pareigos / sutartis]**) | klausimai ir pataisymai |

## 7.4 Kur rasti žinias

| Tema | Dokumentas |
|---|---|
| Kodo sandara, kur ką pridėti | `docs/ARCHITECTURE.md`, `CLAUDE.md` („Struktūra") |
| Diegimas, kintamieji, kopijos, žurnalai, stebėsena | `docs/DEPLOYMENT.md` |
| Organizacinis diegimas, tinklas, resursai, atnaujinimas, rollback | `docs/DIEGIMAS-ORGANIZACIJOJE.md` |
| Kubernetes | `docs/KUBERNETES.md` |
| Integracijos | `docs/INTEGRACIJOS.md` |
| Naudotojo ir administratoriaus žinynas | programoje: Nustatymai → Dokumentacija |
| Kiekviena taisyklė su pavyzdžiu | automatiniai testai (`tests/`) — 655 vykdomi apibrėžimai |

## 7.5 Kūrimo būdas

Kodas kurtas su dirbtinio intelekto asistentais (ChatGPT, Claude) prižiūrint
kūrėjui. Kokybę užtikrina ne kūrimo priemonė, o patikra: kiekvienas pakeitimas
praeina automatinius testus, statinę saugumo analizę, priklausomybių ir image
pažeidžiamumų skenavimą, atkūrimo pratybas ir apkrovos testą. Rekomenduojamas
nepriklausomas kodo auditas ir įsiskverbimo testas prieš produkciją (žr. 09).

## 7.6 Incidentai

1. Aptikimas: SIEM / Prometheus įspėjimas, naudotojo pranešimas.
2. Klasifikacija: pasiekiamumas / saugumas / asmens duomenų pažeidimas (DAP — per 72 val. vertinimas, BDAR 33 str.).
3. Sulaikymas: vien SSO režimas, naudotojo išjungimas AD, API raktų atšaukimas, webhook'ų išjungimas, prireikus — programos sustabdymas.
4. Tyrimas: audito žurnalas (nekeičiamas, su `request_id`), JSON žurnalai SIEM'e.
5. Atkūrimas: [06 — kopijavimo ir atkūrimo planas](06-kopijavimo-ir-atkurimo-planas.md).
6. Pamokos: pataisymas su regresijos testu.

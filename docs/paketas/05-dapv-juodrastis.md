# 5. Poveikio duomenų apsaugai vertinimo (DAPV) juodraštis

> **Juodraštis.** Techninę dalį parengė sistemos kūrėjas; laukus, pažymėtus
> **[ORGANIZACIJA]**, užpildo duomenų valdytojas kartu su duomenų apsaugos
> pareigūnu (DAP). Ar DAPV privalomas (BDAR 35 str.), sprendžia DAP; CRM netvarko
> specialių kategorijų duomenų ir neatlieka profiliavimo, bet laisvas tekstas ir
> gauti laiškai gali jų netyčia turėti, todėl vertinimą atlikti rekomenduojama.

## 1. Tvarkymo aprašymas

| Klausimas | Atsakymas |
|---|---|
| Duomenų valdytojas | **[ORGANIZACIJA]** |
| Sistemos savininkas (padalinys) | **[ORGANIZACIJA]** |
| Tikslas | organizacijos ryšių su klientais, partneriais ir kitomis organizacijomis valdymas: kontaktų registras, bendravimo istorija, užduotys ir priminimai, ataskaitos **[ORGANIZACIJA: patikslinti]** |
| Duomenų subjektai | klientų, partnerių, tiekėjų ir kitų organizacijų kontaktiniai asmenys; individualią veiklą vykdantys asmenys; organizacijos darbuotojai — CRM naudotojai |
| Duomenų kategorijos | vardas, pavardė, pareigos, įmonė, telefonai, el. paštai, adresai, nuorodos; bendravimo istorija ir pastabos (laisvas tekstas); prisegti failai; iš kontaktų gauti el. laiškai (jei įjungta); darbuotojų vardai, el. paštas, AD grupės, IP adresai ir veiksmai žurnale — pilnas sąrašas [04 — duomenų žodyne](04-duomenu-zodynas.md) |
| Specialių kategorijų duomenys | netvarkomi pagal paskirtį; laisvame tekste ir prieduose gali atsirasti netyčia — darbuotojų instrukcija **[ORGANIZACIJA]** |
| Šaltiniai | darbuotojų įvedimas; CSV/XLSX importas; el. laiškai iš organizacijos dėžutės (neprivaloma); REST API iš organizacijos sistemų (neprivaloma) |
| Gavėjai | organizacijos darbuotojai pagal rolę ir matomumą; organizacijos sistemos per API, webhook'us ar `reporting` schemą (tik įjungus); IT administratoriai; tvarkytojai — **[ORGANIZACIJA: prieglobos teikėjas, jei ne savas]** |
| Perdavimas už ES/EEE | nėra (sistema organizacijos infrastruktūroje, be išorinių paslaugų). Išimtis — jei Entra ID naudojamas, tapatybės duomenys tvarkomi Microsoft pagal organizacijos esamą sutartį |
| Saugojimo terminai | aktyvūs įrašai — **[ORGANIZACIJA]**; archyvuoti — ištrinami po nustatyto dienų skaičiaus; gauti laiškai — po nustatyto termino; audito žurnalas — ≥180 d. arba visada; kopijos — `BACKUP_KEEP` dienų (numatyta 14) + kopijų saugykloje `BACKUP_REMOTE_KEEP_DAYS` (30) |
| Technologija | žr. [01](01-sistemos-aprasas.md), [02](02-architektura-ir-schemos.md) |

## 2. Būtinumas ir proporcingumas

| Klausimas | Atsakymas |
|---|---|
| Teisinis pagrindas (6 str.) | **[ORGANIZACIJA + DAP]**: tikėtina — teisėtas interesas (f) kontaktams su organizacijomis; sutarties vykdymas (b), kai santykis sutartinis; teisės aktų prievolė (c) — jei taikoma |
| Teisėto intereso pusiausvyra | **[ORGANIZACIJA + DAP]** |
| Duomenų kiekio mažinimas | laukai ribojami paskirtimi; papildomus laukus kuria tik administratorius; `reporting` schemoje nėra laisvo teksto ir kontaktinių duomenų; žurnaluose SIEM'ui nėra asmens duomenų |
| Tikslumas | redagavimas kortelėje, dublikatų paieška ir sujungimas, keitimų istorija |
| Saugojimo apribojimas | automatiniai terminai archyvuotiems įrašams, laiškams, žurnalui; neaktyvių paskyrų išjungimas |
| Informavimas (13–14 str.) | **[ORGANIZACIJA]**: privatumo pranešimas kontaktams |
| Subjektų teisės | susipažinimas ir perkeliamumas — ZIP eksportas; ištaisymas — redagavimas; ištrynimas — „Duomenų apsauga" su žurnalo nuasmeninimu; apribojimas — archyvavimas; nesutikimas — ištrynimas arba archyvavimas |
| Tvarkytojai ir sutartys | **[ORGANIZACIJA]** |

## 3. Rizikos duomenų subjektų teisėms ir laisvėms

Tikimybė ir poveikis: M — maža, V — vidutinė, D — didelė. Įvertinta **su** 4 skyriaus priemonėmis.

| # | Rizika | Priežastis | Tikimybė | Poveikis | Priemonės | Likutinė |
|---|---|---|---|---|---|---|
| R1 | Neteisėta prieiga prie kontaktų | pavogti prisijungimo duomenys | M | V | SSO su organizacijos MFA; vien SSO režimas; blokavimas; sesijų pertikrinimas; auditas | M |
| R2 | Per plati darbuotojų prieiga | netinkamos rolės | V | V | rolės pagal AD grupes; matomumas „savi/komandos"; Skaitytojo rolė; auditas | M |
| R3 | Buvęs darbuotojas išlaiko prieigą | vėluojantis išjungimas | M | V | prieiga atšaukiama per ≤15 min. po AD išjungimo; neaktyvių paskyrų išjungimas; API raktai nustoja veikti | M |
| R4 | Duomenų nutekėjimas per eksportą | didelis CSV/ZIP eksportas | V | V | eksporto teisė pagal rolę; kiekvienas eksportas audituojamas; metrika ir SIEM | M |
| R5 | Nutekėjimas iš kopijų | kopijų laikmenos praradimas | M | D | age šifravimas, privatus raktas ne serveryje | M |
| R6 | Tikri duomenys testinėje aplinkoje | produkcijos kopija staging'e | V | V | automatinis nuasmeninimas; išjungtos integracijos | M |
| R7 | Pertekliniai ar specialių kategorijų duomenys laisvame tekste | darbuotojų įpročiai, gauti laiškai | V | V | instrukcija **[ORGANIZACIJA]**; laiškų saugojimo terminas; ištrynimas pagal užklausą | V |
| R8 | Per ilgas saugojimas | terminai nenustatyti | V | V | automatiniai terminai — **reikia nustatyti** | M (nustačius) |
| R9 | Ištrinti duomenys lieka kopijose | kopijų rotacija | D | M | ribotas kopijų laikas; informuoti subjektą; atkūrus kopiją pakartoti ištrynimą | M |
| R10 | Kenkėjiškas failas | priedas ar laiškas | M | V | ClamAV kiekvienam failui; atsisiuntimas tik prisijungus | M |
| R11 | Duomenų vientisumo pažeidimas / sunaikinimas | klaida, išpuolis | M | D | šifruotos kopijos už serverio ribų; automatinės atkūrimo pratybos; nekeičiamas auditas | M |
| R12 | Neteisėtas duomenų perdavimas kitai sistemai | integracija be kontrolės | M | V | API raktai su scope ir terminu; webhook'ai tik administratoriui; `reporting` be laisvo teksto | M |
| R13 | Veiksmų neatsekamumas | žurnalo klastojimas | M | V | nekeičiamas žurnalas (DB trigeris), kopija SIEM'e | M |

## 4. Priemonės

Techninės — [03 — saugumo priemonės](03-saugumo-priemones.md). Organizacinės —
**[ORGANIZACIJA]**: prieigos suteikimo tvarka (AD grupių savininkai), darbuotojų
instrukcija dėl laisvo teksto ir failų, subjektų užklausų procedūra, saugojimo
terminų patvirtinimas, žurnalo peržiūros tvarka, incidentų valdymas.

## 5. Išvada

**[DAP]**: ar likutinės rizikos priimtinos; ar reikia išankstinių konsultacijų su
VDAI (36 str.); peržiūros data.

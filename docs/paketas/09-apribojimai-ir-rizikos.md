# 9. Žinomi apribojimai ir rizikų registras

Sąmoningai įvardyti apribojimai — ne paslėpti trūkumai. Kiekvienam nurodyta, kaip
rizika mažinama dabar ir kas dar galima. Tikimybė / poveikis: M — maža, V — vidutinė, D — didelė.

## 9.1 Rizikų registras

| # | Rizika | T | P | Esamos priemonės | Papildomai galima / reikia | Savininkas |
|---|---|---|---|---|---|---|
| K1 | **Priklausomybė nuo vieno kūrėjo** | D | D | pilna dokumentacija, 655 testai, standartinės technologijos, automatizuota priežiūra | perdavimo planas (07): du IT darbuotojai, repozitorija organizacijoje | savininkas |
| K2 | **Nėra nepriklausomo įsiskverbimo testo ar kodo audito** | V | D | bandit, CodeQL, pip-audit, Trivy, saugumo testai, CSP | pentest ir/ar kodo auditas prieš produkciją (pilotas, 2 etapas) | IT sauga |
| K3 | Neišbandyta su organizacijos Entra ID / AD FS | V | V | protokolo testai, žetono tikrinimo įrankis, ištaisytos Entra adresų klaidos | pilotas, 1 etapas: bandomosios paskyros ir grupės | IT |
| K4 | Kodas kurtas su DI asistentais | V | V | tas pats patikros rinkinys kaip bet kuriam kodui; kiekvienas pakeitimas per CI | nepriklausomas kodo auditas (K2) | savininkas |
| S1 | DB superuser gali apeiti audito trigerį | M | V | trigeris saugo nuo programos ir jos DB rolės; kiekvienas įvykis kopijuojamas į SIEM be asmens duomenų | DB administratorių prieigos kontrolė; SIEM kaip nekeičiama kopija | IT sauga |
| S2 | Proxy → CRM segmentas be TLS | M | V | tik vidiniame tinkle; CRM prievadas atveriamas tik proxy adresui | TLS iki programos (proxy ↔ Gunicorn su sertifikatu) arba proxy tame pačiame hoste | infrastruktūra |
| S3 | Avarinė vietinė paskyra be MFA | M | D | naudojama tik kai katalogas nepasiekiamas; ilgas slaptažodis saugykloje; blokavimas po 5 klaidų; auditas | CRM prievadas prieinamas tik iš administravimo tinklo; periodinis slaptažodžio keitimas | IT sauga |
| S4 | Kalendoriaus prenumeratos nuoroda (.ics) su žetonu URL'e | M | M | žetonas atsitiktinis, perkuriamas profilyje; rodo tik naudotojo priminimus | organizacijai — išjungti funkciją, jei nenaudojama (nustatymas galimas) | savininkas |
| S5 | El. pašto pranešimuose — priminimų tekstai ir kontaktų vardai | V | M | tik darbuotojų dėžutėms; TLS | naudotojų instrukcija; pranešimai išjungiami asmeniškai | savininkas |
| S6 | API ribojimas tik vienam raktui, ne bendras | M | M | 120 užkl./min raktui, galiojimo terminai, auditas | globalus ribojimas proxy / WAF | infrastruktūra |
| D1 | Ištrinti duomenys lieka kopijose iki galiojimo pabaigos | D | M | šifruotos kopijos, ribotas saugojimas (14 / 30 d.) | informuoti subjektą; po atkūrimo pakartoti ištrynimus (06, 5 žingsnis) | DAP |
| D2 | Specialių kategorijų ar pertekliniai duomenys laisvame tekste | V | V | ištrynimas pagal užklausą; saugojimo terminai | darbuotojų instrukcija; periodinė peržiūra | savininkas, DAP |
| D3 | Individualią veiklą vykdantis asmuo kaip „Įmonė" neturi subjekto užklausų lango | M | M | šalinamas per saugojimo terminą arba rankiniu būdu | užklausų langą išplėsti įmonėms (≈0,5 d.) | savininkas |
| D4 | `--keep-personal-data` leidžia palikti tikrus duomenis staging'e | M | V | numatytai nuasmeninama; staging integracijos išjungtos | naudojimas tik su DAP leidimu | IT |
| P1 | Našumo riba ≈15 užkl./s su 2 vCPU | M | M | apkrovos testas CI; 50 aktyvių naudotojų p95 1,7 s | 4 vCPU arba Kubernetes replikos (DIEGIMAS-ORGANIZACIJOJE.md 4 sk.) | IT |
| P2 | Gunicorn procesų skaičius neautomatinis | M | M | kintamieji `CRM_GUNICORN_*` | nustatyti pagal VM | IT |
| I1 | Oracle nepalaikoma produkcijai | M (jei politika reikalauja — D) | V | migracijos praeina, 515/644 testų, įvertinta 1,5–2,5 d. | atlikti likusius darbus, jei reikalaujama | savininkas |
| I2 | ClamAV reikalauja ~1,5 GB RAM; neprieinamas — įkėlimai atmetami | M | M | sveikatos patikra, metrika, aiškus pranešimas | organizacijos esamas clamd; `CRM_CLAMAV_REQUIRED` sprendimas | IT |
| I3 | Didelės AD grupių aibės (>200) Entra žetone | M | M | atmetama su paaiškinimu | Entra: siųsti tik programai priskirtas grupes | IT |
| O1 | Esamas repozitorijos diegimas (NAS, Tailscale Funnel, self-hosted runner) netinka organizacijai | — | — | organizacijos diegimas aprašytas atskirai, be Tailscale ir Caddy | organizacijoje nenaudoti `compose.tailscale.yaml` ir NAS runner'io | IT |

## 9.2 Funkciniai apribojimai

- Teisės valdomos rolės lygiu (4 rolės + teisių lentelė), ne kiekvienam naudotojui atskirai.
- Nėra el. paštu siunčiamo slaptažodžio atkūrimo (prisijungiama per katalogą).
- Nėra dvipusės kalendoriaus sinchronizacijos (tik .ics prenumerata).
- Nėra el. laiškų siuntimo kontaktams iš CRM (tik pranešimai darbuotojams ir gautų laiškų priskyrimas).
- Viena sąsajos kalbų pora (LT/EN); tekstai redaguojami be perkrovimo.

# Pirmojo susitikimo su infrastruktūra planas

**Tikslas:** ne gauti leidimą iš karto, o sutarti **kitą konkretų žingsnį** —
saugos klausimyną, reikalavimų sąrašą arba pilotinės aplinkos užsakymą.

## Prieš susitikimą

- [ ] Užpildytas ir užsakovo pasirašytas [poreikio aprašas](00-poreikio-aprasas.md)
- [ ] Išsiaiškinta autorystės situacija ([11](11-autorystes-ir-licencijos-pareiskimas.md), 2 ir 5 skyriai)
- [ ] Trumpa pirminė DAP konsultacija (ar reikės DAPV)
- [ ] Nusiųstas paketas: 00, 01, 02, 03, 09, 10 (kitus — pagal poreikį)
- [ ] Parengta demonstracija staging aplinkoje su nuasmenintais duomenimis

## Darbotvarkė (45 min.)

| Min. | Tema | Kas parodoma | Dokumentas |
|---|---|---|---|
| 5 | Poreikis: kas prašo, kokia problema, kiek naudotojų | — | 00 |
| 10 | Demonstracija | sąrašas → kortelė → istorija → priminimas; Skaitytojo rolė; žurnalas su CSV eksportu; Duomenų apsauga (eksportas / ištrynimas); Prisijungimas → Katalogo grupės → „Patikrinti žetoną" | 01 |
| 5 | Architektūra ir tinklo srautai | schema 2.1, srautų lentelė | 02, DIEGIMAS-ORGANIZACIJOJE |
| 10 | Sauga ir duomenys | prieiga per AD grupes, auditas, kopijos su pratybomis, antivirusas, CI patikros | 03, 06 |
| 5 | Rizikos ir apribojimai — atvirai | vienas kūrėjas, pentest, Entra neišbandyta su organizacija | 09 |
| 10 | **Klausimai jiems** ir kitas žingsnis | — | 10 |

## Ką būtinai išsiaiškinti

1. Ar leidžiama PostgreSQL (ar reikalaujama Oracle)?
2. Konteineriai ar VM? Kas yra reverse proxy ir kokiu adresu jis pasiekia CRM?
3. Entra ID ar AD FS; kas registruos programą ir sukurs CRM grupes?
4. Naujos sistemos priėmimo procesas: saugos klausimynas, pentest, CAB.
5. Kas bus IT kontaktas pilotui ir kiek laiko užtrunka VM ir prieigų užsakymas?

## Po susitikimo

- Užrašyti atsakymus į [10](10-klausimai.md) ir sprendimus.
- Atnaujinti `.env` planą ir [08](08-pilotinis-projektas.md) terminus.
- Išsiųsti santrauką su sutartu kitu žingsniu ir atsakingais.

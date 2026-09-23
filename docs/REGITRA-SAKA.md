# Šaka `regitra`

Regitros CRM versija. Nuo bendrinio produkto ji skiriasi tuo, kas gyvena tik
Regitros poreikiams: įrašo kortelės vidurinė kolona su registrų blokais, asmens
kodas ir (toliau) specializuota paieška su pagrindu bei prieigos seansai.

| Šaka | Kas tai | Diegiama |
| --- | --- | --- |
| `main` | bendrinis, viešas CRM | `v*` žyma → produkcija |
| `regitra` | ši versija | push → Regitros staging (`docs/REGITRA-STAGING.md`) |

Atsišakojo nuo `regitra-base-0.79.0` (`3c41a72`).

## Svarbu: iš `main` imti tik `cherry-pick`

`main` viršūnė (`daed7b7`) yra commit'as, kuris **pašalina** registrų koloną,
blokus, pavyzdinius duomenis ir asmens kodą — būtent tai, kas šioje šakoje yra
esmė. Todėl:

```bash
# TAIP — vienas bendrinis pataisymas į regitrą:
git cherry-pick <sha>

# NE — nurytų visą Regitros dalį:
git merge main
```

Jei `git merge main` vis dėlto būtinas (pvz. labai išsiskyrė istorijos),
po jo privaloma atstatyti pašalintus failus iš `regitra-base-0.79.0` ir
peržiūrėti diff'ą prieš commit'ą.

Į kitą pusę — iš `regitra` į `main` — keliauja tik tai, kas nėra Regitros
specifika, irgi `cherry-pick`.

## Kiek ši šaka atsilikusi

Paskutinis pavijimas — **2026-09-23**, iki `main` viršūnės `ca9c30e`. Perkelta:
slaptažodžio atkūrimas ir prisijungimo langas (`b072202`), mygtukų ir paviršių
skalė (`cf6f080`, `0e5c6e4`), klaidų puslapiai (`3a408cf`), leidimo workflow
(`ae9a71c`).

Neperkelta sąmoningai: `daed7b7` (registrų kolonos išėmimas — tai, kas čia
esmė) ir tie `main` commit'ai, kuriems ši šaka jau turi savo atitikmenį —
`74e7207`, `f1dee2b`, `1ed3673`, `d241eaf`, `ad161d1`, `e67e70f`, `ca9c30e`.

Pavyti verta neatidėliojant: kuo ilgiau laukiama, tuo daugiau vietų, kur tas
pats dalykas jau pataisytas dviem skirtingais būdais, ir tuo brangesnis
kiekvienas `cherry-pick`.

## Kas šioje šakoje yra, o `main` nėra

- `contacts/record_blocks.py` — kortelės vidurinės kolonos blokų registras
  (`register_block`, `kinds`: kontakto ir įmonės kortelės turi skirtingus
  blokus); `contacts/record_blocks_demo.py` — pavyzdiniai duomenys
  (`CRM_DEMO_BLOCKS=1`, niekada produkcijoje), `compose.staging.yaml` juos
  įjungia staginge.
- `Person.personal_code` + `contacts/validators.py` (11 skaitmenų, šimtmečio
  skaitmuo, kontrolinis skaitmuo) ir paieška pagal jį.
- `docs/REGITRA-INTEGRACIJA.md` — kaip Regitros dalis vėliau iškeliama į
  atskirą repozitorijų, kai ji turės savo modelius ir migracijas.

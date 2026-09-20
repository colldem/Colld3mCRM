# Šaka `regitra`

Regitros CRM versija. Nuo bendrinio produkto ji skiriasi tuo, kas gyvena tik
Regitros poreikiams: įrašo kortelės vidurinė kolona su registrų blokais, asmens
kodas ir (toliau) specializuota paieška su pagrindu bei prieigos seansai.

| Šaka | Kas tai | Diegiama |
| --- | --- | --- |
| `main` | bendrinis, viešas CRM | `v*` žyma → produkcija |
| `regitra` | ši versija | dar nediegiama |

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

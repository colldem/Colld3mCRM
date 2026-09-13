# Oracle suderinamumo patikra

**Išvada:** CRM palaikoma ir testuojama su PostgreSQL. Oracle nėra palaikoma
produkcijos platforma, bet atstumas iki jos išmatuotas ir nedidelis. CI darbas
`oracle-compatibility` kiekvieno pakeitimo metu paleidžia visus testus su
Oracle Database Free 23 ir įkelia ataskaitą (`oracle-report`); build'o jis
nesustabdo.

## Būklė (2026-09-13)

| Sritis | Rezultatas |
|---|---|
| Prisijungimas (`python-oracledb` thin, be Oracle kliento) | ✅ veikia |
| Visos migracijos (0001–0052) | ✅ praeina |
| Testai | **515 iš 644 praeina**; 129 krenta; 5 praleisti (PostgreSQL specifiniai) |
| Klaidų rūšys | viena: `ORA-22848: cannot use NCLOB type as comparison key` |

Patikros metu rastos ir ištaisytos dvi problemos, kurios buvo ir PostgreSQL rizika:
`Translation.msgid` turėjo unikalų indeksą ant neriboto teksto (PostgreSQL lūžtų
ties ~2,7 kB) ir migracija rikiavo pagal teksto stulpelį. Dabar unikalumas per
SHA-256 (`msgid_hash`, migracija 0052).

## Likęs darbas

Oracle neleidžia `DISTINCT`, `GROUP BY` ir `ORDER BY` su `NCLOB` stulpeliais, o
Django `TextField` Oracle'e yra `NCLOB`. CRM modeliai `Person`, `Company`,
`Activity` turi teksto laukus, todėl lūžta užklausos, kurios:

| Vieta | Kiekis | Taisymas |
|---|---|---|
| `.distinct()` ant įrašų su teksto laukais (sąrašų filtrai, paieška, analitika, laiškų priskyrimas, privatumo paieška, automatika) | 24 vietos, 11 failų | `Model.objects.filter(pk__in=qs.values("pk"))` arba `qs.values("pk").distinct()` skaičiavimams — veikia visose DB |
| `.annotate(Count(...))` ant tų pačių modelių (įmonių sąrašas, analitika, automatika) | ~25 vietos | agregatai per `Subquery`/`OuterRef` arba `values("pk")` grupavimas |

Paveikti puslapiai: kontaktų ir įmonių sąrašai, paieška, analitika, automatika,
IMAP laiškų priskyrimas, duomenų apsaugos paieška.

**Įvertinimas:** 1,5–2,5 darbo dienos (pakeitimai + patikra, kad PostgreSQL užklausų
planai nepablogėjo), po to `oracle-compatibility` darbą galima padaryti privalomu.
Papildomai Oracle'e reikėtų: PL/SQL trigerio audito žurnalo apsaugai (PostgreSQL
trigerio atitikmuo), `reporting` rodinių Oracle sintaksės ir atsarginių kopijų
per organizacijos Oracle įrankius (RMAN / Data Pump) vietoje `pg_dump`.

## Kada to reikia

Tik jei infrastruktūros politika reikalauja visas duomenų bazes laikyti Oracle.
Kitu atveju rekomenduojama atskira PostgreSQL duomenų bazė (konteineryje su CRM
arba organizacijos PostgreSQL serveryje): viskas jau ištestuota, įskaitant
audito apsaugą duomenų bazėje, atsargines kopijas ir atkūrimo pratybas.
Integracija su Oracle sistemomis nuo to nepriklauso — žr. `docs/INTEGRACIJOS.md`.

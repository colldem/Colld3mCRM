# Prieiga prie įrašų: paieška su pagrindu ir aktyvus darbas

Regitros versijoje kontaktų ir įmonių sąrašas nustoja būti visos bazės langu.
Sąraše matyti tik tie įrašai, su kuriais naudotojas **dirba dabar**, ir kiekvienas
jų ten atsirado dėl užfiksuotos priežasties. Visą bazę mato tik administratorius
ir vadovas (manager).

Pagrindas: su registro duomenimis kortelėje kiekvienas atvėrimas yra asmens
duomenų tvarkymas, tad jis turi turėti tikslą, ir tas tikslas turi būti
įrašytas.

## Rolės

| Rolė | Ką mato sąraše |
| --- | --- |
| Administratorius | visus įrašus |
| Vadovas (manager) | visus įrašus |
| Skyriaus vadovas (komandos vadovas) | savo komandos narių **aktyvius** įrašus |
| Vadybininkas / specialistas | savo **aktyvius** įrašus |
| Skaitytojas | kaip iki šiol, be pakeitimų |

Rolė nustatoma Nustatymai → Naudotojai; du paskutiniai variantai atitinka
įrašų matomumą „Tik savo aktyvūs įrašai“ ir „Tik komandos aktyvūs įrašai“.
Vadovui (manager) matomumo nustatymas negalioja — rolė visada atveria viską.
Komandos vadovas pažymimas Nustatymai → Komandos (`Team.leads`); juo galima
pažymėti tik komandos narį, o nevadovaujant jokiai komandai „komandos aktyvūs“
reiškia tą patį, ką „savo aktyvūs“ — profilio laukas vienas komandos neatveria. Vadovui aktyvūs įrašai
matomi todėl, kad jis turi galėti pavaduoti ir prižiūrėti, o ne todėl, kad jam
priklauso visa bazė — jam jie irgi baigiasi.

## Kaip įrašas atsiranda sąraše

**1. Paieška su pagrindu** (`/paieska/`, meniu „Rasti įrašą“; rodoma tik toms
rolėms, kurių sąrašas prasideda tuščias). Naudotojas įveda asmens kodą arba vardą ir pavardę,
pasirenka pagrindą iš sąrašo (skambutis klientui, kliento kreipimasis, vidinis
patikrinimas, skundo nagrinėjimas, dokumentų tvarkymas, kita) ir, jei nori,
prirašo komentarą. Radus — įrašas atsiranda jo sąraše.

**2. Priskyrimas.** Komandos vadovas, administratorius arba vadovas (manager)
įrašo kortelėje mato, kas su juo dirba, ir gali įdėti jį į darbuotojo sąrašą.
Paieškos tam nereikia; užfiksuojama, kas priskyrė. Komandos vadovas gali
priskirti tik savo komandų nariams — kitiems adresas grąžina 404. Prieigą
galima nutraukti anksčiau laiko: eilutė lieka, baigiasi tik terminas.

**3. Priminimas.** Jei naudotojui priskirtas neužbaigtas priminimas ant įrašo,
įrašas jo sąraše yra tol, kol priminimas atviras.

## Kiek laiko įrašas lieka

Numatytai — **iki dienos pabaigos** (vietos laiku 00:00). Toliau eina taisyklės,
kurios tą terminą pratęsia, kad mėnesį trunkantis darbas nedingtų kas naktį:

- **Atviras priminimas** — įrašas lieka, kol priminimas neužbaigtas. Terminas
  nebegalioja. Tai pagrindinis būdas ilgam darbui, ir jis nieko naujo nereikalauja:
  pradėdamas darbą su klientu, darbuotojas ir taip susikuria priminimą. Priminimas
  turi būti priskirtas **tam pačiam** darbuotojui — kolegos priminimas jo sąraše
  įrašo nelaiko. Ar rolė taip gali, nustatoma Nustatymai → Rolės ir teisės,
  varnelė „Palikti sąraše, kol yra aktyvus priminimas“
  (`can_keep_with_reminder`); numatytai įjungta abiem naudotojų rolėms.
- **Veikla ant įrašo** — įrašius pastabą, skambutį ar susitikimą, terminas
  atnaujinamas iki tos dienos pabaigos. Kelias dienas trunkantis darbas be
  priminimo pats savaime tęsiasi, kol prie jo grįžtama.
- **„Imu į darbą"** — sąmoningas veiksmas, pratęsiantis 30 d.; matomas vadovui
  kartu su pagrindu. Skirtas tam, kas tęsis ilgai ir neturi priminimo.

Pasibaigus terminui įrašas iš sąrašo dingsta. Jo niekas netrina — tik prieiga
baigiasi, ir norint vėl jį atverti reikia naujos paieškos su nauju pagrindu.

## Ką matyti žurnale

Kiekviena prieiga — eilutė: kas, kurį įrašą, kada atvėrė, kokiu pagrindu, kaip
ji atsirado (paieška / priskyrimas / priminimas), kas priskyrė, kada baigėsi.
Tai ir yra atsakomybės mechanizmas — ne draudimas atverti, o tai, kad kiekvienas
atvėrimas turi vardą ir priežastį.

Nustatymai → Žurnalas, veiksmas „Prieiga prie įrašo“: stulpelyje „Laukas“ —
pagrindas, „Buvo“ — kaip įrašas atsidarė (paieška su pagrindu ar priskyrė
vadovas), „Tapo“ — komentaras arba darbuotojas, kuriam priskirta.

## Tas pats įrašo kortelėje

Kortelės veiklos juostoje yra skiltis **„Prieiga“** — tos pačios eilutės, tik
apie tą vieną įrašą: kas jį atvėrė, kokiu pagrindu, su kokiu komentaru ir kada.
Kiekvienas atvėrimas yra atskira eilutė, nors sąraše įrašas lieka vienas: tą
pačią dieną pakartota paieška prieigos termino tik nepratęsia dvigubai, bet
žurnale ir kortelėje matosi abu kartai.

Skiltis rodoma tam, kas gali įrašą priskirti — administratoriui, vadovui,
komandos vadovui. Tai tas pats sprendimas, kaip ir dešinėje esantis langelis
„Kas dirba su šiuo įrašu“: kas ką atvėrė, yra faktas apie kolegas, ne apie
klientą. Duomenys imami iš žurnalo, todėl jų nepakeisi nei kortelėje, nei
niekur kitur, ir jie pasitraukia kartu su žurnalo saugojimo terminu.

## Asmens kodas

Kortelėje jis rodomas uždengtas — `3890101****`. Visą reikšmę atiduoda tik
`POST /kontaktai/<pk>/asmens-kodas/` (`contacts/personal_code.py`), ir kiekvienas
toks atidavimas įrašomas į žurnalą kaip „Asmens kodo peržiūra" su peržiūrėtojo
vardu ir asmeniu, kurio kodas žiūrėtas. Paties kodo žurnale nėra.

Uždengta ir kortelės HTML: nei rodomoje reikšmėje, nei redagavimo laukelyje
tikro kodo nėra, todėl jo nepamatysi nei puslapio šaltinyje, nei atsitiktinai
per petį. Redaguojant laukas pirma užklausia serverio — taigi ir redagavimas
lieka žurnale.

Kas gali peržiūrėti: tas, kas mato tą kortelę. Atskiros teisės nėra sąmoningai —
klientų aptarnavimo specialistui kodas reikalingas kasdien, tad ribojimas
trukdytų, o atsakomybę sukuria žurnalas.

## Bendra paieška viršuje

Ji lieka, bet ne kaip antras kelias į bazę. Du apribojimai:

- **Asmens kodas atpažįstamas tik visas.** Įvedus dalį kodo neieškoma pagal jį
  visai — kitaip keturi skaitmenys ir grįžęs vardų sąrašas atsakytų, kas yra
  bazėje. Vienuolika skaitmenų nurodo vieną žmogų, tad tik tokio ilgio užklausa
  ir verta atsakymo. Galioja visiems, įskaitant administratorių.
- **Kas mato ne visą bazę, variantų negauna, kol užklausa neįvardija žmogaus:**
  visas vardas ir pavardė, telefono numeris arba asmens kodas. Vietoj sąrašo
  rodomas paaiškinimas, kodėl tuščia. Matantiems visą bazę niekas nesikeičia —
  jiems naršyti galima.

Antrasis apribojimas saugo ir tuos matomumo variantus, kuriuose be savininko
likę įrašai matomi visiems (`Tik savo`, `Tik komandos`) — ten paieškos laukelis
buvo trečias būdas peržiūrėti bazę be pagrindo.

## Ko šis modelis nedaro

Jis neriboja, kiek įrašų galima atsiverti, ir netikrina, ar pagrindas teisingas.
Tai sąmoninga: griežtesnis ribojimas trukdytų darbui, o piktnaudžiavimą gaudo
žurnalas ir peržiūra, ne forma.

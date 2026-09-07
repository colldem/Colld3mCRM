# CRM 0.4.0 dizaino ir funkcijų atitiktis

Atitiktis vertinta pagal `CRM_prototipai_aktualus.zip` prototipus ir vėlesnes naudotojo pastabas. Kai prototipas buvo neaiškus, pasirinktas įprastas CRM elgesys, prieinamumas ir saugus duomenų išsaugojimas.

| Sritis | 0.4.0 rezultatas | Būsena |
|---|---|---|
| Bendras karkasas | Šviesi AdminLTE pagrindu suvienodinta sąsaja, tamsiai mėlynas meniu, vienodo stiliaus SVG ikonos | Įgyvendinta |
| Navigacija | Pašalintas bendras „Veiklos“ punktas, palikti kontaktai, įmonės, priminimai, importas / eksportas, archyvas ir nustatymai | Įgyvendinta |
| Kontaktų ir įmonių sąrašai | Paieška, rikiavimas, 50 arba 100 eilučių, stulpelių valdymas, filtrai, išsaugoti filtrai ir masiniai veiksmai | Įgyvendinta |
| Sąrašo redagavimas | Žymos ir kategorijos keičiamos neišeinant iš sąrašo, mėgstami kontaktai pažymimi žvaigždute | Įgyvendinta |
| Kontaktų kortelė | Keli telefonai, el. paštai, adresai, URL ir įmonės, atskirų laukų redagavimas vietoje | Įgyvendinta |
| Įmonių kortelė | Rekvizitai, kontaktiniai asmenys ir bendra įmonės bei susietų kontaktų istorija | Įgyvendinta |
| Istorija ir failai | Formatuojamas tekstas, failai ir nuotraukos, saugus atsisiuntimas, ilgų pavadinimų laužymas | Įgyvendinta |
| Priminimai | Kontakto priminimai, bendras varpelis, aktyvių ir suplanuotų priminimų skirtukai, automatinis atnaujinimas | Įgyvendinta |
| Importas ir eksportas | UTF-8 CSV ir XLSX importas, kontaktų bei įmonių eksportas, pažymėtų įrašų eksportas | Įgyvendinta |
| Dublikatai | Kontaktų ir įmonių tikrinimas, įspėjimai, importo ataskaita ir peržiūros puslapis | Įgyvendinta |
| Nustatymai | Profilis, žymų ir kategorijų administravimas, žymų spalvos, dublikatų taisyklės | Įgyvendinta |
| Kalbos | Lietuvių ir anglų sąsaja su išsaugomu pasirinkimu | Įgyvendinta |
| Mobilus vaizdas | Prisitaikantis meniu ir turinys, plačios lentelės slenka savo srityje | Įgyvendintas bazinis variantas |
| Išorinė prieiga | HTTPS per privatų Tailscale tailnet domeną | Įgyvendinta |

## Sąmoningi sprendimai

- „Būklė“ pašalinta iš kontaktų ir įmonių filtrų pagal naudotojo sprendimą.
- Archyvavimas rodomas įrašo kortelėje arba pažymėjus sąrašo įrašus. Negrįžtamas šalinimas nėra pagrindinis sąrašo veiksmas.
- Įmonės istorija sujungia pačios įmonės ir jos susietų kontaktų įrašus. Kontakto istorija rodo tik to kontakto įrašus.
- Tailscale adresas skirtas tik prie to paties tailnet prijungtiems įrenginiams. Viešas anoniminis interneto adresas sąmoningai nekuriamas.

## Patikra

- Vietinis leidimo patikros scenarijus: 70 testų.
- UGREEN Docker aplinka: 70 testų, migracijos ir sveikatos patikra.
- Naršyklėje patikrinti pagrindiniai kontaktų, įmonių, filtrų, redagavimo, istorijos, priminimų, importo, eksporto, nustatymų ir kalbų scenarijai.
- Galutinė vizualinė apdaila ir papildomas mobiliojo vaizdo tankio optimizavimas gali būti tęsiami kaip atskiras UX etapas.

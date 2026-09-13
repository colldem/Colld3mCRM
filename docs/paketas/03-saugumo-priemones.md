# 3. Saugumo priemonės

Kiekviena priemonė nurodyta su vieta kode ar konfigūracijoje ir tuo, kaip ji
patikrinama. Stulpelis „Organizacija" — kas lieka infrastruktūros atsakomybe
(bendros atsakomybės modelis). Sritys sugrupuotos pagal įprastas informacijos
saugos kontrolių temas; tai nėra atitikties sertifikavimo teiginys.

## 3.1 Tapatybė ir prieiga

| Priemonė | Įgyvendinimas | Patikra | Organizacija |
|---|---|---|---|
| Vieningas prisijungimas | OIDC su Entra ID arba AD FS; žetono parašas (JWKS), nonce, `iss`, `aud`, `exp`, `tid`; bendras „common" katalogas draudžiamas | testai `DirectoryAccessTests` | programos registracija, MFA ir sąlyginės prieigos politika |
| Rolės pagal AD grupes | grupė → rolė ir komandos kiekvieno prisijungimo metu; stipriausia rolė; be CRM grupės — atmetama; grupių „overage" atmetamas su paaiškinimu | testai, „Patikrinti žetoną" įrankis | grupių valdymas AD |
| Tapatybės pririšimas | po pirmo prisijungimo naudotojas atpažįstamas pagal nekintamą `oid`/`sub`; tas pats el. paštas kitam žmogui neprisijungia | testai | — |
| Vien SSO režimas | vietiniai slaptažodžiai tik avarinėms paskyroms (`CRM_BREAK_GLASS_USERS`); kitų vietinės sesijos baigiamos | testai `SsoOnlyAndSessionRefreshTests` | avarinės paskyros slaptažodžio saugojimas |
| Greitas prieigos atšaukimas | sesija kas 15 min. (nustatoma) tyliai pertikrinama IdP; AD išjungtas ar iš grupės pašalintas naudotojas atjungiamas | testai | naudotojų išjungimas AD |
| Neaktyvios paskyros | išjungiamos po nustatyto dienų skaičiaus; kartu nustoja veikti API raktai | testai `InactiveAccountTests` | termino parinkimas |
| Mažiausios privilegijos | 4 rolės, teisių lentelė, komandų ir įrašų matomumas; „Skaitytojas" užtikrinamas serveryje (middleware), ne tik sąsajoje | testai `ReadOnlyRoleTests` | rolių priskyrimo tvarka |
| Vietiniai slaptažodžiai | Argon2, ≥12 simbolių, 4 validatoriai; katalogo naudotojams vietinis slaptažodis neleidžiamas | Django `check --deploy` | — |
| Slaptažodžių spėliojimas | 5 klaidos → 30 min. blokada pagal IP ir naudotoją; tikras kliento IP už proxy (`CRM_TRUSTED_PROXIES`), jo suklastoti negalima | testai `ClientAddressTests` | proxy adresų sąrašas |
| Sesijos | HttpOnly, SameSite=Lax, Secure (HTTPS), neaktyvumo laikas 8 val. (nustatoma), CSRF apsauga | `check --deploy` | — |
| Pirmas administratorius | vienkartinis `CRM_SETUP_TOKEN`, puslapis išsijungia sukūrus naudotoją | testai | žetono saugojimas |

## 3.2 Duomenų apsauga

| Priemonė | Įgyvendinimas | Patikra | Organizacija |
|---|---|---|---|
| Šifravimas perdavimo metu | HTTPS iki proxy; HSTS; Secure slapukai; SMTP/IMAP TLS | `check --deploy` | TLS sertifikatas; proxy→CRM segmentas vidiniame tinkle |
| Integracijų paslaptys | Fernet šifravimas DB (`CRM_SECRETS_KEY`, laikomas tik `.env`) | testai | rakto saugojimas |
| API raktai | DB saugomas tik SHA-256; galiojimo terminas 30–365 d.; 120 užkl./min; scope; skaitytojo raktai tik skaitymui | testai `ApiTokenLifecycleTests` | raktų išdavimo tvarka |
| Kopijos | age šifravimas viešuoju raktu (privatus — ne serveryje), SHA-256 sumos, `BACKUP_REQUIRE_ENCRYPTION` | CI `backup-restore` | disko šifravimas, kopijų saugykla, privataus rakto saugojimas |
| Duomenų subjekto teisės | ZIP eksportas; ištrynimas su failais, laiškais ir audito nuasmeninimu | testai `DataSubjectRequestTests` | užklausų procesas su DAP |
| Saugojimo terminai | archyvuotų įrašų, gautų laiškų, audito žurnalo; kasdien, su peržiūra | testai `RetentionTests` | terminų nustatymas |
| Testinė aplinka | `CRM_ENVIRONMENT≠production` išjungia SMTP/IMAP/SSO/webhook'us; staging duomenys nuasmeninami | testai `StagingAnonymisationTests` | staging prieigos ribojimas |
| Ataskaitų prieiga | `reporting` schema be laisvo teksto ir paslapčių; rolė tik `SELECT` | PostgreSQL testai CI | DWH tinklo prieiga |

## 3.3 Programos sauga

| Priemonė | Įgyvendinimas | Patikra |
|---|---|---|
| XSS | Django automatinis išvedimo apsaugojimas; vienintelis `mark_safe` tikrinamas regresijos testais | testai `RichTextEscapingTests`, bandit |
| Content-Security-Policy | skriptai tik iš CRM arba su kiekvienos užklausos nonce; be įterptinių tvarkytojų; be rėmelių, įskiepių; formos tik į CRM | testai `ContentSecurityPolicyTests` |
| Kitos antraštės | X-Frame-Options DENY, nosniff, Referrer-Policy, Permissions-Policy, COOP | testai |
| Injekcijos | ORM parametrizuotos užklausos; CSV eksportuose formulių neutralizavimas | bandit, testai |
| Failų įkėlimas | ≤10 MB, plėtinių sąrašas, ClamAV kiekvienam failui (priedai, laiškai, nuotraukos, importas); neprieinamas skeneris → atmetama | testai `AntivirusTests`, CI su tikru ClamAV |
| Failų atsisiuntimas | tik prisijungus, pagal įrašo matomumą | testai |
| Webhook'ai | HMAC-SHA256 parašas; tik http(s) adresai | testai |
| Skaitytojo apribojimai | serverio middleware atmeta redagavimo puslapius ir rašymus; atmetimai audituojami | testai |

## 3.4 Stebėsena ir auditas

| Priemonė | Įgyvendinimas | Organizacija |
|---|---|---|
| Audito žurnalas | įrašai, nustatymai, naudotojai, importas/eksportas, prisijungimai, blokados, katalogo pakeitimai, atmetimai; su IP ir `request_id` | peržiūros tvarka |
| Nekeičiamumas | programa draudžia keisti/trinti; PostgreSQL trigeris — taip pat; išimtys: saugojimo termino valymas ir asmens nuasmeninimas (tik vertės, ne faktai) | DB superuser prieigos kontrolė; kopija SIEM'e |
| SIEM | JSON žurnalai stdout: programa, `crm.security` (visi audito įvykiai be asmens duomenų), Gunicorn access log be query string | žurnalų surinkimas, įspėjimai |
| Metrikos | `/metrics` su žetonu: DB, antivirusas, foniniai darbai, nesėkmingi prisijungimai, skaitytojo atmetimai, besibaigiantys raktai | Prometheus ir įspėjimai |
| Sveikata | `/health/live`, `/health/ready`; kopijų konteinerio sveikata pagal paskutinę sėkmingą kopiją | stebėsena |

## 3.5 Infrastruktūra ir tiekimo grandinė

| Priemonė | Įgyvendinimas | Patikra |
|---|---|---|
| Konteineriai | ne root (UID 10001), `no-new-privileges`; Kubernetes: read-only root, seccomp RuntimeDefault, visos capabilities atmestos, be SA žetono, NetworkPolicy | CI read-only paleidimas, kubeconform |
| Priklausomybės | tikslios versijos; bazinių image SHA; Dependabot kas savaitę | Dependabot |
| Pažeidžiamumai | pip-audit (Python), Trivy (image, HIGH/CRITICAL su pataisymu — build krenta), bandit, CodeQL | CI kiekvienam pakeitimui |
| SBOM | CycloneDX (Python ir image) kiekvieno CI artefaktai; GHCR image su SBOM ir provenance atestacijomis | CI |
| Pakeitimų valdymas | kodas Git; kiekvienas pakeitimas per CI; automatinis staging; produkcija tik per versijos žymą su kopija ir sveikatos patikra | GitHub Actions |
| Veiklos tęstinumas | šifruotos kopijos, kopija už serverio ribų, atkūrimo skriptas, automatinės atkūrimo pratybos | CI `backup-restore` |
| Našumas | apkrovos testas su slenksčiais (p95 < 2 s, klaidos < 1 %) | CI `load` |

## 3.6 Žinomos ribos

Žr. [09 — apribojimai ir rizikos](09-apribojimai-ir-rizikos.md): nėra nepriklausomo
įsiskverbimo testo; DB superuser gali apeiti audito trigerį; kopijose ištrinti
duomenys lieka iki kopijų galiojimo pabaigos; proxy→CRM segmentas be TLS (vidinis tinklas).

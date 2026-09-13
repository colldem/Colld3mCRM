# 2. Architektūra ir schemos

Schemos pateiktos Mermaid formatu (GitHub, GitLab, Confluence ir dauguma
Markdown peržiūros priemonių jas atvaizduoja).

## 2.1 Loginė schema

```mermaid
flowchart LR
  U[Darbuotojo naršyklė] -- HTTPS 443 --> P[Organizacijos reverse proxy / WAF]
  P -- HTTP 8080 --> W[crm-web<br/>Django + Gunicorn]
  subgraph VM[CRM serveris — Docker Compose]
    I[crm-init<br/>vienkartinis] -.-> W
    W --> DB[(crm-db<br/>PostgreSQL 17)]
    K[crm-worker<br/>foniniai darbai] --> DB
    W --> M[/runtime/media<br/>priedai/]
    K --> M
    B[crm-backup<br/>age + rclone] --> DB
    B --> M
    B --> BK[/runtime/backups<br/>šifruoti rinkiniai/]
    W -- INSTREAM 3310 --> AV[crm-clamav]
    K --> AV
  end
  W -- OIDC 443 --> IDP[Entra ID / AD FS]
  K -- SMTP 587 / IMAP 993 --> MAIL[Pašto serveris]
  K -- HTTPS --> WH[Webhook gavėjai]
  B -- HTTPS / SFTP --> OFF[Kopijų saugykla]
  W -. stdout JSON .-> SIEM[SIEM]
  PR[Prometheus] -- /metrics --> P
  DWH[Duomenų saugykla] -- 5432 tik reporting.* --> DB
```

## 2.2 Prisijungimas ir teisės

```mermaid
sequenceDiagram
  participant N as Naršyklė
  participant C as CRM
  participant I as Entra ID / AD FS
  N->>C: /oidc/authenticate/
  C->>N: 302 į IdP (state, nonce)
  N->>I: prisijungimas (MFA pagal organizacijos politiką)
  I->>N: 302 atgal su code
  N->>C: /oidc/callback/?code
  C->>I: code → ID žetonas (server-to-server)
  C->>C: parašas, nonce, iss, aud, exp, tid; tapatybė pagal oid
  C->>C: AD grupės → rolė ir komandos; be CRM grupės — atmetama
  C->>N: sesija
  loop kas 15 min (nustatoma)
    C->>I: tylus pertikrinimas (prompt=none)
    I-->>C: išjungtas naudotojas → atjungiama; pakitusios grupės → pritaikoma
  end
```

## 2.3 Aplinkos

```mermaid
flowchart LR
  DEV[Kūrimas<br/>lokaliai, SQLite,<br/>be tikrų duomenų] -->|push į main| CI[CI: testai, sauga,<br/>atkūrimo pratybos, apkrova]
  CI -->|automatiškai| STG[Staging<br/>nuasmeninta produkcijos kopija<br/>SMTP/IMAP/SSO/webhook'ai išjungti]
  STG -->|versijos žyma v*| PROD[Produkcija<br/>kopija prieš diegimą,<br/>sveikatos patikra]
```

## 2.4 Asmens duomenų srautai

```mermaid
flowchart TB
  D[Darbuotojas] -- įveda / importuoja --> CRM[(CRM duomenų bazė)]
  IMAP[Organizacijos pašto dėžutė] -- laiškai iš kontaktų --> CRM
  CRM -- pranešimai --> SMTP[Darbuotojų el. paštas]
  CRM -- šifruotos kopijos --> BK[Kopijų saugykla]
  CRM -- nuasmeninta kopija --> STG[Staging]
  CRM -- API / webhook'ai<br/>tik įjungus --> EXT[Organizacijos sistemos]
  CRM -- reporting.* be laisvo teksto --> DWH[DWH / BI]
  CRM -- žurnalai be asmens duomenų --> SIEM[SIEM]
  DS[Duomenų subjekto užklausa] --> ADM[Administratorius]
  ADM -- ZIP eksportas / ištrynimas --> CRM
```

## 2.5 Komponentai ir duomenų vietos

| Komponentas | Paskirtis | Duomenys | Tinklas |
|---|---|---|---|
| `crm-web` | Sąsaja, API, prisijungimas | nesaugo (be `/tmp`) | įeina 8080 iš proxy |
| `crm-worker` | Pranešimai, IMAP, webhook'ai, automatika, saugojimo terminai, neaktyvių paskyrų išjungimas | nesaugo | išeina SMTP, IMAP, HTTPS |
| `crm-db` | PostgreSQL | visi įrašai, auditas | tik Docker tinkle (arba 5432 DWH) |
| `runtime/media` | Priedų failai | failai | — |
| `crm-backup` | Šifruotos kopijos | `runtime/backups` | išeina į kopijų saugyklą |
| `crm-clamav` | Antivirusas | parašai `runtime/clamav` | išeina parašų atnaujinimui |
| `crm-init` | `runtime/media` teisės prieš paleidimą | — | — |

Kubernetes variantas: web Deployment (2+ replikos), migracijų Job, 8 CronJob'ai
vietoj `crm-worker`, išorinis PostgreSQL ir S3 saugykla — `docs/KUBERNETES.md`.

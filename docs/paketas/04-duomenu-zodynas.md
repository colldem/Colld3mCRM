# Duomenų žodynas

> Generuojama: `python manage.py data_dictionary > docs/paketas/04-duomenu-zodynas.md`.
> Testas neleidžia pridėti modelio ar pakeisti laukų neatnaujinus šio dokumento.

Visi duomenys laikomi vienoje PostgreSQL duomenų bazėje (priedų failai — `runtime/media` arba S3).
Asmens duomenų tvarkymo tikslai, pagrindai ir rizikos — DAPV juodraštyje (05).

## Kategorijos

| Kodas | Kategorija |
|---|---|
| A | Asmens duomenys: tapatybė ir kontaktai |
| L | Laisvas tekstas — gali būti bet kokių asmens duomenų |
| D | Darbuotojų (naudotojų) duomenys |
| S | Paslaptys ir saugumo duomenys (šifruojami arba hash) |
| R | Ryšiai, klasifikatoriai, būsenos |
| T | Techniniai duomenys ir konfigūracija |

## User (`auth_user`)

**Paskirtis:** CRM naudotojo paskyra (Django). **Saugojimas:** kol yra darbuotojas; neaktyvi išjungiama pagal terminą.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `password` | CharField | taip | S |
| `last_login` | DateTimeField | ne | D |
| `is_superuser` | BooleanField | taip | T |
| `username` | CharField | taip | D |
| `first_name` | CharField | ne | D |
| `last_name` | CharField | ne | D |
| `email` | CharField | ne | D |
| `is_staff` | BooleanField | taip | T |
| `is_active` | BooleanField | taip | T |
| `date_joined` | DateTimeField | taip | D |
| `groups` | ryšys → Group (daug) | — | T |
| `user_permissions` | ryšys → Permission (daug) | — | T |

## Activity (`contacts_activity`)

**Paskirtis:** Bendravimo istorija: pastabos, skambučiai, susitikimai, laiškai. **Saugojimas:** kartu su įrašu.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `created_at` | DateTimeField | ne | T |
| `updated_at` | DateTimeField | ne | T |
| `deleted_at` | DateTimeField | ne | T |
| `person` | ryšys → Person | ne | R |
| `company` | ryšys → Company | ne | R |
| `activity_type` | CharField | taip | T |
| `text` | TextField | taip | L |
| `created_by` | ryšys → User | taip | D |
| `submission_token` | CharField | ne | T |
| `message_id` | CharField | ne | T |

## AnalyticsSnapshot (`contacts_analyticssnapshot`)

**Paskirtis:** Iš anksto suskaičiuoti analitikos skaičiai (tik skaičiai ir įrašų ID). **Saugojimas:** perrašoma; senesni nei 1 d. trinami.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `key` | CharField | taip | T |
| `payload` | JSONField | taip | T |
| `computed_at` | DateTimeField | taip | T |

## ApiToken (`contacts_apitoken`)

**Paskirtis:** REST API raktai. **Saugojimas:** iki galiojimo pabaigos / atšaukimo; įrašas lieka istorijai.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `name` | CharField | taip | T |
| `token_hash` | CharField | taip | S |
| `prefix` | CharField | taip | S |
| `scope` | CharField | taip | T |
| `created_by` | ryšys → User | taip | D |
| `last_used_at` | DateTimeField | ne | T |
| `revoked_at` | DateTimeField | ne | T |
| `expires_at` | DateTimeField | ne | T |
| `rate_window_start` | DateTimeField | ne | T |
| `rate_count` | PositiveIntegerField | taip | T |
| `created_at` | DateTimeField | ne | T |

## Attachment (`contacts_attachment`)

**Paskirtis:** Prie veiklos prisegti failai. **Saugojimas:** kartu su veikla; failas ištrinamas kartu.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `created_at` | DateTimeField | ne | T |
| `updated_at` | DateTimeField | ne | T |
| `deleted_at` | DateTimeField | ne | T |
| `activity` | ryšys → Activity | taip | R |
| `file` | FileField | taip | L |
| `original_name` | CharField | taip | L |
| `content_type` | CharField | ne | T |
| `size` | PositiveIntegerField | taip | T |

## AuditLog (`contacts_auditlog`)

**Paskirtis:** Veiksmų žurnalas: kas, ką, kada, iš kur. **Saugojimas:** pagal „Saugoti įrašus (dienų)“ (≥180 d. arba visada); nuasmeninamas ištrinant asmenį.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `actor` | ryšys → User | ne | D |
| `actor_label` | CharField | ne | D |
| `action` | CharField | taip | T |
| `target_type` | CharField | ne | T |
| `target_id` | CharField | ne | T |
| `target_label` | CharField | ne | L |
| `field` | CharField | ne | T |
| `old_value` | TextField | ne | L |
| `new_value` | TextField | ne | L |
| `detail` | JSONField | ne | L |
| `ip` | GenericIPAddressField | ne | D |
| `created_at` | DateTimeField | ne | T |

## AutomationLog (`contacts_automationlog`)

**Paskirtis:** Automatikos vykdymo žurnalas. **Saugojimas:** 90 d. (automatiškai).

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `rule` | ryšys → AutomationRule | taip | T |
| `target_type` | CharField | taip | T |
| `target_id` | CharField | taip | T |
| `target_label` | CharField | ne | L |
| `status` | CharField | taip | T |
| `detail` | JSONField | ne | L |
| `created_at` | DateTimeField | ne | T |

## AutomationRule (`contacts_automationrule`)

**Paskirtis:** Automatikos taisyklės. **Saugojimas:** kol naudojamos.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `name` | CharField | taip | T |
| `trigger` | CharField | taip | T |
| `threshold` | PositiveIntegerField | taip | T |
| `action` | CharField | taip | T |
| `action_user` | ryšys → User | ne | D |
| `action_tag` | ryšys → Tag | ne | T |
| `action_text` | CharField | ne | L |
| `action_due_days` | PositiveIntegerField | taip | T |
| `active` | BooleanField | taip | T |
| `last_run_at` | DateTimeField | ne | T |
| `created_by` | ryšys → User | ne | D |
| `created_at` | DateTimeField | ne | T |

## Category (`contacts_category`)

**Paskirtis:** Kategorijos. **Saugojimas:** kol naudojamos.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `name` | CharField | taip | T |

## Company (`contacts_company`)

**Paskirtis:** Įmonė / organizacija (gali būti individuali veikla). **Saugojimas:** kol aktyvi; archyvuota — pagal terminą.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `description` | TextField | ne | L |
| `created_at` | DateTimeField | ne | T |
| `updated_at` | DateTimeField | ne | T |
| `deleted_at` | DateTimeField | ne | T |
| `merged_into` | ryšys → Company | ne | R |
| `owner` | ryšys → User | ne | D |
| `created_by` | ryšys → User | ne | D |
| `name` | CharField | taip | A |
| `company_code` | CharField | ne | A |
| `vat_code` | CharField | ne | A |
| `address` | CharField | ne | A |
| `city` | CharField | ne | T |
| `phone` | CharField | ne | A |
| `phone_digits` | CharField | ne | A |
| `email` | CharField | ne | A |
| `url` | CharField | ne | A |
| `responsibles` | ryšys → User (daug) | — | D |
| `tags` | ryšys → Tag (daug) | — | R |
| `categories` | ryšys → Category (daug) | — | R |

## CustomField (`contacts_customfield`)

**Paskirtis:** Administratoriaus apibrėžti papildomi laukai. **Saugojimas:** kol naudojami.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `entity` | CharField | taip | T |
| `name` | CharField | taip | T |
| `field_type` | CharField | taip | T |
| `options` | JSONField | ne | T |
| `order` | PositiveIntegerField | taip | T |
| `created_at` | DateTimeField | ne | T |

## CustomValue (`contacts_customvalue`)

**Paskirtis:** Papildomų laukų reikšmės. **Saugojimas:** kartu su įrašu.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `field` | ryšys → CustomField | taip | R |
| `person` | ryšys → Person | ne | R |
| `company` | ryšys → Company | ne | R |
| `value` | TextField | ne | L |

## DirectoryGroupMapping (`contacts_directorygroupmapping`)

**Paskirtis:** AD grupių susiejimas su rolėmis ir komandomis. **Saugojimas:** kol naudojamas.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `group` | CharField | taip | T |
| `label` | CharField | ne | T |
| `role` | CharField | ne | T |
| `team` | ryšys → Team | ne | T |
| `created_at` | DateTimeField | ne | T |

## DuplicateCandidate (`contacts_duplicatecandidate`)

**Paskirtis:** Foninės patikros rastos galimų dublikatų poros. **Saugojimas:** perrašoma kiekvienos patikros metu.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `kind` | CharField | taip | T |
| `left_id` | PositiveIntegerField | taip | T |
| `right_id` | PositiveIntegerField | taip | T |
| `reasons` | CharField | taip | T |
| `found_at` | DateTimeField | ne | T |

## DuplicateException (`contacts_duplicateexception`)

**Paskirtis:** Poros, pažymėtos „ne dublikatas“. **Saugojimas:** kol yra įrašai.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `kind` | CharField | taip | T |
| `left_id` | PositiveIntegerField | taip | T |
| `right_id` | PositiveIntegerField | taip | T |
| `created_by` | ryšys → User | ne | D |
| `created_at` | DateTimeField | ne | T |

## DuplicateSettings (`contacts_duplicatesettings`)

**Paskirtis:** Dublikatų tikrinimo nustatymai. **Saugojimas:** nuolat.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `enabled` | BooleanField | taip | T |
| `check_on_edit` | BooleanField | taip | T |
| `check_on_import` | BooleanField | taip | T |
| `updated_at` | DateTimeField | ne | T |

## EmailAddress (`contacts_emailaddress`)

**Paskirtis:** Asmens el. pašto adresai. **Saugojimas:** kartu su asmeniu.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `person` | ryšys → Person | taip | R |
| `email` | CharField | taip | A |
| `label` | CharField | ne | T |
| `is_primary` | BooleanField | taip | T |

## IncomingMail (`contacts_incomingmail`)

**Paskirtis:** Iš IMAP dėžutės gauti laiškai, laukiantys priskyrimo. **Saugojimas:** pagal „Gauti el. laiškai“ terminą.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `message_id` | CharField | taip | T |
| `from_addr` | CharField | taip | A |
| `to_addrs` | CharField | ne | A |
| `subject` | CharField | ne | L |
| `body` | TextField | ne | L |
| `received_at` | DateTimeField | taip | T |
| `resolved_at` | DateTimeField | ne | T |
| `resolved_activity` | ryšys → Activity | ne | R |
| `created_at` | DateTimeField | ne | T |

## JobHeartbeat (`contacts_jobheartbeat`)

**Paskirtis:** Foninių darbų paskutinė sėkmė ar klaida (stebėsenai). **Saugojimas:** nuolat, perrašoma.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `name` | CharField | taip | T |
| `last_success_at` | DateTimeField | ne | T |
| `last_failure_at` | DateTimeField | ne | T |
| `last_error` | CharField | ne | T |

## Person (`contacts_person`)

**Paskirtis:** Kontaktinis asmuo. **Saugojimas:** kol aktyvus; archyvuotas — pagal „Archyvuoti kontaktai ir įmonės“ terminą; ištrynimas pagal užklausą.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `description` | TextField | ne | L |
| `created_at` | DateTimeField | ne | T |
| `updated_at` | DateTimeField | ne | T |
| `deleted_at` | DateTimeField | ne | T |
| `merged_into` | ryšys → Person | ne | R |
| `owner` | ryšys → User | ne | D |
| `created_by` | ryšys → User | ne | D |
| `favourite` | BooleanField | taip | T |
| `first_name` | CharField | taip | A |
| `last_name` | CharField | taip | A |
| `job_title` | CharField | ne | A |
| `birth_date` | DateField | ne | A |
| `personal_code_type` | CharField | ne | T |
| `personal_code_encrypted` | TextField | ne | A |
| `personal_code_hash` | CharField | ne | S |
| `external_source` | CharField | ne | T |
| `external_id` | CharField | ne | A |
| `synced_at` | DateTimeField | ne | T |
| `responsibles` | ryšys → User (daug) | — | D |
| `companies` | ryšys → Company (daug) | — | R |
| `tags` | ryšys → Tag (daug) | — | R |
| `categories` | ryšys → Category (daug) | — | R |

## PersonCompanyLink (`contacts_personcompanylink`)

**Paskirtis:** Asmens ryšys su įmone ir pareigos. **Saugojimas:** kartu su asmeniu ar įmone.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `person` | ryšys → Person | taip | R |
| `company` | ryšys → Company | taip | R |
| `role` | CharField | ne | A |
| `is_primary` | BooleanField | taip | T |

## PhoneNumber (`contacts_phonenumber`)

**Paskirtis:** Asmens telefono numeriai. **Saugojimas:** kartu su asmeniu.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `person` | ryšys → Person | taip | R |
| `number` | CharField | taip | A |
| `digits` | CharField | ne | A |
| `label` | CharField | ne | T |
| `is_primary` | BooleanField | taip | T |

## PostalAddress (`contacts_postaladdress`)

**Paskirtis:** Asmens adresai. **Saugojimas:** kartu su asmeniu.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `person` | ryšys → Person | taip | R |
| `address` | CharField | taip | A |
| `label` | CharField | ne | T |

## Reminder (`contacts_reminder`)

**Paskirtis:** Priminimai, užduotys, kalendoriaus įvykiai. **Saugojimas:** kartu su įrašu.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `created_at` | DateTimeField | ne | T |
| `updated_at` | DateTimeField | ne | T |
| `deleted_at` | DateTimeField | ne | T |
| `person` | ryšys → Person | ne | R |
| `company` | ryšys → Company | ne | R |
| `kind` | CharField | taip | T |
| `text` | CharField | taip | L |
| `description` | TextField | ne | L |
| `meeting_url` | CharField | ne | L |
| `due_at` | DateTimeField | taip | T |
| `end_at` | DateTimeField | ne | T |
| `completed_at` | DateTimeField | ne | T |
| `read_at` | DateTimeField | ne | T |
| `created_by` | ryšys → User | taip | D |
| `assigned_to` | ryšys → User | ne | D |
| `priority` | CharField | taip | T |
| `submission_token` | CharField | ne | T |
| `notify_before` | PositiveSmallIntegerField | ne | T |
| `upcoming_notified_at` | DateTimeField | ne | T |
| `assigned_notified_to` | ryšys → User | ne | D |
| `recurrence_freq` | CharField | ne | T |
| `recurrence_interval` | PositiveSmallIntegerField | taip | T |
| `recurrence_until` | DateField | ne | T |
| `recurrence_count` | PositiveSmallIntegerField | ne | T |
| `recurrence_parent` | ryšys → Reminder | ne | R |

## RolePermissions (`contacts_rolepermissions`)

**Paskirtis:** Rolių teisių lentelė. **Saugojimas:** nuolat.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `role` | CharField | taip | T |
| `permissions` | JSONField | ne | T |

## SavedFilter (`contacts_savedfilter`)

**Paskirtis:** Naudotojo išsaugoti sąrašų filtrai. **Saugojimas:** kol naudotojas juos laiko.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `user` | ryšys → User | taip | D |
| `scope` | CharField | taip | T |
| `name` | CharField | taip | L |
| `filters` | JSONField | taip | L |
| `is_default` | BooleanField | taip | T |
| `created_at` | DateTimeField | ne | T |

## SystemSettings (`contacts_systemsettings`)

**Paskirtis:** Sistemos nustatymai ir integracijos. **Saugojimas:** nuolat.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `default_page_size` | PositiveSmallIntegerField | taip | T |
| `date_format` | CharField | taip | T |
| `import_delimiter` | CharField | taip | T |
| `import_encoding` | CharField | taip | T |
| `notifications_enabled` | BooleanField | taip | T |
| `digest_default_time` | TimeField | taip | T |
| `email_host` | CharField | ne | T |
| `email_port` | PositiveIntegerField | taip | T |
| `email_host_user` | CharField | ne | D |
| `email_host_password` | CharField | ne | S |
| `email_use_tls` | BooleanField | taip | T |
| `email_use_ssl` | BooleanField | taip | T |
| `email_from` | CharField | ne | T |
| `site_base_url` | CharField | ne | T |
| `imap_enabled` | BooleanField | taip | T |
| `imap_host` | CharField | ne | T |
| `imap_port` | PositiveIntegerField | taip | T |
| `imap_user` | CharField | ne | D |
| `imap_password` | CharField | ne | S |
| `imap_folder` | CharField | ne | T |
| `oidc_enabled` | BooleanField | taip | T |
| `oidc_tenant_id` | CharField | ne | T |
| `oidc_client_id` | CharField | ne | T |
| `oidc_client_secret` | CharField | ne | S |
| `oidc_create_users` | BooleanField | taip | T |
| `oidc_provider` | CharField | taip | T |
| `oidc_issuer` | CharField | ne | T |
| `oidc_authorization_endpoint` | CharField | ne | T |
| `oidc_token_endpoint` | CharField | ne | T |
| `oidc_userinfo_endpoint` | CharField | ne | T |
| `oidc_jwks_endpoint` | CharField | ne | T |
| `oidc_groups_claim` | CharField | ne | T |
| `oidc_sync_groups` | BooleanField | taip | T |
| `sso_only` | BooleanField | taip | T |
| `oidc_session_check_minutes` | PositiveSmallIntegerField | taip | T |
| `deactivate_inactive_days` | PositiveSmallIntegerField | taip | T |
| `audit_retention_days` | PositiveIntegerField | taip | T |
| `archived_retention_days` | PositiveIntegerField | taip | T |
| `calendar_feed_enabled` | BooleanField | taip | T |
| `incoming_mail_retention_days` | PositiveIntegerField | taip | T |
| `automations_enabled` | BooleanField | taip | T |
| `updated_at` | DateTimeField | ne | T |

## Tag (`contacts_tag`)

**Paskirtis:** Žymos. **Saugojimas:** kol naudojamos.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `name` | CharField | taip | T |
| `color` | CharField | ne | T |

## Team (`contacts_team`)

**Paskirtis:** Komandos. **Saugojimas:** kol naudojamos.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `name` | CharField | taip | T |
| `visibility` | CharField | taip | T |
| `created_at` | DateTimeField | ne | T |
| `members` | ryšys → User (daug) | — | D |

## Translation (`contacts_translation`)

**Paskirtis:** Redaguoti sąsajos tekstai. **Saugojimas:** kol naudojami.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `msgid` | TextField | taip | T |
| `msgid_hash` | CharField | taip | T |
| `lt` | TextField | ne | T |
| `en` | TextField | ne | T |
| `updated_at` | DateTimeField | ne | T |
| `updated_by` | ryšys → User | ne | D |

## UserProfile (`contacts_userprofile`)

**Paskirtis:** CRM naudotojo profilis, rolė, nustatymai, katalogo susiejimas. **Saugojimas:** kol yra naudotojo paskyra.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `user` | ryšys → User | taip | D |
| `role` | CharField | taip | T |
| `record_visibility` | CharField | taip | T |
| `language` | CharField | taip | T |
| `timezone` | CharField | taip | T |
| `avatar` | FileField | ne | D |
| `digest_enabled` | BooleanField | taip | T |
| `digest_time` | TimeField | ne | T |
| `digest_skip_weekends` | BooleanField | taip | T |
| `digest_sent_on` | DateField | ne | T |
| `unsubscribe_token` | CharField | taip | S |
| `calendar_token` | CharField | taip | S |
| `menu_config` | JSONField | ne | T |
| `directory_managed` | BooleanField | taip | T |
| `directory_subject` | CharField | ne | D |
| `directory_groups` | JSONField | ne | D |
| `directory_synced_at` | DateTimeField | ne | T |
| `deactivated_reason` | CharField | ne | T |
| `updated_at` | DateTimeField | ne | T |

## WebLink (`contacts_weblink`)

**Paskirtis:** Asmens nuorodos (svetainė, profilis). **Saugojimas:** kartu su asmeniu.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `person` | ryšys → Person | taip | R |
| `url` | CharField | taip | A |
| `label` | CharField | ne | T |

## Webhook (`contacts_webhook`)

**Paskirtis:** Webhook'ų prenumeratos. **Saugojimas:** kol naudojamos.

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `target_url` | CharField | taip | T |
| `secret` | CharField | ne | S |
| `events` | JSONField | taip | T |
| `active` | BooleanField | taip | T |
| `failure_streak` | PositiveIntegerField | taip | T |
| `last_delivery_at` | DateTimeField | ne | T |
| `last_status` | CharField | ne | T |
| `created_by` | ryšys → User | ne | D |
| `created_at` | DateTimeField | ne | T |

## WebhookDelivery (`contacts_webhookdelivery`)

**Paskirtis:** Webhook'ų pristatymų eilė ir istorija. **Saugojimas:** 30 d. (automatiškai).

| Laukas | Tipas | Privalomas | Kategorija |
|---|---|---|---|
| `webhook` | ryšys → Webhook | taip | T |
| `event` | CharField | taip | T |
| `payload` | JSONField | taip | L |
| `attempts` | PositiveIntegerField | taip | T |
| `next_attempt_at` | DateTimeField | taip | T |
| `delivered_at` | DateTimeField | ne | T |
| `status` | CharField | ne | T |
| `created_at` | DateTimeField | ne | T |

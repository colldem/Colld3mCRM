"""Data dictionary: every stored field, what kind of data it is, why and how long.

``python manage.py data_dictionary`` renders docs/paketas/04-duomenu-zodynas.md
from the models and the classification below. A test fails when a model or
field is added without being classified here, and when the committed document
is stale — so the dictionary the DPO reads is the one the code actually has.
"""
from django.apps import apps
from django.contrib.auth import get_user_model

CATEGORIES = {
    "A": "Asmens duomenys: tapatybė ir kontaktai",
    "L": "Laisvas tekstas — gali būti bet kokių asmens duomenų",
    "D": "Darbuotojų (naudotojų) duomenys",
    "S": "Paslaptys ir saugumo duomenys (šifruojami arba hash)",
    "R": "Ryšiai, klasifikatoriai, būsenos",
    "T": "Techniniai duomenys ir konfigūracija",
}

# model: (paskirtis, saugojimas, numatyta kategorija)
MODELS = {
    "Person": ("Kontaktinis asmuo", "kol aktyvus; archyvuotas — pagal „Archyvuoti kontaktai ir įmonės“ terminą; ištrynimas pagal užklausą", "R"),
    "PhoneNumber": ("Asmens telefono numeriai", "kartu su asmeniu", "R"),
    "EmailAddress": ("Asmens el. pašto adresai", "kartu su asmeniu", "R"),
    "PostalAddress": ("Asmens adresai", "kartu su asmeniu", "R"),
    "WebLink": ("Asmens nuorodos (svetainė, profilis)", "kartu su asmeniu", "R"),
    "Company": ("Įmonė / organizacija (gali būti individuali veikla)", "kol aktyvi; archyvuota — pagal terminą", "R"),
    "PersonCompanyLink": ("Asmens ryšys su įmone ir pareigos", "kartu su asmeniu ar įmone", "R"),
    "Activity": ("Bendravimo istorija: pastabos, skambučiai, susitikimai, laiškai", "kartu su įrašu", "R"),
    "Attachment": ("Prie veiklos prisegti failai", "kartu su veikla; failas ištrinamas kartu", "R"),
    "Reminder": ("Priminimai, užduotys, kalendoriaus įvykiai", "kartu su įrašu", "R"),
    "CustomField": ("Administratoriaus apibrėžti papildomi laukai", "kol naudojami", "T"),
    "CustomValue": ("Papildomų laukų reikšmės", "kartu su įrašu", "R"),
    "Tag": ("Žymos", "kol naudojamos", "R"),
    "Category": ("Kategorijos", "kol naudojamos", "R"),
    "SavedFilter": ("Naudotojo išsaugoti sąrašų filtrai", "kol naudotojas juos laiko", "R"),
    "UserProfile": ("CRM naudotojo profilis, rolė, nustatymai, katalogo susiejimas", "kol yra naudotojo paskyra", "T"),
    "Team": ("Komandos", "kol naudojamos", "R"),
    "DirectoryGroupMapping": ("AD grupių susiejimas su rolėmis ir komandomis", "kol naudojamas", "T"),
    "RolePermissions": ("Rolių teisių lentelė", "nuolat", "T"),
    "DuplicateSettings": ("Dublikatų tikrinimo nustatymai", "nuolat", "T"),
    "DuplicateException": ("Poros, pažymėtos „ne dublikatas“", "kol yra įrašai", "R"),
    "SystemSettings": ("Sistemos nustatymai ir integracijos", "nuolat", "T"),
    "JobHeartbeat": ("Foninių darbų paskutinė sėkmė ar klaida (stebėsenai)", "nuolat, perrašoma", "T"),
    "AuditLog": ("Veiksmų žurnalas: kas, ką, kada, iš kur", "pagal „Saugoti įrašus (dienų)“ (≥180 d. arba visada); nuasmeninamas ištrinant asmenį", "T"),
    "IncomingMail": ("Iš IMAP dėžutės gauti laiškai, laukiantys priskyrimo", "pagal „Gauti el. laiškai“ terminą", "R"),
    "AutomationRule": ("Automatikos taisyklės", "kol naudojamos", "T"),
    "AutomationLog": ("Automatikos vykdymo žurnalas", "90 d. (automatiškai)", "T"),
    "ApiToken": ("REST API raktai", "iki galiojimo pabaigos / atšaukimo; įrašas lieka istorijai", "T"),
    "Webhook": ("Webhook'ų prenumeratos", "kol naudojamos", "T"),
    "WebhookDelivery": ("Webhook'ų pristatymų eilė ir istorija", "30 d. (automatiškai)", "T"),
    "Translation": ("Redaguoti sąsajos tekstai", "kol naudojami", "T"),
}

# Values are category codes; bandit mistakes the ones next to *_token names for
# hardcoded passwords, hence the reviewed nosec markers below.
FIELDS = {
    "Person.first_name": "A", "Person.last_name": "A", "Person.personal_code": "A",
    "Person.job_title": "A", "Person.description": "L",
    "PhoneNumber.number": "A", "EmailAddress.email": "A", "PostalAddress.address": "A", "WebLink.url": "A",
    "Company.name": "A", "Company.company_code": "A", "Company.vat_code": "A", "Company.address": "A",
    "Company.phone": "A", "Company.email": "A", "Company.url": "A", "Company.description": "L",
    "PersonCompanyLink.role": "A",
    "Activity.text": "L", "Activity.submission_token": "T", "Activity.message_id": "T",  # nosec B105
    "Attachment.file": "L", "Attachment.original_name": "L",
    "Reminder.text": "L", "Reminder.description": "L", "Reminder.meeting_url": "L",
    "Reminder.submission_token": "T",  # nosec B105
    "CustomValue.value": "L",
    "SavedFilter.filters": "L", "SavedFilter.name": "L",
    "UserProfile.avatar": "D", "UserProfile.directory_subject": "D", "UserProfile.directory_groups": "D",
    "UserProfile.unsubscribe_token": "S", "UserProfile.calendar_token": "S", "UserProfile.user": "D",  # nosec B105
    "SystemSettings.email_host_password": "S", "SystemSettings.imap_password": "S",
    "SystemSettings.oidc_client_secret": "S", "SystemSettings.email_host_user": "D", "SystemSettings.imap_user": "D",
    "AuditLog.actor": "D", "AuditLog.actor_label": "D", "AuditLog.ip": "D", "AuditLog.target_label": "L",
    "AuditLog.old_value": "L", "AuditLog.new_value": "L", "AuditLog.detail": "L",
    "IncomingMail.from_addr": "A", "IncomingMail.to_addrs": "A", "IncomingMail.subject": "L", "IncomingMail.body": "L",
    "AutomationLog.target_label": "L", "AutomationLog.detail": "L", "AutomationRule.action_text": "L",
    "ApiToken.token_hash": "S", "ApiToken.prefix": "S", "Webhook.secret": "S", "Webhook.target_url": "T",
    "WebhookDelivery.payload": "L", "JobHeartbeat.last_error": "T",
    "Translation.msgid": "T", "Translation.lt": "T", "Translation.en": "T",
}

# Django's own user table holds CRM users' identities and password hashes.
USER_FIELDS = {"username": "D", "first_name": "D", "last_name": "D", "email": "D", "password": "S",  # nosec B105
               "last_login": "D", "date_joined": "D", "is_active": "T", "is_staff": "T", "is_superuser": "T",
               "groups": "T", "user_permissions": "T"}

SENSITIVE_DEFAULTS = {"created_by", "owner", "assigned_to", "updated_by", "responsibles", "members", "user",
                      "action_user", "assigned_notified_to"}


def stored_fields(model):
    return [field for field in model._meta.get_fields()
            if (getattr(field, "concrete", False) and not field.auto_created)
            or (getattr(field, "many_to_many", False) and not field.auto_created)]


def classify(model, field):
    key = "%s.%s" % (model.__name__, field.name)
    if model is get_user_model():
        return USER_FIELDS.get(field.name)
    if key in FIELDS:
        return FIELDS[key]
    if field.name in SENSITIVE_DEFAULTS:
        return "D"
    return MODELS[model.__name__][2] if field.is_relation else "T"


def _type(field):
    if field.many_to_many:
        return "ryšys → %s (daug)" % field.related_model.__name__
    if field.is_relation:
        return "ryšys → %s" % field.related_model.__name__
    return field.get_internal_type()


def unclassified():
    """Models or user fields the dictionary does not describe yet."""
    missing = [model.__name__ for model in apps.get_app_config("contacts").get_models() if model.__name__ not in MODELS]
    missing += ["User.%s" % f.name for f in stored_fields(get_user_model()) if f.name not in USER_FIELDS]
    return missing


def render():
    lines = [
        "# Duomenų žodynas",
        "",
        "> Generuojama: `python manage.py data_dictionary > docs/paketas/04-duomenu-zodynas.md`.",
        "> Testas neleidžia pridėti modelio ar pakeisti laukų neatnaujinus šio dokumento.",
        "",
        "Visi duomenys laikomi vienoje PostgreSQL duomenų bazėje (priedų failai — `runtime/media` arba S3).",
        "Asmens duomenų tvarkymo tikslai, pagrindai ir rizikos — DAPV juodraštyje (05).",
        "",
        "## Kategorijos",
        "",
        "| Kodas | Kategorija |",
        "|---|---|",
    ]
    lines += ["| %s | %s |" % item for item in CATEGORIES.items()]
    User = get_user_model()
    models = [User] + sorted(apps.get_app_config("contacts").get_models(), key=lambda m: m.__name__)
    for model in models:
        if model is User:
            purpose, retention = "CRM naudotojo paskyra (Django)", "kol yra darbuotojas; neaktyvi išjungiama pagal terminą"
            table = "auth_user"
        else:
            purpose, retention, _ = MODELS[model.__name__]
            table = model._meta.db_table
        fields = stored_fields(model)
        counts = {}
        for field in fields:
            code = classify(model, field)
            counts[code] = counts.get(code, 0) + 1
        lines += ["", "## %s (`%s`)" % (model.__name__, table), "",
                  "**Paskirtis:** %s. **Saugojimas:** %s." % (purpose, retention), "",
                  "| Laukas | Tipas | Privalomas | Kategorija |", "|---|---|---|---|"]
        for field in fields:
            required = "—" if field.many_to_many else ("ne" if getattr(field, "null", False) or getattr(field, "blank", False) else "taip")
            lines.append("| `%s` | %s | %s | %s |" % (field.name, _type(field), required, classify(model, field)))
    return "\n".join(lines) + "\n"

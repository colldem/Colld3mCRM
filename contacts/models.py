import hashlib
from datetime import time
from secrets import token_urlsafe

from django.utils.translation import gettext_lazy as tr
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models
from django.urls import reverse


# Email-notification lead time, shared by SystemSettings and UserProfile (G7).
NOTIFY_LEAD_CHOICES = ((0, tr("Išjungta")), (15, tr("15 min.")), (60, tr("1 val.")), (1440, tr("1 diena")))


class RecordDetailsModel(models.Model):
    """Shared free-text description for a contact/company card."""
    description = models.TextField(blank=True, max_length=5000)

    class Meta:
        abstract = True


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        abstract = True


class Company(RecordDetailsModel, TimestampedModel):
    merged_into = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="merged_companies")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="owned_companies", db_index=True)
    responsibles = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="responsible_for_companies")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_companies")
    tags = models.ManyToManyField("Tag", blank=True, related_name="companies")
    categories = models.ManyToManyField("Category", blank=True, related_name="companies")
    name = models.CharField(max_length=200, db_index=True)
    company_code = models.CharField(max_length=40, blank=True, db_index=True)
    vat_code = models.CharField(max_length=40, blank=True, db_index=True)
    address = models.CharField(max_length=300, blank=True)
    # Kept apart from `address` so lists and the dashboard can show a place
    # without parsing a free-text line.
    city = models.CharField(max_length=120, blank=True, db_index=True)
    phone = models.CharField(max_length=80, blank=True)
    email = models.EmailField(blank=True)
    url = models.URLField(blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = tr("Įmonės")

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("contacts:company-detail", args=[self.pk])


class Tag(models.Model):
    COLOR_CHOICES = tuple((f"tag-color-{index}", label) for index, label in enumerate((tr("Mėlyna"), tr("Pilka"), tr("Žalia"), tr("Violetinė"), tr("Oranžinė"), tr("Žydra"), tr("Raudona"), tr("Auksinė"))))

    name = models.CharField(max_length=60, unique=True)
    color = models.CharField(max_length=20, choices=COLOR_CHOICES, blank=True)

    @property
    def color_class(self):
        # The fallback gives imported and existing tags a stable automatic color.
        return self.color or f"tag-color-{(self.pk or 1) % 8}"

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Category(models.Model):
    name = models.CharField(max_length=60, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = tr("Kategorijos")

    def __str__(self):
        return self.name


class SavedFilter(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="crm_saved_filters")
    scope = models.CharField(max_length=20, default="contacts", db_index=True)
    name = models.CharField(max_length=100)
    filters = models.JSONField(default=dict)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_default", "name"]
        constraints = [models.UniqueConstraint(fields=["user", "scope", "name"], name="unique_saved_filter_scope_name")]

    def __str__(self):
        return self.name

    @property
    def query_string(self):
        from .filters import encoded_filter_values

        return encoded_filter_values(self.filters)


class UserProfile(models.Model):
    ROLE_ADMIN = "admin"
    ROLE_MEMBER = "member"
    ROLE_RESTRICTED = "restricted"
    ROLE_CHOICES = (
        (ROLE_ADMIN, tr("Administratorius")),
        (ROLE_MEMBER, tr("Naudotojas (visi įrašai)")),
        (ROLE_RESTRICTED, tr("Naudotojas (tik savi įrašai)")),
    )

    VISIBILITY_ALL = "all"
    VISIBILITY_TEAM = "team"
    VISIBILITY_OWN = "own"
    VISIBILITY_CHOICES = (
        (VISIBILITY_ALL, tr("Visi įrašai")),
        (VISIBILITY_TEAM, tr("Tik komandos įrašai")),
        (VISIBILITY_OWN, tr("Tik savo įrašai")),
    )

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="crm_profile")
    role = models.CharField(max_length=12, choices=ROLE_CHOICES, default=ROLE_MEMBER)
    record_visibility = models.CharField(max_length=8, choices=VISIBILITY_CHOICES, default=VISIBILITY_ALL)
    language = models.CharField(max_length=5, choices=(("lt", "Lietuvių"), ("en", "English")), default="lt")
    timezone = models.CharField(max_length=64, default="Europe/Vilnius")
    avatar = models.FileField(upload_to="avatars/%Y/%m/", blank=True)
    # Email notifications (G7). Effective defaults come from SystemSettings.
    digest_enabled = models.BooleanField(default=True)
    digest_time = models.TimeField(null=True, blank=True)
    notify_lead = models.PositiveSmallIntegerField(null=True, blank=True, choices=NOTIFY_LEAD_CHOICES)
    digest_sent_on = models.DateField(null=True, blank=True)
    unsubscribe_token = models.CharField(max_length=48, unique=True, default=token_urlsafe, editable=False)
    calendar_token = models.CharField(max_length=48, unique=True, default=token_urlsafe, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    def new_calendar_token(self):
        self.calendar_token = token_urlsafe(24)
        self.save(update_fields=["calendar_token", "updated_at"])

    def __str__(self):
        return str(self.user)


class Team(models.Model):
    """A department/group. Members share record visibility per `visibility`."""
    VISIBILITY_ALL = "all"
    VISIBILITY_TEAM = "team"
    VISIBILITY_CHOICES = (
        (VISIBILITY_ALL, tr("Visi įrašai")),
        (VISIBILITY_TEAM, tr("Tik komandos įrašai")),
    )

    name = models.CharField(max_length=80, unique=True)
    visibility = models.CharField(max_length=8, choices=VISIBILITY_CHOICES, default=VISIBILITY_ALL)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="crm_teams")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class RolePermissions(models.Model):
    """Per-role capability toggles. Admins always have every capability."""
    role = models.CharField(max_length=12, unique=True)
    permissions = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return self.role


class DuplicateSettings(models.Model):
    LEVEL_CHOICES = (("strict", tr("Griežtas")), ("standard", tr("Standartinis")), ("loose", tr("Laisvas")))

    enabled = models.BooleanField(default=True)
    level = models.CharField(max_length=12, choices=LEVEL_CHOICES, default="standard")
    check_on_edit = models.BooleanField(default=True)
    check_on_import = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def load(cls):
        settings_object, _ = cls.objects.get_or_create(pk=1)
        return settings_object

    def save(self, *args, **kwargs):
        self.pk = 1
        return super().save(*args, **kwargs)


class SystemSettings(models.Model):
    PAGE_SIZE_CHOICES = ((25, "25"), (50, "50"), (100, "100"))
    DATE_FORMAT_CHOICES = (
        ("Y-m-d", "2026-12-31"),
        ("d.m.Y", "31.12.2026"),
        ("m/d/Y", "12/31/2026"),
    )
    IMPORT_DELIMITER_CHOICES = (
        ("auto", tr("Automatiškai")),
        (",", tr("Kablelis ( , )")),
        (";", tr("Kabliataškis ( ; )")),
        ("tab", tr("Tabuliacija")),
    )
    IMPORT_ENCODING_CHOICES = (
        ("auto", tr("Automatiškai")),
        ("utf-8-sig", "UTF-8"),
        ("cp1257", tr("Windows-1257 (Baltijos)")),
    )

    default_page_size = models.PositiveSmallIntegerField(default=50, choices=PAGE_SIZE_CHOICES)
    date_format = models.CharField(max_length=12, default="Y-m-d", choices=DATE_FORMAT_CHOICES)
    import_delimiter = models.CharField(max_length=8, default="auto", choices=IMPORT_DELIMITER_CHOICES)
    import_encoding = models.CharField(max_length=16, default="auto", choices=IMPORT_ENCODING_CHOICES)
    notifications_enabled = models.BooleanField(default=False)
    digest_default_time = models.TimeField(default=time(7, 30))
    notify_default_lead = models.PositiveSmallIntegerField(default=60, choices=NOTIFY_LEAD_CHOICES)

    # Outgoing email (SMTP) — configured in Settings -> Pranešimai. The password
    # is stored encrypted (see contacts/crypto.py); the rest is plain.
    email_host = models.CharField(max_length=255, blank=True, default="")
    email_port = models.PositiveIntegerField(default=587)
    email_host_user = models.CharField(max_length=255, blank=True, default="")
    email_host_password = models.CharField(max_length=500, blank=True, default="")
    email_use_tls = models.BooleanField(default=True)
    email_use_ssl = models.BooleanField(default=False)
    email_from = models.CharField(max_length=255, blank=True, default="")
    site_base_url = models.CharField(max_length=255, blank=True, default="")

    # Incoming mail (IMAP) — configured in Settings -> Gauti laiškai.
    imap_enabled = models.BooleanField(default=False)
    imap_host = models.CharField(max_length=255, blank=True, default="")
    imap_port = models.PositiveIntegerField(default=993)
    imap_user = models.CharField(max_length=255, blank=True, default="")
    imap_password = models.CharField(max_length=500, blank=True, default="")
    imap_folder = models.CharField(max_length=128, blank=True, default="INBOX")

    # Microsoft Entra ID (OIDC) login — configured in Settings -> Prisijungimas.
    oidc_enabled = models.BooleanField(default=False)
    oidc_tenant_id = models.CharField(max_length=255, blank=True, default="")
    oidc_client_id = models.CharField(max_length=255, blank=True, default="")
    oidc_client_secret = models.CharField(max_length=500, blank=True, default="")
    oidc_create_users = models.BooleanField(default=False)

    # Automation rules master switch (Settings -> Automatika).
    automations_enabled = models.BooleanField(default=False)

    updated_at = models.DateTimeField(auto_now=True)

    @property
    def datetime_format(self):
        return f"{self.date_format} H:i"

    @classmethod
    def load(cls):
        settings_object, _ = cls.objects.get_or_create(pk=1)
        return settings_object

    def save(self, *args, **kwargs):
        self.pk = 1
        return super().save(*args, **kwargs)


class Person(RecordDetailsModel, TimestampedModel):
    merged_into = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="merged_people")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="owned_people", db_index=True)
    responsibles = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="responsible_for_people")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_people")
    favourite = models.BooleanField(default=False, db_index=True)
    first_name = models.CharField(max_length=100, db_index=True)
    last_name = models.CharField(max_length=100, db_index=True)
    job_title = models.CharField(max_length=160, blank=True)
    companies = models.ManyToManyField(Company, through="PersonCompanyLink", related_name="people", blank=True)
    tags = models.ManyToManyField(Tag, related_name="people", blank=True)
    categories = models.ManyToManyField(Category, related_name="people", blank=True)

    class Meta:
        ordering = ["last_name", "first_name"]
        indexes = [models.Index(fields=["last_name", "first_name"])]

    def __str__(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_absolute_url(self):
        return reverse("contacts:detail", args=[self.pk])

    @property
    def primary_company(self):
        link = self.company_links.filter(company__deleted_at__isnull=True).select_related("company").order_by("-is_primary", "company__name").first()
        return link.company if link else None


class PersonCompanyLink(models.Model):
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="company_links")
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="person_links")
    role = models.CharField(max_length=160, blank=True)
    is_primary = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["person", "company"], name="unique_person_company")]
        ordering = ["-is_primary", "company__name"]

    def __str__(self):
        return f"{self.person} - {self.company}"


class PhoneNumber(models.Model):
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="phones")
    number = models.CharField(max_length=80)
    label = models.CharField(max_length=40, blank=True, default="Darbo")
    is_primary = models.BooleanField(default=False)

    def __str__(self):
        return self.number


class EmailAddress(models.Model):
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="emails")
    email = models.EmailField()
    label = models.CharField(max_length=40, blank=True, default="Darbo")
    is_primary = models.BooleanField(default=False)

    def __str__(self):
        return self.email


class PostalAddress(models.Model):
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="addresses")
    address = models.CharField(max_length=300)
    label = models.CharField(max_length=40, blank=True, default="Darbo")

    def __str__(self):
        return self.address


class WebLink(models.Model):
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="web_links")
    url = models.URLField()
    label = models.CharField(max_length=80, blank=True, default="Svetainė")

    def __str__(self):
        return self.url


class Activity(TimestampedModel):
    NOTE = "note"
    CALL = "call"
    EMAIL = "email"
    MEETING = "meeting"
    TASK = "task"
    TYPE_CHOICES = [(NOTE, tr("Pastaba")), (CALL, tr("Skambutis")), (EMAIL, tr("El. laiškas")), (MEETING, tr("Susitikimas")), (TASK, tr("Užduotis"))]
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="activities", null=True, blank=True)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="activities", null=True, blank=True)
    activity_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=NOTE)
    text = models.TextField(max_length=10000)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="crm_activities")
    submission_token = models.CharField(max_length=64, blank=True, unique=True, null=True)
    # Set for entries created from an incoming email (G6) — dedup key.
    message_id = models.CharField(max_length=255, blank=True, default="", db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "Veiklos"

    @property
    def record(self):
        """The contact or company this entry belongs to — as on Reminder."""
        return self.person or self.company

    @property
    def record_url(self):
        record = self.record
        return record.get_absolute_url() if record else ""


class Attachment(TimestampedModel):
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="attachments/%Y/%m/")
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=120, blank=True)
    size = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return self.original_name


class Reminder(TimestampedModel):
    """A scheduled item. Shown on the record card, in the bell and on the calendar.

    It can hang off a contact, a company, or neither (a plain calendar entry).
    """
    PRIORITY_LOW = "low"
    PRIORITY_NORMAL = "normal"
    PRIORITY_HIGH = "high"
    PRIORITY_CHOICES = (
        (PRIORITY_LOW, tr("Žemas")),
        (PRIORITY_NORMAL, tr("Įprastas")),
        (PRIORITY_HIGH, tr("Aukštas")),
    )
    FREQ_CHOICES = (
        ("", tr("Nekartoti")),
        ("daily", tr("Kasdien")),
        ("weekly", tr("Kas savaitę")),
        ("monthly", tr("Kas mėnesį")),
        ("yearly", tr("Kasmet")),
    )
    # How far ahead occurrences are materialised as real rows.
    RECURRENCE_HORIZON_DAYS = 400
    RECURRENCE_MAX_OCCURRENCES = 200

    person = models.ForeignKey(Person, null=True, blank=True, on_delete=models.CASCADE, related_name="reminders")
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.CASCADE, related_name="reminders")
    text = models.CharField(max_length=500)
    due_at = models.DateTimeField(db_index=True)
    end_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="crm_reminders")
    # Who owns the task. Null is treated as "the creator" everywhere it matters.
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="crm_assigned_reminders")
    priority = models.CharField(max_length=8, choices=PRIORITY_CHOICES, default=PRIORITY_NORMAL)
    submission_token = models.CharField(max_length=64, blank=True, unique=True, null=True)
    # Email-notification bookkeeping (G7).
    upcoming_notified_at = models.DateTimeField(null=True, blank=True)
    assigned_notified_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    # Recurrence (G3). The rule lives on the series root; every occurrence is a
    # real row, children point back at the root via recurrence_parent.
    recurrence_freq = models.CharField(max_length=8, blank=True, default="", choices=FREQ_CHOICES)
    recurrence_interval = models.PositiveSmallIntegerField(default=1)
    recurrence_until = models.DateField(null=True, blank=True)
    recurrence_count = models.PositiveSmallIntegerField(null=True, blank=True)
    recurrence_parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="recurrence_children")

    @property
    def is_recurring(self):
        return bool(self.recurrence_freq) and self.recurrence_parent_id is None

    @property
    def series_root_id(self):
        return self.recurrence_parent_id or self.pk

    DEFAULT_MINUTES = 30

    @property
    def owner(self):
        """The user responsible for this task (assignee, or the creator if unset)."""
        return self.assigned_to or self.created_by

    class Meta:
        ordering = ["due_at"]

    @property
    def is_active(self):
        from django.utils import timezone

        return self.completed_at is None and self.due_at <= timezone.now()

    @property
    def record(self):
        """The contact or company this reminder is about, if any."""
        return self.person or self.company

    @property
    def record_url(self):
        record = self.record
        return record.get_absolute_url() if record else ""

    @property
    def finish_at(self):
        """End of the slot the reminder occupies (defaults to DEFAULT_MINUTES)."""
        from datetime import timedelta

        return self.end_at or self.due_at + timedelta(minutes=self.DEFAULT_MINUTES)

    @property
    def is_past(self):
        from django.utils import timezone

        return self.finish_at < timezone.now()

    @property
    def contact_phone(self):
        record = self.record
        if isinstance(record, Person):
            phone = record.phones.first()
            return phone.number if phone else ""
        return record.phone if record else ""

    @property
    def contact_address(self):
        record = self.record
        if isinstance(record, Person):
            address = record.addresses.first()
            return address.address if address else ""
        return record.address if record else ""


def validate_relation_limit(instance, relation_name):
    if instance.pk and getattr(instance, relation_name).count() > 3:
        raise ValidationError(f"Galima pasirinkti ne daugiau kaip 3 {relation_name}.")


class CustomField(models.Model):
    PERSON = "person"
    COMPANY = "company"
    ENTITY_CHOICES = ((PERSON, tr("Kontaktai")), (COMPANY, tr("Įmonės")))
    TEXT = "text"
    TEXTAREA = "textarea"
    BOOL = "bool"
    SELECT = "select"
    MULTISELECT = "multiselect"
    TYPE_CHOICES = (
        (TEXT, tr("Trumpas tekstas")),
        (TEXTAREA, tr("Ilgas tekstas")),
        (BOOL, tr("Žymimasis langelis")),
        (SELECT, tr("Vienas pasirinkimas")),
        (MULTISELECT, tr("Keli pasirinkimai")),
    )

    entity = models.CharField(max_length=10, choices=ENTITY_CHOICES, db_index=True)
    name = models.CharField(max_length=60)
    field_type = models.CharField(max_length=12, choices=TYPE_CHOICES, default=TEXT)
    options = models.JSONField(default=list, blank=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "name"]
        constraints = [models.UniqueConstraint(fields=["entity", "name"], name="unique_custom_field_name_per_entity")]

    def __str__(self):
        return f"{self.name} ({self.get_entity_display()})"

    @property
    def key(self):
        return f"cf_{self.pk}"

    @property
    def choice_type(self):
        return self.field_type in (self.SELECT, self.MULTISELECT)


class CustomValue(models.Model):
    field = models.ForeignKey(CustomField, on_delete=models.CASCADE, related_name="values")
    person = models.ForeignKey(Person, null=True, blank=True, on_delete=models.CASCADE, related_name="custom_values")
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.CASCADE, related_name="custom_values")
    value = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["field", "person"], name="unique_custom_value_person", condition=models.Q(person__isnull=False)),
            models.UniqueConstraint(fields=["field", "company"], name="unique_custom_value_company", condition=models.Q(company__isnull=False)),
        ]


class AuditLog(models.Model):
    """Append-only trail: who did what, to which record or setting, when."""
    CREATE = "create"
    UPDATE = "update"
    ARCHIVE = "archive"
    RESTORE = "restore"
    DELETE = "delete"
    MERGE = "merge"
    IMPORT = "import"
    EXPORT = "export"
    SETTING = "setting"
    LOGIN = "login"
    LOGOUT = "logout"
    LOGIN_FAILED = "login_failed"
    ACTION_CHOICES = (
        (CREATE, tr("Sukūrimas")),
        (UPDATE, tr("Keitimas")),
        (ARCHIVE, tr("Archyvavimas")),
        (RESTORE, tr("Atkūrimas")),
        (DELETE, tr("Trynimas")),
        (MERGE, tr("Sujungimas")),
        (IMPORT, tr("Importas")),
        (EXPORT, tr("Eksportas")),
        (SETTING, tr("Nustatymų keitimas")),
        (LOGIN, tr("Prisijungimas")),
        (LOGOUT, tr("Atsijungimas")),
        (LOGIN_FAILED, tr("Nepavykęs prisijungimas")),
    )

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_entries")
    actor_label = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=16, choices=ACTION_CHOICES, db_index=True)
    target_type = models.CharField(max_length=32, blank=True, db_index=True)
    target_id = models.CharField(max_length=32, blank=True)
    target_label = models.CharField(max_length=255, blank=True)
    field = models.CharField(max_length=64, blank=True)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    detail = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "Žurnalo įrašas"
        verbose_name_plural = "Žurnalas"

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor_label} {self.action} {self.target_label}".strip()


class IncomingMail(models.Model):
    """An email pulled from the CRM dropbox that could not be matched to a
    contact automatically. An admin assigns it from Settings -> Gauti laiškai."""
    message_id = models.CharField(max_length=255, unique=True)
    from_addr = models.CharField(max_length=320)
    to_addrs = models.CharField(max_length=1000, blank=True)
    subject = models.CharField(max_length=500, blank=True)
    body = models.TextField(blank=True)
    received_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_activity = models.ForeignKey("Activity", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.from_addr}: {self.subject}"


class AutomationRule(models.Model):
    """An admin-configured "when X, do Y" rule, evaluated by the worker (H2)."""
    NO_OWNER = "contact_no_owner_after"
    SILENT = "contact_silent_days"
    NEVER = "contact_never_contacted_after"
    OVERDUE = "reminder_overdue_days"
    TRIGGER_CHOICES = (
        (NO_OWNER, tr("Kontaktas be atsakingo ilgiau nei N dienų")),
        (SILENT, tr("Su kontaktu (turinčiu atsakingą) nebendrauta N dienų")),
        (NEVER, tr("Su nauju kontaktu nebendrauta N dienų")),
        (OVERDUE, tr("Priminimas vėluoja N dienų")),
    )

    NOTIFY = "notify_user"
    ASSIGN = "assign_owner"
    CREATE_TASK = "create_task"
    ADD_TAG = "add_tag"
    ACTION_CHOICES = (
        (NOTIFY, tr("Pranešti naudotojui el. paštu")),
        (ASSIGN, tr("Priskirti atsakingą")),
        (CREATE_TASK, tr("Sukurti užduotį")),
        (ADD_TAG, tr("Pridėti žymą")),
    )
    # Which actions each trigger allows (the target type differs).
    TRIGGER_ACTIONS = {
        NO_OWNER: {NOTIFY, ASSIGN, CREATE_TASK, ADD_TAG},
        SILENT: {NOTIFY, CREATE_TASK, ADD_TAG},
        NEVER: {NOTIFY, ASSIGN, CREATE_TASK},
        OVERDUE: {NOTIFY, CREATE_TASK},
    }

    name = models.CharField(max_length=100)
    trigger = models.CharField(max_length=32, choices=TRIGGER_CHOICES)
    threshold = models.PositiveIntegerField(default=1, help_text=tr("Dienų skaičius (N)."))
    action = models.CharField(max_length=16, choices=ACTION_CHOICES)
    action_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    action_tag = models.ForeignKey(Tag, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    action_text = models.CharField(max_length=200, blank=True, default="")
    action_due_days = models.PositiveIntegerField(default=3)
    active = models.BooleanField(default=False)
    last_run_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class AutomationLog(models.Model):
    """One record of an automation rule acting (or failing) on a target."""
    rule = models.ForeignKey(AutomationRule, on_delete=models.CASCADE, related_name="events")
    target_type = models.CharField(max_length=16)
    target_id = models.CharField(max_length=32, db_index=True)
    target_label = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=8, default="ok")  # "ok" / "error"
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-pk"]


class ApiToken(models.Model):
    """A bearer token for the JSON API (H3). Acts with its creator's visibility
    and capabilities; only the sha256 of the token is stored."""
    READ = "read"
    READ_WRITE = "read_write"
    SCOPE_CHOICES = ((READ, tr("Tik skaityti")), (READ_WRITE, tr("Skaityti ir keisti")))

    name = models.CharField(max_length=80)
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    prefix = models.CharField(max_length=16)
    scope = models.CharField(max_length=12, choices=SCOPE_CHOICES, default=READ)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_tokens")
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    @staticmethod
    def new():
        """Return (raw_token, sha256_hex). The raw token is shown to the user once."""
        raw = "crmk_" + token_urlsafe(30)
        return raw, hashlib.sha256(raw.encode()).hexdigest()


class Webhook(models.Model):
    """An outbound HTTP hook (H4). The worker POSTs a JSON payload per event with
    an HMAC-SHA256 signature. Auto-disabled after a long failure streak."""
    EVENTS = [
        "contact.created", "contact.updated", "contact.archived",
        "company.created", "company.updated", "company.archived",
        "activity.created", "reminder.created", "reminder.completed",
    ]
    target_url = models.URLField(max_length=500, validators=[URLValidator(schemes=["http", "https"])])
    secret = models.CharField(max_length=500, blank=True, default="")  # encrypted
    events = models.JSONField(default=list)
    active = models.BooleanField(default=True)
    failure_streak = models.PositiveIntegerField(default=0)
    last_delivery_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=60, blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.target_url


class WebhookDelivery(models.Model):
    webhook = models.ForeignKey(Webhook, on_delete=models.CASCADE, related_name="deliveries")
    event = models.CharField(max_length=40)
    payload = models.JSONField(default=dict)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(db_index=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=60, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

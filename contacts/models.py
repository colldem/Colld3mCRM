from django.utils.translation import gettext_lazy as tr
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        abstract = True


class Company(TimestampedModel):
    merged_into = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="merged_companies")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="owned_companies", db_index=True)
    responsibles = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="responsible_for_companies")
    tags = models.ManyToManyField("Tag", blank=True, related_name="companies")
    categories = models.ManyToManyField("Category", blank=True, related_name="companies")
    name = models.CharField(max_length=200, db_index=True)
    company_code = models.CharField(max_length=40, blank=True, db_index=True)
    vat_code = models.CharField(max_length=40, blank=True, db_index=True)
    address = models.CharField(max_length=300, blank=True)
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
    updated_at = models.DateTimeField(auto_now=True)

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


class Person(TimestampedModel):
    merged_into = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="merged_people")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="owned_people", db_index=True)
    responsibles = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="responsible_for_people")
    favourite = models.BooleanField(default=False, db_index=True)
    first_name = models.CharField(max_length=100, db_index=True)
    last_name = models.CharField(max_length=100, db_index=True)
    job_title = models.CharField(max_length=160, blank=True)
    status = models.CharField(max_length=40, blank=True, default="Aktyvus")
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

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "Veiklos"


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
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="reminders")
    text = models.CharField(max_length=500)
    due_at = models.DateTimeField(db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="crm_reminders")
    submission_token = models.CharField(max_length=64, blank=True, unique=True, null=True)

    class Meta:
        ordering = ["due_at"]

    @property
    def is_active(self):
        from django.utils import timezone

        return self.completed_at is None and self.due_at <= timezone.now()


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

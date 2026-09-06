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
    name = models.CharField(max_length=60, unique=True)

    @property
    def color_class(self):
        # Stable across renames, assignment changes, languages and page reloads.
        return f"tag-color-{(self.pk or 1) % 8}"

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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["user", "scope", "name"], name="unique_saved_filter_scope_name")]

    def __str__(self):
        return self.name

    @property
    def query_string(self):
        from .filters import encoded_filter_values

        return encoded_filter_values(self.filters)


class Person(TimestampedModel):
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

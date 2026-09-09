from django.utils.translation import gettext_lazy as tr
from django import forms
from django.db import transaction
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from . import permissions
from .models import Activity, AutomationRule, Company, DuplicateSettings, EmailAddress, NOTIFY_LEAD_CHOICES, Person, PersonCompanyLink, PhoneNumber, PostalAddress, Reminder, SystemSettings, Tag, UserProfile, WebLink


class UserProfileForm(forms.Form):
    first_name = forms.CharField(max_length=150, required=False, label=tr("Vardas"))
    last_name = forms.CharField(max_length=150, required=False, label=tr("Pavardė"))
    email = forms.EmailField(required=False, label=tr("El. paštas"))
    language = forms.ChoiceField(choices=(("lt", "Lietuvių"), ("en", "English")), label=tr("Kalba"))
    timezone = forms.ChoiceField(choices=(("Europe/Vilnius", "Europe/Vilnius"), ("Europe/London", "Europe/London"), ("Europe/Berlin", "Europe/Berlin"), ("UTC", "UTC"), ("America/New_York", "America/New_York")), label=tr("Laiko zona"))
    avatar = forms.FileField(required=False, label=tr("Profilio nuotrauka"), widget=forms.FileInput(attrs={"accept": "image/png,image/jpeg,image/webp,image/gif"}))
    remove_avatar = forms.BooleanField(required=False, label=tr("Pašalinti profilio nuotrauką"))
    digest_enabled = forms.BooleanField(required=False, label=tr("Gauti rytinę santrauką el. paštu"))
    digest_time = forms.TimeField(required=False, label=tr("Santraukos laikas"), widget=forms.TimeInput(attrs={"type": "time"}))
    notify_lead = forms.TypedChoiceField(required=False, coerce=int, empty_value=None, label=tr("Priminti apie įvykį prieš"),
                                         choices=[("", tr("Kaip nustatyta sistemoje"))] + list(NOTIFY_LEAD_CHOICES))

    def __init__(self, *args, user, **kwargs):
        self.user = user
        self.profile, _ = UserProfile.objects.get_or_create(user=user)
        kwargs.setdefault("initial", {"first_name": user.first_name, "last_name": user.last_name, "email": user.email,
                                      "language": self.profile.language, "timezone": self.profile.timezone,
                                      "digest_enabled": self.profile.digest_enabled, "digest_time": self.profile.digest_time,
                                      "notify_lead": "" if self.profile.notify_lead is None else self.profile.notify_lead})
        super().__init__(*args, **kwargs)

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if not avatar:
            return avatar
        if avatar.size > 5 * 1024 * 1024:
            raise forms.ValidationError(tr("Profilio nuotrauka negali būti didesnė nei 5 MB."))
        if getattr(avatar, "content_type", "") not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
            raise forms.ValidationError(tr("Pasirinkite PNG, JPG, WEBP arba GIF formato nuotrauką."))
        return avatar

    @transaction.atomic
    def save(self):
        self.user.first_name = self.cleaned_data["first_name"].strip()
        self.user.last_name = self.cleaned_data["last_name"].strip()
        self.user.email = self.cleaned_data["email"].strip()
        self.user.save(update_fields=["first_name", "last_name", "email"])
        self.profile.language = self.cleaned_data["language"]
        self.profile.timezone = self.cleaned_data["timezone"]
        self.profile.digest_enabled = self.cleaned_data["digest_enabled"]
        self.profile.digest_time = self.cleaned_data.get("digest_time")
        self.profile.notify_lead = self.cleaned_data.get("notify_lead")
        if self.cleaned_data["remove_avatar"] and self.profile.avatar:
            self.profile.avatar.delete(save=False)
            self.profile.avatar = ""
        if self.cleaned_data.get("avatar"):
            if self.profile.avatar:
                self.profile.avatar.delete(save=False)
            self.profile.avatar = self.cleaned_data["avatar"]
        self.profile.save()
        return self.profile


class DuplicateSettingsForm(forms.ModelForm):
    class Meta:
        model = DuplicateSettings
        fields = ["enabled", "level", "check_on_edit", "check_on_import"]
        labels = {
            "enabled": tr("Įjungti dublikatų tikrinimą"),
            "level": tr("Tikrinimo lygis"),
            "check_on_edit": tr("Tikrinti redaguojant įrašą"),
            "check_on_import": tr("Tikrinti importuojant"),
        }
        widgets = {"level": forms.Select(attrs={"class": "duplicate-level-select"})}


class SystemSettingsForm(forms.ModelForm):
    class Meta:
        model = SystemSettings
        fields = ["default_page_size", "date_format"]
        labels = {
            "default_page_size": tr("Numatytas eilučių skaičius sąrašuose"),
            "date_format": tr("Datos formatas"),
        }


class _SecretFieldsMixin:
    """Write-only handling for encrypted secret fields on a SystemSettings form.

    The stored value is never rendered. Submitting blank keeps the existing
    secret; submitting a value encrypts and replaces it; ticking the matching
    ``<name>_clear`` box wipes it.
    """

    secret_fields = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .crypto import secrets_available

        self._secrets_available = secrets_available()
        for name in self.secret_fields:
            stored = bool(getattr(self.instance, name, ""))
            self.fields[name].required = False
            self.fields[name].widget = forms.PasswordInput(
                render_value=False,
                attrs={"placeholder": "••••••••" if stored else "", "autocomplete": "new-password"},
            )
            self.initial[name] = ""
            self.fields["%s_clear" % name] = forms.BooleanField(
                required=False, label=tr("Išvalyti išsaugotą reikšmę"),
            )

    def clean(self):
        cleaned = super().clean()
        from .crypto import encrypt

        for name in self.secret_fields:
            submitted = (cleaned.get(name) or "").strip()
            if cleaned.get("%s_clear" % name):
                cleaned[name] = ""
            elif not submitted:
                cleaned[name] = getattr(self.instance, name, "")
            elif not self._secrets_available:
                self.add_error(name, tr("Nustatykite CRM_SECRETS_KEY faile .env, kad galėtumėte saugoti slaptažodį."))
            else:
                cleaned[name] = encrypt(submitted)
        return cleaned


class NotificationSettingsForm(_SecretFieldsMixin, forms.ModelForm):
    secret_fields = ("email_host_password",)

    class Meta:
        model = SystemSettings
        fields = [
            "notifications_enabled", "digest_default_time", "notify_default_lead",
            "email_host", "email_port", "email_host_user", "email_host_password",
            "email_use_tls", "email_use_ssl", "email_from", "site_base_url",
        ]
        labels = {
            "notifications_enabled": tr("Siųsti pranešimus el. paštu"),
            "digest_default_time": tr("Numatytas rytinės santraukos laikas"),
            "notify_default_lead": tr("Numatyta įspėti apie įvykį prieš"),
            "email_host": tr("SMTP serveris"),
            "email_port": tr("Prievadas"),
            "email_host_user": tr("Naudotojas"),
            "email_host_password": tr("Slaptažodis"),
            "email_use_tls": tr("Naudoti TLS (STARTTLS)"),
            "email_use_ssl": tr("Naudoti SSL"),
            "email_from": tr("Siuntėjo adresas (From)"),
            "site_base_url": tr("CRM adresas nuorodoms laiškuose"),
        }
        widgets = {
            "digest_default_time": forms.TimeInput(attrs={"type": "time"}),
            "site_base_url": forms.TextInput(attrs={"placeholder": "https://crm.tailb8493f.ts.net"}),
        }


class IncomingMailSettingsForm(_SecretFieldsMixin, forms.ModelForm):
    secret_fields = ("imap_password",)

    class Meta:
        model = SystemSettings
        fields = ["imap_enabled", "imap_host", "imap_port", "imap_user", "imap_password", "imap_folder"]
        labels = {
            "imap_enabled": tr("Tikrinti dėžutę"),
            "imap_host": tr("IMAP serveris"),
            "imap_port": tr("Prievadas"),
            "imap_user": tr("Naudotojas"),
            "imap_password": tr("Slaptažodis"),
            "imap_folder": tr("Aplankas"),
        }


class LoginSettingsForm(_SecretFieldsMixin, forms.ModelForm):
    secret_fields = ("oidc_client_secret",)

    class Meta:
        model = SystemSettings
        fields = ["oidc_enabled", "oidc_tenant_id", "oidc_client_id", "oidc_client_secret", "oidc_create_users"]
        labels = {
            "oidc_enabled": tr("Leisti prisijungti per Microsoft Entra ID"),
            "oidc_tenant_id": tr("Katalogo (nuomininko) ID"),
            "oidc_client_id": tr("Programos (kliento) ID"),
            "oidc_client_secret": tr("Kliento paslaptis (secret)"),
            "oidc_create_users": tr("Kurti naujus naudotojus automatiškai"),
        }


class ImportSettingsForm(forms.ModelForm):
    class Meta:
        model = SystemSettings
        fields = ["import_delimiter", "import_encoding"]
        labels = {
            "import_delimiter": tr("CSV skyriklis"),
            "import_encoding": tr("CSV koduotė"),
        }


class AutomationRuleForm(forms.ModelForm):
    class Meta:
        model = AutomationRule
        fields = ["name", "trigger", "threshold", "action", "action_user",
                  "action_tag", "action_text", "action_due_days"]
        labels = {
            "name": tr("Pavadinimas"),
            "trigger": tr("Sąlyga (kada)"),
            "threshold": tr("N (dienų)"),
            "action": tr("Veiksmas (ką)"),
            "action_user": tr("Naudotojas (pranešimui / priskyrimui / vykdytojui)"),
            "action_tag": tr("Žyma"),
            "action_text": tr("Užduoties tekstas ({vardas} pakeičiamas kontaktu)"),
            "action_due_days": tr("Užduoties terminas po (dienų)"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["action_user"].queryset = get_user_model().objects.filter(is_active=True).order_by("first_name", "last_name", "username")
        self.fields["action_tag"].queryset = Tag.objects.order_by("name")

    def clean(self):
        cleaned = super().clean()
        trigger, action = cleaned.get("trigger"), cleaned.get("action")
        allowed = AutomationRule.TRIGGER_ACTIONS.get(trigger, set())
        if trigger and action and action not in allowed:
            self.add_error("action", tr("Šis veiksmas netinka pasirinktai sąlygai."))
        if action in (AutomationRule.NOTIFY, AutomationRule.ASSIGN) and not cleaned.get("action_user"):
            self.add_error("action_user", tr("Nurodykite naudotoją."))
        if action == AutomationRule.ADD_TAG and not cleaned.get("action_tag"):
            self.add_error("action_tag", tr("Nurodykite žymą."))
        return cleaned


class PersonForm(forms.ModelForm):
    companies = forms.ModelMultipleChoiceField(queryset=Company.objects.filter(deleted_at__isnull=True), required=False, label=tr("Priskirtos įmonės"), help_text=tr("Galite pasirinkti vieną ar kelias įmones."), widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            # A restricted user must not see or link companies outside their scope;
            # companies already linked to this contact stay selectable.
            visible = permissions.visible_companies(user, Company.objects.filter(deleted_at__isnull=True))
            if self.instance.pk:
                visible = visible | Company.objects.filter(pk__in=self.instance.companies.values("pk"))
            self.fields["companies"].queryset = visible.distinct()
    phone = forms.CharField(required=False, label=tr("Telefonai"), widget=forms.Textarea(attrs={"rows": 3, "placeholder": tr("Vienas numeris eilutėje")}))
    email = forms.CharField(required=False, label=tr("El. paštai"), widget=forms.Textarea(attrs={"rows": 3, "placeholder": tr("Vienas adresas eilutėje")}))
    address = forms.CharField(required=False, label=tr("Adresai"), widget=forms.Textarea(attrs={"rows": 3, "placeholder": tr("Vienas adresas eilutėje")}))
    url = forms.CharField(required=False, label=tr("URL nuorodos"), widget=forms.Textarea(attrs={"rows": 3, "placeholder": tr("Viena nuoroda eilutėje")}))

    class Meta:
        model = Person
        fields = ["first_name", "last_name", "job_title", "description", "companies", "tags", "categories"]
        labels = {"first_name": tr("Vardas"), "last_name": tr("Pavardė"), "job_title": tr("Pareigos"), "description": tr("Aprašymas"), "tags": tr("Tagai"), "categories": tr("Kategorijos")}
        widgets = {"tags": forms.CheckboxSelectMultiple, "categories": forms.CheckboxSelectMultiple, "description": forms.Textarea(attrs={"rows": 4})}

    def clean_tags(self):
        tags = self.cleaned_data["tags"]
        if len(tags) > 3:
            raise forms.ValidationError(tr("Pasirinkite ne daugiau kaip 3 tagus."))
        return tags

    def clean_categories(self):
        categories = self.cleaned_data["categories"]
        if len(categories) > 3:
            raise forms.ValidationError(tr("Pasirinkite ne daugiau kaip 3 kategorijas."))
        return categories

    @transaction.atomic
    def save(self, commit=True):
        person = super().save(commit=commit)
        if not commit:
            return person
        selected = list(self.cleaned_data["companies"])
        PersonCompanyLink.objects.filter(person=person).exclude(company__in=selected).delete()
        for index, company in enumerate(selected):
            PersonCompanyLink.objects.update_or_create(person=person, company=company, defaults={"is_primary": index == 0})
        self._replace_multiple(PhoneNumber, "phones", "number", self.cleaned_data.get("phone"), has_primary=True)
        self._replace_multiple(EmailAddress, "emails", "email", self.cleaned_data.get("email"), has_primary=True)
        self._replace_multiple(PostalAddress, "addresses", "address", self.cleaned_data.get("address"), has_primary=False)
        self._replace_multiple(WebLink, "web_links", "url", self.cleaned_data.get("url"), has_primary=False)
        return person

    def _replace_multiple(self, model, relation_name, value_field, value, has_primary=True):
        from .sanitizers import safe_url

        relation = getattr(self.instance, relation_name)
        values = [line.strip() for line in (value or "").splitlines() if line.strip()]
        if value_field == "url":
            values = [safe for safe in (safe_url(item) for item in values) if safe]
        relation.all().delete()
        for index, item in enumerate(values):
            attrs = {value_field: item}
            if has_primary:
                attrs["is_primary"] = index == 0
            model.objects.create(person=self.instance, **attrs)


class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ["name", "company_code", "vat_code", "address", "phone", "email", "url", "description"]
        labels = {"name": tr("Pavadinimas"), "company_code": tr("Įmonės kodas"), "vat_code": tr("PVM kodas"), "address": tr("Adresas"), "phone": tr("Telefonas"), "email": tr("El. paštas"), "url": "URL", "description": tr("Aprašymas")}
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}


class ActivityForm(forms.ModelForm):
    class Meta:
        model = Activity
        fields = ["activity_type", "text"]
        labels = {"activity_type": tr("Įrašo tipas"), "text": tr("Tekstas")}
        widgets = {"text": forms.Textarea(attrs={"rows": 4, "placeholder": tr("Įrašykite pastabą...")})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["text"].required = False

    def clean_text(self):
        return (self.cleaned_data.get("text") or "").strip()


class ReminderForm(forms.ModelForm):
    apply_future = forms.BooleanField(required=False, label=tr("Taikyti visiems būsimiems"))

    class Meta:
        model = Reminder
        fields = ["text", "due_at", "assigned_to", "priority",
                  "recurrence_freq", "recurrence_interval", "recurrence_until", "recurrence_count"]
        labels = {"text": tr("Priminimas"), "due_at": tr("Data ir laikas"),
                  "assigned_to": tr("Priskirta"), "priority": tr("Prioritetas"),
                  "recurrence_freq": tr("Kartojimas"), "recurrence_interval": tr("Kas kiek"),
                  "recurrence_until": tr("Kartoti iki"), "recurrence_count": tr("Kartų skaičius")}
        widgets = {
            "text": forms.TextInput(attrs={"id": "id_reminder_text"}),
            "due_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "recurrence_until": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["due_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["assigned_to"].required = False
        self.fields["assigned_to"].empty_label = None
        self.fields["assigned_to"].label_from_instance = permissions.user_label
        self.fields["priority"].required = False
        for name in ("recurrence_interval", "recurrence_until", "recurrence_count"):
            self.fields[name].required = False
        # A single occurrence out of a series cannot carry its own rule.
        self.editing_occurrence = bool(self.instance.pk and self.instance.recurrence_parent_id)
        if self.editing_occurrence:
            for name in ("recurrence_freq", "recurrence_interval", "recurrence_until", "recurrence_count", "apply_future"):
                self.fields.pop(name)
        if user is not None:
            self.fields["assigned_to"].queryset = permissions.assignable_users_for(user)
            if not self.instance.pk and not self.initial.get("assigned_to"):
                self.initial["assigned_to"] = user.pk

    def clean_priority(self):
        return self.cleaned_data.get("priority") or Reminder.PRIORITY_NORMAL

    def clean_recurrence_interval(self):
        return max(1, self.cleaned_data.get("recurrence_interval") or 1)


class SetupAdminForm(UserCreationForm):
    setup_token = forms.CharField(label="Vienkartinis diegimo kodas", widget=forms.PasswordInput)

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ["username", "setup_token", "password1", "password2"]

from django.utils.translation import gettext_lazy as tr
from django import forms
from django.db import transaction
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import Activity, Category, Company, DuplicateSettings, EmailAddress, Person, PersonCompanyLink, PhoneNumber, PostalAddress, Reminder, Tag, UserProfile, WebLink


class UserProfileForm(forms.Form):
    first_name = forms.CharField(max_length=150, required=False, label=tr("Vardas"))
    last_name = forms.CharField(max_length=150, required=False, label=tr("Pavardė"))
    email = forms.EmailField(required=False, label=tr("El. paštas"))
    language = forms.ChoiceField(choices=(("lt", "Lietuvių"), ("en", "English")), label=tr("Kalba"))
    timezone = forms.ChoiceField(choices=(("Europe/Vilnius", "Europe/Vilnius"), ("Europe/London", "Europe/London"), ("Europe/Berlin", "Europe/Berlin"), ("UTC", "UTC"), ("America/New_York", "America/New_York")), label=tr("Laiko zona"))
    avatar = forms.FileField(required=False, label=tr("Profilio nuotrauka"), widget=forms.FileInput(attrs={"accept": "image/png,image/jpeg,image/webp,image/gif"}))
    remove_avatar = forms.BooleanField(required=False, label=tr("Pašalinti profilio nuotrauką"))

    def __init__(self, *args, user, **kwargs):
        self.user = user
        self.profile, _ = UserProfile.objects.get_or_create(user=user)
        kwargs.setdefault("initial", {"first_name": user.first_name, "last_name": user.last_name, "email": user.email, "language": self.profile.language, "timezone": self.profile.timezone})
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


class PersonForm(forms.ModelForm):
    companies = forms.ModelMultipleChoiceField(queryset=Company.objects.filter(deleted_at__isnull=True), required=False, label=tr("Priskirtos įmonės"), help_text=tr("Galite pasirinkti vieną ar kelias įmones."), widget=forms.CheckboxSelectMultiple)
    phone = forms.CharField(required=False, label=tr("Telefonai"), widget=forms.Textarea(attrs={"rows": 3, "placeholder": tr("Vienas numeris eilutėje")}))
    email = forms.CharField(required=False, label=tr("El. paštai"), widget=forms.Textarea(attrs={"rows": 3, "placeholder": tr("Vienas adresas eilutėje")}))
    address = forms.CharField(required=False, label=tr("Adresai"), widget=forms.Textarea(attrs={"rows": 3, "placeholder": tr("Vienas adresas eilutėje")}))
    url = forms.CharField(required=False, label=tr("URL nuorodos"), widget=forms.Textarea(attrs={"rows": 3, "placeholder": tr("Viena nuoroda eilutėje")}))

    class Meta:
        model = Person
        fields = ["first_name", "last_name", "job_title", "status", "companies", "tags", "categories"]
        labels = {"first_name": tr("Vardas"), "last_name": tr("Pavardė"), "job_title": tr("Pareigos"), "status": tr("Būsena"), "tags": tr("Tagai"), "categories": tr("Kategorijos")}
        widgets = {"tags": forms.CheckboxSelectMultiple, "categories": forms.CheckboxSelectMultiple}

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
        relation = getattr(self.instance, relation_name)
        values = [line.strip() for line in (value or "").splitlines() if line.strip()]
        relation.all().delete()
        for index, item in enumerate(values):
            attrs = {value_field: item}
            if has_primary:
                attrs["is_primary"] = index == 0
            model.objects.create(person=self.instance, **attrs)


class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ["name", "company_code", "vat_code", "address", "phone", "email", "url"]
        labels = {"name": tr("Pavadinimas"), "company_code": tr("Įmonės kodas"), "vat_code": tr("PVM kodas"), "address": tr("Adresas"), "phone": tr("Telefonas"), "email": tr("El. paštas"), "url": "URL"}


class ActivityForm(forms.ModelForm):
    class Meta:
        model = Activity
        fields = ["activity_type", "text"]
        labels = {"activity_type": tr("Įrašo tipas"), "text": tr("Tekstas")}
        widgets = {"text": forms.Textarea(attrs={"rows": 4, "placeholder": tr("Įrašykite pastabą...")})}

    def clean_text(self):
        return self.cleaned_data["text"].strip()


class ReminderForm(forms.ModelForm):
    class Meta:
        model = Reminder
        fields = ["text", "due_at"]
        labels = {"text": tr("Priminimas"), "due_at": tr("Data ir laikas")}
        widgets = {"text": forms.TextInput(attrs={"id": "id_reminder_text"}), "due_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["due_at"].input_formats = ["%Y-%m-%dT%H:%M"]


class SetupAdminForm(UserCreationForm):
    setup_token = forms.CharField(label="Vienkartinis diegimo kodas", widget=forms.PasswordInput)

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ["username", "setup_token", "password1", "password2"]

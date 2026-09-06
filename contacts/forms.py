from django.utils.translation import gettext_lazy as tr
from django import forms
from django.db import transaction
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import Activity, Category, Company, EmailAddress, Person, PersonCompanyLink, PhoneNumber, PostalAddress, Reminder, Tag, WebLink


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

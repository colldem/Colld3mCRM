from datetime import timedelta
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.core.files.uploadedfile import SimpleUploadedFile

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from contacts.models import Activity, Attachment, Category, Company, DuplicateSettings, EmailAddress, Person, PersonCompanyLink, PhoneNumber, PostalAddress, Reminder, SavedFilter, Tag, WebLink
from contacts.duplicates import find_company_duplicates, find_person_duplicates


@override_settings(CRM_SETUP_TOKEN="one-time-setup-token")
class SetupTests(TestCase):
    def test_setup_rejects_wrong_token(self):
        response = self.client.post(reverse("setup"), {
            "username": "owner",
            "setup_token": "wrong-token",
            "password1": "correct-horse-battery-staple",
            "password2": "correct-horse-battery-staple",
        })
        self.assertContains(response, "Neteisingas arba neaktyvus diegimo kodas")
        self.assertFalse(get_user_model().objects.exists())

    def test_setup_creates_only_first_admin(self):
        response = self.client.post(reverse("setup"), {
            "username": "owner",
            "setup_token": "one-time-setup-token",
            "password1": "correct-horse-battery-staple",
            "password2": "correct-horse-battery-staple",
        })
        self.assertRedirects(response, reverse("login"))
        user = get_user_model().objects.get(username="owner")
        self.assertTrue(user.is_superuser)
        self.assertRedirects(self.client.get(reverse("setup")), reverse("login"))


class LoginSecurityTests(TestCase):
    def test_login_is_temporarily_locked_after_five_failures(self):
        get_user_model().objects.create_user("owner", password="correct-horse-battery-staple")
        login_url = reverse("login")
        for _ in range(settings.AXES_FAILURE_LIMIT):
            response = self.client.post(login_url, {"username": "owner", "password": "wrong-password"})
        self.assertEqual(response.status_code, settings.AXES_HTTP_RESPONSE_CODE)
        response = self.client.post(login_url, {"username": "owner", "password": "correct-horse-battery-staple"})
        self.assertEqual(response.status_code, settings.AXES_HTTP_RESPONSE_CODE)


class ContactModelTests(TestCase):
    def test_person_can_link_multiple_companies(self):
        person = Person.objects.create(first_name="Rūta", last_name="Žukaitė")
        first = Company.objects.create(name="Aukštaitijos projektai")
        second = Company.objects.create(name="Nordika Grupė")
        PersonCompanyLink.objects.create(person=person, company=first, is_primary=True, role="Projektų vadovė")
        PersonCompanyLink.objects.create(person=person, company=second, role="Konsultantė")
        self.assertEqual(person.companies.count(), 2)
        self.assertEqual(person.primary_company, first)

    def test_person_cannot_have_more_than_three_tags(self):
        person = Person.objects.create(first_name="Rūta", last_name="Žukaitė")
        tags = [Tag.objects.create(name=f"Tagas {index}") for index in range(4)]
        with self.assertRaises(ValidationError):
            person.tags.add(*tags)


class ContactViewTests(TestCase):
    def test_english_pages_and_live_reminder_catalog(self):
        self.client.force_login(self.user)
        self.client.post(reverse('set_language'), {'language': 'en', 'next': '/contacts/'})
        for route in ['contacts:list', 'contacts:company-list', 'contacts:reminder-list', 'contacts:settings', 'contacts:archive-list', 'contacts:import-export']:
            response = self.client.get(reverse(route))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'lang="en"')
        self.assertContains(self.client.get(reverse('contacts:list')), 'Filters')
        self.assertContains(self.client.get(reverse('javascript-catalog')), 'Saving...')
        self.assertContains(self.client.get(reverse('javascript-catalog')), 'Save anyway')
        live = self.client.get(reverse('contacts:reminder-snapshot')).json()
        self.assertIn('No active reminders.', live['html'])
        self.assertNotIn('Aktyvių priminimų nėra.', live['html'])

    def test_language_switch_persists_without_translating_contact_data(self):
        self.client.force_login(self.user)
        name = str(self.person)
        response = self.client.post(reverse('set_language'), {'language':'en', 'next': self.person.get_absolute_url()})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.cookies['django_language'].value, 'en')
        response = self.client.get(self.person.get_absolute_url())
        self.assertContains(response, 'Contact details')
        self.assertContains(response, 'Sign out')
        self.assertContains(response, name)
        self.assertContains(response, 'lang="en"')
        self.assertContains(self.client.get(self.company.get_absolute_url()), 'Company details')
        self.client.post(reverse('set_language'), {'language':'lt', 'next': self.person.get_absolute_url()})
        self.assertContains(self.client.get(self.person.get_absolute_url()), 'Kontaktiniai duomenys')

    def test_company_note_edit_scope_and_person_history_isolation(self):
        self.client.force_login(self.user)
        note = Activity.objects.create(company=self.company, text='Įmonės istorija QA', created_by=self.user)
        url = reverse('contacts:company-activity-edit', args=[self.company.pk, note.pk])
        self.assertContains(self.client.get(self.company.get_absolute_url()), url)
        for _ in range(2):
            self.assertEqual(self.client.post(url, {'activity_type':'note', 'text':'Atnaujinta QA istorija'}).status_code, 302)
        note.refresh_from_db()
        self.assertEqual(note.text, 'Atnaujinta QA istorija')
        self.assertEqual(Activity.objects.filter(company=self.company).count(), 1)
        self.assertNotContains(self.client.get(self.person.get_absolute_url()), 'Atnaujinta QA istorija')
        other = Company.objects.create(name='Kita')
        self.assertEqual(self.client.get(reverse('contacts:company-activity-edit', args=[other.pk, note.pk])).status_code, 404)
        note.deleted_at = timezone.now()
        note.save()
        self.assertNotContains(self.client.get(self.company.get_absolute_url()), 'Atnaujinta QA istorija')

    def test_company_attachment_download_checks_owner_and_file(self):
        self.client.force_login(self.user)
        note = Activity.objects.create(company=self.company, text='Priedas QA', created_by=self.user)
        attachment = Attachment.objects.create(activity=note, file='qa.txt', original_name='qa.txt')
        url = reverse('contacts:attachment-download', args=[attachment.pk])
        with patch('django.core.files.storage.FileSystemStorage.open', return_value=BytesIO(b'QA data')):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b''.join(response.streaming_content), b'QA data')
        with patch('django.core.files.storage.FileSystemStorage.open', side_effect=FileNotFoundError):
            self.assertEqual(self.client.get(url).status_code, 404)
        self.company.deleted_at = timezone.now()
        self.company.save()
        self.assertEqual(self.client.get(url).status_code, 404)
        self.company.deleted_at = None
        self.company.save()
        attachment.deleted_at = timezone.now()
        attachment.save()
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_live_reminder_snapshot_auth_cache_and_time_transition(self):
        url = reverse('contacts:reminder-snapshot')
        self.assertEqual(self.client.get(url).status_code, 401)
        self.client.force_login(self.user)
        now = timezone.now()
        reminder = Reminder.objects.create(person=self.person, text='Live QA <test>', due_at=now+timedelta(minutes=1), created_by=self.user)
        with patch('contacts.context_processors.timezone.now', return_value=now):
            response = self.client.get(url)
            self.assertEqual(response.json()['count'], 0)
            self.assertIn('no-store', response['Cache-Control'])
            self.assertIn('Live QA &lt;test&gt;', response.json()['html'])
        with patch('contacts.context_processors.timezone.now', return_value=now+timedelta(minutes=2)):
            response = self.client.get(url)
            self.assertEqual(response.json()['count'], 1)
            self.assertIn('Live QA &lt;test&gt;', response.json()['html'].split('id="bell-scheduled"')[0])
        reminder.refresh_from_db()
        self.assertIsNone(reminder.read_at)
        self.assertIsNone(reminder.completed_at)
        self.assertEqual(self.client.post(url).status_code, 405)

    def test_rescheduled_reminder_becomes_unread_when_due(self):
        self.client.force_login(self.user)
        reminder = Reminder.objects.create(person=self.person, text="Skambutis", due_at=timezone.now()-timedelta(days=1), read_at=timezone.now(), created_by=self.user)
        due = timezone.localtime(timezone.now()+timedelta(days=2)).replace(second=0, microsecond=0)
        url = reverse('contacts:reminder-edit', args=[reminder.pk])
        payload = {"text": "Skambutis", "due_at": due.strftime('%Y-%m-%dT%H:%M')}
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        reminder.refresh_from_db()
        self.assertIsNone(reminder.read_at)
        self.assertEqual(self.client.get(reverse('contacts:list')).context['active_reminder_count'], 0)
        Reminder.objects.filter(pk=reminder.pk).update(due_at=timezone.now()-timedelta(minutes=1))
        self.assertEqual(self.client.get(reverse('contacts:list')).context['active_reminder_count'], 1)
        self.client.get(reverse('contacts:reminder-list'))
        self.assertEqual(self.client.get(reverse('contacts:list')).context['active_reminder_count'], 0)

    def test_reminder_menu_tabs_order_and_archived_people(self):
        self.client.force_login(self.user)
        now = timezone.now()
        soon = Reminder.objects.create(person=self.person, text="Artimas", due_at=now+timedelta(days=1), created_by=self.user)
        later = Reminder.objects.create(person=self.person, text="Vėlesnis", due_at=now+timedelta(days=2), created_by=self.user)
        active = Reminder.objects.create(person=self.person, text="Aktyvus", due_at=now-timedelta(days=1), created_by=self.user)
        response = self.client.get(reverse('contacts:list'))
        self.assertEqual(list(response.context['scheduled_reminders_menu']), [soon, later])
        self.assertEqual(list(response.context['active_reminders_menu']), [active])
        self.assertContains(response, 'id="bell-scheduled"')
        self.person.deleted_at = now
        self.person.save()
        response = self.client.get(reverse('contacts:reminder-list'))
        self.assertEqual(response.context['active_reminder_count'], 0)
        self.assertFalse(response.context['active_reminders'].exists())
        self.assertFalse(response.context['scheduled_reminders'].exists())

    def test_company_fields_edit_in_place_and_retry_is_noop(self):
        self.client.force_login(self.user)
        url = reverse("contacts:company-field-edit", args=[self.company.pk])
        for field, value in {"name": "QA įmonė", "company_code": "123", "vat_code": "LT123",
                             "address": "Vilnius", "phone": "+370123", "email": "qa@example.test", "url": "https://example.test"}.items():
            payload = {"field": field, "value": value}
            response = self.client.post(url, payload)
            self.assertEqual(response.status_code, 200)
            self.company.refresh_from_db()
            self.assertEqual(getattr(self.company, field), value)
            timestamp = self.company.updated_at
            self.assertEqual(self.client.post(url, payload).status_code, 200)
            self.company.refresh_from_db()
            self.assertEqual(self.company.updated_at, timestamp)
        detail = self.client.get(self.company.get_absolute_url())
        self.assertNotContains(detail, "data-edit-url")
        self.assertContains(detail, "QA įmonė")
        self.assertEqual(self.client.post(url, {"field": "email", "value": "invalid"}).status_code, 400)
        self.assertEqual(self.client.post(url, {"field": "name", "value": ""}).status_code, 400)
        self.assertEqual(self.client.post(url, {"field": "deleted_at", "value": ""}).status_code, 400)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(url, {"field": "name", "value": "No"}).status_code, 302)

    def test_reminder_completion_retry_preserves_timestamps(self):
        self.client.force_login(self.user)
        reminder = Reminder.objects.create(person=self.person, text="Pakartojimas",
            due_at=timezone.now(), created_by=self.user)
        url = reverse("contacts:reminder-complete", args=[reminder.pk])
        self.assertEqual(self.client.get(url).status_code, 302)
        reminder.refresh_from_db()
        self.assertIsNone(reminder.completed_at)
        self.assertEqual(self.client.post(url).status_code, 302)
        reminder.refresh_from_db()
        first_state = (reminder.completed_at, reminder.updated_at)
        self.assertIsNotNone(reminder.completed_at)
        self.assertEqual(self.client.post(url).status_code, 302)
        reminder.refresh_from_db()
        self.assertEqual((reminder.completed_at, reminder.updated_at), first_state)

    def test_scheduled_reminder_has_edit_action_and_saves_changes(self):
        self.client.force_login(self.user)
        reminder = Reminder.objects.create(person=self.person, text="Suplanuota",
            due_at=timezone.now() + timedelta(days=2), created_by=self.user)
        url = reverse("contacts:reminder-edit", args=[reminder.pk])
        self.assertContains(self.client.get(reverse("contacts:reminder-list")), f'href="{url}"')
        date = timezone.localtime(timezone.now() + timedelta(days=3)).replace(second=0, microsecond=0)
        self.assertEqual(self.client.post(url, {"text": "Atnaujinta", "due_at": date.strftime("%Y-%m-%dT%H:%M")}).status_code, 302)
        reminder.refresh_from_db()
        self.assertEqual(reminder.text, "Atnaujinta")
        self.assertEqual(reminder.due_at, date)
        self.assertContains(self.client.get(url), "Atnaujinta")

    def test_contact_inline_creates_company_and_reuses_it_on_retry(self):
        self.client.force_login(self.user)
        payload = {"field": "companies", "companies": [self.company.pk], "new_name": "QA Nauja"}
        url = reverse('contacts:field-edit', args=[self.person.pk])
        for _ in range(2):
            self.assertEqual(self.client.post(url, payload).status_code, 200)
        self.assertEqual(self.person.companies.count(), 2)
        self.assertEqual(Company.objects.filter(name='QA Nauja').count(), 1)
        self.assertEqual(self.person.company_links.filter(is_primary=True).count(), 1)

    def test_contact_field_edit_is_scoped_and_validated(self):
        self.client.force_login(self.user)
        url = reverse('contacts:field-edit', args=[self.person.pk])
        original_name = self.person.first_name
        before_phones = list(self.person.phones.values_list('pk', 'number'))
        response = self.client.post(url, {"field": "job_title", "value": "Naujos pareigos"})
        self.assertEqual(response.status_code, 200)
        self.person.refresh_from_db()
        self.assertEqual(self.person.job_title, "Naujos pareigos")
        self.assertEqual(self.person.first_name, original_name)
        self.assertEqual(list(self.person.phones.values_list('pk', 'number')), before_phones)
        self.assertEqual(self.client.post(url, {"field": "first_name", "value": ""}).status_code, 400)
        self.assertEqual(self.client.post(url, {"field": "emails", "value": "not-an-email"}).status_code, 400)
        self.assertEqual(self.client.post(url, {"field": "web_links", "value": "javascript:alert(1)"}).status_code, 400)
        self.assertEqual(self.client.post(url, {"field": "deleted_at", "value": "2026-01-01"}).status_code, 400)
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_contact_inline_multiple_values_preserve_rows_and_other_relations(self):
        self.client.force_login(self.user)
        url = reverse('contacts:field-edit', args=[self.person.pk])
        phone = self.person.phones.first()
        if phone is None:
            phone = PhoneNumber.objects.create(person=self.person, number="123", label="Asmeninis", is_primary=True)
        payload = {"field": "phones", "value": phone.number + "\n456\n456"}
        for _ in range(2):
            self.assertEqual(self.client.post(url, payload).status_code, 200)
        self.assertEqual(self.person.phones.count(), 2)
        self.assertTrue(self.person.phones.filter(pk=phone.pk, label=phone.label).exists())
        self.assertEqual(self.person.phones.filter(is_primary=True).count(), 1)
        self.assertEqual(self.client.post(url, {"field": "phones", "value": ""}).status_code, 200)
        self.assertFalse(self.person.phones.exists())

    def test_company_editor_renders_all_links_and_rejects_invalid_selection(self):
        self.client.force_login(self.user)
        second = Company.objects.create(name="Antra įmonė")
        PersonCompanyLink.objects.get_or_create(person=self.person, company=self.company)
        PersonCompanyLink.objects.create(person=self.person, company=second, role="Konsultantė")
        response = self.client.get(self.person.get_absolute_url())
        self.assertContains(response, second.name)
        self.assertContains(response, "Pridėti naują")
        self.assertNotContains(response, "data-edit-url")
        url = reverse('contacts:field-edit', args=[self.person.pk])
        before = self.person.companies.count()
        self.assertEqual(self.client.post(url, {"field": "companies", "companies": [999999], "new_name": "Nekurti"}).status_code, 400)
        self.assertEqual(self.person.companies.count(), before)
        self.assertFalse(Company.objects.filter(name="Nekurti").exists())
        self.assertEqual(self.client.post(url, {"field": "companies", "companies": [self.company.pk, second.pk]}).status_code, 200)
        self.assertEqual(self.person.company_links.get(company=second).role, "Konsultantė")
        self.assertNotContains(self.client.get(reverse('contacts:edit', args=[self.person.pk])), 'name="new_companies"')

    def test_inline_favourite_filter_and_company_relations(self):
        self.client.force_login(self.user)
        url = reverse('contacts:inline-update', args=['person', self.person.pk])
        for _ in range(2):
            self.assertEqual(self.client.post(url, {'field': 'favourite', 'value': 'true'}).status_code, 200)
        self.person.refresh_from_db()
        self.assertTrue(self.person.favourite)
        other = Person.objects.create(first_name='Other', last_name='Test')
        response = self.client.get(reverse('contacts:list'), {'favourite': '1'})
        self.assertEqual(list(response.context['page']), [self.person])
        for kind, record in [('person', self.person), ('company', self.company)]:
            url = reverse('contacts:inline-update', args=[kind, record.pk])
            for field, model in [('tags', Tag), ('categories', Category)]:
                values = [model.objects.get_or_create(name=f'Inline {i}')[0].pk for i in range(4)]
                self.assertEqual(self.client.post(url, {'field': field, 'values': values[:3]}).status_code, 200)
                self.assertEqual(self.client.post(url, {'field': field, 'values': values}).status_code, 400)
                self.assertEqual(getattr(record, field).count(), 3)
                self.assertEqual(self.client.post(url, {'field': field, 'values': []}).status_code, 200)
                self.assertEqual(getattr(record, field).count(), 0)

    def test_import_all_companies_and_rollback_on_invalid_later_row(self):
        from contacts.views import _import_contact_rows
        rows = [{"Vardas": "QA", "Pavardė": "Importas", "Įmonė": "Alfa; Beta"}]
        _import_contact_rows(rows)
        _import_contact_rows(rows)
        person = Person.objects.get(first_name="QA", last_name="Importas")
        self.assertEqual(set(person.companies.values_list("name", flat=True)), {"Alfa", "Beta"})
        self.assertEqual(person.company_links.filter(is_primary=True).count(), 1)
        with self.assertRaises(ValueError):
            _import_contact_rows([
                {"Vardas": "Atšaukiamas", "Pavardė": "Importas", "Įmonė": "Atšaukiama"},
                {"Vardas": "Klaida", "Pavardė": "Importas", "Tagai": "A;B;C;D"},
            ])
        self.assertFalse(Person.objects.filter(first_name="Atšaukiamas").exists())
        self.assertFalse(Company.objects.filter(name="Atšaukiama").exists())

    def test_export_csv_structure_selection_and_archived_exclusion(self):
        import csv
        from io import StringIO
        self.client.force_login(self.user)
        PostalAddress.objects.create(person=self.person, address='Vilnius, "Centras"')
        archived = Person.objects.create(first_name="Archyvas", last_name="QA", deleted_at=timezone.now())
        response = self.client.post(reverse("contacts:contacts-export"), {"selected": [self.person.pk, archived.pk]})
        rows = list(csv.DictReader(StringIO(response.content.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Vardas"], self.person.first_name)
        self.assertEqual(rows[0]["Adresai"], 'Vilnius, "Centras"')
        response = self.client.post(reverse("contacts:contacts-export"), {"selected": []})
        self.assertEqual(list(csv.DictReader(StringIO(response.content.decode("utf-8-sig")))), [])

    def test_archive_restore_retries_preserve_state_and_timestamps(self):
        self.client.force_login(self.user)
        for record, archive, restore in (
            (self.person, "archive", "restore"),
            (self.company, "company-archive", "company-restore"),
        ):
            for action in (archive, restore):
                url = reverse("contacts:" + action, args=[record.pk])
                self.assertEqual(self.client.post(url).status_code, 302)
                record.refresh_from_db()
                expected = (record.deleted_at, record.updated_at)
                self.assertEqual(self.client.post(url).status_code, 302)
                record.refresh_from_db()
                self.assertEqual((record.deleted_at, record.updated_at), expected)

    def setUp(self):
        self.user = get_user_model().objects.create_user("admin", password="very-secure-password")
        self.person = Person.objects.create(first_name="Rūta", last_name="Žukaitė", job_title="Projektų vadovė")
        self.company = Company.objects.create(name="Aukštaitijos projektai")
        PersonCompanyLink.objects.create(person=self.person, company=self.company, is_primary=True)
        PhoneNumber.objects.create(person=self.person, number="+370 645 21 987", is_primary=True)
        EmailAddress.objects.create(person=self.person, email="ruta@example.lt", is_primary=True)

    def test_contacts_require_login(self):
        response = self.client.get(reverse("contacts:list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_main_navigation_has_no_activities_item(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("contacts:list"))
        self.assertNotContains(response, ">Veiklos<")
        self.assertContains(response, "Priminimai")
        self.assertContains(response, "Nustatymai")
        self.assertContains(response, 'class="nav-icon"')

    def test_common_action_layout_is_used_for_import_forms_and_detail_headers(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("contacts:create"))
        self.assertContains(response, reverse("contacts:import-export"))
        self.assertContains(response, "Importuoti")
        response = self.client.get(reverse("contacts:import-export"))
        self.assertContains(response, 'class="import-card-actions"', count=3)
        self.assertContains(response, "Importuoti")
        self.assertContains(response, "Eksportuoti kontaktus")
        self.assertContains(response, "Eksportuoti įmones")
        response = self.client.get(self.person.get_absolute_url())
        self.assertContains(response, 'class="page-actions"')
        response = self.client.get(self.company.get_absolute_url())
        self.assertContains(response, 'class="page-actions"')
        response = self.client.get(reverse("contacts:person-create"))
        self.assertContains(response, 'class="form-actions"')

    def test_companies_search_related_contact_fields_and_ignore_removed_contacts_filter(self):
        self.client.force_login(self.user)
        empty_company = Company.objects.create(name="Be kontaktų", address="Vilnius")
        for query in ["Aukštaitijos", "Rūta", "Projektų", "ruta@example.lt"]:
            with self.subTest(query=query):
                response = self.client.get(reverse("contacts:company-list"), {"q": query})
                self.assertEqual(list(response.context["page"]), [self.company])
        response = self.client.get(reverse("contacts:company-list"), {"contacts": "with"})
        self.assertEqual(set(response.context["page"]), {self.company, empty_company})
        self.assertNotIn("contacts", response.context["filter_values"])
        self.assertNotContains(response, 'name="contacts"')
        self.assertContains(response, "Įmonių filtrai")

    def test_company_sorting_and_pagination_preserve_filters_and_columns(self):
        self.client.force_login(self.user)
        first = Company.objects.create(name="Alfa", company_code="100")
        last = Company.objects.create(name="Žara", company_code="300")
        for index in range(51):
            Company.objects.create(name=f"Įmonė {index:02d}")
        response = self.client.get(reverse("contacts:company-list"), {
            "sort": "company_code", "direction": "desc", "columns": ["company_code", "contacts"], "page_size": "50",
        })
        self.assertEqual(response.context["sort"], "company_code")
        self.assertEqual(response.context["direction"], "desc")
        self.assertEqual(response.context["page"].paginator.count, 54)
        self.assertEqual(response.context["page"].paginator.num_pages, 2)
        self.assertEqual(response.context["page"].object_list[0], last)
        self.assertIn("columns=company_code&columns=contacts", response.context["list_query"])
        self.assertContains(response, "sort=contacts")
        self.assertNotEqual(first, last)

    def test_all_contact_data_columns_offer_sort_menu_and_id_sorting(self):
        self.client.force_login(self.user)
        other = Person.objects.create(first_name="Asta", last_name="Nauja")
        first_category = Category.objects.create(name="A kategorija")
        second_category = Category.objects.create(name="B kategorija")
        self.person.categories.add(first_category, second_category)
        columns = ["company", "phone", "email", "category", "tags", "status", "updated"]

        response = self.client.get(reverse("contacts:list"), {"columns": columns, "sort": "id", "direction": "desc"})

        self.assertEqual(response.context["sort"], "id")
        self.assertEqual(list(response.context["page"])[0], other)
        self.assertEqual(response.context["page"].paginator.count, Person.objects.filter(deleted_at__isnull=True).count())
        self.assertContains(response, 'class="sort-control"', count=8)
        for key in ("name", "company", "phone", "email", "category", "tags", "status", "updated", "id"):
            with self.subTest(key=key):
                self.assertContains(response, f"sort={key}&amp;direction=asc")
                self.assertContains(response, f"sort={key}&amp;direction=desc")

    def test_all_company_data_columns_offer_sort_menu_and_id_sorting(self):
        self.client.force_login(self.user)
        other = Company.objects.create(name="Nauja įmonė")
        first_tag = Tag.objects.create(name="A žyma")
        second_tag = Tag.objects.create(name="B žyma")
        self.company.tags.add(first_tag, second_tag)

        response = self.client.get(reverse("contacts:company-list"), {"sort": "id", "direction": "desc"})

        self.assertEqual(response.context["sort"], "id")
        self.assertEqual(list(response.context["page"])[0], other)
        self.assertEqual(response.context["page"].paginator.count, Company.objects.filter(deleted_at__isnull=True).count())
        self.assertContains(response, 'class="sort-control"', count=8)
        for key in ("name", "company_code", "vat_code", "phone", "email", "contacts", "category", "tags", "id"):
            with self.subTest(key=key):
                self.assertContains(response, f"sort={key}&amp;direction=asc")
                self.assertContains(response, f"sort={key}&amp;direction=desc")

    def test_searches_related_fields(self):
        self.client.force_login(self.user)
        PostalAddress.objects.create(person=self.person, address="Gedimino pr. 1, Vilnius")
        WebLink.objects.create(person=self.person, url="https://ruta.example.lt")
        self.person.status = "Laukiamas"
        self.person.save(update_fields=["status", "updated_at"])
        for query in ["Žukai", "Rūta Žukaitė", "Aukštaitijos", "645 21", "ruta@example", "Gedimino", "ruta.example", "Laukiam"]:
            with self.subTest(query=query):
                response = self.client.get(reverse("contacts:list"), {"q": query})
                self.assertContains(response, "Rūta Žukaitė")

    def test_sorting_and_page_size_preserve_active_filters_and_columns(self):
        self.client.force_login(self.user)
        category = Category.objects.create(name="Klientas")
        self.person.categories.add(category)
        response = self.client.get(reverse("contacts:list"), {
            "category": category.pk,
            "columns": ["phone", "status"],
            "page_size": "100",
            "sort": "name",
            "direction": "asc",
        })
        self.assertEqual(response.context["page_size"], 100)
        self.assertEqual(response.context["columns"], ["phone", "status"])
        self.assertContains(response, f"category={category.pk}&amp;columns=phone&amp;columns=status&amp;page_size=100&amp;sort=name")

    def test_contacts_can_be_filtered_and_archived_in_bulk(self):
        self.client.force_login(self.user)
        category = Category.objects.create(name="Klientas")
        self.person.categories.add(category)
        response = self.client.get(reverse("contacts:list"), {"category": category.pk})
        self.assertContains(response, "Rūta Žukaitė")
        response = self.client.post(reverse("contacts:bulk-action"), {"selected": [self.person.pk], "action": "archive"})
        self.assertRedirects(response, reverse("contacts:list"))
        self.person.refresh_from_db()
        self.assertIsNotNone(self.person.deleted_at)

    def test_contact_filters_support_multiple_values_and_date_range_without_status_filter(self):
        self.client.force_login(self.user)
        client = Category.objects.create(name="Klientas")
        partner = Category.objects.create(name="Partneris")
        important = Tag.objects.create(name="Svarbus")
        self.person.categories.add(client)
        self.person.tags.add(important)
        other = Person.objects.create(first_name="Kitas", last_name="Asmuo", favourite=True)
        other.categories.add(partner)
        other_email = EmailAddress.objects.create(person=other, email="other@example.lt")
        note = Activity.objects.create(person=self.person, text="Pokalbis", created_by=self.user)
        today = timezone.localdate().isoformat()

        response = self.client.get(reverse("contacts:list"), {
            "categories": [client.pk, partner.pk],
            "tags": [important.pk],
            "companies": [self.company.pk],
            "email": "ruta@example",
            "last_contact_from": today,
            "last_contact_to": today,
            "status": "Aktyvus",
        })

        self.assertEqual(list(response.context["page"]), [self.person])
        self.assertEqual(response.context["filter_values"]["categories"], [client.pk, partner.pk])
        self.assertEqual(response.context["active_filter_count"], 5)
        self.assertContains(response, "Klientas")
        self.assertContains(response, "Partneris")
        self.assertNotContains(response, 'name="status"')
        self.assertNotContains(response, 'name="companies"')
        self.assertNotIn("status", response.context["filter_values"])
        self.assertNotIn("companies", response.context["filter_values"])
        self.assertIsNotNone(note.pk)
        self.assertIsNotNone(other_email.pk)

    def test_company_filters_include_categories_tags_address_and_linked_contact_history(self):
        self.client.force_login(self.user)
        client = Category.objects.create(name="Klientas")
        supplier = Category.objects.create(name="Tiekėjas")
        important = Tag.objects.create(name="Svarbus")
        self.company.address = "Vilnius, Gedimino pr. 1"
        self.company.save()
        self.company.categories.add(client)
        self.company.tags.add(important)
        other = Company.objects.create(name="Kita įmonė", address="Kaunas")
        other.categories.add(supplier)
        Activity.objects.create(person=self.person, text="Susitikimas", created_by=self.user)
        today = timezone.localdate().isoformat()

        response = self.client.get(reverse("contacts:company-list"), {
            "categories": [client.pk, supplier.pk],
            "tags": [important.pk],
            "city": "Vilnius",
            "last_contact_from": today,
            "last_contact_to": today,
        })

        self.assertEqual(list(response.context["page"]), [self.company])
        self.assertEqual(response.context["active_filter_count"], 5)
        self.assertContains(response, "Miestas arba adresas")
        self.assertNotContains(response, 'name="status"')

    def test_filter_drawers_use_list_style_category_and_tag_labels_without_status(self):
        self.client.force_login(self.user)
        category = Category.objects.create(name="Klientas")
        tag = Tag.objects.create(name="Svarbus", color="tag-color-3")

        for route in ("contacts:list", "contacts:company-list"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route), {"categories": category.pk, "tags": tag.pk})
                self.assertContains(response, 'class="filter-panel"')
                self.assertContains(response, 'data-filter-multiselect', count=2)
                self.assertContains(response, 'class="filter-choice"', count=2)
                self.assertContains(response, '<span class="crm-label">Klientas</span>', html=True)
                self.assertContains(response, '<span class="crm-label tag-color-3">Svarbus</span>', html=True)
                self.assertContains(response, 'class="filter-selected-tag crm-label"', count=1)
                self.assertContains(response, 'class="filter-selected-tag crm-label tag-color-3"', count=1)
                self.assertContains(response, 'data-filter-remove', count=2)
                self.assertNotContains(response, 'name="status"')
                if route == "contacts:list":
                    self.assertNotContains(response, 'name="companies"')
                else:
                    self.assertNotContains(response, 'name="contacts"')
        self.assertIsNotNone(category.pk)
        self.assertIsNotNone(tag.pk)

    def test_saved_filter_preserves_multiple_values_and_invalid_filter_input_is_ignored(self):
        self.client.force_login(self.user)
        first = Category.objects.create(name="Pirma")
        second = Category.objects.create(name="Antra")
        payload = {"name": "Kelios kategorijos", "categories": [first.pk, second.pk], "last_contact_from": "2026-09-01"}
        self.client.post(reverse("contacts:saved-filter-create"), payload)
        saved = SavedFilter.objects.get(user=self.user, scope="contacts", name="Kelios kategorijos")

        self.assertEqual(saved.filters["categories"], [first.pk, second.pk])
        self.assertIn(f"categories={first.pk}", saved.query_string)
        self.assertIn(f"categories={second.pk}", saved.query_string)
        response = self.client.get(reverse("contacts:list"), {"categories": ["bad", "999999"], "last_contact_from": "not-a-date"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["filter_values"]["categories"], [999999])
        self.assertEqual(response.context["filter_values"]["last_contact_from"], "")

    def test_archived_contact_can_be_restored(self):
        self.client.force_login(self.user)
        self.person.deleted_at = timezone.now()
        self.person.save()
        response = self.client.post(reverse("contacts:restore", args=[self.person.pk]))
        self.assertRedirects(response, reverse("contacts:archive-list"))
        self.person.refresh_from_db()
        self.assertIsNone(self.person.deleted_at)

    def test_saved_filter_is_idempotently_updated_by_name(self):
        self.client.force_login(self.user)
        payload = {"name": "VIP", "q": "Rūta"}
        self.client.post(reverse("contacts:saved-filter-create"), payload)
        self.client.post(reverse("contacts:saved-filter-create"), payload)
        self.assertEqual(SavedFilter.objects.filter(user=self.user, scope="contacts", name="VIP").count(), 1)

    def test_saved_filter_can_be_renamed_and_deleted(self):
        self.client.force_login(self.user)
        saved = SavedFilter.objects.create(user=self.user, scope="contacts", name="Sena", filters={"q": "Rūta"})
        self.client.post(reverse("contacts:saved-filter-update", args=[saved.pk]), {"action": "rename", "name": "Nauja"})
        saved.refresh_from_db()
        self.assertEqual(saved.name, "Nauja")
        response = self.client.post(reverse("contacts:saved-filter-update", args=[saved.pk]), {"action": "delete"})
        self.assertRedirects(response, reverse("contacts:list"))
        self.assertFalse(SavedFilter.objects.filter(pk=saved.pk).exists())

    def test_saved_filter_rename_rejects_duplicate_name(self):
        self.client.force_login(self.user)
        SavedFilter.objects.create(user=self.user, scope="contacts", name="Klientai", filters={})
        saved = SavedFilter.objects.create(user=self.user, scope="contacts", name="Tiekėjai", filters={})
        self.client.post(reverse("contacts:saved-filter-update", args=[saved.pk]), {"action": "rename", "name": "Klientai"})
        saved.refresh_from_db()
        self.assertEqual(saved.name, "Tiekėjai")

    def test_user_cannot_change_another_users_saved_filter(self):
        other = get_user_model().objects.create_user("kitas", password="very-secure-password")
        saved = SavedFilter.objects.create(user=other, scope="contacts", name="Slaptas", filters={})
        self.client.force_login(self.user)
        response = self.client.post(reverse("contacts:saved-filter-update", args=[saved.pk]), {"action": "delete"})
        self.assertEqual(response.status_code, 404)
        self.assertTrue(SavedFilter.objects.filter(pk=saved.pk).exists())

    def test_only_one_default_saved_filter_per_scope(self):
        self.client.force_login(self.user)
        first = SavedFilter.objects.create(user=self.user, scope="contacts", name="A", filters={"favourite": "1"})
        second = SavedFilter.objects.create(user=self.user, scope="contacts", name="B", filters={"q": "x"})
        self.client.post(reverse("contacts:saved-filter-update", args=[first.pk]), {"action": "default"})
        self.client.post(reverse("contacts:saved-filter-update", args=[second.pk]), {"action": "default"})
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_default)
        self.assertTrue(second.is_default)
        self.client.post(reverse("contacts:saved-filter-update", args=[second.pk]), {"action": "default"})
        second.refresh_from_db()
        self.assertFalse(second.is_default)

    def test_default_saved_filter_applies_once_per_session_then_lets_user_see_all(self):
        self.client.force_login(self.user)
        SavedFilter.objects.create(user=self.user, scope="contacts", name="Mėgstami", filters={"favourite": "1"}, is_default=True)
        response = self.client.get(reverse("contacts:list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("favourite=1", response.url)
        # Second parameter-free visit in the same session shows everything.
        response = self.client.get(reverse("contacts:list"))
        self.assertEqual(response.status_code, 200)

    def test_company_columns_and_saved_list_are_persistent_and_scoped(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("contacts:company-list"), {"columns": ["phone", "contacts"]})
        self.assertEqual(response.context["columns"], ["phone", "contacts"])
        self.assertContains(response, "Stulpeliai")
        self.assertContains(response, "Mano filtrai")
        payload = {"name": "Vilniaus įmonės", "city": "Vilnius", "contacts": "with"}
        self.client.post(reverse("contacts:company-saved-filter-create"), payload)
        self.client.post(reverse("contacts:company-saved-filter-create"), payload)
        saved = SavedFilter.objects.get(user=self.user, scope="companies", name="Vilniaus įmonės")
        self.assertEqual(saved.filters, {"city": "Vilnius"})
        self.assertEqual(SavedFilter.objects.filter(user=self.user, scope="contacts", name="Vilniaus įmonės").count(), 0)

    def test_settings_adds_tags_and_categories_idempotently(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("contacts:settings"))
        self.assertContains(response, "Žymos")
        self.assertContains(response, "Kategorijos")
        for _ in range(2):
            self.client.post(reverse("contacts:settings"), {"kind": "tag", "name": "Svarbus"})
            self.client.post(reverse("contacts:settings"), {"kind": "category", "name": "Klientas"})
        self.assertEqual(Tag.objects.filter(name="Svarbus").count(), 1)
        self.assertEqual(Category.objects.filter(name="Klientas").count(), 1)

    def test_documentation_requires_login_and_is_linked_from_settings(self):
        url = reverse("contacts:settings-documentation")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

        self.client.force_login(self.user)
        response = self.client.get(reverse("contacts:settings"))
        self.assertContains(response, url)
        self.assertContains(response, "Dokumentacija")

    def test_documentation_topics_are_directly_linkable_and_invalid_topic_falls_back(self):
        self.client.force_login(self.user)
        url = reverse("contacts:settings-documentation")
        expected = {
            "overview": "CRM dokumentacija",
            "installation": "Diegimas naujame įrenginyje",
            "screens": "Langai, mygtukai ir duomenys",
            "user": "Naudotojo instrukcija",
            "admin": "Administratoriaus instrukcija",
            "data": "Duomenys, sauga ir ribos",
            "backup": "Atsarginės kopijos ir atkūrimas",
        }
        for topic, heading in expected.items():
            response = self.client.get(url, {"topic": topic})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["documentation_topic"], topic)
            self.assertContains(response, heading)
            self.assertContains(response, f"?topic={topic}")

        response = self.client.get(url, {"topic": "not-a-topic"})
        self.assertEqual(response.context["documentation_topic"], "overview")
        self.assertContains(response, "CRM dokumentacija")

    def test_technical_documentation_exposes_verified_configuration_and_operations(self):
        self.client.force_login(self.user)
        url = reverse("contacts:settings-documentation")
        installation = self.client.get(url, {"topic": "installation"})
        for value in ("Docker Compose", "POSTGRES_PASSWORD", "DJANGO_SECRET_KEY", "CRM_SETUP_TOKEN", "/health/ready", "/setup/"):
            self.assertContains(installation, value)

        screens = self.client.get(url, {"topic": "screens"})
        for value in ("Kontaktų sąrašas", "Įmonių sąrašas", "Priminimai", "Importas / eksportas", "Archyvas", "Nustatymai"):
            self.assertContains(screens, value)

        admin = self.client.get(url, {"topic": "admin"})
        for value in ("changepassword", "axes_reset_username", "Django administravimas", "Nėra atskirų CRM vaidmenų"):
            self.assertContains(admin, value)

        backup = self.client.get(url, {"topic": "backup"})
        for value in ("pg_dump", "pg_restore", "runtime/media", "Atkūrimo patikra"):
            self.assertContains(backup, value)

    def test_profile_settings_update_user_preferences_and_avatar_menu(self):
        from contacts.models import UserProfile

        self.client.force_login(self.user)
        response = self.client.post(reverse("contacts:settings"), {
            "first_name": "Rasa",
            "last_name": "Jonaitė",
            "email": "rasa@example.lt",
            "language": "en",
            "timezone": "Europe/London",
        })
        self.assertRedirects(response, reverse("contacts:settings"))
        self.assertEqual(response.cookies["django_language"].value, "en")
        self.user.refresh_from_db()
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual((self.user.first_name, self.user.last_name, self.user.email), ("Rasa", "Jonaitė", "rasa@example.lt"))
        self.assertEqual((profile.language, profile.timezone), ("en", "Europe/London"))
        response = self.client.get(reverse("contacts:list"))
        self.assertContains(response, 'aria-label="Open user menu"')
        self.assertContains(response, ">RJ</summary>")
        self.assertContains(response, reverse("contacts:settings"))

    def test_profile_avatar_is_saved_and_served_to_authenticated_user(self):
        self.client.force_login(self.user)
        image = b"\x89PNG\r\n\x1a\nprofile-image"

        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.post(reverse("contacts:settings"), {
                "first_name": "Rasa",
                "last_name": "Jonaitė",
                "email": "rasa@example.lt",
                "language": "lt",
                "timezone": "Europe/Vilnius",
                "avatar": SimpleUploadedFile("profile.png", image, content_type="image/png"),
            })
            self.assertRedirects(response, reverse("contacts:settings"))
            self.user.crm_profile.refresh_from_db()
            self.assertTrue(self.user.crm_profile.avatar.name.startswith("avatars/"))
            avatar_url = reverse("contacts:profile-avatar")
            self.assertContains(self.client.get(reverse("contacts:settings")), f'src="{avatar_url}"')
            avatar_response = self.client.get(avatar_url)
            self.assertEqual(avatar_response.status_code, 200)
            self.assertEqual(b"".join(avatar_response.streaming_content), image)

        anonymous_response = self.client_class().get(reverse("contacts:profile-avatar"))
        self.assertEqual(anonymous_response.status_code, 302)

    def test_activity_history_uses_updated_profile_name_in_contact_and_company(self):
        self.client.force_login(self.user)
        Activity.objects.create(person=self.person, text="Kontakto istorija", created_by=self.user)
        Activity.objects.create(company=self.company, text="Įmonės istorija", created_by=self.user)
        self.client.post(reverse("contacts:settings"), {
            "first_name": "Rasa",
            "last_name": "Jonaitė",
            "email": "rasa@example.lt",
            "language": "lt",
            "timezone": "Europe/Vilnius",
        })

        self.assertContains(self.client.get(self.person.get_absolute_url()), "- Rasa Jonaitė")
        self.assertContains(self.client.get(self.company.get_absolute_url()), "- Rasa Jonaitė")

    def test_profile_save_action_is_aligned_to_the_right(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("contacts:settings"))
        self.assertContains(response, 'class="form-actions profile-form-actions"')

    def test_profile_rejects_non_image_avatar_and_taxonomy_pages_remain_available(self):
        self.client.force_login(self.user)
        invalid = SimpleUploadedFile("avatar.txt", b"not an image", content_type="text/plain")
        response = self.client.post(reverse("contacts:settings"), {
            "first_name": "",
            "last_name": "",
            "email": "",
            "language": "lt",
            "timezone": "Europe/Vilnius",
            "avatar": invalid,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pasirinkite PNG, JPG, WEBP arba GIF formato nuotrauką.")
        self.assertFalse(self.user.crm_profile.avatar)
        self.assertContains(self.client.get(reverse("contacts:settings-tags")), "Žymos")
        self.assertContains(self.client.get(reverse("contacts:settings-categories")), "Kategorijos")

    def test_taxonomy_settings_rename_tag_set_color_and_show_usage(self):
        self.client.force_login(self.user)
        tag = Tag.objects.create(name="Svarbus")
        self.person.tags.add(tag)
        response = self.client.post(reverse("contacts:settings-tags"), {
            "item_id": tag.pk,
            "name": "Prioritetinis",
            "color": "tag-color-6",
        })
        self.assertRedirects(response, reverse("contacts:settings-tags"))
        tag.refresh_from_db()
        self.assertEqual((tag.name, tag.color, tag.color_class), ("Prioritetinis", "tag-color-6", "tag-color-6"))
        response = self.client.get(reverse("contacts:settings-tags"))
        self.assertContains(response, "Prioritetinis")
        self.assertContains(response, "Kontaktai: 1, įmonės: 0")
        self.assertContains(self.client.get(reverse("contacts:list")), "tag-color-6")

    def test_taxonomy_settings_reject_duplicate_name_and_invalid_color(self):
        self.client.force_login(self.user)
        first = Tag.objects.create(name="Pirma")
        second = Tag.objects.create(name="Antra")
        response = self.client.post(reverse("contacts:settings-tags"), {
            "item_id": second.pk,
            "name": "pirma",
            "color": "tag-color-2",
        }, follow=True)
        second.refresh_from_db()
        self.assertEqual(second.name, "Antra")
        self.assertContains(response, "Tokia žyma jau yra.")
        response = self.client.post(reverse("contacts:settings-tags"), {
            "item_id": first.pk,
            "name": "Pirma",
            "color": "not-a-color",
        }, follow=True)
        first.refresh_from_db()
        self.assertEqual(first.color, "")
        self.assertContains(response, "Pasirinkta netinkama žymos spalva.")

    def test_english_ui_translates_dynamic_titles_and_action_messages(self):
        self.client.force_login(self.user)
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"
        self.assertContains(self.client.get(reverse("contacts:person-create")), "Add person")
        response = self.client.post(reverse("contacts:bulk-action"), {
            "action": "archive",
            "selected": [self.person.pk],
        }, follow=True)
        self.assertContains(response, "Archived contacts: 1.")
        invalid = SimpleUploadedFile("contacts.txt", b"invalid", content_type="text/plain")
        response = self.client.post(reverse("contacts:import-export"), {"file": invalid})
        self.assertContains(response, "The file could not be read. Check its columns and format.")

    def test_duplicate_warning_requires_explicit_create_anyway(self):
        self.client.force_login(self.user)
        payload = {
            "first_name": "Rūta",
            "last_name": "Žukaitė",
            "companies": [self.company.pk],
            "email": "ruta@example.lt",
            "phone": "+370 645 21 987",
        }
        before = Person.objects.count()
        response = self.client.post(reverse("contacts:person-create"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rastas galimas dublikatas")
        self.assertEqual(Person.objects.count(), before)
        response = self.client.post(reverse("contacts:person-create"), {**payload, "confirm_duplicate": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Person.objects.count(), before + 1)

    def test_duplicate_settings_and_review_page(self):
        self.client.force_login(self.user)
        settings_response = self.client.get(reverse("contacts:settings-duplicates"))
        self.assertContains(settings_response, '<select name="level" class="duplicate-level-select"')
        self.assertNotContains(settings_response, 'type="radio"')
        other = Person.objects.create(first_name="Kita", last_name="Pavardė")
        EmailAddress.objects.create(person=other, email="ruta@example.lt")
        response = self.client.get(reverse("contacts:duplicate-list"))
        self.assertContains(response, self.person.get_absolute_url())
        self.assertContains(response, other.get_absolute_url())
        self.assertContains(response, "Tas pats el. paštas")
        response = self.client.post(reverse("contacts:settings-duplicates"), {
            "level": "strict",
        })
        self.assertRedirects(response, reverse("contacts:settings-duplicates"))
        duplicate_settings = DuplicateSettings.load()
        self.assertFalse(duplicate_settings.enabled)
        self.assertEqual(duplicate_settings.level, "strict")

    def test_company_duplicate_warning_and_review(self):
        self.client.force_login(self.user)
        self.company.company_code = "123456789"
        self.company.save(update_fields=["company_code"])
        payload = {"name": "Kita įmonė", "company_code": "123456789"}
        before = Company.objects.count()
        response = self.client.post(reverse("contacts:company-create"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rastas galimas dublikatas")
        self.assertEqual(Company.objects.count(), before)
        response = self.client.post(reverse("contacts:company-create"), {**payload, "confirm_duplicate": "1"})
        self.assertEqual(response.status_code, 302)
        created = Company.objects.get(name="Kita įmonė")
        response = self.client.get(reverse("contacts:duplicate-list"))
        self.assertContains(response, self.company.get_absolute_url())
        self.assertContains(response, created.get_absolute_url())
        self.assertContains(response, "Tas pats įmonės kodas")

    def test_person_duplicates_can_be_merged_without_deleting_source(self):
        self.client.force_login(self.user)
        target = Person.objects.create(first_name="Rūta", last_name="Žukaitė", favourite=True)
        EmailAddress.objects.create(person=target, email="ruta@example.lt", is_primary=True)
        extra_company = Company.objects.create(name="Kita darbovietė")
        PersonCompanyLink.objects.create(person=self.person, company=extra_company, role="Konsultantė")
        PhoneNumber.objects.create(person=target, number="+370 600 00 001", is_primary=True)
        note = Activity.objects.create(person=self.person, text="Perkeliama istorija", created_by=self.user)
        attachment = Attachment.objects.create(activity=note, file="qa.txt", original_name="qa.txt")
        reminder = Reminder.objects.create(person=self.person, text="Perkeliamas priminimas", due_at=timezone.now(), created_by=self.user)
        source_tag = Tag.objects.create(name="Šaltinio žyma")
        target_tag = Tag.objects.create(name="Tikslo žyma")
        self.person.tags.add(source_tag)
        target.tags.add(target_tag)

        response = self.client.post(reverse("contacts:duplicate-merge", args=["person", self.person.pk, target.pk]))

        self.assertRedirects(response, target.get_absolute_url())
        self.person.refresh_from_db()
        target.refresh_from_db()
        self.assertEqual(self.person.merged_into, target)
        self.assertIsNotNone(self.person.deleted_at)
        self.assertTrue(Person.objects.filter(pk=self.person.pk).exists())
        self.assertEqual(target.job_title, "Projektų vadovė")
        self.assertTrue(target.favourite)
        self.assertEqual(set(target.phones.values_list("number", flat=True)), {"+370 600 00 001", "+370 645 21 987"})
        self.assertEqual(set(target.companies.values_list("name", flat=True)), {"Aukštaitijos projektai", "Kita darbovietė"})
        self.assertEqual(set(target.tags.values_list("name", flat=True)), {"Šaltinio žyma", "Tikslo žyma"})
        self.assertEqual(Activity.objects.get(pk=note.pk).person, target)
        self.assertEqual(Attachment.objects.get(pk=attachment.pk).activity_id, note.pk)
        self.assertEqual(Reminder.objects.get(pk=reminder.pk).person, target)
        self.assertNotContains(self.client.get(reverse("contacts:archive-list")), self.person.get_absolute_url())
        self.assertEqual(self.client.post(reverse("contacts:restore", args=[self.person.pk])).status_code, 404)
        self.assertRedirects(
            self.client.post(reverse("contacts:duplicate-merge", args=["person", self.person.pk, target.pk])),
            target.get_absolute_url(),
        )

    def test_company_duplicates_can_be_merged_with_people_and_history(self):
        self.client.force_login(self.user)
        source = Company.objects.create(name="Dubliuota įmonė", address="Vilnius", company_code="123")
        target = Company.objects.create(name="Paliekama įmonė", company_code="123")
        source_link = PersonCompanyLink.objects.create(person=self.person, company=source, role="Vadovė", is_primary=True)
        PersonCompanyLink.objects.create(person=self.person, company=target)
        other = Person.objects.create(first_name="Kitas", last_name="Asmuo")
        PersonCompanyLink.objects.create(person=other, company=source, role="Specialistas")
        note = Activity.objects.create(company=source, text="Įmonės istorija", created_by=self.user)
        source_tag = Tag.objects.create(name="Įmonės žyma")
        source.tags.add(source_tag)

        response = self.client.post(reverse("contacts:duplicate-merge", args=["company", source.pk, target.pk]))

        self.assertRedirects(response, target.get_absolute_url())
        source.refresh_from_db()
        target.refresh_from_db()
        self.assertEqual(source.merged_into, target)
        self.assertIsNotNone(source.deleted_at)
        self.assertTrue(Company.objects.filter(pk=source.pk).exists())
        self.assertEqual(target.address, "Vilnius")
        self.assertEqual(set(target.people.values_list("pk", flat=True)), {self.person.pk, other.pk})
        merged_link = PersonCompanyLink.objects.get(person=self.person, company=target)
        self.assertEqual((merged_link.role, merged_link.is_primary), (source_link.role, True))
        self.assertEqual(Activity.objects.get(pk=note.pk).company, target)
        self.assertEqual(list(target.tags.values_list("name", flat=True)), ["Įmonės žyma"])

    def test_duplicate_review_offers_directional_merge_and_rejects_invalid_pair(self):
        self.client.force_login(self.user)
        other = Person.objects.create(first_name="Kita", last_name="Kontaktė")
        EmailAddress.objects.create(person=other, email="ruta@example.lt")
        review = self.client.get(reverse("contacts:duplicate-list"))
        self.assertContains(review, reverse("contacts:duplicate-merge", args=["person", other.pk, self.person.pk]))
        self.assertContains(review, reverse("contacts:duplicate-merge", args=["person", self.person.pk, other.pk]))
        self.assertContains(review, "Palikti šį kontaktą")
        before = Person.objects.count()
        self.assertEqual(
            self.client.post(reverse("contacts:duplicate-merge", args=["person", self.person.pk, self.person.pk])).status_code,
            400,
        )
        self.assertEqual(Person.objects.count(), before)

    def test_card_titles_support_double_click_editing(self):
        self.client.force_login(self.user)
        contact = self.client.get(self.person.get_absolute_url())
        self.assertContains(contact, 'class="detail-title-editor"')
        self.assertContains(contact, 'name="field" value="full_name"')
        response = self.client.post(reverse("contacts:field-edit", args=[self.person.pk]), {
            "field": "full_name", "first_name": "Rasa", "last_name": "Žukė",
        })
        self.assertEqual(response.status_code, 200)
        self.person.refresh_from_db()
        self.assertEqual((self.person.first_name, self.person.last_name), ("Rasa", "Žukė"))
        self.assertIn("Rasa Žukė", response.json()["html"])

        company = self.client.get(self.company.get_absolute_url())
        self.assertContains(company, 'class="detail-title-editor"')
        self.assertContains(company, 'name="field" value="name"')
        response = self.client.post(reverse("contacts:company-field-edit", args=[self.company.pk]), {
            "field": "name", "value": "Naujas pavadinimas", "render_title": "1",
        })
        self.assertEqual(response.status_code, 200)
        self.company.refresh_from_db()
        self.assertEqual(self.company.name, "Naujas pavadinimas")
        self.assertIn("Naujas pavadinimas", response.json()["html"])

    def test_contact_title_edit_checks_combined_name_for_duplicates(self):
        self.client.force_login(self.user)
        other = Person.objects.create(first_name="Kita", last_name="Kontaktė")
        PersonCompanyLink.objects.create(person=other, company=self.company)
        response = self.client.post(reverse("contacts:field-edit", args=[self.person.pk]), {
            "field": "full_name", "first_name": "Kita", "last_name": "Kontaktė",
        })
        self.assertEqual(response.status_code, 409)
        self.person.refresh_from_db()
        self.assertEqual((self.person.first_name, self.person.last_name), ("Rūta", "Žukaitė"))
        response = self.client.post(reverse("contacts:field-edit", args=[self.person.pk]), {
            "field": "full_name", "first_name": "Kita", "last_name": "Kontaktė", "confirm_duplicate": "1",
        })
        self.assertEqual(response.status_code, 200)
        self.person.refresh_from_db()
        self.assertEqual((self.person.first_name, self.person.last_name), ("Kita", "Kontaktė"))

    def test_merge_rolls_back_when_combined_labels_exceed_limit(self):
        self.client.force_login(self.user)
        other = Person.objects.create(first_name="Kita", last_name="Kontaktė")
        EmailAddress.objects.create(person=other, email="ruta@example.lt")
        tags = [Tag.objects.create(name=f"Sujungimo žyma {index}") for index in range(4)]
        self.person.tags.add(*tags[:2])
        other.tags.add(*tags[2:])

        response = self.client.post(
            reverse("contacts:duplicate-merge", args=["person", self.person.pk, other.pk]),
            follow=True,
        )

        self.assertContains(response, "Prieš sujungiant palikite ne daugiau kaip 3 bendras žymas")
        self.person.refresh_from_db()
        other.refresh_from_db()
        self.assertIsNone(self.person.deleted_at)
        self.assertIsNone(self.person.merged_into_id)
        self.assertEqual(other.tags.count(), 2)

    def test_inline_contact_edit_blocks_duplicate_and_allows_explicit_confirmation(self):
        self.client.force_login(self.user)
        other = Person.objects.create(first_name="Kita", last_name="Kontaktė")
        EmailAddress.objects.create(person=other, email="duplicate@example.lt", is_primary=True)
        url = reverse("contacts:field-edit", args=[self.person.pk])

        response = self.client.post(url, {"field": "emails", "value": "duplicate@example.lt"})
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.json()["duplicate"])
        self.assertEqual(response.json()["candidates"][0]["label"], "Kita Kontaktė")
        self.assertIn("email", response.json()["candidates"][0]["reasons"])
        self.assertEqual(list(self.person.emails.values_list("email", flat=True)), ["ruta@example.lt"])

        response = self.client.post(url, {
            "field": "emails", "value": "duplicate@example.lt", "confirm_duplicate": "1",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(self.person.emails.values_list("email", flat=True)), ["duplicate@example.lt"])

    def test_inline_company_edit_blocks_duplicate_identifier_and_allows_confirmation(self):
        self.client.force_login(self.user)
        other = Company.objects.create(name="Kita įmonė", company_code="123456789")
        url = reverse("contacts:company-field-edit", args=[self.company.pk])

        response = self.client.post(url, {"field": "company_code", "value": other.company_code})
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.json()["duplicate"])
        self.company.refresh_from_db()
        self.assertEqual(self.company.company_code, "")

        response = self.client.post(url, {
            "field": "company_code", "value": other.company_code, "confirm_duplicate": "1",
        })
        self.assertEqual(response.status_code, 200)
        self.company.refresh_from_db()
        self.assertEqual(self.company.company_code, other.company_code)

    def test_inline_duplicate_warning_is_translated_in_english(self):
        self.client.force_login(self.user)
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"
        other = Company.objects.create(name="Other company", company_code="123456789")
        response = self.client.post(reverse("contacts:company-field-edit", args=[self.company.pk]), {
            "field": "company_code", "value": other.company_code,
        })
        self.assertEqual(response.status_code, 409)
        self.assertIn("A possible duplicate was found", response.json()["error"])
        self.assertIn("same company code", response.json()["candidates"][0]["reason_labels"])

    def test_inline_edit_does_not_block_fields_that_cannot_create_a_duplicate(self):
        self.client.force_login(self.user)
        other = Person.objects.create(first_name="Kita", last_name="Kontaktė")
        EmailAddress.objects.create(person=other, email="ruta@example.lt", is_primary=True)
        response = self.client.post(reverse("contacts:field-edit", args=[self.person.pk]), {
            "field": "job_title", "value": "Naujos pareigos",
        })
        self.assertEqual(response.status_code, 200)
        self.person.refresh_from_db()
        self.assertEqual(self.person.job_title, "Naujos pareigos")

    def test_inline_duplicate_check_is_idempotent_for_an_unchanged_value(self):
        self.client.force_login(self.user)
        other = Person.objects.create(first_name="Kita", last_name="Kontaktė")
        EmailAddress.objects.create(person=other, email="ruta@example.lt", is_primary=True)
        response = self.client.post(reverse("contacts:field-edit", args=[self.person.pk]), {
            "field": "emails", "value": "ruta@example.lt",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(self.person.emails.values_list("email", flat=True)), ["ruta@example.lt"])

    def test_inline_duplicate_check_respects_disabled_edit_check(self):
        self.client.force_login(self.user)
        other = Company.objects.create(name="Kita įmonė", company_code="123456789")
        DuplicateSettings.objects.update_or_create(pk=1, defaults={
            "enabled": True, "check_on_edit": False, "level": "standard",
        })
        response = self.client.post(reverse("contacts:company-field-edit", args=[self.company.pk]), {
            "field": "company_code", "value": other.company_code,
        })
        self.assertEqual(response.status_code, 200)
        self.company.refresh_from_db()
        self.assertEqual(self.company.company_code, other.company_code)

    def test_duplicate_levels_have_distinct_person_and_company_rules(self):
        same_name = Person.objects.create(first_name=self.person.first_name, last_name=self.person.last_name)
        PersonCompanyLink.objects.create(person=same_name, company=self.company)
        person_data = {
            "first_name": self.person.first_name,
            "last_name": self.person.last_name,
            "email": "",
            "phone": "",
            "companies": [self.company],
        }
        strict_matches = find_person_duplicates(person_data, exclude_pk=self.person.pk, level="strict")
        self.assertEqual(strict_matches[0]["record"], same_name)
        self.assertIn("name", strict_matches[0]["reasons"])
        self.assertEqual(find_person_duplicates(person_data, exclude_pk=self.person.pk, level="standard")[0]["record"], same_name)

        company = Company.objects.create(name="Tas pats pavadinimas")
        company_data = {"name": company.name, "company_code": "", "vat_code": "", "email": "", "phone": "", "url": ""}
        self.assertEqual(find_company_duplicates(company_data, exclude_pk=company.pk, level="standard"), [])
        loose_matches = find_company_duplicates(company_data, exclude_pk=company.pk, level="loose")
        self.assertEqual(loose_matches, [])
        duplicate_name = Company.objects.create(name=company.name)
        self.assertEqual(find_company_duplicates(company_data, exclude_pk=company.pk, level="loose")[0]["record"], duplicate_name)

    def test_strict_review_detects_exact_full_name_without_shared_company(self):
        self.client.force_login(self.user)
        DuplicateSettings.objects.update_or_create(pk=1, defaults={"enabled": True, "level": "strict"})
        other = Person.objects.create(first_name=self.person.first_name, last_name=self.person.last_name)

        response = self.client.get(reverse("contacts:duplicate-list"))

        self.assertContains(response, self.person.get_absolute_url())
        self.assertContains(response, other.get_absolute_url())
        self.assertContains(response, "Tas pats vardas")

    def test_import_does_not_report_exact_record_that_it_updates(self):
        self.client.force_login(self.user)
        content = "Vardas,Pavardė,El. paštai\nRūta,Žukaitė,ruta@example.lt\n".encode()
        response = self.client.post(reverse("contacts:import-export"), {
            "file": SimpleUploadedFile("contacts.csv", content, content_type="text/csv"),
        })
        self.assertContains(response, "Galimi dublikatai: 0")
        self.assertNotContains(response, "Peržiūrėti dublikatus")
        self.assertContains(response, "Atnaujinti: 1")
        self.assertEqual(Person.objects.filter(first_name="Rūta", last_name="Žukaitė").count(), 1)

    def test_import_uses_selected_duplicate_level_and_reports_real_phone_duplicate(self):
        self.client.force_login(self.user)
        content = "Vardas,Pavardė,Telefonai\nKitas,Asmuo,+370 645 21 987\n".encode()
        response = self.client.post(reverse("contacts:import-export"), {
            "file": SimpleUploadedFile("contacts.csv", content, content_type="text/csv"),
        })
        self.assertContains(response, "Galimi dublikatai: 1")
        imported = Person.objects.get(first_name="Kitas", last_name="Asmuo")
        review = self.client.get(reverse("contacts:duplicate-list"))
        self.assertContains(review, self.person.get_absolute_url())
        self.assertContains(review, imported.get_absolute_url())
        self.assertContains(review, "Tas pats telefonas")

        DuplicateSettings.objects.update_or_create(pk=1, defaults={"enabled": True, "check_on_import": False})
        response = self.client.post(reverse("contacts:import-export"), {
            "file": SimpleUploadedFile("contacts.csv", content, content_type="text/csv"),
        })
        self.assertNotContains(response, "Galimi dublikatai:")

    def test_contact_detail_contains_protocol_links(self):
        self.client.force_login(self.user)
        response = self.client.get(self.person.get_absolute_url())
        self.assertContains(response, 'href="tel:+370 645 21 987"')
        self.assertContains(response, 'href="mailto:ruta@example.lt"')

    def test_active_reminder_count_is_global(self):
        self.client.force_login(self.user)
        Reminder.objects.create(person=self.person, text="Perskambinti", due_at=timezone.now() - timedelta(minutes=1), created_by=self.user)
        response = self.client.get(reverse("contacts:list"))
        self.assertEqual(response.context["active_reminder_count"], 1)

    def test_page_size_is_limited_to_50_or_100(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("contacts:list"), {"page_size": "1000"})
        self.assertEqual(response.context["page_size"], 50)

    def test_contact_type_choice_links_person_and_company_flows(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("contacts:create"))
        self.assertContains(response, reverse("contacts:person-create"))
        self.assertContains(response, reverse("contacts:company-create"))

    def test_activity_can_be_added_to_contact(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("contacts:activity-create", args=[self.person.pk]),
            {"activity_type": "call", "text": "Aptartas pasiūlymas."},
        )
        self.assertRedirects(response, self.person.get_absolute_url())
        self.assertEqual(self.person.activities.get().text, "Aptartas pasiūlymas.")

    def test_activity_submission_token_prevents_duplicates_and_stores_attachment(self):
        self.client.force_login(self.user)
        payload = {"activity_type": "note", "text": "Pastaba", "submission_token": "same-request"}
        self.client.post(reverse("contacts:activity-create", args=[self.person.pk]), payload)
        self.client.post(reverse("contacts:activity-create", args=[self.person.pk]), payload)
        self.assertEqual(self.person.activities.count(), 1)
        upload = SimpleUploadedFile("pastaba.txt", b"test", content_type="text/plain")
        response = self.client.post(reverse("contacts:activity-create", args=[self.person.pk]), {"activity_type": "note", "text": "Su failu", "submission_token": "with-file", "attachments": upload})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Attachment.objects.count(), 1)

    def test_activity_can_be_edited_and_uses_safe_limited_formatting(self):
        self.client.force_login(self.user)
        activity = Activity.objects.create(person=self.person, activity_type="note", text="Sena pastaba", created_by=self.user)
        response = self.client.post(
            reverse("contacts:activity-edit", args=[self.person.pk, activity.pk]),
            {"activity_type": "note", "text": "**Svarbu** _šiandien_ https://example.test <script>alert(1)</script>"},
        )
        self.assertRedirects(response, self.person.get_absolute_url())
        response = self.client.get(self.person.get_absolute_url())
        self.assertContains(response, "<strong>Svarbu</strong>", html=True)
        self.assertContains(response, "<em>šiandien</em>", html=True)
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")

    def test_edit_replaces_multiple_contact_values_without_duplicates(self):
        self.client.force_login(self.user)
        payload = {"first_name": "Rūta", "last_name": "Žukaitė", "status": "Aktyvus", "phone": "+370 600 00001\n+370 600 00002", "email": "ruta@example.lt\nruta2@example.lt"}
        self.client.post(reverse("contacts:edit", args=[self.person.pk]), payload)
        self.client.post(reverse("contacts:edit", args=[self.person.pk]), payload)
        self.assertEqual(self.person.phones.count(), 2)
        self.assertEqual(self.person.emails.count(), 2)

    def test_reminder_can_be_completed(self):
        self.client.force_login(self.user)
        reminder = Reminder.objects.create(
            person=self.person,
            text="Perskambinti",
            due_at=timezone.now() - timedelta(minutes=1),
            created_by=self.user,
        )
        response = self.client.post(reverse("contacts:reminder-complete", args=[reminder.pk]))
        self.assertRedirects(response, self.person.get_absolute_url())
        reminder.refresh_from_db()
        self.assertIsNotNone(reminder.completed_at)

    def test_reminder_center_marks_active_reminders_read_and_lists_scheduled(self):
        self.client.force_login(self.user)
        active = Reminder.objects.create(person=self.person, text="Dabar", due_at=timezone.now() - timedelta(minutes=1), created_by=self.user)
        Reminder.objects.create(person=self.person, text="Rytoj", due_at=timezone.now() + timedelta(days=1), created_by=self.user)
        response = self.client.get(reverse("contacts:reminder-list"))
        self.assertContains(response, "Dabar")
        self.assertContains(response, "Rytoj")
        active.refresh_from_db()
        self.assertIsNotNone(active.read_at)

    def test_csv_import_is_repeatable_and_export_is_utf8(self):
        self.client.force_login(self.user)
        content = "Vardas,Pavardė,Įmonė,Telefonai,El. paštai\nJonas,Jonauskas,Nauja įmonė,+37060000000,jonas@example.lt\n"
        for _ in range(2):
            upload = SimpleUploadedFile("kontaktai.csv", content.encode("utf-8"), content_type="text/csv")
            response = self.client.post(reverse("contacts:import-export"), {"file": upload})
            self.assertContains(response, "Importas baigtas")
        self.assertEqual(Person.objects.filter(first_name="Jonas", last_name="Jonauskas").count(), 1)
        response = self.client.get(reverse("contacts:contacts-export"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith("\ufeff".encode("utf-8")))

    def test_import_restores_tags_and_categories_without_duplicates(self):
        self.client.force_login(self.user)
        content = "Vardas,Pavardė,Tagai,Kategorijos\nJonas,Jonauskas,VIP;Partneris,Klientas;Svarbus\n"
        for _ in range(2):
            upload = SimpleUploadedFile("kontaktai.csv", content.encode("utf-8"), content_type="text/csv")
            response = self.client.post(reverse("contacts:import-export"), {"file": upload})
            self.assertContains(response, "Importas baigtas")
        person = Person.objects.get(first_name="Jonas", last_name="Jonauskas")
        self.assertEqual(list(person.tags.values_list("name", flat=True)), ["Partneris", "VIP"])
        self.assertEqual(list(person.categories.values_list("name", flat=True)), ["Klientas", "Svarbus"])


    def test_selected_contacts_export_only_selected_rows(self):
        self.client.force_login(self.user)
        other = Person.objects.create(first_name="Kitas", last_name="Kontaktas")
        response = self.client.post(reverse("contacts:contacts-export"), {"selected": [self.person.pk]})
        self.assertContains(response, "Rūta")
        self.assertNotContains(response, str(other))

    def test_selected_companies_can_be_exported_archived_and_restored(self):
        self.client.force_login(self.user)
        other = Company.objects.create(name="Kita įmonė")

        response = self.client.get(reverse("contacts:company-list"))
        self.assertContains(response, 'id="company-bulk-form"')
        self.assertContains(response, "company-row-select")

        response = self.client.post(reverse("contacts:companies-export"), {"selected": [self.company.pk]})
        self.assertContains(response, self.company.name)
        self.assertNotContains(response, other.name)

        response = self.client.post(reverse("contacts:company-bulk-action"), {"selected": [self.company.pk], "action": "archive"})
        self.assertRedirects(response, reverse("contacts:company-list"))
        self.company.refresh_from_db()
        self.assertIsNotNone(self.company.deleted_at)

        response = self.client.post(reverse("contacts:company-restore", args=[self.company.pk]))
        self.assertRedirects(response, reverse("contacts:archive-list"))
        self.company.refresh_from_db()
        self.assertIsNone(self.company.deleted_at)

    def test_archive_actions_are_available_in_cards_not_contact_row_menu(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("contacts:list"))
        self.assertNotContains(response, 'action="/contacts/%s/archive/"' % self.person.pk)
        response = self.client.get(self.person.get_absolute_url())
        self.assertContains(response, reverse("contacts:archive", args=[self.person.pk]))
        response = self.client.get(self.company.get_absolute_url())
        self.assertContains(response, reverse("contacts:company-archive", args=[self.company.pk]))

    def test_xlsx_import_creates_contact(self):
        from openpyxl import Workbook

        self.client.force_login(self.user)
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Vardas", "Pavardė", "El. paštai"])
        sheet.append(["Ona", "Onaitė", "ona@example.lt"])
        output = BytesIO()
        workbook.save(output)
        upload = SimpleUploadedFile("kontaktai.xlsx", output.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response = self.client.post(reverse("contacts:import-export"), {"file": upload})
        self.assertContains(response, "Importas baigtas")
        self.assertTrue(Person.objects.filter(first_name="Ona", last_name="Onaitė").exists())

    def test_company_detail_lists_linked_person(self):
        self.client.force_login(self.user)
        response = self.client.get(self.company.get_absolute_url())
        self.assertContains(response, "Rūta Žukaitė")

    def test_company_history_includes_company_and_linked_person_entries(self):
        self.client.force_login(self.user)
        Activity.objects.create(company=self.company, text="Įmonės pastaba", created_by=self.user)
        Activity.objects.create(person=self.person, text="Kontakto pastaba", created_by=self.user)
        response = self.client.get(self.company.get_absolute_url())
        self.assertContains(response, "Įmonės ir kontaktų įrašų istorija")
        self.assertContains(response, "Įmonės pastaba")
        self.assertContains(response, "Kontakto pastaba")

    def test_company_can_be_edited(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("contacts:company-edit", args=[self.company.pk]))
        self.assertContains(response, self.company.get_absolute_url())
        response = self.client.post(
            reverse("contacts:company-edit", args=[self.company.pk]),
            {"name": "Atnaujinta įmonė", "company_code": "123", "email": "biuras@example.test"},
        )
        self.assertRedirects(response, self.company.get_absolute_url())
        self.company.refresh_from_db()
        self.assertEqual(self.company.name, "Atnaujinta įmonė")

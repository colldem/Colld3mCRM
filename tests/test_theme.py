from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.translation import override
from contacts.models import Tag, Person, Company


class ThemeTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user(username="theme-qa"))

    def test_shared_theme_and_toolbar(self):
        for route in ["contacts:list", "contacts:company-list"]:
            response = self.client.get(reverse(route))
            self.assertContains(response, "vendor/adminlte/adminlte.min.css")
            self.assertContains(response, 'class="app-wrapper"')
            self.assertContains(response, 'class="record-toolbar"')
            self.assertContains(response, 'class="record-actions"')
            self.assertContains(response, "Mano filtrai")
            self.assertNotContains(response, "Mano sąrašai")
            html = response.content.decode()
            self.assertLess(html.index('class="record-actions"'), html.index('id="' + ('company-' if 'company' in route else '') + 'bulk-form"'))

    def test_english_filter_label(self):
        self.client.cookies["django_language"] = "en"
        for route in ["contacts:list", "contacts:company-list"]:
            self.assertContains(self.client.get(reverse(route)), "My filters")

    def test_tag_colors_stable_and_shared(self):
        tags = [Tag.objects.create(name=f"Color {n}") for n in range(8)]
        self.assertEqual(len({t.color_class for t in tags}), 8)
        tag = tags[0]
        original = tag.color_class
        tag.name = "Renamed"
        tag.save()
        tag.refresh_from_db()
        self.assertEqual(tag.color_class, original)
        person = Person.objects.create(first_name="Theme", last_name="QA")
        company = Company.objects.create(name="Theme QA")
        person.tags.add(tag)
        company.tags.add(tag)
        for url in [reverse("contacts:list"), reverse("contacts:company-list"), person.get_absolute_url(), company.get_absolute_url()]:
            response = self.client.get(url)
            self.assertContains(response, f'class="crm-label {original}"')
            self.assertContains(response, f'data-color-class="{original}"')

    def test_theme_on_other_screens(self):
        for route in ["contacts:settings", "contacts:import-export", "contacts:archive-list", "contacts:reminder-list", "contacts:create"]:
            response = self.client.get(reverse(route))
            self.assertContains(response, "vendor/adminlte/adminlte.min.css")
            self.assertContains(response, "css/theme.css")

    def test_settings_uses_same_stable_tag_colors(self):
        tag = Tag.objects.create(name="Settings color")
        response = self.client.get(reverse("contacts:settings"))
        self.assertContains(response, f'class="crm-label {tag.color_class}"')

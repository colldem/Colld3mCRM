from django.contrib.auth import get_user_model
from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from contacts.models import Tag, Person, Company


class ThemeTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user(username="theme-qa", is_superuser=True))

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
        response = self.client.get(reverse("contacts:settings-tags"))
        self.assertContains(response, f'class="crm-label {tag.color_class}"')

    def test_crm_timeline_disables_conflicting_adminlte_line(self):
        css = (settings.BASE_DIR / "static" / "css" / "app.css").read_text()
        self.assertIn(".timeline::before{display:none}", css)

    def test_native_form_controls_are_normalised_across_browsers(self):
        css = (settings.BASE_DIR / "static" / "css" / "app.css").read_text()
        # A shared chevron and appearance reset so <select> looks the same in Safari/Firefox/Chrome.
        self.assertIn("select{-webkit-appearance:none;-moz-appearance:none;appearance:none;", css)
        self.assertIn("background-image:url(\"data:image/svg+xml", css)
        # Checkboxes/radios follow the CRM navy instead of each browser's system accent.
        self.assertIn("accent-color:var(--navy-950)", css)

    def test_font_sizes_follow_one_type_scale(self):
        app_css = (settings.BASE_DIR / "static" / "css" / "app.css").read_text()
        # The 8-step scale is declared once as tokens.
        for token in ("--fs-2xs:11px", "--fs-xs:12px", "--fs-sm:13px", "--fs-base:14px",
                      "--fs-md:16px", "--fs-lg:20px", "--fs-xl:24px", "--fs-2xl:28px"):
            self.assertIn(token, app_css)

    def test_stylesheets_have_no_malformed_declarations(self):
        # Guards against bulk find/replace eating a ";" (e.g. "transparent padding:4px").
        for name in ("app.css", "theme.css"):
            css = (settings.BASE_DIR / "static" / "css" / name).read_text()
            self.assertEqual(css.count("{"), css.count("}"), name)
            self.assertNotRegex(css, r"[a-z0-9%)]\s+(padding|margin|gap|border-radius|min-height|width|height):")

    def test_radius_and_control_heights_use_one_scale(self):
        app_css = (settings.BASE_DIR / "static" / "css" / "app.css").read_text()
        theme_css = (settings.BASE_DIR / "static" / "css" / "theme.css").read_text()
        for token in ("--radius:6px", "--radius-sm:4px", "--radius-lg:8px", "--radius-pill:999px",
                      "--control-h:40px", "--control-h-sm:32px", "--control-h-lg:48px"):
            self.assertIn(token, app_css)
        import re
        # Corner radii collapse to 4 / 6 / 8 / pill; interactive controls to 32 / 40 / 48.
        for sheet in (app_css, theme_css):
            self.assertEqual(set(re.findall(r"border-radius:(5|7|10|11|12|16|18|20)px", sheet)), set())
            self.assertEqual(set(re.findall(r"min-height:(26|28|30|34|36|38|42|46)px", sheet)), set())
        # No text sits between the scale steps any more (icon glyphs at 18/19/25px stay).
        import re
        offenders = set()
        for sheet in (app_css, theme_css):
            offenders |= set(re.findall(r"font-size:(10|15|17|21|23|27|30|32)px", sheet))
            offenders |= set(re.findall(r"font-size:[0-9.]+em", sheet))
        self.assertEqual(offenders, set())

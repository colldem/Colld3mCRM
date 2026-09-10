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
        for route in ["contacts:settings", "contacts:import-export", "contacts:archive-list", "contacts:calendar", "contacts:create"]:
            response = self.client.get(reverse(route))
            self.assertContains(response, "vendor/adminlte/adminlte.min.css")
            self.assertContains(response, "css/theme.css")

    def test_settings_uses_same_stable_tag_colors(self):
        tag = Tag.objects.create(name="Settings color")
        response = self.client.get(reverse("contacts:settings-tags"))
        self.assertContains(response, f'class="crm-label {tag.color_class}"')

    def test_filter_drawer_slides_in_and_back_out(self):
        """A <details> cannot transition out of display:none, so closing has to
        play an animation first and drop `open` when it ends — with a timeout in
        case the tab never paints."""
        theme_css = (settings.BASE_DIR / "static" / "css" / "theme.css").read_text()
        js = (settings.BASE_DIR / "static" / "js" / "list-editing.js").read_text()
        self.assertIn("@keyframes drawer-in{", theme_css)
        self.assertIn("@keyframes drawer-out{", theme_css)
        self.assertIn(".filter-drawer.is-closing .filter-panel{animation:drawer-out", theme_css)
        # Motion stays behind the reduced-motion guard.
        self.assertIn("@media(prefers-reduced-motion:no-preference){\n .filter-drawer[open]", theme_css)
        self.assertIn("prefers-reduced-motion: reduce", js)
        for path in ("closeDrawer", "is-closing", "animationend", "setTimeout(finish"):
            with self.subTest(fragment=path):
                self.assertIn(path, js)

    def test_each_selector_is_defined_once_per_stylesheet(self):
        """The sheets had grown by appending overrides at the end, so .nav-item,
        .bulk-bar and .chart-legend were each declared two or three times and the
        real value could only be found by reading to the bottom of the file."""
        import re

        for name in ("app.css", "theme.css"):
            css = (settings.BASE_DIR / "static" / "css" / name).read_text()
            css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
            seen, duplicated, depth, buffer = set(), [], 0, ""
            for char in css:
                if char == "{":
                    if depth == 0:
                        selector = re.sub(r"\s+", " ", buffer).strip()
                        if selector and not selector.startswith("@"):
                            if selector in seen:
                                duplicated.append(selector)
                            seen.add(selector)
                    depth += 1
                    buffer = ""
                elif char == "}":
                    depth -= 1
                    buffer = ""
                elif depth == 0:
                    buffer += char
            with self.subTest(sheet=name):
                self.assertEqual(duplicated, [], f"{name} declares these twice: {duplicated}")

    def test_file_pickers_wear_the_crm_button_not_the_browser_one(self):
        """The browser's own file control was the one place the visual language
        broke, and its "no file chosen" text ignored the app's language."""
        theme_css = (settings.BASE_DIR / "static" / "css" / "theme.css").read_text()
        forms_js = (settings.BASE_DIR / "static" / "js" / "forms.js").read_text()
        self.assertIn(".file-field{", theme_css)
        self.assertIn(".file-btn{", theme_css)
        # The native input stays in the form — it is only hidden, never replaced.
        self.assertIn(".file-field input[type=file]{position:absolute", theme_css)
        self.assertIn("input[type=file]", forms_js)
        self.assertIn("field.append(input,", forms_js)

    def test_file_picker_wording_is_translated_for_javascript(self):
        """forms.js builds the label itself, so the wording has to live in the
        JavaScript catalogue — not only in django.po."""
        from django.urls import reverse

        po = (settings.BASE_DIR / "locale" / "en" / "LC_MESSAGES" / "djangojs.po").read_text()
        for source, english in (("Pasirinkti failą", "Choose a file"),
                                ("Pasirinkti failus", "Choose files"),
                                ("Failas nepasirinktas", "No file chosen"),
                                ("Failai nepasirinkti", "No files chosen")):
            with self.subTest(word=source):
                self.assertIn(f'msgid "{source}"\nmsgstr "{english}"', po)
        self.client.post(reverse("set_language"), {"language": "en", "next": "/contacts/"})
        catalog = self.client.get(reverse("javascript-catalog")).content.decode()
        self.assertIn("Choose a file", catalog)

    def test_list_rows_stay_dense_enough_to_scan(self):
        """Rows were 73px: a two-line name cell plus 15px padding and a 40px
        chip editor. Scannable lists sit near 48-52px, so the padding, the
        subtitle and the chip editor all have to stay compact."""
        app_css = (settings.BASE_DIR / "static" / "css" / "app.css").read_text()
        theme_css = (settings.BASE_DIR / "static" / "css" / "theme.css").read_text()
        self.assertIn("th,td{padding:10px 12px", app_css)
        self.assertIn("table td{padding:10px 12px}", theme_css)
        # Name and job title share one line.
        self.assertIn(".row-link{display:flex", app_css)
        self.assertIn(".row-link small{display:inline", app_css)
        # The tag/category editor must not set a 40px floor under every row.
        self.assertIn(".table-wrap .choice-trigger{min-height:0", theme_css)

    def test_tags_are_called_zymos_everywhere_in_the_interface(self):
        """One word for one thing — the list column said "Tagai", the rest of
        the product says "Žymos"."""
        for path in (settings.BASE_DIR / "templates" / "contacts" / "list.html",
                     settings.BASE_DIR / "contacts" / "forms.py"):
            with self.subTest(path=path.name):
                self.assertNotIn("Tagai", path.read_text(encoding="utf-8"))

    def test_one_card_system_across_dashboard_analytics_and_settings(self):
        """`.dash-card` is the only card shell; the old `.panel` / AdminLTE
        `info-box` markup is gone, and no card title falls back to AdminLTE's
        32px <h2> — which was larger than the page's own <h1>."""
        templates = settings.BASE_DIR / "templates"
        for path in templates.rglob("*.html"):
            markup = path.read_text(encoding="utf-8")
            with self.subTest(template=path.name):
                self.assertNotIn('class="panel', markup)
                self.assertNotIn("crm-info-box", markup)
                self.assertNotIn('class="row g-3"', markup)
        theme_css = (settings.BASE_DIR / "static" / "css" / "theme.css").read_text()
        app_css = (settings.BASE_DIR / "static" / "css" / "app.css").read_text()
        self.assertNotIn(".panel{", theme_css)
        # Every card title is the same step of the type scale.
        self.assertIn(".dash-card-head h2{margin:0;font-size:var(--fs-md)", theme_css)
        for rule in (".import-grid h2{", ".settings-card h2{"):
            self.assertIn(rule + "margin:0 0 8px;font-size:var(--fs-md)", app_css)

    def test_analytics_detail_pages_use_the_dashboard_cards(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse

        user = get_user_model().objects.create_user("kortelės", password="very-secure-password",
                                                    is_superuser=True)
        self.client.force_login(user)
        for name in ("analytics-care", "analytics-communication", "analytics-reminders",
                     "analytics-growth", "analytics-system", "analytics-overview"):
            with self.subTest(page=name):
                response = self.client.get(reverse(f"contacts:{name}"))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "dash-card")

    def test_activity_feed_replaced_the_adminlte_timeline(self):
        """The record page draws its own feed, so no AdminLTE `.timeline` is left
        to fight with — and nothing may reintroduce that class by accident."""
        app_css = (settings.BASE_DIR / "static" / "css" / "app.css").read_text()
        theme_css = (settings.BASE_DIR / "static" / "css" / "theme.css").read_text()
        self.assertIn(".feed-entry{display:grid", theme_css)
        for sheet in (app_css, theme_css):
            self.assertNotIn(".timeline", sheet)

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


class DeploymentReadinessTests(TestCase):
    """The app has to run unchanged on one Docker host and on Kubernetes."""

    def test_media_backend_switches_between_disk_and_object_storage(self):
        import importlib
        import os
        from unittest import mock

        from django.conf import settings as live

        # The default is the local disk, which is what a Compose install wants.
        self.assertEqual(live.STORAGES["default"]["BACKEND"],
                         "django.core.files.storage.FileSystemStorage")

        env = {"CRM_MEDIA_BACKEND": "s3", "CRM_S3_BUCKET": "crm-media",
               "CRM_S3_ENDPOINT": "https://minio.example.com",
               "CRM_S3_ACCESS_KEY": "key", "CRM_S3_SECRET_KEY": "secret",
               "CRM_S3_ADDRESSING": "path"}
        with mock.patch.dict(os.environ, env):
            module = importlib.reload(importlib.import_module("config.settings"))
        try:
            storage = module.STORAGES["default"]
            self.assertEqual(storage["BACKEND"], "storages.backends.s3.S3Storage")
            self.assertEqual(storage["OPTIONS"]["bucket_name"], "crm-media")
            self.assertEqual(storage["OPTIONS"]["endpoint_url"], "https://minio.example.com")
            self.assertEqual(storage["OPTIONS"]["addressing_style"], "path")
            # Uploads stay private — the CRM checks who may see the record first.
            self.assertIsNone(storage["OPTIONS"]["default_acl"])
            self.assertTrue(storage["OPTIONS"]["querystring_auth"])
        finally:
            importlib.reload(importlib.import_module("config.settings"))

    def test_startup_steps_are_switchable_for_kubernetes(self):
        """Several replicas must not race each other into `migrate`."""
        entrypoint = (settings.BASE_DIR / "scripts" / "entrypoint.sh").read_text()
        dockerfile = (settings.BASE_DIR / "Dockerfile").read_text()
        self.assertIn('if [ "${CRM_RUN_MIGRATIONS:-1}" = "1" ]', entrypoint)
        self.assertIn('if [ "${CRM_COLLECTSTATIC:-1}" = "1" ]', entrypoint)
        # The static files ship inside the image, so a pod starts without them —
        # and the build must not run in debug, or WhiteNoise writes no manifest
        # and a non-debug runtime cannot resolve a single hashed asset.
        self.assertIn("manage.py collectstatic --noinput", dockerfile)
        self.assertIn("DJANGO_DEBUG=false", dockerfile)
        self.assertIn("test -f /app/staticfiles/staticfiles.json", dockerfile)

    def test_health_endpoints_answer_without_a_session(self):
        for path, expected in (("/health/live", "live"), ("/health/ready", "ready")):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(expected, response.content.decode())

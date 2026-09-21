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

    def test_toolbar_keeps_one_row_and_bulk_actions_behind_one_control(self):
        """The selection bar used to live inside .record-actions, so as soon as
        it appeared it pushed the filter buttons out of line with "+ Pridėti" —
        and it laid seven controls across the row."""
        for route in ("contacts:list", "contacts:company-list"):
            with self.subTest(route=route):
                html = self.client.get(reverse(route)).content.decode()
                start = html.index('class="record-actions"')
                actions = html[start:html.index("</div>", start)]
                # Row one holds the primary action and nothing else; the selection
                # bar is a row of its own, after the toolbar closes.
                self.assertIn('class="btn primary"', actions)
                self.assertNotIn("bulk-form", actions)
                self.assertNotIn("bulk-bar", actions)
                self.assertLess(html.index('class="list-actions'), html.index("bulk-form"))
                # One trigger, not a row of selects.
                self.assertIn("Masiniai veiksmai", html)
                self.assertIn('class="bulk-panel"', html)
                bar = html[html.index('class="bulk-bar"'):html.index('class="bulk-panel"')]
                self.assertNotIn("<select", bar)

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

    def test_base_stylesheet_stays_readable(self):
        """app.css had grown to 40 lines, one of them 5,000 characters wide, with
        overrides appended at the bottom. It is grouped by component now — keep
        it that way: one rule per line, and a home for every rule."""
        css = (settings.BASE_DIR / "static" / "css" / "app.css").read_text()
        lines = css.split("\n")
        longest = max(len(line) for line in lines)
        self.assertLess(longest, 700, "a rule ran onto a shared line — one rule per line")
        for section in ("Design tokens and element defaults",
                        "Application shell: sidebar, top bar, content",
                        "Buttons, chips and small controls",
                        "Lists: tables, row menus, filter drawers, bulk actions",
                        "Forms", "Reminders", "Responsive"):
            with self.subTest(section=section):
                self.assertIn(f"/* --- {section}", css)
        # The chevron rule must keep sitting after the shared input rule it narrows.
        self.assertLess(css.index("input,select,textarea{"), css.index("select{-webkit-appearance"))

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

    def test_every_setting_the_app_reads_is_written_down(self):
        """A knob nobody documented is a knob nobody can turn.

        Both files earn their place: `.env.example` is what an installer copies,
        DEPLOYMENT.md is what they read when the default is wrong for them.
        """
        import re

        settings_py = (settings.BASE_DIR / "config" / "settings.py").read_text()
        entrypoint = (settings.BASE_DIR / "scripts" / "entrypoint.sh").read_text()
        used = set(re.findall(r'os\.environ(?:\.get)?[\(\[]\s*["\'](CRM_[A-Z0-9_]+)', settings_py))
        used |= set(re.findall(r"\$\{(CRM_[A-Z0-9_]+)", entrypoint))
        self.assertGreater(len(used), 10, "the scan found almost nothing — it has stopped working")

        example = (settings.BASE_DIR / ".env.example").read_text()
        deployment = (settings.BASE_DIR / "docs" / "DEPLOYMENT.md").read_text()
        for name in sorted(used):
            with self.subTest(variable=name):
                self.assertIn(name, example, f"{name} is missing from .env.example")
                self.assertIn(name, deployment, f"{name} is missing from docs/DEPLOYMENT.md")


class HelmChartTests(TestCase):
    """The chart is what makes several replicas safe; these are the parts that
    must not quietly regress. CI additionally runs `helm lint` and `helm template`."""

    @property
    def chart(self):
        return settings.BASE_DIR / "deploy" / "helm" / "crm"

    def test_chart_ships_every_object_the_deployment_needs(self):
        for name in ("Chart.yaml", "values.yaml", "templates/_helpers.tpl",
                     "templates/deployment.yaml", "templates/service.yaml",
                     "templates/ingress.yaml", "templates/configmap.yaml",
                     "templates/secret.yaml", "templates/job-migrate.yaml",
                     "templates/cronjobs.yaml", "templates/NOTES.txt"):
            with self.subTest(file=name):
                self.assertTrue((self.chart / name).exists(), f"{name} is missing")

    def test_chart_version_follows_the_release(self):
        version = (settings.BASE_DIR / "VERSION").read_text().strip()
        chart = (self.chart / "Chart.yaml").read_text()
        self.assertIn(f'appVersion: "{version}"', chart)

    def test_web_pods_never_migrate_and_never_collect(self):
        """Several replicas booting together would race each other."""
        helpers = (self.chart / "templates" / "_helpers.tpl").read_text()
        self.assertIn('- name: CRM_RUN_MIGRATIONS\n  value: "0"', helpers)
        self.assertIn('- name: CRM_COLLECTSTATIC\n  value: "0"', helpers)

    def test_migrations_run_once_per_release_before_the_new_pods(self):
        job = (self.chart / "templates" / "job-migrate.yaml").read_text()
        self.assertIn("helm.sh/hook: pre-install,pre-upgrade", job)
        self.assertIn('command: ["python", "manage.py", "migrate", "--noinput"]', job)

    def test_background_commands_cannot_overlap_themselves(self):
        values = (self.chart / "values.yaml").read_text()
        cronjobs = (self.chart / "templates" / "cronjobs.yaml").read_text()
        self.assertIn("concurrencyPolicy: Forbid", values)
        self.assertIn("concurrencyPolicy: {{ $.Values.worker.concurrencyPolicy }}", cronjobs)
        # Every command the crm-worker container used to loop through.
        for command in ("send_notifications", "fetch_mail", "deliver_webhooks",
                        "run_automations", "extend_recurrences"):
            with self.subTest(command=command):
                self.assertIn(f"command: {command}", values)

    def test_pods_are_hardened_and_only_web_pods_receive_traffic(self):
        values = (self.chart / "values.yaml").read_text()
        templates = self.chart / "templates"
        self.assertIn("readOnlyRootFilesystem: true", values)
        self.assertIn("type: RuntimeDefault", values)
        self.assertIn("automountServiceAccountToken: false", values)
        for name in ("deployment.yaml", "cronjobs.yaml", "job-migrate.yaml"):
            with self.subTest(template=name):
                text = (templates / name).read_text()
                self.assertIn("mountPath: /tmp", text)
                self.assertIn("automountServiceAccountToken:", text)
                self.assertIn("app.kubernetes.io/component:", text)
        self.assertIn("app.kubernetes.io/component: web", (templates / "service.yaml").read_text())
        self.assertIn("kind: PodDisruptionBudget", (templates / "pdb.yaml").read_text())
        self.assertIn("kind: NetworkPolicy", (templates / "networkpolicy.yaml").read_text())

    def test_probes_use_the_endpoints_the_app_actually_serves(self):
        deployment = (self.chart / "templates" / "deployment.yaml").read_text()
        for path in ("/health/live", "/health/ready"):
            with self.subTest(path=path):
                self.assertIn(path, deployment)
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_the_secrets_key_survives_upgrades(self):
        """Stored SMTP/IMAP/Entra passwords are encrypted with it; a regenerated
        key would make every one of them unreadable."""
        secret = (self.chart / "templates" / "secret.yaml").read_text()
        self.assertIn("helm.sh/resource-policy: keep", secret)
        self.assertIn("CRM_SECRETS_KEY", secret)

    def test_publishing_the_image_checks_the_tag_against_version(self):
        workflow = (settings.BASE_DIR / ".github" / "workflows" / "publish-image.yml").read_text()
        self.assertIn("ghcr.io/${{ github.repository_owner }}/crm-web", workflow)
        self.assertIn("Check the tag matches VERSION", workflow)
        self.assertIn("github.repository == 'colldem/Colld3mCRM'", workflow)


class ObservabilityTests(TestCase):
    """JSON logs with request ids, and security events mirrored from the audit trail."""

    def test_every_response_carries_a_request_id_and_keeps_a_sane_incoming_one(self):
        response = self.client.get("/health/live")
        self.assertRegex(response["X-Request-ID"], r"^[0-9a-f]{32}$")
        response = self.client.get("/health/live", HTTP_X_REQUEST_ID="lb-abc123456")
        self.assertEqual(response["X-Request-ID"], "lb-abc123456")
        response = self.client.get("/health/live", HTTP_X_REQUEST_ID="bad id <script>")
        self.assertRegex(response["X-Request-ID"], r"^[0-9a-f]{32}$")

    def test_django_request_warnings_carry_the_request_id(self):
        import logging
        from contacts.observability import RequestIdFilter

        seen = []

        class Capture(logging.Handler):  # filters run at emit time, as on the real stdout handler
            def emit(self, record):
                seen.append(record.request_id)

        handler = Capture()
        handler.addFilter(RequestIdFilter())
        logger = logging.getLogger("django.request")
        logger.addHandler(handler)
        try:
            self.client.get("/definitely-missing/", HTTP_X_REQUEST_ID="trace-404404404")
        finally:
            logger.removeHandler(handler)
        self.assertIn("trace-404404404", seen)

    def test_json_formatter_writes_one_parseable_line_with_structured_fields(self):
        import json
        import logging
        from contacts.observability import JsonFormatter, RequestIdFilter, _request_id
        record = logging.LogRecord("crm.security", logging.WARNING, __file__, 1, "audit.login_failed", None, None)
        record.event, record.ip, record.secret_name = "audit.login_failed", "10.0.0.1", "not exported"
        token = _request_id.set("req-12345678")
        try:
            RequestIdFilter().filter(record)
        finally:
            _request_id.reset(token)
        line = JsonFormatter().format(record)
        self.assertNotIn("\n", line)
        payload = json.loads(line)
        self.assertEqual(payload["level"], "WARNING")
        self.assertEqual(payload["request_id"], "req-12345678")
        self.assertEqual(payload["event"], "audit.login_failed")
        self.assertEqual(payload["ip"], "10.0.0.1")
        self.assertNotIn("secret_name", payload)

    def test_audit_rows_are_mirrored_to_the_security_log_without_personal_data(self):
        from contacts.models import Person
        user = get_user_model().objects.create_user("auditor", password="very-secure-password")
        person = Person.objects.create(first_name="Slaptas", last_name="Vardas", created_by=user, owner=user)
        from contacts.audit import log as audit_log
        from contacts.models import AuditLog
        with self.assertLogs("crm.security", level="INFO") as captured:
            entry = audit_log(AuditLog.UPDATE, actor=user, target=person, field="first_name", old="Slaptas", new="Kitas")
        record = captured.records[0]
        self.assertEqual(record.event, "audit.update")
        self.assertEqual(record.target_id, str(person.pk))
        self.assertNotIn("Slaptas", " ".join(captured.output))
        self.assertNotIn("Kitas", " ".join(captured.output))
        self.assertEqual(entry.target_label, "Slaptas Vardas")

    def test_request_id_is_stored_with_audit_rows(self):
        from contacts.models import AuditLog
        get_user_model().objects.create_user("idtest", password="very-secure-password")
        response = self.client.post(reverse("login"), {"username": "idtest", "password": "wrong-password-123"},
                                    HTTP_X_REQUEST_ID="trace-000111222")
        self.assertEqual(response["X-Request-ID"], "trace-000111222")
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.LOGIN_FAILED, detail__request_id="trace-000111222").exists())

    def test_lockout_is_audited_and_logged_as_a_warning(self):
        from contacts.models import AuditLog
        get_user_model().objects.create_user("locked", password="very-secure-password")
        with self.assertLogs("crm.security", level="WARNING") as captured:
            for _ in range(6):
                self.client.post(reverse("login"), {"username": "locked", "password": "wrong-password-123"})
        self.assertTrue(AuditLog.objects.filter(detail__reason="locked_out").exists())
        self.assertTrue(any(getattr(r, "reason", "") == "locked_out" for r in captured.records))

    def test_production_defaults_to_json_logs_and_gunicorn_json_access_log(self):
        self.assertIn("contacts.observability.RequestIdMiddleware", settings.MIDDLEWARE[0])
        self.assertIn('"logger":"gunicorn.access"', (settings.BASE_DIR / "scripts" / "entrypoint.sh").read_text())


class ContentSecurityPolicyTests(TestCase):
    """Strict script policy: same origin or the request's nonce, never inline handlers."""

    def setUp(self):
        from contacts.models import Company, Person
        self.user = get_user_model().objects.create_superuser("csp", email="c@local", password="very-secure-password")
        self.person = Person.objects.create(first_name="Jonas", last_name="Jonaitis", created_by=self.user, owner=self.user)
        self.company = Company.objects.create(name="UAB CSP", created_by=self.user, owner=self.user)

    def nonce_of(self, response):
        import re
        policy = response["Content-Security-Policy"]
        self.assertIn("object-src 'none'", policy)
        self.assertIn("frame-ancestors 'none'", policy)
        self.assertNotIn("'unsafe-inline'", policy.split("script-src", 1)[1].split(";", 1)[0])
        return re.search(r"'nonce-([^']+)'", policy).group(1)

    def test_every_inline_script_carries_the_response_nonce(self):
        import re
        self.nonce_of(self.client.get(reverse("login")))  # the login page, signed out
        self.client.force_login(self.user)
        pages = [reverse("contacts:list"), reverse("contacts:company-list"), reverse("contacts:home"),
                 reverse("contacts:detail", args=[self.person.pk]), reverse("contacts:calendar"),
                 reverse("contacts:archive-list"), reverse("contacts:settings-menu"),
                 reverse("contacts:settings-custom-fields"), reverse("contacts:settings")]
        for url in pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                nonce = self.nonce_of(response)
                html = response.content.decode()
                for tag in re.findall(r"<script\b[^>]*>", html):
                    if "src=" in tag or 'type="application/json"' in tag:
                        continue
                    self.assertIn('nonce="%s"' % nonce, tag)

    def test_nonce_changes_per_response(self):
        self.assertNotEqual(self.nonce_of(self.client.get(reverse("login"))), self.nonce_of(self.client.get(reverse("login"))))

    def test_templates_have_no_inline_event_handlers_or_javascript_urls(self):
        import re
        for path in (settings.BASE_DIR / "templates").rglob("*.html"):
            text = path.read_text()
            with self.subTest(template=str(path.relative_to(settings.BASE_DIR))):
                self.assertIsNone(re.search(r"\son[a-z]+\s*=", text))
                self.assertNotIn("javascript:", text)

    def test_declarative_behaviours_replace_the_handlers(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("contacts:company-list"))
        self.assertContains(response, 'data-row-href="%s"' % self.company.get_absolute_url())
        self.assertContains(response, "js/behaviors.js")
        self.assertContains(self.client.get(reverse("login")), "js/behaviors.js")

    def test_permissions_policy_and_report_only_switch(self):
        response = self.client.get(reverse("login"))
        self.assertIn("camera=()", response["Permissions-Policy"])
        with self.settings(CRM_CSP_REPORT_ONLY=True):
            response = self.client.get(reverse("login"))
        self.assertIn("Content-Security-Policy-Report-Only", response)
        self.assertNotIn("Content-Security-Policy", response)


class BackupAndRuntimeLayoutTests(TestCase):
    """Guards for the backup service, the restore script and the upload directory."""

    root = settings.BASE_DIR

    def test_app_runs_as_a_fixed_uid_that_crm_init_grants_the_upload_directory(self):
        dockerfile = (self.root / "Dockerfile").read_text()
        compose = (self.root / "compose.yaml").read_text()
        self.assertIn("--uid 10001", dockerfile)
        self.assertIn("chown -R 10001:10001 /media", compose)
        self.assertEqual(compose.count("crm-init: {condition: service_completed_successfully}"), 2)
        self.assertIn("fsGroup: 10001", (self.root / "deploy/helm/crm/values.yaml").read_text())
        self.assertIn("is not writable by uid", (self.root / "scripts/entrypoint.sh").read_text())

    def test_backups_are_encrypted_checksummed_monitored_and_restorable(self):
        backup = (self.root / "scripts/backup.sh").read_text()
        restore = (self.root / "scripts/restore.sh").read_text()
        compose = (self.root / "compose.yaml").read_text()
        for needle in ("age ", "BACKUP_REQUIRE_ENCRYPTION", "sha256sum", "last-success", "rclone copy", "set -euo pipefail"):
            with self.subTest(backup=needle):
                self.assertIn(needle, backup)
        for needle in ("sha256sum -c", "--single-transaction", "--exit-on-error", "-d -i /identity", "health/ready"):
            with self.subTest(restore=needle):
                self.assertIn(needle, restore)
        self.assertIn("dockerfile: deploy/backup/Dockerfile", compose)
        self.assertIn("/backups/last-success", compose)
        self.assertIn("backup-restore:", (self.root / ".github/workflows/ci.yml").read_text())


class MetricsTests(TestCase):
    """/metrics: token-protected Prometheus text with health, security and job heartbeats."""

    def scrape(self, token="metrics-secret-123"):
        return self.client.get("/metrics", HTTP_AUTHORIZATION="Bearer " + token)

    def test_endpoint_is_off_without_a_token_and_refuses_a_wrong_one(self):
        self.assertEqual(self.client.get("/metrics").status_code, 404)
        with self.settings(CRM_METRICS_TOKEN="metrics-secret-123"):
            self.assertEqual(self.scrape("wrong").status_code, 401)
            self.assertEqual(self.client.get("/metrics").status_code, 401)

    def test_exposition_contains_health_security_and_business_gauges(self):
        import re
        from contacts.audit import log as audit_log
        from contacts.models import AuditLog, Person
        user = get_user_model().objects.create_user("m", password="very-secure-password")
        Person.objects.create(first_name="A", last_name="B", created_by=user)
        audit_log(AuditLog.LOGIN_FAILED, target_type="auth", detail={"reason": "locked_out"})
        with self.settings(CRM_METRICS_TOKEN="metrics-secret-123"):
            response = self.scrape()
        self.assertEqual(response["Content-Type"], "text/plain; version=0.0.4; charset=utf-8")
        body = response.content.decode()
        self.assertIn("crm_database_up 1", body)
        self.assertIn('crm_records{kind="person"} 1', body)
        self.assertIn('crm_login_failures_24h{reason="locked_out"} 1', body)
        self.assertIn('crm_job_last_success_timestamp_seconds{job="fetch_mail"} 0', body)
        self.assertNotIn("crm_clamav_up", body)
        for line in body.splitlines():  # every sample line parses as Prometheus text
            if line and not line.startswith("#"):
                self.assertRegex(line, r'^[a-z_][a-z0-9_]*(\{[a-z_]+="[^"]*"(,[a-z_]+="[^"]*")*\})? -?\d+(\.\d+)?$')
        self.assertTrue(re.search(r'crm_info\{version="[^"]+",environment="production"\} 1', body))

    def test_background_commands_record_their_heartbeat(self):
        from io import StringIO
        from unittest.mock import patch
        from django.core.management import call_command
        from contacts.models import JobHeartbeat
        call_command("purge_audit_log", stdout=StringIO())
        beat = JobHeartbeat.objects.get(name="purge_audit_log")
        self.assertIsNotNone(beat.last_success_at)
        with patch("contacts.management.commands.purge_audit_log.purge_expired", side_effect=RuntimeError("disk full")):
            with self.assertRaises(RuntimeError):
                call_command("purge_audit_log", stdout=StringIO())
        beat.refresh_from_db()
        self.assertIn("disk full", beat.last_error)
        with self.settings(CRM_METRICS_TOKEN="metrics-secret-123"):
            body = self.scrape().content.decode()
        self.assertRegex(body, r'crm_job_last_failure_timestamp_seconds\{job="purge_audit_log"\} [1-9]\d+')

    def test_every_scheduled_command_is_tracked(self):
        from contacts.metrics import JOBS
        values = (settings.BASE_DIR / "deploy/helm/crm/values.yaml").read_text()
        for job in JOBS:
            with self.subTest(job=job):
                self.assertIn("command: %s" % job, values)
                source = (settings.BASE_DIR / ("contacts/management/commands/%s.py" % job)).read_text()
                self.assertIn("class Command(TrackedCommand)", source)


class DataDictionaryTests(TestCase):
    """The DPO's data dictionary must describe the schema the code actually has."""

    def test_every_model_is_classified(self):
        from contacts.data_dictionary import unclassified
        self.assertEqual(unclassified(), [])

    def test_committed_document_is_current(self):
        from contacts.data_dictionary import render
        committed = (settings.BASE_DIR / "docs" / "paketas" / "04-duomenu-zodynas.md").read_text()
        self.assertEqual(committed, render(),
                         "run: python manage.py data_dictionary > docs/paketas/04-duomenu-zodynas.md")

    def test_personal_and_secret_fields_are_not_left_technical(self):
        from django.contrib.auth import get_user_model
        from contacts.data_dictionary import classify
        from contacts.models import ApiToken, AuditLog, EmailAddress, Person
        self.assertEqual(classify(Person, Person._meta.get_field("last_name")), "A")
        self.assertEqual(classify(EmailAddress, EmailAddress._meta.get_field("email")), "A")
        self.assertEqual(classify(AuditLog, AuditLog._meta.get_field("ip")), "D")
        self.assertEqual(classify(ApiToken, ApiToken._meta.get_field("token_hash")), "S")
        User = get_user_model()
        self.assertEqual(classify(User, User._meta.get_field("password")), "S")

    def test_classification_names_only_existing_fields(self):
        from django.apps import apps
        from contacts.data_dictionary import FIELDS, MODELS
        for key in FIELDS:
            model_name, field_name = key.split(".")
            with self.subTest(field=key):
                self.assertIn(model_name, MODELS)
                apps.get_model("contacts", model_name)._meta.get_field(field_name)


class ControlScaleTests(TestCase):
    """Buttons and controls must take their size from the token scale.

    The product had twenty separate rules that each said "a small button" in
    their own words — eleven spellings of 32px, seven paddings, five font sizes —
    so two compact buttons side by side were rarely the same height. These tests
    are what stops that from growing back one convenient override at a time.
    """

    @staticmethod
    def _css(name):
        return (settings.BASE_DIR / "static" / "css" / name).read_text()

    @staticmethod
    def _rules(css):
        """(selector, body) for every rule, comments and media queries stripped."""
        import re
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        return [(m.group(1).strip(), m.group(2))
                for m in re.finditer(r"([^{}@]+)\{([^{}]*)\}", css)]

    def test_the_scale_is_declared_once(self):
        root = self._css("app.css").split("}")[0]
        for token in ("--control-h:", "--control-h-sm:", "--control-h-lg:",
                      "--btn-pad-y:", "--btn-pad-x:", "--btn-pad-y-sm:", "--btn-pad-x-sm:"):
            self.assertIn(token, root, "%s must live in the app.css :root scale" % token)

    def test_no_button_rule_hard_codes_its_size(self):
        """A pixel here is how the drift started; the tokens exist for this."""
        import re
        allowed = {
            # An icon button: one glyph, centred, deliberately not text-sized.
            ".shortcut-row .btn",
            # Sits inside a calendar event, so smaller than a compact button.
            ".event-done .btn",
        }
        offenders = []
        for name in ("app.css", "theme.css"):
            for selector, body in self._rules(self._css(name)):
                if ".btn" not in selector:
                    continue
                if selector in allowed:
                    continue
                for prop in ("min-height", "height", "padding", "font-size"):
                    for match in re.finditer(r"(?:^|;)\s*%s\s*:([^;]+)" % prop, body):
                        if "px" in match.group(1) and "var(" not in match.group(1):
                            offenders.append("%s: %s {%s:%s}" % (name, selector, prop, match.group(1).strip()))
        self.assertEqual(offenders, [], "use the --control-h / --btn-pad tokens instead")

    def test_one_compact_button_rule_rather_than_twenty(self):
        """Every compact context shares a rule, so they cannot drift apart."""
        css = self._css("theme.css")
        shared = [body for selector, body in self._rules(css)
                  if ".page-links .btn" in selector and "min-height" in body]
        self.assertEqual(len(shared), 1, "the compact button is defined in exactly one rule")
        for context in (".bulk-bar .btn", ".cal-nav .btn", ".dash-card-tools .btn",
                        ".rec-actions .btn", ".filter-row .btn", ".stack-form .btn"):
            self.assertIn(context, [s for s, _ in self._rules(css) if ".page-links .btn" in s][0],
                          "%s must share the compact button rule, not restate it" % context)

    def test_the_surface_scale_is_declared_once(self):
        root = self._css("app.css").split("}")[0]
        for token in ("--card-pad:", "--card-pad-sm:", "--card-pad-lg:", "--topbar-h:",
                      "--shadow-card:", "--shadow-pop:", "--shadow-modal:", "--line-input:"):
            self.assertIn(token, root, "%s must live in the app.css :root scale" % token)

    def test_no_corner_or_elevation_is_written_as_a_number(self):
        """Ten shadows for three jobs, and three radii for one card shape, is how
        two panels beside each other end up looking like different products."""
        import re
        offenders = []
        for name in ("app.css", "theme.css"):
            css = re.sub(r"/\*.*?\*/", "", self._css(name), flags=re.S)
            body = css[css.index("}") + 1:]          # past :root, where the scale lives
            for prop in ("border-radius", "box-shadow"):
                for match in re.finditer(r"(?:^|[;{])\s*%s\s*:([^;}]+)" % prop, body):
                    value = match.group(1).strip()
                    if "var(" in value or value in ("none", "50%", "0", "inherit"):
                        continue
                    offenders.append("%s: %s:%s" % (name, prop, value))
        self.assertEqual(offenders, [], "use --radius-* / --shadow-* instead")

    def test_the_top_bar_has_one_height(self):
        """It was 86px in app.css and 72px in theme.css; theme.css won, so the
        larger number had not rendered in months and still had to be read."""
        import re
        for name in ("app.css", "theme.css"):
            css = re.sub(r"/\*.*?\*/", "", self._css(name), flags=re.S)
            for selector, body in self._rules(css):
                if selector.strip() not in (".brand", ".topbar", ".crm-topbar"):
                    continue
                for match in re.finditer(r"(?:^|;)\s*(?:min-)?height\s*:([^;]+)", body):
                    self.assertIn("var(--topbar-h", match.group(1),
                                  "%s in %s must take the shell height from the token" % (selector, name))

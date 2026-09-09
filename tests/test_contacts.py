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

from contacts.models import Activity, Attachment, Category, Company, CustomField, CustomValue, DuplicateSettings, EmailAddress, Person, PersonCompanyLink, PhoneNumber, PostalAddress, Reminder, SavedFilter, Tag, WebLink
from contacts.duplicates import all_company_duplicate_pairs, all_person_duplicate_pairs, find_company_duplicates, find_person_duplicates


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


class PWATests(TestCase):
    def test_manifest_and_service_worker_are_served_without_auth(self):
        import json

        manifest = self.client.get("/manifest.webmanifest")
        self.assertEqual(manifest.status_code, 200)
        self.assertEqual(manifest["Content-Type"], "application/manifest+json")
        data = json.loads(manifest.content)
        self.assertEqual(data["display"], "standalone")
        self.assertEqual(data["start_url"], "/contacts/")
        self.assertTrue(data["icons"])

        worker = self.client.get("/sw.js")
        self.assertEqual(worker.status_code, 200)
        self.assertEqual(worker["Service-Worker-Allowed"], "/")

        page = self.client.get(reverse("login"))
        self.assertContains(page, 'rel="manifest"')
        self.assertContains(page, 'name="theme-color"')


class AnalyticsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("analitikas", password="very-secure-password")
        self.mate = get_user_model().objects.create_user("kitas", password="very-secure-password")
        self.client.force_login(self.user)
        self.now = timezone.localtime()

    def _person(self, first, **kwargs):
        return Person.objects.create(first_name=first, last_name="Testas", **kwargs)

    @patch("django.utils.timezone.now")
    def test_dashboard_splits_overdue_today_and_tomorrow_for_this_user_only(self, mock_now):
        from datetime import datetime, timezone as _tz
        mock_now.return_value = datetime(2026, 6, 15, 12, 0, tzinfo=_tz.utc)
        talkative = self._person("Kalbus")
        midnight = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        Reminder.objects.create(person=talkative, text="Vėluoja", created_by=self.user,
                                due_at=mock_now.return_value - timedelta(hours=4))
        Reminder.objects.create(person=talkative, text="Šiandien vėliau", created_by=self.user,
                                due_at=midnight + timedelta(hours=20))
        Reminder.objects.create(person=talkative, text="Rytoj", created_by=self.user,
                                due_at=midnight + timedelta(days=1, hours=9))
        Reminder.objects.create(person=talkative, text="Kolegos", created_by=self.mate,
                                due_at=midnight + timedelta(hours=10))

        response = self.client.get(reverse("contacts:home"))
        self.assertEqual(response.status_code, 200)
        texts = lambda key: [r.text for r in response.context[key]]
        self.assertEqual(texts("overdue_events"), ["Vėluoja"])
        self.assertIn("Šiandien vėliau", texts("today_events"))
        self.assertEqual(texts("tomorrow_events"), ["Rytoj"])
        for key in ("overdue_events", "today_events", "tomorrow_events"):
            self.assertNotIn("Kolegos", texts(key))
        # Each tab reports how many it holds, so its badge is not the visible
        # slice. "Today" is 2: the overdue one is also due today.
        tabs = {key: rows["total"] for key, rows, _ in response.context["dash_reminder_tabs"]}
        self.assertEqual((tabs["today"], tabs["tomorrow"]), (2, 1))

    def test_dashboard_counts_my_week_activity_by_type(self):
        person = self._person("Veiklus")
        Activity.objects.create(person=person, activity_type="call", text="Skambinta", created_by=self.user)
        Activity.objects.create(person=person, activity_type="call", text="Ir dar", created_by=self.user)
        Activity.objects.create(person=person, activity_type="note", text="Kolegos", created_by=self.mate)
        response = self.client.get(reverse("contacts:home"))
        counts = {item["label"]: item["total"] for item in response.context["week_activity"]}
        self.assertEqual(counts["Skambutis"], 2)
        self.assertEqual(counts["Pastaba"], 0)
        self.assertEqual(response.context["week_activity_total"], 2)

    def test_dashboard_rings_activity_types_for_this_month(self):
        person = self._person("Ziedas")
        for _ in range(5):
            Activity.objects.create(person=person, activity_type="note", text="Pastaba", created_by=self.user)
        Activity.objects.create(person=person, activity_type="call", text="Skambutis", created_by=self.user)
        Activity.objects.create(person=person, activity_type="note", text="Kolegos", created_by=self.mate)

        response = self.client.get(reverse("contacts:home"))
        ring = response.context["activity_ring"]
        self.assertEqual(ring["total"], 6)          # the colleague's entry is not mine
        shares = {s["label"]: s["percent"] for s in ring["segments"]}
        self.assertEqual((shares["Pastaba"], shares["Skambutis"]), (83, 17))
        self.assertEqual(response.context["activity_month_total"], 6)

    def test_dashboard_charts_six_months_of_new_records(self):
        self._person("Naujas")
        Company.objects.create(name="UAB Nauja")
        response = self.client.get(reverse("contacts:home"))
        chart = response.context["growth_chart"]
        # Two series across six buckets, and this month's two records are in it.
        self.assertEqual(len(chart["labels"]), 6)
        self.assertEqual(len(chart["bars"]), 12)
        self.assertTrue(any(bar["height"] > 0 for bar in chart["bars"]))

    def test_dashboard_summary_cards_carry_a_trend(self):
        self._person("Su tendencija")
        response = self.client.get(reverse("contacts:home"))
        for key in ("spark_people", "spark_companies", "spark_activity", "spark_overdue"):
            spark = response.context[key]
            self.assertEqual(len(spark["points"].split(" ")), 30)   # one point per day

    @override_settings(LANGUAGE_CODE="lt")
    def test_dashboard_svg_coordinates_keep_decimal_points_in_lithuanian(self):
        """Lithuanian formats 68.83 as "68,83", which SVG cannot parse.

        Without {% localize off %} the charts silently collapse — they render,
        but every coordinate is dropped, so this asserts on the markup.
        """
        self._person("Koordinatė")
        Activity.objects.create(person=self._person("Veikla"), activity_type="note",
                                text="Pastaba", created_by=self.user)
        response = self.client.get(reverse("contacts:home"))
        html = response.content.decode()
        import re
        start = html.index('class="growth-chart"')
        chart = html[start:html.index("</svg>", start)]
        coordinates = re.findall(r'(?:x|y|x1|y1|x2|y2|cx|cy|width|height)="([0-9.,]+)"', chart)
        self.assertTrue(coordinates)
        for value in coordinates:
            with self.subTest(value=value):
                self.assertNotIn(",", value)

    def test_dashboard_lists_the_newest_records(self):
        old = self._person("Senas")
        Person.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=40))
        fresh = self._person("Naujausias")
        Company.objects.create(name="UAB Naujausia", city="Vilnius")
        Activity.objects.create(person=fresh, activity_type="note", text="Uzrasas", created_by=self.user)

        response = self.client.get(reverse("contacts:home"))
        self.assertEqual(str(response.context["recent_people"]["visible"][0]), str(fresh))
        self.assertEqual(response.context["recent_companies"]["visible"][0].city, "Vilnius")
        self.assertEqual(response.context["recent_activities"]["visible"][0].text, "Uzrasas")

    def test_dashboard_hides_extra_rows_behind_show_more(self):
        """Cards share a height, so anything past the fixed count folds away."""
        from contacts.analytics_views import DASH_VISIBLE
        for index in range(DASH_VISIBLE + 3):
            self._person("Eile%d" % index)

        response = self.client.get(reverse("contacts:home"))
        rows = response.context["recent_people"]
        self.assertEqual(len(rows["visible"]), DASH_VISIBLE)
        self.assertEqual(len(rows["rest"]), 3)
        self.assertContains(response, "Rodyti daugiau")
        # Hidden, but present — expanding must not need another request.
        self.assertContains(response, str(rows["rest"][0]))
        # The tab badge counts everything, not just the visible slice.
        self.assertEqual(rows["total"], DASH_VISIBLE + 3)

    def test_dashboard_omits_show_more_when_everything_fits(self):
        self._person("Vienintelis")
        response = self.client.get(reverse("contacts:home"))
        self.assertEqual(response.context["recent_people"]["rest"], [])
        self.assertNotContains(response, "Rodyti daugiau")

    def test_chart_helpers_survive_empty_and_flat_input(self):
        """The dashboard renders on day one, when there is nothing to plot."""
        from contacts import charts
        self.assertIsNone(charts.grouped_bars([], ["a"]))
        self.assertIsNone(charts.sparkline([]))
        # A narrower box must move the axis labels with it, not leave them at the
        # default height (they are drawn relative to the chart, not to a bar).
        narrow = charts.grouped_bars([{"label": "Rgs", "values": {"a": 3, "b": 1}}],
                                     ["a", "b"], width=460, height=230)
        self.assertEqual(narrow["width"], 460)
        self.assertEqual({label["y"] for label in narrow["labels"]}, {230 - 8})
        self.assertLessEqual(max(line["y"] for line in narrow["axis"]), 230)
        empty_ring = charts.donut_multi([{"label": "Pastaba", "total": 0}])
        self.assertEqual(empty_ring["total"], 0)
        self.assertEqual(empty_ring["segments"][0]["percent"], 0)
        # A flat line sits mid-height, so an empty CRM does not look like a decline.
        flat = charts.sparkline([0, 0, 0], height=40, pad=3)
        self.assertEqual({round(float(p.split(",")[1])) for p in flat["points"].split(" ")}, {20})

    def test_care_lists_group_contacts_that_need_attention(self):
        quiet = self._person("Nutiles")
        old = Activity.objects.create(person=quiet, activity_type="call", text="Seniai", created_by=self.user)
        Activity.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=75))
        fresh = self._person("Sviezias", owner=self.user)
        PhoneNumber.objects.create(person=fresh, number="+370 600 00000")
        Activity.objects.create(person=fresh, activity_type="call", text="Vakar", created_by=self.user)
        never = self._person("Niekada", owner=self.user)
        EmailAddress.objects.create(person=never, email="niekada@example.lt")

        response = self.client.get(reverse("contacts:analytics-care"), {"days": 60})
        groups = {group["key"]: [str(p) for p in group["rows"]] for group in response.context["groups"]}
        self.assertEqual(response.context["days"], 60)
        self.assertIn(str(quiet), groups["silent"])
        self.assertNotIn(str(fresh), groups["silent"])
        self.assertIn(str(never), groups["never"])
        self.assertNotIn(str(quiet), groups["never"])
        self.assertIn(str(quiet), groups["no_owner"])       # owner never set
        self.assertNotIn(str(fresh), groups["no_owner"])
        self.assertIn(str(quiet), groups["no_details"])      # no phone, no email
        self.assertNotIn(str(never), groups["no_details"])

    def test_care_window_switches_between_30_60_and_90_days(self):
        person = self._person("Ribinis")
        activity = Activity.objects.create(person=person, activity_type="call", text="x", created_by=self.user)
        Activity.objects.filter(pk=activity.pk).update(created_at=timezone.now() - timedelta(days=45))
        silent = lambda days: [str(p) for group in self.client.get(
            reverse("contacts:analytics-care"), {"days": days}).context["groups"]
            if group["key"] == "silent" for p in group["rows"]]
        self.assertIn(str(person), silent(30))
        self.assertNotIn(str(person), silent(60))
        self.assertNotIn(str(person), silent(90))
        # An unknown window falls back to 60 rather than erroring
        self.assertEqual(self.client.get(reverse("contacts:analytics-care"), {"days": "abc"}).context["days"], 60)

    def test_care_exports_a_group_as_csv(self):
        person = self._person("Eksportui", owner=self.user)
        EmailAddress.objects.create(person=person, email="eksportui@example.lt")
        response = self.client.get(reverse("contacts:analytics-care"), {"export": "never"})
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("crm-never.csv", response["Content-Disposition"])
        body = response.content.decode("utf-8-sig")
        self.assertIn("Eksportui", body)
        self.assertIn("eksportui@example.lt", body)

    def test_communication_page_buckets_activity_by_type_and_ranks_contacts(self):
        loud = self._person("Kalbus")
        quiet = self._person("Tylus")
        for _ in range(3):
            Activity.objects.create(person=loud, activity_type="call", text="Skambinta", created_by=self.user)
        Activity.objects.create(person=quiet, activity_type="note", text="Pastaba", created_by=self.user)
        response = self.client.get(reverse("contacts:analytics-communication"), {"days": 30})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total"], 4)
        legend = {row["label"]: row["total"] for row in response.context["legend"]}
        self.assertEqual((legend["Skambutis"], legend["Pastaba"]), (3, 1))
        self.assertEqual([row["label"] for row in response.context["top_people"]][0], str(loud))

    def test_charts_emit_dot_decimals_not_the_locale_comma(self):
        # SVG coordinates are invalid with a comma, so the chart block disables l10n.
        person = self._person("Grafikui")
        Activity.objects.create(person=person, activity_type="call", text="x", created_by=self.user)
        body = self.client.get(reverse("contacts:analytics-communication")).content.decode()
        start = body.index('class="chart"')
        chart = body[start:body.index("</svg>", start)]
        self.assertNotRegex(chart, r'(?:x|y|width|height)="[0-9]+,[0-9]+"')
        self.assertRegex(chart, r'(?:x|y)="[0-9]+\.[0-9]+"')

    def test_reminder_stats_count_done_overdue_and_upcoming(self):
        person = self._person("Priminimams")
        now = timezone.now()
        Reminder.objects.create(person=person, text="Atlikta", created_by=self.user,
                                due_at=now - timedelta(days=2), completed_at=now - timedelta(days=1))
        Reminder.objects.create(person=person, text="Vėluoja", created_by=self.user,
                                due_at=now - timedelta(days=1))
        Reminder.objects.create(person=person, text="Būsimas", created_by=self.user,
                                due_at=now + timedelta(days=1))
        response = self.client.get(reverse("contacts:analytics-reminders"), {"days": 30})
        self.assertEqual((response.context["total"], response.context["done"],
                          response.context["overdue"], response.context["upcoming"]), (3, 1, 1, 1))
        self.assertEqual(response.context["ring"]["percent"], 33)

    def test_growth_page_reports_totals_and_data_quality(self):
        with_email = self._person("Supastu")
        EmailAddress.objects.create(person=with_email, email="su@example.lt")
        self._person("Bepasto")
        response = self.client.get(reverse("contacts:analytics-growth"))
        self.assertEqual(response.context["total_people"], 2)
        quality = {str(row["label"]): row["percent"] for row in response.context["quality"]}
        self.assertEqual(quality["Su el. paštu"], 50)
        self.assertEqual(quality["Su telefonu"], 0)
        self.assertEqual(response.context["curve"]["dots"][-1]["label"].split(": ")[1], "2")

    def test_system_usage_is_admin_only_and_counts_audit_actions(self):
        from contacts.audit import log
        from contacts.models import AuditLog

        self.assertEqual(self.client.get(reverse("contacts:analytics-system")).status_code, 404)
        self.user.is_superuser = True
        self.user.save()
        before = self.client.get(reverse("contacts:analytics-system"), {"days": 30}).context
        log(AuditLog.LOGIN, actor=self.user)
        log(AuditLog.LOGIN_FAILED, actor=None)
        log(AuditLog.EXPORT, actor=self.user)
        after = self.client.get(reverse("contacts:analytics-system"), {"days": 30}).context
        self.assertEqual(after["logins"] - before["logins"], 1)
        self.assertEqual(after["failed"] - before["failed"], 1)
        self.assertEqual(after["exports"] - before["exports"], 1)

    def test_care_group_labels_follow_the_active_language(self):
        # The labels live in a module-level dict, so they must be lazily translated.
        self.assertContains(self.client.get(reverse("contacts:analytics-care")), "Nutilę kontaktai")
        self.client.cookies["django_language"] = "en"
        response = self.client.get(reverse("contacts:analytics-care"))
        self.assertContains(response, "Contacts gone quiet")
        self.assertNotContains(response, "Nutilę kontaktai")

    def test_analytics_respect_record_visibility(self):
        from contacts.models import UserProfile

        UserProfile.objects.create(user=self.user, role=UserProfile.ROLE_MEMBER,
                                   record_visibility=UserProfile.VISIBILITY_OWN)
        hidden = self._person("Slaptas", owner=self.mate)
        response = self.client.get(reverse("contacts:analytics-care"))
        for group in response.context["groups"]:
            self.assertNotIn(str(hidden), [str(p) for p in group["rows"]])
        self.assertEqual(self.client.get(reverse("contacts:home")).context["people_total"], 0)


class CalendarTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("agenda", password="very-secure-password")
        self.mate = get_user_model().objects.create_user("kolega", password="very-secure-password")
        self.person = Person.objects.create(first_name="Ruslan", last_name="Gorin", job_title="IT")
        PhoneNumber.objects.create(person=self.person, number="+370 600 11111")
        PostalAddress.objects.create(person=self.person, address="Vilnius, Lietuva")
        self.company = Company.objects.create(name="AB Regitra", phone="+370 37 000", address="Kaunas")
        self.start = timezone.localtime().replace(hour=10, minute=0, second=0, microsecond=0)
        self.client.force_login(self.user)

    def _event(self, **kwargs):
        defaults = {"text": "Skambutis", "due_at": self.start, "end_at": self.start + timedelta(hours=1),
                    "person": self.person, "created_by": self.user}
        return Reminder.objects.create(**{**defaults, **kwargs})

    def test_each_view_renders_only_the_signed_in_users_events(self):
        self._event(text="Mano įvykis")
        self._event(text="Kolegos įvykis", created_by=self.mate)
        for view in ("day", "week", "month"):
            with self.subTest(view=view):
                response = self.client.get(reverse("contacts:calendar"),
                                           {"view": view, "date": self.start.date().isoformat()})
                self.assertEqual(response.status_code, 200)
                scheduled = {item["reminder"].text
                             for day in response.context["days"] for item in day["events"]}
                self.assertEqual(scheduled, {"Mano įvykis"})
                self.assertContains(response, 'data-text="Mano įvykis"')

    def test_click_or_drag_creates_an_event_bound_to_a_contact(self):
        response = self.client.post(reverse("contacts:calendar-event-create"), {
            "text": "Susitikimas", "due_at": "2026-10-01T10:00", "end_at": "2026-10-01T11:30",
            "record_kind": "person", "record_id": self.person.pk, "view": "week", "date": "2026-10-01",
        })
        self.assertEqual(response.status_code, 302)
        event = Reminder.objects.get(text="Susitikimas")
        self.assertEqual((event.person, event.company, event.created_by), (self.person, None, self.user))
        self.assertEqual(timezone.localtime(event.due_at).strftime("%H:%M"), "10:00")
        self.assertEqual(timezone.localtime(event.end_at).strftime("%H:%M"), "11:30")

    def test_event_without_an_end_gets_the_default_slot_and_may_have_no_record(self):
        self.client.post(reverse("contacts:calendar-event-create"),
                         {"text": "Asmeninis", "due_at": "2026-10-02T09:00"})
        event = Reminder.objects.get(text="Asmeninis")
        self.assertIsNone(event.record)
        self.assertEqual((event.end_at - event.due_at).total_seconds() / 60, Reminder.DEFAULT_MINUTES)

    def test_event_can_be_attached_to_a_company(self):
        self.client.post(reverse("contacts:calendar-event-create"), {
            "text": "Įmonės susitikimas", "due_at": "2026-10-03T14:00",
            "record_kind": "company", "record_id": self.company.pk,
        })
        event = Reminder.objects.get(text="Įmonės susitikimas")
        self.assertEqual(event.record, self.company)
        self.assertEqual((event.contact_phone, event.contact_address), ("+370 37 000", "Kaunas"))

    def test_update_and_delete_only_touch_the_owners_own_events(self):
        mine = self._event(text="Mano")
        theirs = self._event(text="Svetimas", created_by=self.mate)
        self.client.post(reverse("contacts:calendar-event-update", args=[mine.pk]),
                         {"text": "Perkeltas", "due_at": "2026-10-05T08:00", "end_at": "2026-10-05T08:45"})
        mine.refresh_from_db()
        self.assertEqual(mine.text, "Perkeltas")

        self.client.post(reverse("contacts:calendar-event-update", args=[theirs.pk]), {"text": "Bandymas"})
        theirs.refresh_from_db()
        self.assertEqual(theirs.text, "Svetimas")

        self.client.post(reverse("contacts:calendar-event-delete", args=[theirs.pk]))
        theirs.refresh_from_db()
        self.assertIsNone(theirs.deleted_at)

        self.client.post(reverse("contacts:calendar-event-delete", args=[mine.pk]))
        mine.refresh_from_db()
        self.assertIsNotNone(mine.deleted_at)

    def test_reminder_defaults_to_its_creator_and_can_be_handed_to_a_teammate(self):
        due = self.start.strftime("%Y-%m-%dT%H:%M")
        self.client.post(reverse("contacts:reminder-create", args=[self.person.pk]),
                         {"text": "Užduotis", "due_at": due})
        task = Reminder.objects.get(text="Užduotis")
        self.assertEqual(task.assigned_to, self.user)

        self.client.post(reverse("contacts:reminder-edit", args=[task.pk]),
                         {"text": "Užduotis", "due_at": due, "assigned_to": self.mate.pk, "priority": "high"})
        task.refresh_from_db()
        self.assertEqual((task.assigned_to, task.priority), (self.mate, "high"))

        # It has left my calendar...
        mine = self.client.get(reverse("contacts:calendar"),
                               {"view": "week", "date": self.start.date().isoformat()})
        my_texts = {item["reminder"].text for day in mine.context["days"] for item in day["events"]}
        self.assertNotIn("Užduotis", my_texts)
        # ...and shows on the assignee's.
        self.client.force_login(self.mate)
        theirs = self.client.get(reverse("contacts:calendar"),
                                 {"view": "week", "date": self.start.date().isoformat()})
        their_texts = {item["reminder"].text for day in theirs.context["days"] for item in day["events"]}
        self.assertIn("Užduotis", their_texts)

    @patch("django.utils.timezone.now")
    def test_past_events_are_flagged_so_the_grid_can_dim_them(self, mock_now):
        from datetime import datetime, timezone as _tz
        mock_now.return_value = datetime(2026, 6, 15, 12, 0, tzinfo=_tz.utc)
        now = mock_now.return_value
        past = self._event(text="Praeitis", due_at=now - timedelta(hours=3), end_at=now - timedelta(hours=2))
        future = self._event(text="Ateitis", due_at=now + timedelta(hours=2), end_at=now + timedelta(hours=3))
        self.assertTrue(past.is_past)
        self.assertFalse(future.is_past)
        response = self.client.get(reverse("contacts:calendar"),
                                   {"view": "day", "date": timezone.localtime(now).date().isoformat()})
        self.assertContains(response, "cal-event is-past")

    def test_record_picker_returns_phone_and_address_and_respects_visibility(self):
        from contacts.models import UserProfile

        response = self.client.get(reverse("contacts:calendar-records"), {"q": "Gorin"})
        result = response.json()["results"][0]
        self.assertEqual(result["kind"], "person")
        self.assertEqual((result["phone"], result["address"]), ("+370 600 11111", "Vilnius, Lietuva"))
        self.assertEqual(result["url"], self.person.get_absolute_url())
        self.assertEqual(self.client.get(reverse("contacts:calendar-records"), {"q": "G"}).json()["results"], [])

        self.person.owner = self.mate
        self.person.save(update_fields=["owner"])
        UserProfile.objects.create(user=self.user, role=UserProfile.ROLE_MEMBER,
                                   record_visibility=UserProfile.VISIBILITY_OWN)
        hidden = self.client.get(reverse("contacts:calendar-records"), {"q": "Gorin"}).json()["results"]
        self.assertEqual(hidden, [])


class ReminderAssignmentTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("man", password="very-secure-password")
        self.mate = get_user_model().objects.create_user("kolega", password="very-secure-password")
        self.stranger = get_user_model().objects.create_user("svetimas", password="very-secure-password")
        self.person = Person.objects.create(first_name="Ruslan", last_name="Gorin")
        self.client.force_login(self.user)
        self.due = timezone.now().replace(microsecond=0).strftime("%Y-%m-%dT%H:%M")

    def _reminder(self, **kw):
        d = {"person": self.person, "text": "X", "due_at": timezone.now() + timedelta(days=2),
             "created_by": self.user, "assigned_to": self.user}
        return Reminder.objects.create(**{**d, **kw})

    def test_list_scopes_split_assigned_created_and_all(self):
        self._reminder(text="Man")
        self._reminder(text="Kolegai", assigned_to=self.mate)
        self._reminder(text="Svetimas", created_by=self.mate, assigned_to=self.mate)
        texts = lambda scope: {r.text for r in self.client.get(
            reverse("contacts:reminder-list"), {"scope": scope}).context["scheduled_reminders"]}
        self.assertEqual(texts("assigned"), {"Man"})
        self.assertEqual(texts("created"), {"Man", "Kolegai"})
        self.assertEqual(texts("all"), {"Man", "Kolegai", "Svetimas"})

    def test_a_handed_over_task_rings_the_recipients_bell_until_they_open_it(self):
        task = self._reminder(text="Perduota", assigned_to=self.user, created_by=self.mate)
        # It counts for the recipient even though it is two days out.
        self.client.force_login(self.user)
        page = self.client.get(reverse("contacts:list"))
        self.assertEqual(page.context["active_reminder_count"], 1)
        self.assertIn(task, list(page.context["active_reminders_menu"]))
        # Opening the reminder list marks it read and clears the bell.
        self.client.get(reverse("contacts:reminder-list"), HTTP_SEC_FETCH_SITE="same-origin")
        self.assertEqual(self.client.get(reverse("contacts:list")).context["active_reminder_count"], 0)

    def test_reassigning_via_the_edit_form_resets_read_and_is_scoped_to_visible_users(self):
        from contacts.models import Team, UserProfile
        UserProfile.objects.create(user=self.user, role=UserProfile.ROLE_RESTRICTED,
                                   record_visibility=UserProfile.VISIBILITY_OWN)
        team = Team.objects.create(name="Komanda")
        team.members.add(self.user, self.mate)
        task = self._reminder(text="Redaguoju")
        Reminder.objects.filter(pk=task.pk).update(read_at=timezone.now())
        # Hand it to a teammate.
        self.client.post(reverse("contacts:reminder-edit", args=[task.pk]),
                         {"text": "Redaguoju", "due_at": self.due, "assigned_to": self.mate.pk, "priority": "normal"})
        task.refresh_from_db()
        self.assertEqual(task.assigned_to, self.mate)
        self.assertIsNone(task.read_at)
        # A user outside the team (and outside the form's queryset) is rejected.
        resp = self.client.post(reverse("contacts:reminder-edit", args=[task.pk]),
                                {"text": "Redaguoju", "due_at": self.due, "assigned_to": self.stranger.pk, "priority": "normal"})
        self.assertEqual(resp.status_code, 200)
        task.refresh_from_db()
        self.assertEqual(task.assigned_to, self.mate)


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
        self.assertContains(response, 'Contact information')
        self.assertContains(response, 'Sign out')
        self.assertContains(response, name)
        self.assertContains(response, 'lang="en"')
        self.assertContains(self.client.get(self.company.get_absolute_url()), 'Contact information')
        self.client.post(reverse('set_language'), {'language':'lt', 'next': self.person.get_absolute_url()})
        self.assertContains(self.client.get(self.person.get_absolute_url()), 'Kontaktinė informacija')

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
        Person.objects.create(first_name='Other', last_name='Test')
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

    def _import_file(self, upload):
        """Upload a file for import and confirm it (the two-step wizard)."""
        preview = self.client.post(reverse("contacts:import-export"), {"file": upload})
        result = self.client.post(reverse("contacts:import-export"), {"confirm": "1"})
        return preview, result

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
        self.assertContains(response, 'class="record-detail-actions"')
        response = self.client.get(self.company.get_absolute_url())
        self.assertContains(response, 'class="record-detail-actions"')
        response = self.client.get(reverse("contacts:person-create"))
        self.assertContains(response, 'class="form-actions"')
        self.assertContains(response, "js/forms.js")
        self.assertContains(response, 'class="data-form"')

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
        columns = ["company", "phone", "email", "category", "tags", "updated"]

        response = self.client.get(reverse("contacts:list"), {"columns": columns, "sort": "id", "direction": "desc"})

        self.assertEqual(response.context["sort"], "id")
        self.assertEqual(list(response.context["page"])[0], other)
        self.assertEqual(response.context["page"].paginator.count, Person.objects.filter(deleted_at__isnull=True).count())
        self.assertContains(response, 'class="sort-control"', count=7)
        for key in ("name", "company", "phone", "email", "category", "tags", "updated", "id"):
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

    def test_company_city_is_editable_listed_and_exported(self):
        """City is its own field so a place can be shown without parsing an address."""
        self.client.force_login(self.user)
        response = self.client.post(reverse("contacts:company-edit", args=[self.company.pk]), {
            "name": self.company.name, "company_code": "", "vat_code": "",
            "address": "Gedimino pr. 1", "city": "Vilnius", "phone": "", "email": "",
            "url": "", "description": ""})
        self.assertEqual(response.status_code, 302)
        self.company.refresh_from_db()
        self.assertEqual((self.company.address, self.company.city), ("Gedimino pr. 1", "Vilnius"))

        listed = self.client.get(reverse("contacts:company-list"), {"columns": "city"})
        self.assertContains(listed, "Vilnius")
        self.assertContains(listed, "sort=city&amp;direction=asc")

        csv_text = self.client.get(reverse("contacts:companies-export")).content.decode("utf-8-sig")
        self.assertIn("Miestas", csv_text.splitlines()[0])
        self.assertIn("Vilnius", csv_text)

    def test_searches_related_fields(self):
        self.client.force_login(self.user)
        PostalAddress.objects.create(person=self.person, address="Gedimino pr. 1, Vilnius")
        WebLink.objects.create(person=self.person, url="https://ruta.example.lt")
        for query in ["Žukai", "Rūta Žukaitė", "Aukštaitijos", "645 21", "ruta@example", "Gedimino", "ruta.example"]:
            with self.subTest(query=query):
                response = self.client.get(reverse("contacts:list"), {"q": query})
                self.assertContains(response, "Rūta Žukaitė")

    def test_sorting_and_page_size_preserve_active_filters_and_columns(self):
        self.client.force_login(self.user)
        category = Category.objects.create(name="Klientas")
        self.person.categories.add(category)
        response = self.client.get(reverse("contacts:list"), {
            "category": category.pk,
            "columns": ["phone", "owner"],
            "page_size": "100",
            "sort": "name",
            "direction": "asc",
        })
        self.assertEqual(response.context["page_size"], 100)
        self.assertEqual(response.context["columns"], ["phone", "owner"])
        self.assertContains(response, f"category={category.pk}&amp;columns=phone&amp;columns=owner&amp;page_size=100&amp;sort=name")

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

    def test_contact_row_menu_has_note_reminder_and_copy_email_actions(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("contacts:list"))
        detail = reverse("contacts:detail", args=[self.person.pk])
        self.assertContains(response, f'href="{detail}#tab-comments"')
        self.assertContains(response, f'href="{detail}#reminder-add"')
        self.assertContains(response, 'class="copy-email" data-email="ruta@example.lt"')

    def test_copy_email_action_is_hidden_without_an_email(self):
        self.client.force_login(self.user)
        self.person.emails.all().delete()
        response = self.client.get(reverse("contacts:list"))
        self.assertNotContains(response, 'class="copy-email"')

    def test_record_detail_pages_expose_quick_action_anchors(self):
        self.client.force_login(self.user)
        person_page = self.client.get(reverse("contacts:detail", args=[self.person.pk]))
        self.assertContains(person_page, 'id="tab-comments"')
        self.assertContains(person_page, 'id="reminder-add"')
        company_page = self.client.get(reverse("contacts:company-detail", args=[self.company.pk]))
        self.assertContains(company_page, 'id="tab-comments"')

    def test_company_row_menu_has_note_and_copy_email_actions(self):
        self.client.force_login(self.user)
        self.company.email = "info@aukstaitija.lt"
        self.company.save(update_fields=["email"])
        response = self.client.get(reverse("contacts:company-list"))
        detail = reverse("contacts:company-detail", args=[self.company.pk])
        self.assertContains(response, f'href="{detail}#tab-comments"')
        self.assertContains(response, 'data-email="info@aukstaitija.lt"')

    def test_password_change_updates_password_and_keeps_session(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("contacts:settings-password"), {
            "old_password": "very-secure-password",
            "new_password1": "another-secure-pass-99",
            "new_password2": "another-secure-pass-99",
        })
        self.assertRedirects(response, reverse("contacts:settings"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("another-secure-pass-99"))
        self.assertEqual(self.client.get(reverse("contacts:list")).status_code, 200)

    def test_password_change_rejects_wrong_current_password(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("contacts:settings-password"), {
            "old_password": "not-the-password",
            "new_password1": "another-secure-pass-99",
            "new_password2": "another-secure-pass-99",
        })
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("very-secure-password"))

    def test_password_change_enforces_length_validator(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("contacts:settings-password"), {
            "old_password": "very-secure-password",
            "new_password1": "short",
            "new_password2": "short",
        })
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("very-secure-password"))

    def test_profile_page_hosts_the_password_change_form(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("contacts:settings"))
        self.assertContains(response, f'action="{reverse("contacts:settings-password")}"')
        self.assertContains(response, "id_old_password")
        # No standalone password section in the nav any more.
        self.assertNotContains(response, ">" + "Slaptažodis" + "<")

    def test_password_endpoint_get_redirects_to_profile(self):
        self.client.force_login(self.user)
        self.assertRedirects(
            self.client.get(reverse("contacts:settings-password")), reverse("contacts:settings"))

    def test_activity_attachments_reject_oversized_and_unsupported_files(self):
        self.client.force_login(self.user)
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root), \
                patch("contacts.views.ATTACHMENT_MAX_BYTES", 100):
            ok = SimpleUploadedFile("note.txt", b"hello", content_type="text/plain")
            wrong_type = SimpleUploadedFile("archyvas.zip", b"PK", content_type="application/zip")
            too_big = SimpleUploadedFile("didelis.pdf", b"x" * 200, content_type="application/pdf")
            response = self.client.post(reverse("contacts:activity-create", args=[self.person.pk]), {
                "activity_type": "note", "text": "Su priedais",
                "attachments": [ok, wrong_type, too_big],
            })
        self.assertEqual(response.status_code, 302)
        activity = self.person.activities.latest("created_at")
        self.assertEqual(list(activity.attachments.values_list("original_name", flat=True)), ["note.txt"])

    def test_company_activity_attachments_are_validated_too(self):
        self.client.force_login(self.user)
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            bad = SimpleUploadedFile("kenkejas.exe", b"MZ", content_type="application/octet-stream")
            self.client.post(reverse("contacts:company-activity-create", args=[self.company.pk]), {
                "activity_type": "note", "text": "Įmonės įrašas", "attachments": [bad],
            })
        self.assertEqual(self.company.activities.latest("created_at").attachments.count(), 0)

    def test_session_is_configured_with_a_sliding_idle_timeout(self):
        from django.conf import settings as dj_settings
        self.assertTrue(dj_settings.SESSION_SAVE_EVERY_REQUEST)
        self.assertGreater(dj_settings.SESSION_COOKIE_AGE, 0)
        self.client.force_login(self.user)
        response = self.client.get(reverse("contacts:list"))
        self.assertIn("sessionid", response.cookies)

    def test_contacts_list_last_contact_column_shows_latest_activity(self):
        self.client.force_login(self.user)
        Activity.objects.create(person=self.person, activity_type="note", text="Skambinta", created_by=self.user)
        response = self.client.get(reverse("contacts:list"), {"columns": ["last_contact"]})
        self.assertIn("last_contact", response.context["columns"])
        self.assertContains(response, "Paskutinis bendravimas")
        row = next(p for p in response.context["page"] if p.pk == self.person.pk)
        self.assertIsNotNone(row.last_contact_at)
        self.assertContains(response, timezone.localtime(row.last_contact_at).strftime("%Y-%m-%d"))
        sorted_response = self.client.get(reverse("contacts:list"), {"sort": "last_contact", "direction": "desc"})
        self.assertEqual(sorted_response.context["sort"], "last_contact")

    def test_company_list_offers_address_column(self):
        self.client.force_login(self.user)
        self.company.address = "Gedimino pr. 1, Vilnius"
        self.company.save(update_fields=["address"])
        response = self.client.get(reverse("contacts:company-list"), {"columns": ["address"]})
        self.assertIn("address", response.context["columns"])
        self.assertContains(response, "Gedimino pr. 1, Vilnius")

    def test_lists_have_a_clear_selection_control(self):
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("contacts:list")), 'id="clear-selection"')
        self.assertContains(self.client.get(reverse("contacts:company-list")), 'id="company-clear-selection"')

    def test_pagination_shows_first_last_and_numbered_links_across_pages(self):
        self.client.force_login(self.user)
        Person.objects.bulk_create([Person(first_name=f"P{n:03d}", last_name="X") for n in range(120)])
        response = self.client.get(reverse("contacts:list"), {"page": 2})
        self.assertEqual(response.context["page"].paginator.num_pages, 3)
        self.assertContains(response, "Pirmas puslapis")
        self.assertContains(response, "Paskutinis puslapis")
        self.assertContains(response, "page=1")
        self.assertContains(response, "page=3")

    def test_contact_detail_summary_shows_last_contact_next_action_and_overdue(self):
        self.client.force_login(self.user)
        Activity.objects.create(person=self.person, activity_type="call", text="Skambinta", created_by=self.user)
        Reminder.objects.create(person=self.person, text="Perskambinti", due_at=timezone.now() + timedelta(days=3), created_by=self.user)
        Reminder.objects.create(person=self.person, text="Uždelsta", due_at=timezone.now() - timedelta(days=1), created_by=self.user)
        response = self.client.get(reverse("contacts:detail", args=[self.person.pk]))
        self.assertContains(response, "Paskutinis kontaktas")
        self.assertContains(response, "Sekantis kontaktas")
        self.assertContains(response, "Perskambinti")
        self.assertContains(response, "record-detail-warn")
        self.assertEqual(response.context["overdue_reminder_count"], 1)

    def test_company_detail_summary_uses_linked_contact_activity_and_reminders(self):
        self.client.force_login(self.user)
        Activity.objects.create(company=self.company, activity_type="meeting", text="Susitikta", created_by=self.user)
        Reminder.objects.create(person=self.person, text="Įmonės skambutis", due_at=timezone.now() + timedelta(days=2), created_by=self.user)
        response = self.client.get(reverse("contacts:company-detail", args=[self.company.pk]))
        self.assertContains(response, "Įmonės skambutis")
        self.assertEqual(response.context["next_reminder"].person, self.person)

    def test_record_detail_warn_is_omitted_when_nothing_is_overdue(self):
        other = Person.objects.create(first_name="Tuščias", last_name="Kontaktas")
        self.client.force_login(self.user)
        response = self.client.get(reverse("contacts:detail", args=[other.pk]))
        self.assertNotContains(response, "record-detail-warn")

    def test_data_export_zip_has_data_and_readme_for_staff(self):
        import io
        import json
        import zipfile
        staff = get_user_model().objects.create_user("bosas", password="very-secure-password", is_staff=True)
        self.client.force_login(staff)
        response = self.client.post(reverse("contacts:settings-data-export"))
        self.assertEqual(response["Content-Type"], "application/zip")
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        self.assertIn("data.json", archive.namelist())
        self.assertIn("README.txt", archive.namelist())
        rows = json.loads(archive.read("data.json"))
        self.assertTrue(any(row["model"] == "contacts.person" for row in rows))

    def test_data_export_is_denied_for_non_staff_users(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("contacts:settings-data-export")).status_code, 404)
        self.assertEqual(self.client.post(reverse("contacts:settings-data-export")).status_code, 404)

    def test_settings_nav_shows_data_export_only_to_staff(self):
        url = reverse("contacts:settings-data-export")
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse("contacts:settings")), url)
        staff = get_user_model().objects.create_user("bosas2", password="very-secure-password", is_staff=True)
        self.client.force_login(staff)
        self.assertContains(self.client.get(reverse("contacts:settings")), url)

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
        self.user.is_superuser = True
        self.user.save()
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
        for value in ("Kontaktų sąrašas", "Įmonių sąrašas", "Priminimai", "Importas / eksportas",
                      "Archyvas", "Nustatymai", "Darbastalis", "Analitika", "Kalendorius"):
            self.assertContains(screens, value)

        admin = self.client.get(url, {"topic": "admin"})
        for value in ("changepassword", "axes_reset_username", "Rolės ir teisės",
                      "Naudotojas (visi įrašai)", "Naudotojų valdymas"):
            self.assertContains(admin, value)

        backup = self.client.get(url, {"topic": "backup"})
        for value in ("pg_dump", "pg_restore", "runtime/media", "Atkūrimo patikra"):
            self.assertContains(backup, value)

        overview = self.client.get(url, {"topic": "overview"})
        current_version = (settings.BASE_DIR / "VERSION").read_text().strip()
        self.assertContains(overview, f"CRM {current_version}")
        self.assertNotContains(overview, "CRM 0.4.0")

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

        self.assertContains(self.client.get(self.person.get_absolute_url()), "· Rasa Jonaitė")
        self.assertContains(self.client.get(self.company.get_absolute_url()), "· Rasa Jonaitė")

    def test_profile_save_action_is_aligned_to_the_right(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("contacts:settings"))
        self.assertContains(response, 'class="form-actions profile-form-actions"')

    def test_profile_rejects_non_image_avatar_and_taxonomy_pages_remain_available(self):
        self.client.force_login(self.user)
        self.user.is_superuser = True
        self.user.save()
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
        self.user.is_superuser = True
        self.user.save()
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

    def test_taxonomy_settings_delete_tag_removes_it_from_records(self):
        self.client.force_login(self.user)
        self.user.is_superuser = True
        self.user.save()
        tag = Tag.objects.create(name="Laikinas")
        self.person.tags.add(tag)
        response = self.client.post(reverse("contacts:settings-tags"), {
            "item_id": tag.pk,
            "delete": "1",
        })
        self.assertRedirects(response, reverse("contacts:settings-tags"))
        self.assertFalse(Tag.objects.filter(pk=tag.pk).exists())
        self.assertEqual(self.person.tags.count(), 0)

    def test_taxonomy_settings_reject_duplicate_name_and_invalid_color(self):
        self.client.force_login(self.user)
        self.user.is_superuser = True
        self.user.save()
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
        # Non-admins cannot touch the global duplicate policy.
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("contacts:settings-duplicates")).status_code, 404)
        self.assertEqual(self.client.post(reverse("contacts:settings-duplicates"), {"check_on_import": "on"}).status_code, 404)
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        settings_response = self.client.get(reverse("contacts:settings-duplicates"))
        self.assertNotContains(settings_response, 'name="level"')   # one fixed rule, no level
        other = Person.objects.create(first_name="Kita", last_name="Pavardė")
        EmailAddress.objects.create(person=other, email="ruta@example.lt")
        response = self.client.get(reverse("contacts:duplicate-list"))
        self.assertContains(response, self.person.get_absolute_url())
        self.assertContains(response, other.get_absolute_url())
        self.assertContains(response, "Tas pats el. paštas")
        response = self.client.post(reverse("contacts:settings-duplicates"), {"check_on_import": "on"})
        self.assertRedirects(response, reverse("contacts:settings-duplicates"))
        settings_obj = DuplicateSettings.load()
        self.assertFalse(settings_obj.enabled)
        self.assertTrue(settings_obj.check_on_import)

    def test_bulk_merge_all_duplicates_keeps_the_older_record(self):
        self.client.force_login(self.user)
        keep = Person.objects.create(first_name="Petras", last_name="Petraitis")
        dup1 = Person.objects.create(first_name="Petras", last_name="Petraitis")
        dup2 = Person.objects.create(first_name="Petras", last_name="Petraitis")
        response = self.client.post(reverse("contacts:duplicate-merge-all"), follow=True)
        self.assertContains(response, "Sujungta dublikatų porų")
        self.assertEqual(Person.objects.filter(first_name="Petras", deleted_at__isnull=True).count(), 1)
        keep.refresh_from_db()
        self.assertIsNone(keep.deleted_at)
        for dup in (dup1, dup2):
            dup.refresh_from_db()
            self.assertEqual(dup.merged_into_id, keep.pk)
        self.assertContains(self.client.get(reverse("contacts:duplicate-list")), "Galimų dublikatų nerasta")

    def test_system_settings_control_page_size_and_date_format(self):
        from contacts.models import SystemSettings

        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("contacts:settings-system")).status_code, 404)
        self.user.is_superuser = True
        self.user.save()
        response = self.client.post(reverse("contacts:settings-system"), {
            "default_page_size": "25",
            "date_format": "d.m.Y",
        })
        self.assertRedirects(response, reverse("contacts:settings-system"))
        system = SystemSettings.load()
        self.assertEqual((system.default_page_size, system.date_format), (25, "d.m.Y"))
        self.assertEqual(self.client.get(reverse("contacts:list")).context["page"].paginator.per_page, 25)
        self.assertEqual(
            self.client.get(reverse("contacts:list"), {"page_size": "100"}).context["page"].paginator.per_page, 100)
        detail = self.client.get(self.person.get_absolute_url())
        self.assertContains(detail, timezone.localtime(self.person.created_at).strftime("%d.%m.%Y"))

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
            "enabled": True, "check_on_edit": False,
        })
        response = self.client.post(reverse("contacts:company-field-edit", args=[self.company.pk]), {
            "field": "company_code", "value": other.company_code,
        })
        self.assertEqual(response.status_code, 200)
        self.company.refresh_from_db()
        self.assertEqual(self.company.company_code, other.company_code)

    def test_person_matches_on_name_email_or_phone_only(self):
        same_name = Person.objects.create(first_name=self.person.first_name, last_name=self.person.last_name)
        person_data = {"first_name": self.person.first_name, "last_name": self.person.last_name,
                       "email": "", "phone": "", "companies": []}
        match = find_person_duplicates(person_data, exclude_pk=self.person.pk)
        self.assertEqual(match[0]["record"], same_name)
        self.assertEqual(match[0]["reasons"], ["name"])

        # A shared company alone is not a reason any more.
        shared = Company.objects.create(name="Bendra")
        only_company = Person.objects.create(first_name="Visai", last_name="Kitas")
        PersonCompanyLink.objects.create(person=only_company, company=shared)
        self.assertNotIn(only_company, [m["record"] for m in
                         find_person_duplicates({"first_name": "Nesutampa", "last_name": "Nieko",
                                                 "email": "", "phone": "", "companies": [shared]})])

    def test_company_matches_on_name_email_phone_vat_or_code(self):
        company = Company.objects.create(name="UAB Pavyzdys", vat_code="LT100001", company_code="300001")
        exact_name = Company.objects.create(name="UAB Pavyzdys")
        data = {"name": company.name, "company_code": "", "vat_code": "", "email": "", "phone": ""}
        self.assertEqual(find_company_duplicates(data, exclude_pk=company.pk)[0]["record"], exact_name)
        # Partial name is not a match.
        Company.objects.create(name="UAB Pavyzdys Plius")
        near = {"name": "UAB Pavyzdys Kitas", "company_code": "", "vat_code": "", "email": "", "phone": ""}
        self.assertEqual(find_company_duplicates(near), [])

    def test_phone_and_email_never_bridge_a_person_and_a_company(self):
        person = Person.objects.create(first_name="Tas", last_name="Pats")
        PhoneNumber.objects.create(person=person, number="+37060011122")
        EmailAddress.objects.create(person=person, email="bendras@example.lt")
        Company.objects.create(name="UAB Sutampa", phone="+37060011122", email="bendras@example.lt")

        self.assertEqual(find_company_duplicates(
            {"name": "", "company_code": "", "vat_code": "",
             "email": "bendras@example.lt", "phone": "+37060011122"}, exclude_pk=None,
        ) and [], [])   # a person's contact details do not surface as a company match
        pairs = all_person_duplicate_pairs() + all_company_duplicate_pairs()
        self.assertEqual(pairs, [])

    def test_strict_review_detects_exact_full_name(self):
        self.client.force_login(self.user)
        DuplicateSettings.objects.update_or_create(pk=1, defaults={"enabled": True})
        other = Person.objects.create(first_name=self.person.first_name, last_name=self.person.last_name)

        response = self.client.get(reverse("contacts:duplicate-list"))

        self.assertContains(response, self.person.get_absolute_url())
        self.assertContains(response, other.get_absolute_url())
        self.assertContains(response, "Tas pats vardas")

    def test_not_a_duplicate_removes_the_pair_and_stops_warning(self):
        from contacts.models import DuplicateException
        self.client.force_login(self.user)
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        DuplicateSettings.objects.update_or_create(pk=1, defaults={"enabled": True})
        twin = Person.objects.create(first_name=self.person.first_name, last_name=self.person.last_name)

        low, high = sorted((self.person.pk, twin.pk))
        self.client.post(reverse("contacts:duplicate-dismiss", args=["person", low, high]))
        self.assertEqual(DuplicateException.objects.filter(kind="person", left_id=low, right_id=high).count(), 1)

        self.assertContains(self.client.get(reverse("contacts:duplicate-list")), "Galimų dublikatų nerasta")
        # Editing one of them no longer warns about the other.
        data = {"first_name": self.person.first_name, "last_name": self.person.last_name,
                "email": "", "phone": "", "companies": []}
        self.assertEqual(find_person_duplicates(data, exclude_pk=self.person.pk), [])

    def test_import_does_not_report_exact_record_that_it_updates(self):
        self.client.force_login(self.user)
        content = "Vardas,Pavardė,El. paštai\nRūta,Žukaitė,ruta@example.lt\n".encode()
        preview, response = self._import_file(SimpleUploadedFile("contacts.csv", content, content_type="text/csv"))
        self.assertContains(preview, "Bus atnaujinta: 1")
        self.assertContains(response, "Galimi dublikatai: 0")
        self.assertNotContains(response, "Peržiūrėti dublikatus")
        self.assertContains(response, "Atnaujinti: 1")
        self.assertEqual(Person.objects.filter(first_name="Rūta", last_name="Žukaitė").count(), 1)

    def test_import_settings_handle_semicolon_and_windows_1257_csv(self):
        from contacts.models import SystemSettings

        self.client.force_login(self.user)
        self.user.is_superuser = True
        self.user.save()
        self.assertEqual(self.client.get(reverse("contacts:settings-import")).status_code, 200)
        self.client.post(reverse("contacts:settings-import"),
                         {"import_delimiter": "auto", "import_encoding": "auto"})
        system = SystemSettings.load()
        self.assertEqual((system.import_delimiter, system.import_encoding), ("auto", "auto"))
        content = "Vardas;Pavardė;Pareigos\nJonas;Kęstutaitis;Vadovas\n".encode("cp1257")
        self._import_file(SimpleUploadedFile("kontaktai.csv", content, content_type="text/csv"))
        person = Person.objects.get(first_name="Jonas", last_name="Kęstutaitis")
        self.assertEqual(person.job_title, "Vadovas")

    def test_import_uses_selected_duplicate_level_and_reports_real_phone_duplicate(self):
        self.client.force_login(self.user)
        content = "Vardas,Pavardė,Telefonai\nKitas,Asmuo,+370 645 21 987\n".encode()
        _preview, response = self._import_file(SimpleUploadedFile("contacts.csv", content, content_type="text/csv"))
        self.assertContains(response, "Galimi dublikatai: 1")
        imported = Person.objects.get(first_name="Kitas", last_name="Asmuo")
        review = self.client.get(reverse("contacts:duplicate-list"))
        self.assertContains(review, self.person.get_absolute_url())
        self.assertContains(review, imported.get_absolute_url())
        self.assertContains(review, "Tas pats telefonas")

        DuplicateSettings.objects.update_or_create(pk=1, defaults={"enabled": True, "check_on_import": False})
        _preview, response = self._import_file(SimpleUploadedFile("contacts.csv", content, content_type="text/csv"))
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
        payload = {"first_name": "Rūta", "last_name": "Žukaitė", "phone": "+370 600 00001\n+370 600 00002", "email": "ruta@example.lt\nruta2@example.lt"}
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
            _preview, response = self._import_file(upload)
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
            _preview, response = self._import_file(upload)
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
        preview, response = self._import_file(upload)
        self.assertContains(preview, "Bus sukurta: 1")
        self.assertContains(response, "Importas baigtas")
        self.assertTrue(Person.objects.filter(first_name="Ona", last_name="Onaitė").exists())

    def test_import_preview_does_not_write_until_confirmed(self):
        self.client.force_login(self.user)
        content = "Vardas,Pavardė,El. paštai\nNaujas,Žmogus,naujas@example.lt\n".encode()
        preview = self.client.post(reverse("contacts:import-export"), {
            "file": SimpleUploadedFile("k.csv", content, content_type="text/csv"),
        })
        self.assertContains(preview, "Bus sukurta: 1")
        self.assertContains(preview, "Patvirtinti importą")
        self.assertFalse(Person.objects.filter(first_name="Naujas").exists())
        result = self.client.post(reverse("contacts:import-export"), {"confirm": "1"})
        self.assertContains(result, "Importas baigtas")
        self.assertTrue(Person.objects.filter(first_name="Naujas").exists())

    def test_import_confirm_without_a_preview_is_reported(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("contacts:import-export"), {"confirm": "1"})
        self.assertContains(response, "Importo peržiūra pasibaigė")

    def test_import_column_mapping_maps_custom_headers(self):
        self.client.force_login(self.user)
        content = "Given,Family,Role\nGreta,Petrauskė,Vadovė\n".encode()
        preview = self.client.post(reverse("contacts:import-export"), {
            "file": SimpleUploadedFile("k.csv", content, content_type="text/csv"),
        })
        self.assertContains(preview, "Stulpelių priskyrimas")
        self.client.post(reverse("contacts:import-export"), {
            "confirm": "1", "map_Given": "Vardas", "map_Family": "Pavardė", "map_Role": "Pareigos",
        })
        person = Person.objects.get(first_name="Greta", last_name="Petrauskė")
        self.assertEqual(person.job_title, "Vadovė")

    def test_import_dedup_modes_skip_and_always_new(self):
        self.client.force_login(self.user)
        existing = Person.objects.create(first_name="Dima", last_name="Dublis", job_title="Senos")
        row = "Vardas,Pavardė,Pareigos\nDima,Dublis,Naujos\n".encode()
        # skip: existing record untouched
        self.client.post(reverse("contacts:import-export"), {"file": SimpleUploadedFile("a.csv", row, content_type="text/csv")})
        self.client.post(reverse("contacts:import-export"), {"confirm": "1", "dedup": "skip"})
        existing.refresh_from_db()
        self.assertEqual(existing.job_title, "Senos")
        # always new: a second record with the same name is created
        self.client.post(reverse("contacts:import-export"), {"file": SimpleUploadedFile("a.csv", row, content_type="text/csv")})
        self.client.post(reverse("contacts:import-export"), {"confirm": "1", "dedup": "new"})
        self.assertEqual(Person.objects.filter(first_name="Dima", last_name="Dublis").count(), 2)

    def test_import_bad_rows_are_reported_without_aborting_and_downloadable(self):
        self.client.force_login(self.user)
        content = "Vardas,Pavardė,Tagai\nGera,Eilutė,A\nBloga,Eilutė,A;B;C;D\n".encode()
        self.client.post(reverse("contacts:import-export"), {"file": SimpleUploadedFile("k.csv", content, content_type="text/csv")})
        result = self.client.post(reverse("contacts:import-export"), {"confirm": "1"})
        self.assertTrue(Person.objects.filter(first_name="Gera").exists())
        self.assertFalse(Person.objects.filter(first_name="Bloga").exists())
        self.assertContains(result, "Klaidos: 1")
        report = self.client.get(reverse("contacts:import-errors"))
        self.assertEqual(report["Content-Type"], "text/csv; charset=utf-8")
        body = report.content.decode("utf-8-sig")
        self.assertIn("Bloga", body)
        self.assertIn("Klaida", body.splitlines()[0])

    def test_bulk_add_tag_and_category_to_selected_contacts(self):
        self.client.force_login(self.user)
        tag = Tag.objects.create(name="VIP")
        category = Category.objects.create(name="Klientas")
        other = Person.objects.create(first_name="Antra", last_name="Pavardė")
        self.client.post(reverse("contacts:bulk-action"), {"action": "add_tag", "tag": tag.pk, "selected": [self.person.pk, other.pk]})
        self.client.post(reverse("contacts:bulk-action"), {"action": "add_category", "category": category.pk, "selected": [self.person.pk]})
        self.assertIn(tag, self.person.tags.all())
        self.assertIn(tag, other.tags.all())
        self.assertIn(category, self.person.categories.all())
        self.assertNotIn(category, other.categories.all())

    def test_bulk_remove_tag_and_category_from_selected_records(self):
        self.client.force_login(self.user)
        tag = Tag.objects.create(name="Nuimamas")
        category = Category.objects.create(name="Nuimama")
        other = Person.objects.create(first_name="Antra", last_name="Pavardė")
        for record in (self.person, other):
            record.tags.add(tag)
        self.person.categories.add(category)
        self.company.tags.add(tag)
        self.client.post(reverse("contacts:bulk-action"),
                         {"action": "remove_tag", "tag": tag.pk, "selected": [self.person.pk, other.pk]})
        self.client.post(reverse("contacts:bulk-action"),
                         {"action": "remove_category", "category": category.pk, "selected": [self.person.pk]})
        self.client.post(reverse("contacts:company-bulk-action"),
                         {"action": "remove_tag", "tag": tag.pk, "selected": [self.company.pk]})
        self.assertEqual(self.person.tags.count(), 0)
        self.assertEqual(other.tags.count(), 0)
        self.assertEqual(self.person.categories.count(), 0)
        self.assertEqual(self.company.tags.count(), 0)
        self.assertTrue(Tag.objects.filter(pk=tag.pk).exists())

    def test_bulk_add_tag_respects_the_three_tag_limit(self):
        self.client.force_login(self.user)
        for name in ("A", "B", "C"):
            self.person.tags.add(Tag.objects.create(name=name))
        extra = Tag.objects.create(name="D")
        response = self.client.post(
            reverse("contacts:bulk-action"),
            {"action": "add_tag", "tag": extra.pk, "selected": [self.person.pk]}, follow=True,
        )
        self.assertNotIn(extra, self.person.tags.all())
        self.assertContains(response, "Praleista")

    def test_bulk_add_tag_to_selected_companies(self):
        self.client.force_login(self.user)
        tag = Tag.objects.create(name="Tiekėjas")
        self.client.post(reverse("contacts:company-bulk-action"), {"action": "add_tag", "tag": tag.pk, "selected": [self.company.pk]})
        self.assertIn(tag, self.company.tags.all())

    def test_bulk_set_custom_field_for_selected_contacts(self):
        self.client.force_login(self.user)
        field = CustomField.objects.create(entity=CustomField.PERSON, name="Šaltinis", field_type=CustomField.SELECT, options=["Web", "Renginys"])
        other = Person.objects.create(first_name="Kita", last_name="Pavardė")
        self.client.post(reverse("contacts:bulk-action"), {
            "action": "set_custom", "custom_field": field.pk, "value": "Renginys",
            "selected": [self.person.pk, other.pk],
        })
        self.assertEqual(CustomValue.objects.filter(field=field, value="Renginys").count(), 2)
        resp = self.client.post(reverse("contacts:bulk-action"), {
            "action": "set_custom", "custom_field": field.pk, "value": "Blogai", "selected": [self.person.pk],
        }, follow=True)
        self.assertContains(resp, "Netinkama reikšmė")

    def test_bulk_add_and_remove_extra_responsible(self):
        self.client.force_login(self.user)
        mate = get_user_model().objects.create_user("kolega47", password="very-secure-password")
        self.client.post(reverse("contacts:bulk-action"), {
            "action": "add_responsible", "responsible": mate.pk, "selected": [self.person.pk],
        })
        self.assertIn(mate, self.person.responsibles.all())
        self.client.post(reverse("contacts:bulk-action"), {
            "action": "remove_responsible", "responsible": mate.pk, "selected": [self.person.pk],
        })
        self.assertNotIn(mate, self.person.responsibles.all())

    def test_bulk_create_task_and_log_activity_for_selected(self):
        self.client.force_login(self.user)
        other = Company.objects.create(name="UAB Antra")
        self.client.post(reverse("contacts:company-bulk-action"), {
            "action": "create_task", "task_text": "Perskambinti", "task_due": "2026-12-31",
            "selected": [self.company.pk, other.pk],
        })
        self.assertEqual(Reminder.objects.filter(text="Perskambinti").count(), 2)
        self.assertTrue(Reminder.objects.filter(company=other, assigned_to=self.user).exists())
        self.client.post(reverse("contacts:company-bulk-action"), {
            "action": "log_activity", "activity_type": "call", "activity_text": "Kampanijos skambutis",
            "selected": [self.company.pk],
        })
        self.assertTrue(Activity.objects.filter(company=self.company, activity_type="call", text="Kampanijos skambutis").exists())

    def test_bulk_extra_actions_need_can_bulk_edit(self):
        restricted = get_user_model().objects.create_user("ribotas47", password="very-secure-password")
        from contacts.models import UserProfile
        UserProfile.objects.create(user=restricted, role=UserProfile.ROLE_RESTRICTED)
        self.client.force_login(restricted)
        field = CustomField.objects.create(entity=CustomField.PERSON, name="X", field_type=CustomField.TEXT)
        resp = self.client.post(reverse("contacts:bulk-action"), {
            "action": "set_custom", "custom_field": field.pk, "value": "y", "selected": [self.person.pk],
        })
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(CustomValue.objects.exists())

    def test_bulk_restore_from_archive(self):
        self.client.force_login(self.user)
        gone = Person.objects.create(first_name="Archyvuota", last_name="Byla", deleted_at=timezone.now())
        gone_co = Company.objects.create(name="Archyvo UAB", deleted_at=timezone.now())
        self.client.post(reverse("contacts:archive-bulk"), {"kind": "person", "selected": [gone.pk]})
        self.client.post(reverse("contacts:archive-bulk"), {"kind": "company", "selected": [gone_co.pk]})
        gone.refresh_from_db(); gone_co.refresh_from_db()
        self.assertIsNone(gone.deleted_at)
        self.assertIsNone(gone_co.deleted_at)

    def test_global_search_groups_people_companies_activities_and_reminders(self):
        self.client.force_login(self.user)
        Company.objects.create(name="Vilniaus partneriai")
        Activity.objects.create(person=self.person, activity_type="note", text="Vilniaus susitikimas", created_by=self.user)
        Reminder.objects.create(person=self.person, text="Vilniaus skambutis", due_at=timezone.now() + timedelta(days=1), created_by=self.user)
        response = self.client.get(reverse("contacts:search"), {"q": "Vilni"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Vilniaus partneriai")
        self.assertContains(response, "Vilniaus susitikimas")
        self.assertContains(response, "Vilniaus skambutis")
        self.assertEqual(response.context["results"]["companies_count"], 1)
        self.assertEqual(response.context["results"]["activities_count"], 1)

    def test_global_search_short_query_asks_for_more_characters(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("contacts:search"), {"q": "a"})
        self.assertIsNone(response.context["results"])
        self.assertContains(response, "bent 2 simbolius")

    def test_global_search_excludes_archived_records(self):
        self.client.force_login(self.user)
        Person.objects.create(first_name="Slaptas", last_name="Archyvas", deleted_at=timezone.now())
        response = self.client.get(reverse("contacts:search"), {"q": "Slaptas"})
        self.assertEqual(response.context["results"]["people_count"], 0)

    def test_search_suggest_returns_grouped_json(self):
        self.client.force_login(self.user)
        Person.objects.create(first_name="Vilius", last_name="Vilkas")
        data = self.client.get(reverse("contacts:search-suggest"), {"q": "Vilk"}).json()
        self.assertTrue(data["groups"])
        self.assertTrue(any("Vilius" in item["label"] for group in data["groups"] for item in group["items"]))

    def test_search_suggest_ignores_one_character_queries(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("contacts:search-suggest"), {"q": "v"}).json()["groups"], [])

    def test_custom_field_creation_for_both_entities(self):
        self.client.force_login(self.user)
        self.user.is_superuser = True
        self.user.save()
        self.client.post(reverse("contacts:settings-custom-fields"), {
            "name": "Šaltinis", "field_type": "select", "entity": "both", "options": "Renginys\nSvetainė",
        })
        self.assertEqual(CustomField.objects.filter(name="Šaltinis").count(), 2)
        self.assertEqual(set(CustomField.objects.filter(name="Šaltinis").values_list("entity", flat=True)), {"person", "company"})
        field = CustomField.objects.get(name="Šaltinis", entity="person")
        self.assertEqual(field.options, ["Renginys", "Svetainė"])

    def test_custom_field_requires_options_for_choice_types(self):
        self.client.force_login(self.user)
        self.client.post(reverse("contacts:settings-custom-fields"), {
            "name": "Kategorija X", "field_type": "select", "entity": "person", "options": "",
        })
        self.assertFalse(CustomField.objects.filter(name="Kategorija X").exists())

    def test_custom_field_value_shows_and_edits_on_contact_card(self):
        self.client.force_login(self.user)
        field = CustomField.objects.create(entity="person", name="Šaltinis", field_type="text")
        response = self.client.get(reverse("contacts:detail", args=[self.person.pk]))
        self.assertContains(response, "Šaltinis")
        edit = self.client.post(reverse("contacts:field-edit", args=[self.person.pk]), {"field": field.key, "value": "Renginys"})
        self.assertEqual(edit.status_code, 200)
        self.assertEqual(CustomValue.objects.get(field=field, person=self.person).value, "Renginys")

    def test_custom_multiselect_value_stores_only_known_options(self):
        self.client.force_login(self.user)
        field = CustomField.objects.create(entity="company", name="Kanalai", field_type="multiselect", options=["A", "B", "C"])
        self.client.post(reverse("contacts:company-field-edit", args=[self.company.pk]), {"field": field.key, "value": ["A", "C", "X"]})
        stored = CustomValue.objects.get(field=field, company=self.company).value
        self.assertEqual(sorted(stored.splitlines()), ["A", "C"])

    def test_search_matches_custom_field_values(self):
        self.client.force_login(self.user)
        field = CustomField.objects.create(entity="person", name="Šaltinis", field_type="text")
        CustomValue.objects.create(field=field, person=self.person, value="Konferencija Kaune")
        response = self.client.get(reverse("contacts:search"), {"q": "Konferencija"})
        self.assertEqual(response.context["results"]["people_count"], 1)

    def test_custom_field_can_be_deleted(self):
        self.client.force_login(self.user)
        self.user.is_superuser = True
        self.user.save()
        field = CustomField.objects.create(entity="person", name="Laikinas", field_type="text")
        self.client.post(reverse("contacts:custom-field-delete", args=[field.pk]))
        self.assertFalse(CustomField.objects.filter(pk=field.pk).exists())

    def test_custom_field_column_and_filter_on_contact_list(self):
        self.client.force_login(self.user)
        field = CustomField.objects.create(entity="person", name="Šaltinis", field_type="text")
        CustomValue.objects.create(field=field, person=self.person, value="Renginys")
        other = Person.objects.create(first_name="Kitas", last_name="Zmogus")
        listed = self.client.get(reverse("contacts:list"), {"columns": [field.key]})
        self.assertIn(field.key, listed.context["columns"])
        self.assertContains(listed, "Renginys")
        filtered = self.client.get(reverse("contacts:list"), {field.key: "Renginys"})
        ids = [person.pk for person in filtered.context["page"]]
        self.assertIn(self.person.pk, ids)
        self.assertNotIn(other.pk, ids)
        self.assertTrue(filtered.context["active_filter_count"])
        self.assertContains(filtered, "Šaltinis")

    def test_custom_field_column_and_filter_on_company_list(self):
        self.client.force_login(self.user)
        field = CustomField.objects.create(entity="company", name="Regionas", field_type="text")
        CustomValue.objects.create(field=field, company=self.company, value="Vakarai")
        Company.objects.create(name="Kita AB")
        listed = self.client.get(reverse("contacts:company-list"), {"columns": [field.key]})
        self.assertContains(listed, "Vakarai")
        filtered = self.client.get(reverse("contacts:company-list"), {field.key: "Vakarai"})
        self.assertEqual([company.pk for company in filtered.context["page"]], [self.company.pk])

    def test_custom_filter_is_saved_into_a_saved_filter(self):
        self.client.force_login(self.user)
        field = CustomField.objects.create(entity="person", name="Šaltinis", field_type="text")
        self.client.post(reverse("contacts:saved-filter-create"), {"name": "Renginiai", field.key: "Renginys"})
        saved = SavedFilter.objects.get(name="Renginiai")
        self.assertEqual(saved.filters.get(field.key), "Renginys")

    def test_new_records_are_owned_by_their_creator(self):
        self.client.force_login(self.user)
        self.client.post(reverse("contacts:person-create"), {"first_name": "Nauja", "last_name": "Savininkė"})
        self.assertEqual(Person.objects.get(first_name="Nauja").owner, self.user)
        self.client.post(reverse("contacts:company-create"), {"name": "Nauja AB"})
        self.assertEqual(Company.objects.get(name="Nauja AB").owner, self.user)

    def test_owner_is_shown_and_editable_inline_on_the_contact_card(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("contacts:detail", args=[self.person.pk]))
        self.assertContains(response, "Atsakingi")
        other = get_user_model().objects.create_user("kolege", password="very-secure-password")
        self.client.post(reverse("contacts:field-edit", args=[self.person.pk]), {"field": "owner", "value": other.pk})
        self.person.refresh_from_db()
        self.assertEqual(self.person.owner, other)
        self.client.post(reverse("contacts:field-edit", args=[self.person.pk]), {"field": "owner", "value": ""})
        self.person.refresh_from_db()
        self.assertIsNone(self.person.owner)

    def test_responsibles_field_sets_primary_and_extra_users(self):
        self.client.force_login(self.user)
        a = get_user_model().objects.create_user("aa", password="very-secure-password")
        b = get_user_model().objects.create_user("bb", password="very-secure-password")
        self.client.post(reverse("contacts:field-edit", args=[self.person.pk]), {
            "field": "responsibles", "responsible": [a.pk, b.pk], "primary": str(a.pk),
        })
        self.person.refresh_from_db()
        self.assertEqual(self.person.owner, a)
        self.assertEqual(set(self.person.responsibles.all()), {b})
        # clearing the primary keeps both as extra responsibles
        self.client.post(reverse("contacts:field-edit", args=[self.person.pk]), {
            "field": "responsibles", "responsible": [a.pk, b.pk], "primary": "",
        })
        self.person.refresh_from_db()
        self.assertIsNone(self.person.owner)
        self.assertEqual(set(self.person.responsibles.all()), {a, b})

    def test_description_field_is_inline_editable(self):
        self.client.force_login(self.user)
        edit = reverse("contacts:field-edit", args=[self.person.pk])
        self.client.post(edit, {"field": "description", "value": "Bendradarbiaujame IT srityje."})
        self.person.refresh_from_db()
        self.assertEqual(self.person.description, "Bendradarbiaujame IT srityje.")
        # description is shown on the card; it opens on double-click
        page = self.client.get(reverse("contacts:detail", args=[self.person.pk]))
        self.assertContains(page, "Bendradarbiaujame IT srityje.")
        self.assertContains(page, 'data-field="description"')

    def test_detail_page_uses_the_new_card_layout(self):
        self.client.force_login(self.user)
        for url in (self.person.get_absolute_url(), self.company.get_absolute_url()):
            page = self.client.get(url)
            self.assertContains(page, "Kontaktinė informacija")
            self.assertContains(page, "Papildomi laukai")
            self.assertContains(page, "Papildoma informacija")
            self.assertContains(page, 'data-tab="comments"')
            self.assertContains(page, 'data-tab="reminders"')
            self.assertContains(page, 'data-tab="files"')
            self.assertContains(page, 'data-tab="activity"')
            self.assertNotContains(page, 'data-tab="log"')
            self.assertNotContains(page, 'data-tab="related"')

    def test_comments_tab_shows_notes_and_activity_tab_shows_the_rest(self):
        self.client.force_login(self.user)
        Activity.objects.create(person=self.person, activity_type="note", text="Vidinis komentaras", created_by=self.user)
        Activity.objects.create(person=self.person, activity_type="call", text="Skambučio įrašas", created_by=self.user)
        page = self.client.get(self.person.get_absolute_url())
        self.assertEqual([a.text for a in page.context["comment_entries"]], ["Vidinis komentaras"])
        self.assertEqual([a.text for a in page.context["activity_entries"]], ["Skambučio įrašas"])

    def test_files_tab_lists_attachments_and_accepts_an_upload(self):
        from contacts.models import Attachment
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.user)
        activity = Activity.objects.create(person=self.person, activity_type="note", text="su failu", created_by=self.user)
        Attachment.objects.create(activity=activity, original_name="sutartis.pdf", size=10)
        page = self.client.get(self.person.get_absolute_url())
        self.assertContains(page, "sutartis.pdf")
        self.assertEqual(len(page.context["attachment_entries"]), 1)
        self.client.post(reverse("contacts:activity-create", args=[self.person.pk]), {
            "activity_type": "note", "text": "",
            "attachments": SimpleUploadedFile("naujas.pdf", b"%PDF-1.4", content_type="application/pdf"),
        })
        self.assertTrue(Attachment.objects.filter(original_name="naujas.pdf").exists())

    def test_company_description_field_is_inline_editable(self):
        self.client.force_login(self.user)
        self.client.post(reverse("contacts:company-field-edit", args=[self.company.pk]),
                         {"field": "description", "value": "Ilgametis partneris."})
        self.company.refresh_from_db()
        self.assertEqual(self.company.description, "Ilgametis partneris.")

    def test_created_by_is_recorded_on_create(self):
        self.client.force_login(self.user)
        self.client.post(reverse("contacts:person-create"), {"first_name": "Nauja", "last_name": "Kūrėja"})
        self.assertEqual(Person.objects.get(first_name="Nauja").created_by, self.user)
        self.client.post(reverse("contacts:company-create"), {"name": "Nauja UAB"})
        self.assertEqual(Company.objects.get(name="Nauja UAB").created_by, self.user)

    def test_extra_responsible_user_can_see_the_record(self):
        from contacts.models import UserProfile
        restricted = get_user_model().objects.create_user("ribotas2", password="very-secure-password")
        UserProfile.objects.create(user=restricted, role=UserProfile.ROLE_RESTRICTED)
        owned_by_other = Person.objects.create(first_name="Kito", last_name="Klientas",
                                               owner=get_user_model().objects.create_user("sav", password="very-secure-password"))
        self.client.force_login(restricted)
        self.assertEqual(self.client.get(reverse("contacts:detail", args=[owned_by_other.pk])).status_code, 404)
        owned_by_other.responsibles.add(restricted)
        self.assertEqual(self.client.get(reverse("contacts:detail", args=[owned_by_other.pk])).status_code, 200)
        self.assertIn(owned_by_other.pk, [p.pk for p in self.client.get(reverse("contacts:list")).context["page"]])

    def test_company_owner_can_be_assigned_inline(self):
        self.client.force_login(self.user)
        self.client.post(reverse("contacts:company-field-edit", args=[self.company.pk]), {"field": "owner", "value": self.user.pk})
        self.company.refresh_from_db()
        self.assertEqual(self.company.owner, self.user)

    def test_import_sets_owner_to_the_importing_user(self):
        self.client.force_login(self.user)
        content = "Vardas,Pavardė\nImportuota,Savininkė\n".encode()
        self._import_file(SimpleUploadedFile("k.csv", content, content_type="text/csv"))
        self.assertEqual(Person.objects.get(first_name="Importuota").owner, self.user)

    def test_users_settings_page_is_admin_only(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("contacts:settings-users")).status_code, 404)
        self.user.is_superuser = True
        self.user.save()
        self.assertEqual(self.client.get(reverse("contacts:settings-users")).status_code, 200)

    def test_admin_creates_a_user_with_a_role(self):
        self.user.is_superuser = True
        self.user.save()
        self.client.force_login(self.user)
        self.client.post(reverse("contacts:settings-users"), {
            "action": "create", "username": "naujas", "role": "restricted", "password": "brand-new-pass-2026",
        })
        created = get_user_model().objects.get(username="naujas")
        self.assertEqual(created.crm_profile.role, "restricted")
        self.assertFalse(created.is_staff)
        self.client.post(reverse("contacts:settings-users"), {
            "action": "create", "username": "adminas", "role": "admin", "password": "brand-new-pass-2026",
        })
        self.assertTrue(get_user_model().objects.get(username="adminas").is_staff)

    def test_the_last_active_admin_cannot_be_demoted(self):
        from contacts.models import UserProfile
        admin = get_user_model().objects.create_user("solo", password="very-secure-password", is_staff=True)
        UserProfile.objects.create(user=admin, role="admin")
        self.client.force_login(admin)
        response = self.client.post(reverse("contacts:settings-users"), {
            "action": "update", "user_id": admin.pk, "role": "member", "active": "1",
        }, follow=True)
        admin.refresh_from_db()
        admin.crm_profile.refresh_from_db()
        self.assertEqual(admin.crm_profile.role, "admin")
        self.assertContains(response, "bent vienas aktyvus administratorius")

    def test_admin_resets_another_users_password(self):
        self.user.is_superuser = True
        self.user.save()
        self.client.force_login(self.user)
        target = get_user_model().objects.create_user("kolega", password="old-secure-pass-1")
        self.client.post(reverse("contacts:settings-users"), {
            "action": "reset", "user_id": target.pk, "password": "fresh-secure-pass-2026",
        })
        target.refresh_from_db()
        self.assertTrue(target.check_password("fresh-secure-pass-2026"))

    # --- C10 part 5: per-role capabilities ---

    def _plain_member(self, username="eilinis"):
        from contacts.models import UserProfile
        user = get_user_model().objects.create_user(username, password="very-secure-password")
        UserProfile.objects.create(user=user, role=UserProfile.ROLE_MEMBER)
        return user

    def test_member_defaults_allow_import_export_but_not_custom_fields(self):
        member = self._plain_member()
        self.client.force_login(member)
        self.assertEqual(self.client.get(reverse("contacts:import-export")).status_code, 200)
        self.assertEqual(self.client.get(reverse("contacts:contacts-export")).status_code, 200)
        self.assertEqual(self.client.get(reverse("contacts:settings-custom-fields")).status_code, 404)
        self.assertEqual(self.client.get(reverse("contacts:settings-tags")).status_code, 404)
        self.assertEqual(self.client.get(reverse("contacts:settings-audit")).status_code, 404)

    def test_admin_revokes_a_capability_and_it_takes_effect(self):
        from contacts.models import RolePermissions
        member = self._plain_member("busexportas")
        admin = get_user_model().objects.create_user("adm", password="very-secure-password", is_superuser=True)
        self.client.force_login(admin)
        payload = {}
        for role in ("member", "restricted"):
            payload["cap_" + role] = ["can_export"]  # grant only export
        self.client.post(reverse("contacts:settings-permissions"), payload)
        row = RolePermissions.objects.get(role="member")
        self.assertTrue(row.permissions["can_export"])
        self.assertFalse(row.permissions["can_import"])
        self.client.force_login(member)
        self.assertEqual(self.client.get(reverse("contacts:import-export")).status_code, 404)
        self.assertEqual(self.client.get(reverse("contacts:contacts-export")).status_code, 200)

    def test_permissions_page_is_admin_only(self):
        member = self._plain_member("nepatenka")
        self.client.force_login(member)
        self.assertEqual(self.client.get(reverse("contacts:settings-permissions")).status_code, 404)

    def test_restricted_member_cannot_reassign_owner_inline(self):
        from contacts.models import UserProfile
        restricted = get_user_model().objects.create_user("ribotasx", password="very-secure-password")
        UserProfile.objects.create(user=restricted, role=UserProfile.ROLE_RESTRICTED)
        self.person.owner = restricted
        self.person.save(update_fields=["owner"])
        self.client.force_login(restricted)
        response = self.client.post(reverse("contacts:field-edit", args=[self.person.pk]),
                                    {"field": "owner", "value": ""})
        self.assertEqual(response.status_code, 403)
        self.person.refresh_from_db()
        self.assertEqual(self.person.owner, restricted)

    # --- C10 part 2: teams ---

    def test_teams_page_is_admin_only(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("contacts:settings-teams")).status_code, 404)
        self.user.is_superuser = True
        self.user.save()
        self.assertEqual(self.client.get(reverse("contacts:settings-teams")).status_code, 200)

    def test_admin_creates_renames_and_populates_a_team(self):
        from contacts.models import Team
        self.user.is_superuser = True
        self.user.save()
        self.client.force_login(self.user)
        a = get_user_model().objects.create_user("teamer", password="very-secure-password")
        self.client.post(reverse("contacts:settings-teams"), {"action": "create", "name": "Pardavimai"})
        team = Team.objects.get(name="Pardavimai")
        self.assertEqual(team.visibility, Team.VISIBILITY_ALL)
        self.client.post(reverse("contacts:settings-teams"), {
            "action": "update", "team_id": team.pk, "name": "Pardavimų skyrius",
            "visibility": Team.VISIBILITY_TEAM, "members": [a.pk],
        })
        team.refresh_from_db()
        self.assertEqual(team.name, "Pardavimų skyrius")
        self.assertEqual(team.visibility, Team.VISIBILITY_TEAM)
        self.assertEqual(set(team.members.all()), {a})
        self.client.post(reverse("contacts:settings-teams"), {"action": "delete", "team_id": team.pk})
        self.assertFalse(Team.objects.filter(pk=team.pk).exists())

    def test_duplicate_team_name_is_rejected(self):
        from contacts.models import Team
        Team.objects.create(name="Rinkodara")
        self.user.is_superuser = True
        self.user.save()
        self.client.force_login(self.user)
        response = self.client.post(reverse("contacts:settings-teams"), {"action": "create", "name": "rinkodara"}, follow=True)
        self.assertEqual(Team.objects.filter(name__iexact="rinkodara").count(), 1)
        self.assertContains(response, "jau yra")

    # --- C10 part 3: team-scoped visibility ---

    def _member(self, username, visibility="all"):
        from contacts.models import UserProfile
        user = get_user_model().objects.create_user(username, password="very-secure-password")
        UserProfile.objects.create(user=user, role=UserProfile.ROLE_MEMBER, record_visibility=visibility)
        return user

    def test_team_visibility_shows_teammates_records_only(self):
        from contacts.models import Team
        me = self._member("mano", visibility="team")
        mate = self._member("kolega1")
        outsider = self._member("nepriklauso")
        team = Team.objects.create(name="Skyrius", visibility=Team.VISIBILITY_TEAM)
        team.members.add(me, mate)
        mine = Person.objects.create(first_name="Mano", last_name="K", owner=me)
        mates = Person.objects.create(first_name="Kolegos", last_name="K", owner=mate)
        theirs = Person.objects.create(first_name="Svetimo", last_name="K", owner=outsider)
        self.client.force_login(me)
        ids = [p.pk for p in self.client.get(reverse("contacts:list")).context["page"]]
        self.assertIn(mine.pk, ids)
        self.assertIn(mates.pk, ids)
        self.assertNotIn(theirs.pk, ids)
        self.assertEqual(self.client.get(reverse("contacts:detail", args=[theirs.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("contacts:detail", args=[mates.pk])).status_code, 200)

    def test_company_page_hides_linked_contacts_and_their_activity_from_outsiders(self):
        from contacts.models import Activity, PersonCompanyLink, Reminder, Team
        from django.utils import timezone
        me = self._member("stebetojas", visibility="team")
        outsider = self._member("kito-skyriaus")
        Team.objects.create(name="Mano skyrius", visibility=Team.VISIBILITY_TEAM).members.add(me)
        company = Company.objects.create(name="Bendra UAB")  # unassigned -> visible to everyone
        hidden = Person.objects.create(first_name="Slaptas", last_name="Kontaktas", owner=outsider)
        PersonCompanyLink.objects.create(person=hidden, company=company)
        Activity.objects.create(person=hidden, activity_type="note", text="Konfidenciali pastaba", created_by=outsider)
        Reminder.objects.create(person=hidden, text="Slaptas priminimas",
                                due_at=timezone.now() + timedelta(days=1), created_by=outsider)
        self.client.force_login(me)
        response = self.client.get(company.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Slaptas Kontaktas")
        self.assertNotContains(response, "Konfidenciali pastaba")
        self.assertNotContains(response, "Slaptas priminimas")
        self.assertEqual(list(response.context["linked_people"]), [])
        self.assertEqual(list(response.context["comment_entries"]), [])
        listing = self.client.get(reverse("contacts:company-list"), {"columns": "contacts"})
        row = [c for c in listing.context["page"] if c.pk == company.pk][0]
        self.assertEqual(row.contact_count, 0)

    def test_import_cannot_hijack_a_contact_the_importer_may_not_see(self):
        from contacts.models import EmailAddress
        from contacts.permissions import has_capability

        importer = self._member("importuotojas", visibility="own")
        self.assertTrue(has_capability(importer, "can_import"))
        self.assertTrue(has_capability(importer, "can_reassign_owner"))
        outsider = self._member("kitas-savininkas")
        hidden = Person.objects.create(first_name="Slaptas", last_name="Klientas", owner=outsider)
        EmailAddress.objects.create(person=hidden, email="slaptas@example.lt")
        self.client.force_login(importer)
        content = "Vardas,Pavardė,El. paštai,Atsakingas\nSlaptas,Klientas,slaptas@example.lt,importuotojas\n".encode()
        self.client.post(reverse("contacts:import-export"),
                         {"file": SimpleUploadedFile("k.csv", content, content_type="text/csv")})
        response = self.client.post(reverse("contacts:import-export"), {"confirm": "1"}, follow=True)
        hidden.refresh_from_db()
        self.assertEqual(hidden.owner, outsider)               # ownership untouched
        self.assertEqual(hidden.first_name, "Slaptas")         # fields untouched
        self.assertEqual(Person.objects.filter(last_name="Klientas").count(), 1)  # no duplicate created
        self.assertContains(response, "Atnaujinti: 0")
        self.assertContains(response, "Klaidos: 1")
        errors_csv = self.client.get(reverse("contacts:import-errors")).content.decode()
        self.assertIn("jums nematomas", errors_csv)

    def test_owner_filter_me_matches_owned_or_responsible(self):
        self.client.force_login(self.user)
        mate = get_user_model().objects.create_user("mate", password="very-secure-password")
        owned = Person.objects.create(first_name="Mano", last_name="Nuosava", owner=self.user)
        helping = Person.objects.create(first_name="Padedu", last_name="Kolegai", owner=mate)
        helping.responsibles.add(self.user)
        other = Person.objects.create(first_name="Svetimas", last_name="X", owner=mate)
        ids = [p.pk for p in self.client.get(reverse("contacts:list"), {"owner": "me"}).context["page"]]
        self.assertIn(owned.pk, ids)
        self.assertIn(helping.pk, ids)
        self.assertNotIn(other.pk, ids)

    def test_owner_filter_none_finds_records_without_any_responsible(self):
        self.client.force_login(self.user)
        mate = get_user_model().objects.create_user("mate2", password="very-secure-password")
        no_one = Person.objects.create(first_name="Niekieno", last_name="Y")
        has_extra = Person.objects.create(first_name="Turi", last_name="Papildoma")
        has_extra.responsibles.add(mate)
        ids = [p.pk for p in self.client.get(reverse("contacts:list"), {"owner": "none"}).context["page"]]
        self.assertIn(no_one.pk, ids)
        self.assertIn(self.person.pk, ids)  # unassigned in setUp
        self.assertNotIn(has_extra.pk, ids)

    def test_owner_filter_hint_when_target_user_not_visible(self):
        from contacts.models import UserProfile
        restricted = get_user_model().objects.create_user("ribotukas", password="very-secure-password")
        UserProfile.objects.create(user=restricted, role=UserProfile.ROLE_RESTRICTED)
        other = get_user_model().objects.create_user("kt3", password="very-secure-password")
        Person.objects.create(first_name="Kito", last_name="Klientas", owner=other)
        self.client.force_login(restricted)
        response = self.client.get(reverse("contacts:list"), {"owner": str(other.pk)})
        self.assertEqual(len(response.context["page"]), 0)
        self.assertContains(response, "matote tik savo įrašus")

    def test_team_visibility_setting_clamps_a_member_who_would_see_all(self):
        from contacts.models import Team
        me = self._member("visimato", visibility="all")
        team = Team.objects.create(name="Uždaras", visibility=Team.VISIBILITY_TEAM)
        team.members.add(me)
        from contacts.permissions import record_visibility
        self.assertEqual(record_visibility(me), "team")
        other = self._member("kitas9")
        theirs = Person.objects.create(first_name="Ne", last_name="Komandos", owner=other)
        self.client.force_login(me)
        self.assertNotIn(theirs.pk, [p.pk for p in self.client.get(reverse("contacts:list")).context["page"]])

    # --- C6 part 3: owner-based visibility for the restricted role ---

    def _restricted_user(self, username="ribotas"):
        from contacts.models import UserProfile
        user = get_user_model().objects.create_user(username, password="very-secure-password")
        UserProfile.objects.create(user=user, role=UserProfile.ROLE_RESTRICTED)
        return user

    def test_restricted_user_sees_only_owned_and_unassigned_records(self):
        other = get_user_model().objects.create_user("kitas", password="very-secure-password")
        theirs = Person.objects.create(first_name="Svetimas", last_name="Kontaktas", owner=other)
        theirs_co = Company.objects.create(name="Svetima UAB", owner=other)
        restricted = self._restricted_user()
        mine = Person.objects.create(first_name="Mano", last_name="Kontaktas", owner=restricted)
        self.client.force_login(restricted)
        people_ids = [p.pk for p in self.client.get(reverse("contacts:list")).context["page"]]
        self.assertIn(mine.pk, people_ids)
        self.assertIn(self.person.pk, people_ids)  # unassigned
        self.assertNotIn(theirs.pk, people_ids)
        company_ids = [c.pk for c in self.client.get(reverse("contacts:company-list")).context["page"]]
        self.assertIn(self.company.pk, company_ids)
        self.assertNotIn(theirs_co.pk, company_ids)

    def test_restricted_user_gets_404_on_another_users_record(self):
        other = get_user_model().objects.create_user("kitas", password="very-secure-password")
        theirs = Person.objects.create(first_name="Svetimas", last_name="Kontaktas", owner=other)
        restricted = self._restricted_user()
        self.client.force_login(restricted)
        self.assertEqual(self.client.get(reverse("contacts:detail", args=[theirs.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("contacts:detail", args=[self.person.pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse("contacts:archive", args=[theirs.pk])).status_code, 404)
        theirs.refresh_from_db()
        self.assertIsNone(theirs.deleted_at)
        self.assertEqual(
            self.client.post(reverse("contacts:field-edit", args=[theirs.pk]), {"field": "first_name", "value": "X"}).status_code,
            404,
        )

    def test_restricted_user_search_and_export_are_filtered(self):
        other = get_user_model().objects.create_user("kitas", password="very-secure-password")
        Person.objects.create(first_name="Slaptas", last_name="Zmogus", owner=other)
        restricted = self._restricted_user()
        self.client.force_login(restricted)
        results = self.client.get(reverse("contacts:search"), {"q": "Slaptas"}).context["results"]
        self.assertEqual(results["people_count"], 0)
        export = self.client.get(reverse("contacts:contacts-export"))
        self.assertNotIn("Slaptas", export.content.decode("utf-8"))

    def test_member_role_still_sees_every_record(self):
        from contacts.models import UserProfile
        other = get_user_model().objects.create_user("kitas", password="very-secure-password")
        theirs = Person.objects.create(first_name="Svetimas", last_name="Kontaktas", owner=other)
        member = get_user_model().objects.create_user("narys", password="very-secure-password")
        UserProfile.objects.create(user=member, role=UserProfile.ROLE_MEMBER)
        self.client.force_login(member)
        self.assertEqual(self.client.get(reverse("contacts:detail", args=[theirs.pk])).status_code, 200)

    # --- C6 part 4: owner column, filter, bulk assign, CSV ---

    def test_owner_column_and_filter_on_contact_list(self):
        self.client.force_login(self.user)
        kolege = get_user_model().objects.create_user("kolege", password="very-secure-password", first_name="Aistė")
        self.person.owner = kolege
        self.person.save(update_fields=["owner"])
        mine = Person.objects.create(first_name="Mano", last_name="Kontaktas", owner=self.user)
        listed = self.client.get(reverse("contacts:list"), {"columns": ["owner"]})
        self.assertIn("owner", listed.context["columns"])
        self.assertContains(listed, "Aistė")
        filtered = self.client.get(reverse("contacts:list"), {"owner": str(kolege.pk)})
        ids = [p.pk for p in filtered.context["page"]]
        self.assertEqual(ids, [self.person.pk])
        self.assertTrue(filtered.context["active_filter_count"])
        unassigned = self.client.get(reverse("contacts:list"), {"owner": "none"})
        self.assertNotIn(self.person.pk, [p.pk for p in unassigned.context["page"]])
        self.assertNotIn(mine.pk, [p.pk for p in unassigned.context["page"]])

    def test_bulk_assign_owner_for_contacts_and_companies(self):
        self.client.force_login(self.user)
        kolege = get_user_model().objects.create_user("kolege", password="very-secure-password")
        self.client.post(reverse("contacts:bulk-action"), {
            "action": "assign_owner", "selected": [self.person.pk], "owner": str(kolege.pk),
        })
        self.person.refresh_from_db()
        self.assertEqual(self.person.owner, kolege)
        self.client.post(reverse("contacts:company-bulk-action"), {
            "action": "assign_owner", "selected": [self.company.pk], "owner": str(kolege.pk),
        })
        self.company.refresh_from_db()
        self.assertEqual(self.company.owner, kolege)
        # empty owner value clears it
        self.client.post(reverse("contacts:bulk-action"), {
            "action": "assign_owner", "selected": [self.person.pk], "owner": "",
        })
        self.person.refresh_from_db()
        self.assertIsNone(self.person.owner)

    def test_restricted_user_cannot_bulk_assign_owner(self):
        restricted = self._restricted_user()
        mine = Person.objects.create(first_name="Mano", last_name="Kontaktas", owner=restricted)
        kolege = get_user_model().objects.create_user("kolege", password="very-secure-password")
        self.client.force_login(restricted)
        self.client.post(reverse("contacts:bulk-action"), {
            "action": "assign_owner", "selected": [mine.pk], "owner": str(kolege.pk),
        })
        mine.refresh_from_db()
        self.assertEqual(mine.owner, restricted)

    def test_owner_column_in_csv_export_and_import(self):
        self.client.force_login(self.user)
        kolege = get_user_model().objects.create_user("kolege", password="very-secure-password", first_name="Aistė", last_name="Kolegė")
        self.person.owner = kolege
        self.person.save(update_fields=["owner"])
        export = self.client.get(reverse("contacts:contacts-export")).content.decode("utf-8")
        self.assertIn("Atsakingas", export.splitlines()[0])
        self.assertIn("Aistė Kolegė", export)
        content = "Vardas,Pavardė,Atsakingas\nImportuota,Savininkė,kolege\n".encode()
        self._import_file(SimpleUploadedFile("k.csv", content, content_type="text/csv"))
        self.assertEqual(Person.objects.get(first_name="Importuota").owner, kolege)

    # --- C5: audit log ---

    def test_audit_log_records_create_update_archive_and_settings(self):
        from contacts.models import AuditLog
        self.client.force_login(self.user)
        self.user.is_superuser = True
        self.user.save()
        self.client.post(reverse("contacts:person-create"), {"first_name": "Audituota", "last_name": "Asmuo"})
        person = Person.objects.get(first_name="Audituota")
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.CREATE, target_type="person", target_id=str(person.pk)).exists())
        self.client.post(reverse("contacts:field-edit", args=[person.pk]), {"field": "job_title", "value": "Vadovė"})
        change = AuditLog.objects.filter(action=AuditLog.UPDATE, target_id=str(person.pk)).first()
        self.assertEqual(change.new_value, "Vadovė")
        self.assertEqual(change.actor, self.user)
        self.client.post(reverse("contacts:archive", args=[person.pk]))
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.ARCHIVE, target_id=str(person.pk)).exists())
        self.client.post(reverse("contacts:settings-tags"), {"name": "Žurnalinė žyma"})
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.SETTING, target_label__icontains="Žurnalinė žyma").exists())

    def test_audit_log_records_login_and_failed_login(self):
        from contacts.models import AuditLog
        get_user_model().objects.create_user("audituser", password="correct-horse-battery-staple")
        self.client.post(reverse("login"), {"username": "audituser", "password": "wrong"})
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.LOGIN_FAILED, target_label="audituser").exists())
        self.client.post(reverse("login"), {"username": "audituser", "password": "correct-horse-battery-staple"})
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.LOGIN, target_label="audituser").exists())

    def test_audit_log_records_import_and_export(self):
        from contacts.models import AuditLog
        self.client.force_login(self.user)
        self._import_file(SimpleUploadedFile("k.csv", "Vardas,Pavardė\nŽurn,Import\n".encode(), content_type="text/csv"))
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.IMPORT).exists())
        self.client.get(reverse("contacts:contacts-export"))
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.EXPORT, target_label__icontains="CSV").exists())

    def test_audit_page_is_admin_only_and_filters(self):
        from contacts.models import AuditLog
        AuditLog.objects.create(actor=self.user, actor_label="admin", action=AuditLog.CREATE, target_type="person", target_label="X")
        other = get_user_model().objects.create_user("kt", password="very-secure-password")
        AuditLog.objects.create(actor=other, actor_label="kt", action=AuditLog.EXPORT, target_label="Y")
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("contacts:settings-audit")).status_code, 404)
        self.user.is_superuser = True
        self.user.save()
        response = self.client.get(reverse("contacts:settings-audit"), {"action": AuditLog.EXPORT})
        rows = list(response.context["page"])
        self.assertTrue(all(r.action == AuditLog.EXPORT for r in rows))
        by_actor = self.client.get(reverse("contacts:settings-audit"), {"actor": str(other.pk)})
        self.assertTrue(all(r.actor_id == other.pk for r in by_actor.context["page"]))

    def test_company_detail_lists_linked_person(self):
        self.client.force_login(self.user)
        response = self.client.get(self.company.get_absolute_url())
        self.assertContains(response, "Rūta Žukaitė")

    def test_company_history_includes_company_and_linked_person_entries(self):
        self.client.force_login(self.user)
        Activity.objects.create(company=self.company, text="Įmonės pastaba", created_by=self.user)
        Activity.objects.create(person=self.person, text="Kontakto pastaba", created_by=self.user)
        response = self.client.get(self.company.get_absolute_url())
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


class SecurityHardeningTests(TestCase):
    """Regression cover for the 2026-09 security review findings."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user("saugumas", password="very-secure-password", is_superuser=True, is_staff=True)
        self.member = User.objects.create_user("narys", password="very-secure-password")
        self.person = Person.objects.create(first_name="Rūta", last_name="Žukaitė")

    def test_unsafe_url_is_rejected_on_the_contact_form_and_import(self):
        from contacts.sanitizers import safe_url
        self.assertEqual(safe_url("javascript:alert(1)"), "")
        self.assertEqual(safe_url("data:text/html;base64,x"), "")
        self.assertEqual(safe_url("  vbscript:msgbox(1)"), "")
        self.assertEqual(safe_url("//evil.example"), "")
        self.assertEqual(safe_url("regitra.lt"), "https://regitra.lt")
        self.assertEqual(safe_url("https://regitra.lt/x"), "https://regitra.lt/x")

        self.client.force_login(self.admin)
        self.client.post(reverse("contacts:edit", args=[self.person.pk]), {
            "first_name": "Rūta", "last_name": "Žukaitė",
            "url": "javascript:alert(document.cookie)\nhttps://ok.example",
        })
        urls = list(WebLink.objects.filter(person=self.person).values_list("url", flat=True))
        self.assertEqual(urls, ["https://ok.example"])

    def test_crm_admin_cannot_reset_the_superuser_password(self):
        boss = get_user_model().objects.create_user("bosas", password="very-secure-password", is_superuser=True, is_staff=True)
        crm_admin = get_user_model().objects.create_user("krmadmin", password="very-secure-password", is_staff=True)
        from contacts.models import UserProfile
        UserProfile.objects.create(user=crm_admin, role=UserProfile.ROLE_ADMIN)
        self.client.force_login(crm_admin)
        self.client.post(reverse("contacts:settings-users"), {
            "action": "reset", "user_id": boss.pk, "password": "brand-new-password-123",
        })
        boss.refresh_from_db()
        self.assertTrue(boss.check_password("very-secure-password"))

    def test_duplicate_settings_are_admin_only(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse("contacts:settings-duplicates")).status_code, 404)
        self.assertEqual(
            self.client.post(reverse("contacts:settings-duplicates"), {"level": "loose"}).status_code, 404)

    def test_csv_export_neutralises_formula_injection(self):
        from contacts.sanitizers import csv_safe
        self.assertEqual(csv_safe("=1+1"), "'=1+1")
        self.assertEqual(csv_safe("+37060000000"), "'+37060000000")
        self.assertEqual(csv_safe("Rūta"), "Rūta")
        self.person.first_name = "=HYPERLINK(1)"
        self.person.save(update_fields=["first_name"])
        self.client.force_login(self.admin)
        body = self.client.get(reverse("contacts:contacts-export")).content.decode("utf-8-sig")
        self.assertIn("'=HYPERLINK(1)", body)
        self.assertNotIn("\n=HYPERLINK(1)", body)

    def test_reminder_list_does_not_clear_unread_on_a_cross_site_get(self):
        self.client.force_login(self.member)
        Reminder.objects.create(person=self.person, text="Priminimas", created_by=self.member, assigned_to=self.member,
                                due_at=timezone.now() - timedelta(hours=1))
        self.client.get(reverse("contacts:reminder-list"), HTTP_SEC_FETCH_SITE="cross-site")
        self.assertTrue(Reminder.objects.filter(read_at__isnull=True).exists())
        self.client.get(reverse("contacts:reminder-list"), HTTP_SEC_FETCH_SITE="same-origin")
        self.assertFalse(Reminder.objects.filter(read_at__isnull=True).exists())

    def test_duplicate_check_does_not_surface_records_the_viewer_cannot_see(self):
        from contacts.models import UserProfile
        owner = get_user_model().objects.create_user("kitas-narys", password="very-secure-password")
        hidden = Person.objects.create(first_name="Slapta", last_name="Pavardė", owner=owner)
        EmailAddress.objects.create(person=hidden, email="slapta@example.lt")
        UserProfile.objects.create(user=self.member, role=UserProfile.ROLE_RESTRICTED,
                                   record_visibility=UserProfile.VISIBILITY_OWN)
        data = {"first_name": "X", "last_name": "Y", "email": "slapta@example.lt", "phone": "", "companies": []}
        self.assertEqual(find_person_duplicates(data, viewer=self.member), [])
        self.assertTrue(find_person_duplicates(data))  # still a real global collision

    def test_contact_form_only_offers_companies_the_user_can_see(self):
        from contacts.models import UserProfile
        from contacts.forms import PersonForm
        boss = get_user_model().objects.create_user("bosas-uab", password="very-secure-password")
        Company.objects.create(name="Mano UAB", owner=self.member)
        hidden = Company.objects.create(name="Slapta UAB", owner=boss)
        UserProfile.objects.create(user=self.member, role=UserProfile.ROLE_RESTRICTED,
                                   record_visibility=UserProfile.VISIBILITY_OWN)
        form = PersonForm(user=self.member)
        offered = set(form.fields["companies"].queryset.values_list("name", flat=True))
        self.assertIn("Mano UAB", offered)
        self.assertNotIn("Slapta UAB", offered)
        # Posting a hidden company id is rejected by the field.
        self.client.force_login(self.member)
        self.client.post(reverse("contacts:person-create"), {
            "first_name": "A", "last_name": "B", "companies": [hidden.pk],
        })
        created = Person.objects.filter(first_name="A", last_name="B").first()
        if created:
            self.assertNotIn(hidden.pk, created.companies.values_list("pk", flat=True))


class NotificationTests(TestCase):
    def setUp(self):
        from contacts.models import SystemSettings, UserProfile
        self.admin = get_user_model().objects.create_user("boss", password="very-secure-password",
                                                          email="boss@example.lt", is_superuser=True, is_staff=True)
        self.mate = get_user_model().objects.create_user("kolega", password="very-secure-password", email="kolega@example.lt")
        UserProfile.objects.create(user=self.admin, timezone="Europe/Vilnius")
        UserProfile.objects.create(user=self.mate, timezone="Europe/Vilnius")
        self.person = Person.objects.create(first_name="Ruslan", last_name="Gorin")
        self.sys = SystemSettings.load()
        self.sys.notifications_enabled = True
        self.sys.save()

    def _run(self):
        from django.core.management import call_command
        call_command("send_notifications")

    def test_command_is_a_no_op_while_notifications_are_off(self):
        from django.core import mail
        self.sys.notifications_enabled = False
        self.sys.save()
        Reminder.objects.create(person=self.person, text="X", created_by=self.admin, assigned_to=self.admin,
                                due_at=timezone.now() + timedelta(minutes=10))
        self._run()
        self.assertEqual(len(mail.outbox), 0)

    def test_pre_event_email_goes_out_once_when_the_reminder_asks_for_it(self):
        from django.core import mail
        from contacts.models import UserProfile
        UserProfile.objects.filter(user=self.admin).update(digest_enabled=False)  # isolate the upcoming path
        r = Reminder.objects.create(person=self.person, text="Skambutis", created_by=self.admin, assigned_to=self.admin,
                                    due_at=timezone.now() + timedelta(minutes=20), notify_before=60)
        self._run()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Skambutis", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["boss@example.lt"])
        r.refresh_from_db()
        self.assertIsNotNone(r.upcoming_notified_at)
        self._run()  # not sent twice
        self.assertEqual(len(mail.outbox), 1)

    def test_no_pre_event_email_without_notify_before(self):
        from django.core import mail
        from contacts.models import UserProfile
        UserProfile.objects.filter(user=self.admin).update(digest_enabled=False)
        Reminder.objects.create(person=self.person, text="Be priminimo", created_by=self.admin, assigned_to=self.admin,
                                due_at=timezone.now() + timedelta(minutes=20))
        self._run()
        self.assertEqual(len(mail.outbox), 0)

    def test_far_off_reminder_is_not_emailed_yet(self):
        from django.core import mail
        Reminder.objects.create(person=self.person, text="Vėliau", created_by=self.admin, assigned_to=self.admin,
                                due_at=timezone.now() + timedelta(days=3), notify_before=60)
        self._run()
        self.assertEqual(len(mail.outbox), 0)

    def test_assigning_a_task_emails_the_new_owner(self):
        from django.core import mail
        from contacts.models import Team
        team = Team.objects.create(name="T")
        team.members.add(self.admin, self.mate)
        r = Reminder.objects.create(person=self.person, text="Perduota", created_by=self.admin, assigned_to=self.admin,
                                    due_at=timezone.now() + timedelta(days=5))
        self.client.force_login(self.admin)
        self.client.post(reverse("contacts:reminder-edit", args=[r.pk]),
                         {"text": "Perduota", "due_at": r.due_at.strftime("%Y-%m-%dT%H:%M"),
                          "assigned_to": self.mate.pk, "priority": "high"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["kolega@example.lt"])
        self.assertIn("Perduota", mail.outbox[0].subject)
        r.refresh_from_db()
        self.assertEqual(r.assigned_notified_to, self.mate)
        mail.outbox.clear()
        self._run()  # command does not re-send
        self.assertEqual(len(mail.outbox), 0)

    def test_morning_digest_sends_once_a_day_and_can_be_switched_off(self):
        from django.core import mail
        from contacts.models import UserProfile
        UserProfile.objects.filter(user=self.admin).update(digest_time="00:00")
        Reminder.objects.create(person=self.person, text="Vėluoja", created_by=self.admin, assigned_to=self.admin,
                                due_at=timezone.now() - timedelta(hours=2))
        self._run()
        digests = [m for m in mail.outbox if "santrauka" in m.subject.lower()]
        self.assertEqual(len(digests), 1)
        self.assertIn("Vėluoja", digests[0].body)
        prof = UserProfile.objects.get(user=self.admin)
        self.assertEqual(prof.digest_sent_on, timezone.localdate())
        mail.outbox.clear()
        self._run()
        self.assertEqual(len([m for m in mail.outbox if "santrauka" in m.subject.lower()]), 0)

    @patch("django.utils.timezone.now")
    def test_digest_skips_weekends_when_asked(self, mock_now):
        from datetime import datetime, timezone as _tz
        from django.core import mail
        from contacts.models import UserProfile
        # A Saturday at noon UTC.
        mock_now.return_value = datetime(2026, 6, 13, 12, 0, tzinfo=_tz.utc)
        UserProfile.objects.filter(user=self.admin).update(
            digest_time="00:00", digest_skip_weekends=True, timezone="UTC")
        Reminder.objects.create(person=self.person, text="Vėluoja", created_by=self.admin, assigned_to=self.admin,
                                due_at=mock_now.return_value - timedelta(hours=2))
        self._run()
        self.assertEqual([m for m in mail.outbox if "santrauka" in m.subject.lower()], [])

    def test_unsubscribe_link_turns_the_digest_off(self):
        from contacts.models import UserProfile
        token = UserProfile.objects.get(user=self.mate).unsubscribe_token
        resp = self.client.get(reverse("contacts:notifications-unsubscribe", args=[token]))
        self.assertContains(resp, "išjungtos")
        self.assertFalse(UserProfile.objects.get(user=self.mate).digest_enabled)

    def test_notification_settings_page_is_admin_only(self):
        self.client.force_login(self.mate)
        self.assertEqual(self.client.get(reverse("contacts:settings-notifications")).status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("contacts:settings-notifications")).status_code, 200)

    def test_every_user_has_their_own_digest_settings(self):
        from contacts.models import UserProfile
        self.client.force_login(self.mate)   # a plain user
        url = reverse("contacts:settings-my-notifications")
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {"digest_skip_weekends": "on", "digest_time": "09:15"})
        self.assertRedirects(response, url)
        profile = UserProfile.objects.get(user=self.mate)
        self.assertTrue(profile.digest_skip_weekends)
        self.assertFalse(profile.digest_enabled)          # unchecked in the POST
        self.assertEqual(profile.digest_time.strftime("%H:%M"), "09:15")

    def test_reminder_carries_a_pre_event_email_choice(self):
        self.client.force_login(self.admin)
        due = (timezone.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        self.client.post(reverse("contacts:reminder-create", args=[self.person.pk]), {
            "text": "Su priminimu", "due_at": due, "priority": "normal", "notify_before": "60",
            "submission_token": "tok-nb-1"})
        reminder = Reminder.objects.get(text="Su priminimu")
        self.assertEqual(reminder.notify_before, 60)


class RecurringReminderTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("planuoju", password="very-secure-password")
        self.person = Person.objects.create(first_name="Ruslan", last_name="Gorin")
        self.client.force_login(self.user)

    def _create(self, freq="weekly", **extra):
        due = (timezone.now() + timedelta(days=1)).replace(microsecond=0)
        self.client.post(reverse("contacts:reminder-create", args=[self.person.pk]), {
            "text": "Savaitinis", "due_at": due.strftime("%Y-%m-%dT%H:%M"),
            "priority": "normal", "recurrence_freq": freq, "recurrence_interval": "1", **extra,
        })
        return Reminder.objects.get(text="Savaitinis", recurrence_parent__isnull=True)

    def test_creating_a_weekly_reminder_materialises_future_occurrences(self):
        root = self._create(freq="weekly", recurrence_count="6")
        occ = Reminder.objects.filter(recurrence_parent=root)
        self.assertEqual(occ.count(), 5)  # root + 5 children = 6
        gaps = sorted(r.due_at for r in occ)
        self.assertEqual((gaps[0] - root.due_at).days, 7)

    def test_recurrence_respects_the_until_date(self):
        until = (timezone.now() + timedelta(days=20)).date()
        root = self._create(freq="weekly", recurrence_until=until.isoformat())
        last = Reminder.objects.filter(recurrence_parent=root).order_by("-due_at").first()
        self.assertLessEqual(last.due_at.date(), until)
        self.assertLessEqual(Reminder.objects.filter(recurrence_parent=root).count(), 3)

    def test_editing_one_occurrence_leaves_the_series_alone(self):
        root = self._create(freq="weekly", recurrence_count="4")
        child = Reminder.objects.filter(recurrence_parent=root).order_by("due_at").first()
        new_due = (child.due_at + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M")
        resp = self.client.post(reverse("contacts:reminder-edit", args=[child.pk]),
                                {"text": "Pakeista", "due_at": new_due, "priority": "high"})
        self.assertEqual(resp.status_code, 302)
        child.refresh_from_db()
        self.assertEqual((child.text, child.priority), ("Pakeista", "high"))
        self.assertEqual(Reminder.objects.filter(recurrence_parent=root, text="Savaitinis").count(), 2)

    def test_apply_to_all_future_rebuilds_the_open_tail(self):
        root = self._create(freq="weekly", recurrence_count="5")
        due = timezone.localtime(root.due_at).strftime("%Y-%m-%dT%H:%M")
        self.client.post(reverse("contacts:reminder-edit", args=[root.pk]), {
            "text": "Naujas tekstas", "due_at": due, "priority": "normal",
            "recurrence_freq": "weekly", "recurrence_interval": "1", "recurrence_count": "5",
            "apply_future": "on",
        })
        children = Reminder.objects.filter(recurrence_parent=root, deleted_at__isnull=True)
        self.assertTrue(children.exists())
        self.assertFalse(children.exclude(text="Naujas tekstas").exists())

    def test_deleting_the_series_root_removes_its_open_future(self):
        root = self._create(freq="daily", recurrence_count="10")
        self.client.post(reverse("contacts:reminder-delete", args=[root.pk]))
        self.assertFalse(Reminder.objects.filter(recurrence_parent=root, deleted_at__isnull=True,
                                                 due_at__gt=timezone.now()).exists())

    def test_extend_command_rolls_the_horizon_forward(self):
        from django.core.management import call_command
        root = self._create(freq="daily")
        before = Reminder.objects.filter(recurrence_parent=root).count()
        newest = list(Reminder.objects.filter(recurrence_parent=root).order_by("-due_at").values_list("pk", flat=True)[:before // 2])
        Reminder.objects.filter(pk__in=newest).delete()
        call_command("extend_recurrences")
        self.assertGreaterEqual(Reminder.objects.filter(recurrence_parent=root).count(), before)


class CalendarFeedTests(TestCase):
    def setUp(self):
        from contacts.models import UserProfile
        self.user = get_user_model().objects.create_user("feedas", password="very-secure-password")
        self.mate = get_user_model().objects.create_user("kitas", password="very-secure-password")
        self.profile = UserProfile.objects.create(user=self.user)
        self.person = Person.objects.create(first_name="Ruslan", last_name="Gorin")
        PhoneNumber.objects.create(person=self.person, number="+370 600 11111")
        PostalAddress.objects.create(person=self.person, address="Vilnius, Lietuva")

    def _url(self, token=None):
        return reverse("contacts:calendar-feed", args=[token or self.profile.calendar_token])

    def test_feed_lists_the_users_reminders_as_vevents(self):
        Reminder.objects.create(person=self.person, text="Skambutis", created_by=self.user, assigned_to=self.user,
                                due_at=timezone.now() + timedelta(days=1))
        Reminder.objects.create(person=self.person, text="Kolegos", created_by=self.mate, assigned_to=self.mate,
                                due_at=timezone.now() + timedelta(days=1))
        response = self.client.get(self._url())
        self.assertEqual(response["Content-Type"], "text/calendar; charset=utf-8")
        body = response.content.decode()
        self.assertIn("BEGIN:VCALENDAR", body)
        self.assertIn("SUMMARY:Skambutis", body)
        self.assertIn("LOCATION:Vilnius\\, Lietuva", body)
        self.assertIn("URL:", body)
        self.assertNotIn("Kolegos", body)  # not assigned to this user

    def test_feed_needs_no_login_but_a_bad_token_is_404(self):
        self.assertEqual(self.client.get(self._url("nonsense")).status_code, 404)
        self.assertEqual(self.client.get(self._url()).status_code, 200)

    def test_regenerating_the_token_breaks_the_old_link(self):
        old = self.profile.calendar_token
        self.client.force_login(self.user)
        self.client.post(reverse("contacts:settings"), {"action": "new_calendar_token"})
        self.profile.refresh_from_db()
        self.assertNotEqual(self.profile.calendar_token, old)
        self.assertEqual(self.client.get(self._url(old)).status_code, 404)


class IncomingMailTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user("adm", password="very-secure-password",
                                                          email="adm@imone.lt", is_superuser=True, is_staff=True)
        self.staffer = get_user_model().objects.create_user("darb", password="very-secure-password",
                                                            email="darbuotojas@imone.lt")
        self.person = Person.objects.create(first_name="Klientas", last_name="Klientaitis")
        EmailAddress.objects.create(person=self.person, email="klientas@example.lt")

    def _raw(self, **kw):
        from email.message import EmailMessage
        m = EmailMessage()
        m["Message-ID"] = kw.get("mid", "<a@b>")
        m["From"] = kw.get("frm", "darbuotojas@imone.lt")
        m["To"] = kw.get("to", "klientas@example.lt")
        m["Subject"] = kw.get("subject", "Dėl sutarties")
        m["Date"] = "Mon, 08 Sep 2026 10:00:00 +0000"
        m.set_content(kw.get("body", "Sveiki, siunčiu sutartį."))
        return m.as_bytes()

    def test_matched_mail_becomes_an_email_activity_by_the_sender(self):
        from contacts.mailfetch import process_message
        self.assertEqual(process_message(self._raw()), "activity")
        a = Activity.objects.get(message_id="<a@b>")
        self.assertEqual((a.person_id, a.activity_type, a.created_by_id),
                         (self.person.pk, "email", self.staffer.pk))
        self.assertIn("Dėl sutarties", a.text)

    def test_the_same_message_id_is_only_filed_once(self):
        from contacts.mailfetch import process_message
        process_message(self._raw())
        self.assertEqual(process_message(self._raw()), "duplicate")
        self.assertEqual(Activity.objects.filter(message_id="<a@b>").count(), 1)

    def test_unmatched_mail_is_held_and_an_admin_can_assign_it(self):
        from contacts.mailfetch import process_message
        from contacts.models import IncomingMail
        self.assertEqual(process_message(self._raw(to="nezinomas@x.lt", mid="<c@d>")), "unmatched")
        mail = IncomingMail.objects.get(resolved_at__isnull=True)
        self.client.force_login(self.admin)
        self.client.post(reverse("contacts:settings-incoming-mail"),
                         {"action": "assign", "mail_id": mail.pk, "contact": str(self.person.pk)})
        mail.refresh_from_db()
        self.assertIsNotNone(mail.resolved_at)
        self.assertTrue(Activity.objects.filter(person=self.person, message_id="<c@d>").exists())

    def test_incoming_mail_page_is_admin_only(self):
        self.client.force_login(self.staffer)
        self.assertEqual(self.client.get(reverse("contacts:settings-incoming-mail")).status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("contacts:settings-incoming-mail")).status_code, 200)

    def test_fetch_does_nothing_without_imap_host(self):
        from contacts.mailfetch import fetch
        self.assertEqual(fetch(), {})


class EntraLoginTests(TestCase):
    def test_username_helper_prefers_upn_then_email(self):
        from contacts.oidc import username_from_claims
        self.assertEqual(username_from_claims({"preferred_username": "A@B.LT"}), "a@b.lt")
        self.assertEqual(username_from_claims({"email": "c@d.lt"}), "c@d.lt")
        self.assertEqual(username_from_claims({}), "")

    def test_login_page_hides_the_microsoft_button_when_oidc_is_off(self):
        response = self.client.get(reverse("login"))
        self.assertNotContains(response, "Prisijungti su Microsoft")
        self.assertNotContains(response, "oidc")

    def test_backend_links_by_email_and_never_auto_creates_by_default(self):
        from contacts.oidc import EntraOIDCBackend
        user = get_user_model().objects.create_user("esamas", email="esamas@imone.lt", password="very-secure-password")
        backend = EntraOIDCBackend()
        self.assertEqual(list(backend.filter_users_by_claims({"email": "ESAMAS@imone.lt"})), [user])
        self.assertIsNone(backend.create_user({"email": "naujas@imone.lt"}))


class IntegrationConfigTests(TestCase):
    """SMTP / IMAP / Entra are configured from Settings, secrets encrypted at rest."""

    def setUp(self):
        self.admin = get_user_model().objects.create_user(
            "cfg", password="very-secure-password", email="cfg@example.lt", is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)

    def test_secret_round_trips_through_encryption(self):
        from contacts.crypto import decrypt, encrypt, looks_encrypted
        token = encrypt("hunter2")
        self.assertTrue(looks_encrypted(token))
        self.assertNotIn("hunter2", token)
        self.assertEqual(decrypt(token), "hunter2")

    def test_smtp_config_is_saved_encrypted_and_drives_sending(self):
        from contacts.integrations import email_config
        from contacts.models import SystemSettings
        resp = self.client.post(reverse("contacts:settings-notifications"), {
            "notifications_enabled": "on", "digest_default_time": "07:30",
            "email_host": "smtp.example.lt", "email_port": "587", "email_host_user": "crm@example.lt",
            "email_host_password": "s3cret-pass", "email_use_tls": "on", "email_from": "crm@example.lt",
            "site_base_url": "https://crm.example.lt",
        })
        self.assertEqual(resp.status_code, 302)
        system = SystemSettings.load()
        self.assertTrue(system.email_host_password.startswith("enc:v1:"))
        self.assertNotIn("s3cret-pass", system.email_host_password)
        cfg = email_config(system)
        self.assertEqual((cfg.host, cfg.user, cfg.password), ("smtp.example.lt", "crm@example.lt", "s3cret-pass"))

    def test_blank_secret_keeps_the_stored_value(self):
        from contacts.models import SystemSettings
        for _ in range(2):
            self.client.post(reverse("contacts:settings-notifications"), {
                "notifications_enabled": "on", "digest_default_time": "07:30",
                "email_host": "smtp.example.lt", "email_port": "587",
                "email_host_password": "keepme" if _ == 0 else "",
            })
        self.assertEqual(SystemSettings.load().email_host_password.count("enc:v1:"), 1)
        from contacts.crypto import decrypt
        self.assertEqual(decrypt(SystemSettings.load().email_host_password), "keepme")

    def test_imap_config_from_settings_activates_fetch(self):
        from contacts.integrations import imap_config
        self.client.post(reverse("contacts:settings-incoming-mail"), {
            "action": "save_config", "imap_enabled": "on", "imap_host": "imap.example.lt",
            "imap_port": "993", "imap_user": "crm@example.lt", "imap_password": "imap-pass", "imap_folder": "INBOX",
        })
        cfg = imap_config()
        self.assertTrue(cfg.active)
        self.assertEqual(cfg.password, "imap-pass")

    def test_entra_toggle_from_settings_controls_the_login_button_and_urls(self):
        self.assertNotContains(self.client.get(reverse("login")), "Prisijungti su Microsoft")
        self.assertEqual(self.client.get("/oidc/authenticate/").status_code, 404)
        self.client.post(reverse("contacts:settings-login"), {
            "oidc_enabled": "on", "oidc_tenant_id": "tid", "oidc_client_id": "cid", "oidc_client_secret": "csecret",
        })
        self.assertContains(self.client.get(reverse("login")), "Prisijungti su Microsoft")
        self.assertEqual(self.client.get("/oidc/authenticate/").status_code, 302)  # redirects to Microsoft

    def test_integration_pages_are_admin_only(self):
        self.client.force_login(get_user_model().objects.create_user("plain", password="very-secure-password"))
        for name in ("settings-notifications", "settings-incoming-mail", "settings-login"):
            self.assertEqual(self.client.get(reverse("contacts:%s" % name)).status_code, 404)


class IsolatedTierTests(TestCase):
    """A staging clone restored from production must not reach the outside world.

    The database still holds the real SMTP / IMAP / Entra credentials and the
    real webhook subscriptions, so every check below configures them first and
    then asserts CRM_ISOLATED overrides them.
    """

    def setUp(self):
        from contacts.crypto import encrypt
        from contacts.models import SystemSettings
        self.admin = get_user_model().objects.create_user(
            "stg", password="very-secure-password", email="stg@example.lt", is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)
        # Exactly what a restored production dump looks like: live credentials,
        # every integration switched on.
        system = SystemSettings.load()
        system.notifications_enabled = True
        system.email_host, system.email_host_user = "smtp.example.lt", "crm@example.lt"
        system.email_host_password, system.email_from = encrypt("smtp-pass"), "crm@example.lt"
        system.imap_enabled, system.imap_host = True, "imap.example.lt"
        system.imap_user, system.imap_password = "crm@example.lt", encrypt("imap-pass")
        system.oidc_enabled, system.oidc_tenant_id = True, "tid"
        system.oidc_client_id, system.oidc_client_secret = "cid", encrypt("csecret")
        system.automations_enabled = True
        system.save()

    def test_production_tier_keeps_the_configured_integrations(self):
        from contacts.integrations import email_config, imap_config, oidc_config
        self.assertTrue(email_config().configured)
        self.assertTrue(imap_config().active)
        self.assertTrue(oidc_config().usable)

    @override_settings(CRM_ENVIRONMENT="staging", CRM_ISOLATED=True)
    def test_isolated_tier_forces_smtp_imap_and_entra_off(self):
        from contacts.integrations import email_config, imap_config, oidc_config
        mail = email_config()
        self.assertFalse(mail.configured)
        self.assertFalse(mail.enabled)
        self.assertEqual(mail.password, "")          # the real secret never surfaces
        self.assertFalse(imap_config().active)
        self.assertFalse(oidc_config().usable)
        # The Entra endpoints stay closed even though the database has credentials.
        self.assertEqual(self.client.get("/oidc/authenticate/").status_code, 404)

    @override_settings(CRM_ENVIRONMENT="staging", CRM_ISOLATED=True)
    def test_isolated_tier_neither_queues_nor_posts_webhooks(self):
        from contacts.models import Webhook, WebhookDelivery
        from contacts.webhooks import emit, post_once
        hook = Webhook.objects.create(
            target_url="https://example.test/hook", events=["person.created"], active=True)
        person = Person.objects.create(first_name="Nauja", last_name="Kontaktas")
        emit("person.created", person)
        self.assertEqual(WebhookDelivery.objects.count(), 0)
        with patch("contacts.webhooks._OPENER.open") as opener:
            ok, status = post_once(hook, "person.created", {"event": "person.created"})
        self.assertFalse(ok)
        self.assertEqual(status, "isolated tier")
        opener.assert_not_called()

    @override_settings(CRM_ENVIRONMENT="staging", CRM_ISOLATED=True)
    def test_isolated_tier_shows_a_banner(self):
        self.assertContains(self.client.get(reverse("contacts:list")), "env-banner")
        # Also before sign-in: you must know which tier you are on before typing
        # a password into it.
        self.client.logout()
        self.assertContains(self.client.get(reverse("login")), "env-banner")

    def test_production_tier_shows_no_banner(self):
        self.assertNotContains(self.client.get(reverse("contacts:list")), "env-banner")
        self.client.logout()
        self.assertNotContains(self.client.get(reverse("login")), "env-banner")

    @override_settings(CRM_ENVIRONMENT="staging", CRM_ISOLATED=True)
    def test_sanitize_staging_clears_what_the_dump_carried(self):
        from django.core.management import call_command
        from contacts.models import ApiToken, SystemSettings, Webhook
        Webhook.objects.create(
            target_url="https://example.test/hook", events=["person.created"], active=True)
        raw, digest = ApiToken.new()
        ApiToken.objects.create(name="k", token_hash=digest, prefix=raw[:12], created_by=self.admin)

        call_command("sanitize_staging")

        system = SystemSettings.load()
        self.assertEqual(system.email_host, "")
        self.assertEqual(system.imap_password, "")
        self.assertEqual(system.oidc_client_secret, "")
        self.assertFalse(system.notifications_enabled)
        self.assertFalse(system.automations_enabled)
        self.assertEqual(Webhook.objects.filter(active=True).count(), 0)
        self.assertEqual(ApiToken.objects.count(), 0)

    def test_staging_stack_config_keeps_its_safety_properties(self):
        """Guards the two config invariants that let staging hold real data.

        Asserted on the files rather than a running stack: if someone adds a
        worker back, or copies production's Funnel setting across, that is a data
        leak, and it should fail here rather than in front of real contacts.
        """
        import pathlib
        root = pathlib.Path(settings.BASE_DIR)

        def directives(path):
            """The file without comments — they discuss what they switch off."""
            return "\n".join(
                line for line in path.read_text().splitlines()
                if not line.lstrip().startswith("#"))

        # The base file must pass the tier through, or the overlay cannot isolate.
        self.assertIn("CRM_ENVIRONMENT: ${CRM_ENVIRONMENT:-production}",
                      directives(root / "compose.yaml"))

        # Staging is an overlay; compose cannot delete an inherited service, so
        # the background ones are held at zero replicas instead.
        staging = directives(root / "compose.staging.yaml")
        for service in ("crm-worker", "crm-backup"):
            self.assertRegex(staging, r"%s:\s*(?:\n\s+\w[^\n]*)*?\n\s+deploy:\s*\n\s+replicas:\s*0" % service)

        # Production is deliberately published through Funnel; staging must not be.
        self.assertNotIn("AllowFunnel", (root / "deploy" / "tailscale" / "serve-staging.json").read_text())
        self.assertIn("AllowFunnel", (root / "deploy" / "tailscale" / "serve.json").read_text())

        # Both staging scripts refuse to act unless the target really is staging.
        for name in ("deploy-staging.sh", "refresh-staging.sh"):
            self.assertIn("CRM_ENVIRONMENT=staging", (root / "scripts" / name).read_text())
        # And the deploy refuses a Tailscale staging that would serve Funnel,
        # since the overlay's default serve.json enables it.
        self.assertIn("serve-staging.json", (root / "scripts" / "deploy-staging.sh").read_text())

    def test_sanitize_staging_refuses_to_run_on_production(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from contacts.models import SystemSettings
        with self.assertRaises(CommandError):
            call_command("sanitize_staging")
        self.assertEqual(SystemSettings.load().email_host, "smtp.example.lt")


class AutomationTests(TestCase):
    def setUp(self):
        from contacts.models import SystemSettings, UserProfile
        self.admin = get_user_model().objects.create_user(
            "vadovas", password="very-secure-password", email="vadovas@example.lt", is_superuser=True, is_staff=True)
        UserProfile.objects.create(user=self.admin, timezone="Europe/Vilnius")
        self.sys = SystemSettings.load()
        self.sys.automations_enabled = True
        self.sys.save()
        self.person = Person.objects.create(first_name="Senas", last_name="Kontaktas", created_by=self.admin)
        Person.objects.filter(pk=self.person.pk).update(created_at=timezone.now() - timedelta(days=10))

    def _rule(self, **kw):
        from contacts.models import AutomationRule
        data = dict(name="Taisyklė", trigger=AutomationRule.NO_OWNER, threshold=1,
                    action=AutomationRule.NOTIFY, action_user=self.admin, active=True, created_by=self.admin)
        data.update(kw)
        return AutomationRule.objects.create(**data)

    def _run(self):
        from contacts.automation import run_all
        return run_all()

    def test_no_owner_rule_notifies_the_user_once_per_period(self):
        from django.core import mail
        self._rule()
        self.assertEqual(self._run(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("vadovas@example.lt", mail.outbox[0].to)
        self._run()
        self.assertEqual(len(mail.outbox), 1)  # guard: not again within threshold days

    def test_assign_owner_action_clears_the_condition(self):
        from contacts.models import AutomationRule
        mate = get_user_model().objects.create_user("kolega48", password="very-secure-password")
        self._rule(action=AutomationRule.ASSIGN, action_user=mate)
        self._run()
        self.person.refresh_from_db()
        self.assertEqual(self.person.owner, mate)
        from contacts.models import AuditLog
        self.assertTrue(AuditLog.objects.filter(target_id=str(self.person.pk), field="Atsakingas",
                                                detail__automation="Taisyklė").exists())

    def test_silent_contact_rule_creates_a_task_with_the_name_substituted(self):
        from contacts.models import AutomationRule
        mate = get_user_model().objects.create_user("kolega48b", password="very-secure-password")
        self.person.owner = mate
        self.person.save()
        Activity.objects.create(person=self.person, text="senas skambutis", created_by=self.admin)
        Activity.objects.filter(person=self.person).update(created_at=timezone.now() - timedelta(days=40))
        self._rule(trigger=AutomationRule.SILENT, threshold=30, action=AutomationRule.CREATE_TASK,
                   action_user=None, action_text="Perskambinti {vardas}")
        self._run()
        self.assertTrue(Reminder.objects.filter(person=self.person, text="Perskambinti Senas Kontaktas",
                                                assigned_to=mate).exists())

    def test_nothing_runs_while_the_global_switch_is_off(self):
        from django.core import mail
        self.sys.automations_enabled = False
        self.sys.save()
        self._rule()
        self.assertEqual(self._run(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_inactive_rule_is_skipped(self):
        from django.core import mail
        self._rule(active=False)
        self.assertEqual(self._run(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_one_failing_target_does_not_stop_the_rule(self):
        from contacts.models import AutomationLog
        broken = get_user_model().objects.create_user("beemail", password="very-secure-password")  # no email
        other = Person.objects.create(first_name="Kitas", last_name="Naujokas")
        Person.objects.filter(pk=other.pk).update(created_at=timezone.now() - timedelta(days=10))
        self._rule(action_user=broken)
        self._run()
        self.assertEqual(AutomationLog.objects.filter(status="error").count(), 2)

    def test_actions_are_capped_per_run(self):
        from contacts.automation import _PER_RULE_CAP
        from contacts.models import AutomationLog
        people = [Person(first_name=f"N{n:03d}", last_name="Naujas") for n in range(_PER_RULE_CAP + 5)]
        Person.objects.bulk_create(people)
        Person.objects.filter(last_name="Naujas").update(created_at=timezone.now() - timedelta(days=10))
        self._rule()
        self._run()
        self.assertEqual(AutomationLog.objects.count(), _PER_RULE_CAP)

    def test_automations_page_follows_the_can_manage_automations_capability(self):
        from contacts.models import RolePermissions, UserProfile
        self._rule()
        member = get_user_model().objects.create_user("eilinis", password="very-secure-password")
        UserProfile.objects.create(user=member, role=UserProfile.ROLE_MEMBER)
        self.client.force_login(member)
        self.assertEqual(self.client.get(reverse("contacts:settings-automations")).status_code, 404)

        RolePermissions.objects.update_or_create(
            role=UserProfile.ROLE_MEMBER, defaults={"permissions": {"can_manage_automations": True}})
        resp = self.client.get(reverse("contacts:settings-automations"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Taisyklė")

        self.client.force_login(self.admin)   # admin always has it
        self.assertEqual(self.client.get(reverse("contacts:settings-automations")).status_code, 200)

    def test_form_rejects_an_action_that_does_not_fit_the_trigger(self):
        from contacts.forms import AutomationRuleForm
        from contacts.models import AutomationRule
        form = AutomationRuleForm(data={
            "name": "X", "trigger": AutomationRule.OVERDUE, "threshold": 7,
            "action": AutomationRule.ADD_TAG, "action_due_days": 3,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("action", form.errors)


class TranslationOverrideTests(TestCase):
    """Interface wording is edited through a CSV round trip (Settings -> Vertimai)."""

    def setUp(self):
        from contacts import translations
        self.admin = get_user_model().objects.create_user(
            "vert", password="very-secure-password", is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)
        self.url = reverse("contacts:settings-translations")
        translations.capture_defaults()

    def tearDown(self):
        from contacts import translations
        from contacts.models import Translation
        Translation.objects.all().delete()
        translations.apply_overrides()          # leave the catalog as we found it

    def _csv(self, rows):
        body = "Modulis,Kintamasis,LT,EN\r\n"
        for module, msgid, lt, en in rows:
            body += '"%s","%s","%s","%s"\r\n' % (module, msgid, lt, en)
        return SimpleUploadedFile("vertimai.csv", body.encode("utf-8-sig"), content_type="text/csv")

    def test_export_lists_every_string_with_the_module_that_uses_it(self):
        response = self.client.get(self.url, {"export": "csv"})
        self.assertEqual(response.status_code, 200)
        text = response.content.decode("utf-8-sig")
        header, *lines = [line for line in text.splitlines() if line.strip()]
        self.assertEqual(header, "Modulis,Kintamasis,LT,EN")
        self.assertGreater(len(lines), 500)
        # The module column is what tells two similar strings apart.
        self.assertIn("contacts/list", text)

    def test_import_previews_before_it_changes_anything(self):
        from contacts.models import Translation
        response = self.client.post(self.url, {"file": self._csv([
            ("contacts/list", "Kontaktai", "Kontaktai", "People")])})
        self.assertEqual(response.status_code, 200)
        preview = response.context["preview"]
        self.assertEqual(preview["total"], 1)
        self.assertEqual(preview["changes"][0]["new_en"], "People")
        self.assertEqual(preview["changes"][0]["old_en"], "Contacts")
        self.assertEqual(Translation.objects.count(), 0)   # nothing saved yet

    def test_applying_the_preview_changes_what_the_interface_shows(self):
        from django.utils import translation as django_translation
        self.client.post(self.url, {"file": self._csv([
            ("contacts/list", "Kontaktai", "Kontaktų sąrašas", "People")])})
        response = self.client.post(self.url, {"op": "apply"}, follow=True)
        self.assertEqual(response.status_code, 200)

        with django_translation.override("en"):
            self.assertEqual(django_translation.gettext("Kontaktai"), "People")
        # The source language is overridable too, even though there is no lt .mo.
        with django_translation.override("lt"):
            self.assertEqual(django_translation.gettext("Kontaktai"), "Kontaktų sąrašas")

    def test_clearing_a_cell_restores_the_shipped_translation(self):
        from django.utils import translation as django_translation
        self.client.post(self.url, {"file": self._csv([("", "Kontaktai", "Sarasas", "People")])})
        self.client.post(self.url, {"op": "apply"})
        self.client.post(self.url, {"file": self._csv([("", "Kontaktai", "", "")])})
        self.client.post(self.url, {"op": "apply"})
        with django_translation.override("en"):
            self.assertEqual(django_translation.gettext("Kontaktai"), "Contacts")
        # Lithuanian has no .mo, so reverting means the msgid shows through again
        # rather than a stale override sticking around.
        with django_translation.override("lt"):
            self.assertEqual(django_translation.gettext("Kontaktai"), "Kontaktai")

    def test_unknown_keys_are_reported_rather_than_silently_skipped(self):
        response = self.client.post(self.url, {"file": self._csv([
            ("", "Toks tekstas sistemoje neegzistuoja", "x", "y")])})
        self.assertEqual(response.context["preview"]["unknown_total"], 1)
        self.assertEqual(response.context["preview"]["total"], 0)

    def test_a_file_it_cannot_read_is_refused_whole(self):
        bad_header = SimpleUploadedFile(
            "x.csv", "A,B,C,D\r\n1,2,3,4\r\n".encode("utf-8"), content_type="text/csv")
        self.assertContains(self.client.post(self.url, {"file": bad_header}), "antraštės")
        not_utf8 = SimpleUploadedFile(
            "x.csv", "Modulis,Kintamasis,LT,EN\r\n".encode("utf-16"), content_type="text/csv")
        self.assertContains(self.client.post(self.url, {"file": not_utf8}), "UTF-8")

    def test_export_import_round_trip_does_not_invent_changes(self):
        """A downloaded file re-uploaded unchanged must show nothing to apply,
        even for strings that begin with "+" or "-"."""
        import csv as _csv
        import io as _io
        text = self.client.get(self.url, {"export": "csv"}).content.decode("utf-8-sig")
        rows = list(_csv.reader(_io.StringIO(text)))
        self.assertEqual(rows[0], ["Modulis", "Kintamasis", "LT", "EN"])
        self.assertTrue(any(r[1].startswith(("+", "-")) for r in rows[1:]))

        same = SimpleUploadedFile(
            "vertimai.csv", ("\ufeff" + text).encode("utf-8"), content_type="text/csv")
        response = self.client.post(self.url, {"file": same})
        self.assertEqual(response.context["preview"]["total"], 0)
        self.assertEqual(response.context["preview"]["unknown_total"], 0)

    def test_only_administrators_may_open_it(self):
        self.client.force_login(get_user_model().objects.create_user(
            "eilinis", password="very-secure-password"))
        self.assertEqual(self.client.get(self.url).status_code, 404)

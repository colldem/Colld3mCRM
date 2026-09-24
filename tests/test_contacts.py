import json
import os
from datetime import datetime, time, timedelta
from io import BytesIO, StringIO
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.core.files.uploadedfile import SimpleUploadedFile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from contacts import crypto
from contacts.models import Activity, ApiToken, Attachment, Category, Company, CustomField, CustomValue, DuplicateSettings, EmailAddress, Person, PersonCompanyLink, PhoneNumber, PostalAddress, Reminder, RolePermissions, SavedFilter, Tag, Team, UserProfile, WebLink
from contacts.duplicates import find_company_duplicates, find_person_duplicates, scan_duplicates
from contacts import permissions as perm


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
        # The dashboard opens on "mine", so a fixture without an owner is nobody's.
        kwargs.setdefault("owner", self.user)
        return Person.objects.create(first_name=first, last_name="Testas", **kwargs)

    @patch("django.utils.timezone.now")
    def test_dashboard_agenda_splits_by_horizon_for_this_user_only(self, mock_now):
        from datetime import datetime, timezone as _tz
        # A Monday, so "this week" still has room ahead of it.
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
        tabs = {tab["key"]: tab for tab in response.context["event_tabs"]}
        texts = lambda key: [row.text for row in tabs[key]["rows"]["all"]]
        self.assertEqual(texts("overdue"), ["Vėluoja"])
        self.assertIn("Šiandien vėliau", texts("today"))
        # The horizons nest: today is inside this week, which is inside all.
        # "Overdue" cuts across them — an event late today is in both.
        self.assertEqual(texts("week"), ["Vėluoja", "Šiandien vėliau", "Rytoj"])
        self.assertEqual(texts("all"), ["Vėluoja", "Šiandien vėliau", "Rytoj"])
        for key in tabs:
            self.assertNotIn("Kolegos", texts(key))
        # The tab label carries its own count, and "today" is the one that opens.
        self.assertEqual(tabs["today"]["rows"]["total"], 2)
        self.assertTrue(tabs["today"].get("active"))
        self.assertContains(response, "(2)")

    def test_dashboard_costs_the_same_whichever_horizons_have_events(self):
        """Each horizon is its own query, and a per-row prefetch would only run
        for the ones that found rows — so an empty tab filling up would quietly
        add queries. The rows carry nothing that needs fetching per row."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def queries():
            self.client.get(reverse("contacts:home"))  # warm the per-process caches
            with CaptureQueriesContext(connection) as captured:
                self.client.get(reverse("contacts:home"))
            return len(captured.captured_queries)

        person = self._person("Darbotvarkė")
        Reminder.objects.create(person=person, text="Rytoj", created_by=self.user,
                                due_at=self.now + timedelta(days=1))
        ahead_only = queries()
        Reminder.objects.create(person=person, text="Vėluoja", created_by=self.user,
                                due_at=self.now - timedelta(hours=3))
        self.assertEqual(queries(), ahead_only)

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
        Company.objects.create(name="UAB Nauja", owner=self.user)
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
        Company.objects.create(name="UAB Naujausia", city="Vilnius", owner=self.user)
        Activity.objects.create(person=fresh, activity_type="note", text="Uzrasas", created_by=self.user)

        response = self.client.get(reverse("contacts:home"))
        self.assertEqual(str(response.context["recent_people"]["visible"][0]), str(fresh))
        self.assertEqual(response.context["recent_companies"]["visible"][0].city, "Vilnius")
        self.assertEqual(response.context["recent_activities"]["visible"][0].text, "Uzrasas")

    def test_dashboard_card_shows_a_few_rows_and_its_popup_shows_the_rest(self):
        """Cards share a height; the whole list lives in the block's popup."""
        from contacts.analytics_views import DASH_VISIBLE
        for index in range(DASH_VISIBLE + 3):
            self._person("Eile%d" % index)

        response = self.client.get(reverse("contacts:home"))
        rows = response.context["recent_people"]
        self.assertEqual(len(rows["visible"]), DASH_VISIBLE)
        self.assertEqual(len(rows["all"]), DASH_VISIBLE + 3)
        self.assertEqual(rows["total"], DASH_VISIBLE + 3)
        # The popup is rendered with the page: opening it needs no request.
        self.assertContains(response, 'id="dlg-recent-people"')
        self.assertContains(response, str(rows["all"][-1]))

    def test_every_dashboard_block_opens_a_popup(self):
        """Item 12: the number, and the rows it is made of, are one click apart."""
        response = self.client.get(reverse("contacts:home"))
        for dialog in ("dlg-recent-people", "dlg-recent-companies", "dlg-week-activity",
                       "dlg-events-overdue", "dlg-month-activity", "dlg-new-people",
                       "dlg-recent-activities", "dlg-events-today"):
            with self.subTest(dialog=dialog):
                self.assertContains(response, 'data-dash-open="%s"' % dialog)
                self.assertContains(response, 'id="%s"' % dialog)

    def test_agenda_filters_by_event_type_and_marks_overdue_in_red(self):
        person = self._person("Tipiškas")
        now = timezone.now()
        Reminder.objects.create(person=person, text="Vėluojantis skambutis", kind=Reminder.KIND_CALL,
                                created_by=self.user, due_at=now - timedelta(hours=2))
        Reminder.objects.create(person=person, text="Būsimas priminimas", kind=Reminder.KIND_REMINDER,
                                created_by=self.user, due_at=now + timedelta(hours=2))
        response = self.client.get(reverse("contacts:home"))
        body = response.content.decode()
        # The chips the filter works on, and the kind each row carries.
        for kind, _label in Reminder.KIND_CHOICES:
            self.assertIn('data-dash-kind="%s"' % kind, body)
        self.assertIn('data-kind="call"', body)
        # An event whose time has passed reads as overdue wherever it appears.
        self.assertIn("is-overdue-row", body)

    def test_a_meeting_that_is_over_leaves_the_agenda_by_itself(self):
        person = self._person("Susitikęs")
        past = timezone.now() - timedelta(hours=3)
        Reminder.objects.create(person=person, text="Praėjęs susitikimas", kind=Reminder.KIND_MEETING,
                                created_by=self.user, due_at=past, end_at=past + timedelta(hours=1))
        Reminder.objects.create(person=person, text="Praėjęs skambutis", kind=Reminder.KIND_CALL,
                                created_by=self.user, due_at=past, end_at=past + timedelta(hours=1))
        response = self.client.get(reverse("contacts:home"))
        tabs = {tab["key"]: tab for tab in response.context["event_tabs"]}
        self.assertEqual([row.text for row in tabs["overdue"]["rows"]["all"]], ["Praėjęs skambutis"])
        self.assertEqual(response.context["overdue_total"], 1)

    def test_ticking_an_event_off_from_a_popup_comes_back_to_the_dashboard(self):
        person = self._person("Atliktas")
        event = Reminder.objects.create(person=person, text="Pažymėti", created_by=self.user,
                                        due_at=timezone.now() - timedelta(hours=1))
        response = self.client.post(reverse("contacts:reminder-complete", args=[event.pk]),
                                    {"next": reverse("contacts:home")})
        self.assertRedirects(response, reverse("contacts:home"))
        event.refresh_from_db()
        self.assertIsNotNone(event.completed_at)

    def test_completion_redirect_refuses_to_leave_the_site(self):
        person = self._person("Nukreiptas")
        event = Reminder.objects.create(person=person, text="Pažymėti", created_by=self.user,
                                        due_at=timezone.now() - timedelta(hours=1))
        response = self.client.post(reverse("contacts:reminder-complete", args=[event.pk]),
                                    {"next": "https://kitas.example.com/"})
        self.assertEqual(response["Location"], person.get_absolute_url())


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

    def test_the_dashboard_only_offers_the_scopes_a_role_reaches(self):
        """A scope you cannot reach is not a choice: someone who only ever sees
        their own records gets no picker at all."""
        from contacts.models import Team, UserProfile
        # No team, but full visibility: mine, or everybody's.
        keys = [key for key, _label in self.client.get(reverse("contacts:home")).context["dash_scopes"]]
        self.assertEqual(keys, ["mine", "all"])

        loner = get_user_model().objects.create_user("vienas", password="very-secure-password")
        UserProfile.objects.create(user=loner, role=UserProfile.ROLE_MEMBER,
                                   record_visibility=UserProfile.VISIBILITY_OWN)
        self.client.force_login(loner)
        self.assertEqual(self.client.get(reverse("contacts:home")).context["dash_scopes"], [])

        # In a team, but still walled in to his own records: still no choice.
        Team.objects.create(name="Skyrius").members.add(loner)
        self.assertEqual(self.client.get(reverse("contacts:home")).context["dash_scopes"], [])

        UserProfile.objects.filter(user=loner).update(record_visibility=UserProfile.VISIBILITY_TEAM)
        keys = [key for key, _label in self.client.get(reverse("contacts:home")).context["dash_scopes"]]
        self.assertEqual(keys, ["mine", "team"])

    def test_the_dashboard_scope_widens_from_mine_to_the_team_to_everyone(self):
        from contacts.models import Team
        stranger = get_user_model().objects.create_user("kitur", password="very-secure-password")
        Team.objects.create(name="Skyrius").members.add(self.user, self.mate)
        self._person("Mano")
        self._person("Kolegos", owner=self.mate)
        self._person("Svetimas", owner=stranger)
        totals = {scope: self.client.get(reverse("contacts:home"), {"scope": scope}).context["people_total"]
                  for scope in ("mine", "team", "all")}
        self.assertEqual(totals, {"mine": 1, "team": 2, "all": 3})
        # An unknown scope, or one this user may not pick, falls back to "mine".
        self.assertEqual(self.client.get(reverse("contacts:home"), {"scope": "kazkas"}).context["dash_scope"],
                         "mine")

    def test_care_lists_group_contacts_that_need_attention(self):
        quiet = self._person("Nutiles", owner=None)
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

    def test_analytics_overview_shows_every_section(self):
        person = self._person("Apžvalgai")
        Activity.objects.create(person=person, activity_type="call", text="Skambinta", created_by=self.user)
        Reminder.objects.create(person=person, text="Priminimas", created_by=self.user,
                                due_at=timezone.now() + timedelta(days=1))
        response = self.client.get(reverse("contacts:analytics-overview"))
        self.assertEqual(response.status_code, 200)
        for heading in ("Komunikacija", "Priminimų vykdymas", "Bazė ir augimas", "Ryšių priežiūra"):
            self.assertContains(response, heading)
        self.assertEqual(response.context["kpis"]["people_total"], 1)
        self.assertEqual(response.context["comm"]["total"], 1)

    def test_analytics_overview_system_band_is_admin_only(self):
        self.assertNotContains(self.client.get(reverse("contacts:analytics-overview")),
                               "Sistemos naudojimas")
        self.user.is_superuser = True
        self.user.save()
        response = self.client.get(reverse("contacts:analytics-overview"))
        self.assertContains(response, "Sistemos naudojimas")
        self.assertIsNotNone(response.context["system"])

    def test_analytics_overview_period_defaults_and_clamps(self):
        self.assertEqual(self.client.get(reverse("contacts:analytics-overview"),
                                         {"days": 30}).context["days"], 30)
        self.assertEqual(self.client.get(reverse("contacts:analytics-overview"),
                                         {"days": "abc"}).context["days"], 90)

    def test_analytics_overview_respects_record_visibility(self):
        from contacts.models import UserProfile

        UserProfile.objects.create(user=self.user, role=UserProfile.ROLE_MEMBER,
                                   record_visibility=UserProfile.VISIBILITY_OWN)
        self._person("Slaptas", owner=self.mate)
        self.assertEqual(self.client.get(reverse("contacts:analytics-overview"))
                         .context["kpis"]["people_total"], 0)

    @override_settings(LANGUAGE_CODE="lt")
    def test_analytics_overview_svg_coordinates_keep_decimal_points_in_lithuanian(self):
        person = self._person("Koordinatė")
        Activity.objects.create(person=person, activity_type="call", text="x", created_by=self.user)
        html = self.client.get(reverse("contacts:analytics-overview")).content.decode()
        import re
        for match in re.finditer(r"<svg\b.*?</svg>", html, re.S):
            coordinates = re.findall(
                r'(?:x|y|x1|y1|x2|y2|cx|cy|width|height)="([0-9][0-9.,]*)"', match.group(0))
            for value in coordinates:
                with self.subTest(value=value):
                    self.assertNotIn(",", value)

    def test_analytics_detail_pages_show_a_back_link_not_the_pill_nav(self):
        response = self.client.get(reverse("contacts:analytics-communication"))
        self.assertContains(response, "Analitikos apžvalga")
        self.assertNotContains(response, 'class="analytics-nav"')


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

    def test_calendar_toolbar_groups_navigation_views_and_the_primary_action(self):
        """The primary action sits in the page head like everywhere else, and
        the three views read as one control rather than three loose buttons."""
        response = self.client.get(reverse("contacts:calendar"))
        head = response.content.decode().split('class="cal-toolbar"')[0]
        self.assertIn('class="page-actions"', head)
        self.assertIn("data-cal-new", head)
        self.assertContains(response, 'class="cal-views segmented"')
        # The new-event button left the view switcher.
        toolbar = response.content.decode().split('class="cal-toolbar"')[1].split("</div>\n\n")[0]
        self.assertNotIn("data-cal-new", toolbar)

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
        self.assertContains(response, "is-past")

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

    def test_grid_geometry_is_written_unlocalised(self):
        """A decimal comma is not a CSS length: under lt the browser dropped
        `top:68,4%` and every event fell to the foot of its column."""
        self._event(text="Vidurdienis", due_at=self.start.replace(hour=12), end_at=self.start.replace(hour=13))
        with translation.override("lt"):
            response = self.client.get(reverse("contacts:calendar"),
                                       {"view": "day", "date": self.start.date().isoformat()})
        body = response.content.decode()
        self.assertIn("top:50.0%", body)
        self.assertNotIn("top:50,0%", body)
        # The now-line rides on the same kind of value.
        self.assertNotRegex(body, r'class="cal-now" style="top:\d+,')

    def test_event_carries_its_kind_description_and_meeting_link(self):
        due = self.start.strftime("%Y-%m-%dT%H:%M")
        self.client.post(reverse("contacts:calendar-event-create"), {
            "text": "Susitikimas", "due_at": due, "kind": "meeting",
            "description": "Ką aptarti", "meeting_url": "https://meet.example.com/a",
            "record_kind": "person", "record_id": self.person.pk,
        })
        event = Reminder.objects.get(text="Susitikimas")
        self.assertEqual(event.kind, Reminder.KIND_MEETING)
        self.assertEqual(event.description, "Ką aptarti")
        self.assertEqual(event.meeting_url, "https://meet.example.com/a")

    def test_joining_link_belongs_to_a_meeting_only(self):
        due = self.start.strftime("%Y-%m-%dT%H:%M")
        self.client.post(reverse("contacts:calendar-event-create"), {
            "text": "Skambutis", "due_at": due, "kind": "call",
            "meeting_url": "https://meet.example.com/a",
        })
        self.assertEqual(Reminder.objects.get(text="Skambutis").meeting_url, "")

    def test_picking_a_contact_fills_in_their_company_and_the_other_way_round(self):
        from contacts.models import PersonCompanyLink

        PersonCompanyLink.objects.create(person=self.person, company=self.company, is_primary=True)
        due = self.start.strftime("%Y-%m-%dT%H:%M")
        self.client.post(reverse("contacts:calendar-event-create"),
                         {"text": "Per kontaktą", "due_at": due, "record_kind": "person",
                          "record_id": self.person.pk})
        through_person = Reminder.objects.get(text="Per kontaktą")
        self.assertEqual((through_person.person, through_person.company), (self.person, self.company))

        self.client.post(reverse("contacts:calendar-event-create"),
                         {"text": "Per įmonę", "due_at": due, "record_kind": "company",
                          "record_id": self.company.pk})
        through_company = Reminder.objects.get(text="Per įmonę")
        self.assertEqual((through_company.person, through_company.company), (self.person, self.company))
        # The picker offers the counterpart before anything is saved.
        results = self.client.get(reverse("contacts:calendar-records"), {"q": "Gorin"}).json()["results"]
        self.assertEqual(results[0]["partner"], "AB Regitra")

    def test_reminder_time_is_stored_as_a_lead_and_falls_back_to_five_minutes(self):
        due = self.start.strftime("%Y-%m-%dT%H:%M")
        self.client.post(reverse("contacts:calendar-event-create"),
                         {"text": "Be laiko", "due_at": due, "notify": "1"})
        self.assertEqual(Reminder.objects.get(text="Be laiko").notify_before, 5)

        # The dialog posts a moment; the row keeps the minutes before the event.
        day_before = (self.start - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        self.client.post(reverse("contacts:calendar-event-create"),
                         {"text": "Su laiku", "due_at": due, "notify": "1", "notify_at": day_before})
        self.assertEqual(Reminder.objects.get(text="Su laiku").notify_before, 1440)

        # A moment at or after the event says nothing useful: nudge just before it.
        later = (self.start + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        self.client.post(reverse("contacts:calendar-event-create"),
                         {"text": "Po įvykio", "due_at": due, "notify": "1", "notify_at": later})
        self.assertEqual(Reminder.objects.get(text="Po įvykio").notify_before, 5)

        self.client.post(reverse("contacts:calendar-event-create"),
                         {"text": "Nesiųsti", "due_at": due, "notify_at": day_before})
        self.assertIsNone(Reminder.objects.get(text="Nesiųsti").notify_before)

    def test_the_record_picker_hangs_its_matches_off_the_field(self):
        """The dialog lays its fields out in a grid, and a scrolling box gives a
        grid row no height of its own — in the flow the matches collapsed to a
        sliver and looked like nothing had been found. The list is taken out of
        the flow and anchored to the field instead."""
        page = self.client.get(reverse("contacts:calendar")).content.decode()
        anchor = page.split('class="cal-record-anchor"')[1].split("</div>")[0]
        self.assertIn('id="cal-record"', anchor)
        self.assertIn('id="cal-record-list"', anchor)
        css = (settings.BASE_DIR / "static/css/theme.css").read_text()
        self.assertIn(".cal-record-anchor{position:relative}", css)
        self.assertIn(".cal-record-list{position:absolute", css)

    def test_the_dialog_picks_a_type_by_icon_and_asks_when_to_remind(self):
        """No radio to aim at: each type is a tile with its own icon. The
        reminder itself is a date and a time; the quick picks only fill it in."""
        page = self.client.get(reverse("contacts:calendar")).content.decode()
        for kind in ("call", "meeting", "reminder"):
            self.assertIn(f'class="cal-kind kind-{kind}"', page)
        self.assertEqual(page.count('class="cal-kind-icon"'), 3)
        self.assertIn('id="cal-notify-at" name="notify_at" type="datetime-local"', page)
        self.assertIn('class="cal-quick" data-minutes="1440"', page)

    def test_a_meeting_closes_itself_once_it_is_over_but_a_call_waits(self):
        from contacts.reminder_queries import autocomplete_past_meetings, pending_reminders

        past = timezone.now() - timedelta(hours=2)
        meeting = self._event(text="Praėjęs susitikimas", due_at=past, end_at=past + timedelta(minutes=30),
                              kind=Reminder.KIND_MEETING)
        call = self._event(text="Praėjęs skambutis", due_at=past, end_at=past + timedelta(minutes=30),
                           kind=Reminder.KIND_CALL)
        self.assertTrue(meeting.is_done)
        self.assertFalse(call.is_done)
        # The lists agree with the property before the worker has run at all.
        open_texts = set(pending_reminders(self.user).values_list("text", flat=True))
        self.assertEqual(open_texts, {"Praėjęs skambutis"})

        self.assertEqual(autocomplete_past_meetings(), 1)
        meeting.refresh_from_db()
        call.refresh_from_db()
        self.assertIsNotNone(meeting.completed_at)
        self.assertIsNone(call.completed_at)
        # Idempotent: a second pass finds nothing left to close.
        self.assertEqual(autocomplete_past_meetings(), 0)

    def test_an_event_can_be_ticked_off_from_the_calendar_dialog(self):
        event = self._event(text="Atlikti", due_at=self.start)
        self.client.post(reverse("contacts:calendar-event-complete", args=[event.pk]))
        event.refresh_from_db()
        self.assertIsNotNone(event.completed_at)

        theirs = Reminder.objects.create(text="Svetimas", due_at=self.start,
                                         created_by=self.mate, assigned_to=self.mate)
        self.client.post(reverse("contacts:calendar-event-complete", args=[theirs.pk]))
        theirs.refresh_from_db()
        self.assertIsNone(theirs.completed_at)

    def test_a_colleagues_calendar_is_listed_paged_and_fetched_uncached(self):
        response = self.client.get(reverse("contacts:calendar"))
        self.assertContains(response, 'data-colleague="%d"' % self.mate.pk)
        # Your own calendar is the grid, not an overlay on it.
        self.assertNotContains(response, 'data-colleague="%d"' % self.user.pk)

        theirs = Reminder.objects.create(text="Kolegos įvykis", due_at=self.start,
                                         created_by=self.mate, assigned_to=self.mate)
        feed = self.client.get(reverse("contacts:calendar-colleague-events", args=[self.mate.pk]),
                               {"view": "week", "date": self.start.date().isoformat()})
        payload = feed.json()
        self.assertEqual([row["text"] for row in payload["events"]], ["Kolegos įvykis"])
        self.assertEqual(payload["owner"], perm.user_label(self.mate))
        # Somebody else's agenda is read live, never stored along the way.
        self.assertIn("no-cache", feed.headers["Cache-Control"])
        self.assertEqual(theirs.pk, payload["events"][0]["id"])

    def test_colleague_list_pages_ten_at_a_time_and_respects_visibility(self):
        from contacts.calendar_views import COLLEAGUE_PAGE

        User = get_user_model()
        for index in range(COLLEAGUE_PAGE + 2):
            User.objects.create_user("kolega%02d" % index, password="very-secure-password",
                                     first_name="Vardas%02d" % index)
        response = self.client.get(reverse("contacts:calendar"))
        self.assertEqual(len(response.context["colleagues"]), COLLEAGUE_PAGE)
        rest = self.client.get(reverse("contacts:calendar-colleagues"),
                               {"offset": COLLEAGUE_PAGE}).json()
        self.assertEqual(len(rest["results"]) + COLLEAGUE_PAGE, rest["total"])
        self.assertFalse(rest["has_more"])
        # The first page is the head of the assignable list, and the second
        # carries on from where it stopped rather than repeating it.
        expected = [perm.user_label(other) for other
                    in perm.assignable_users_for(self.user).exclude(pk=self.user.pk)]
        first_page = [row["label"] for row in response.context["colleagues"]]
        self.assertEqual(first_page, expected[:COLLEAGUE_PAGE])
        self.assertEqual([row["label"] for row in rest["results"]], expected[COLLEAGUE_PAGE:])

    def test_you_cannot_read_the_calendar_of_someone_you_may_not_see(self):
        from contacts.models import Team, UserProfile

        UserProfile.objects.create(user=self.user, role=UserProfile.ROLE_MEMBER,
                                   record_visibility=UserProfile.VISIBILITY_TEAM)
        Team.objects.create(name="Mano komanda").members.add(self.user)
        response = self.client.get(reverse("contacts:calendar"))
        self.assertEqual(response.context["colleagues"], [])
        self.assertEqual(
            self.client.get(reverse("contacts:calendar-colleague-events"
                                    , args=[self.mate.pk])).status_code, 404)


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

    def test_a_handed_over_task_rings_the_recipients_bell_until_they_open_it(self):
        task = self._reminder(text="Perduota", assigned_to=self.user, created_by=self.mate)
        # It counts for the recipient even though it is two days out.
        self.client.force_login(self.user)
        page = self.client.get(reverse("contacts:list"))
        self.assertEqual(page.context["active_reminder_count"], 1)
        self.assertIn(task, list(page.context["active_reminders_menu"]))
        # Opening the bell marks it read and clears the badge.
        self.client.post(reverse("contacts:reminder-mark-read"))
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
        for route in ['contacts:list', 'contacts:company-list', 'contacts:settings', 'contacts:archive-list', 'contacts:import-export']:
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
        self.client.post(reverse('contacts:reminder-mark-read'))
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
        response = self.client.get(reverse('contacts:list'))
        self.assertEqual(response.context['active_reminder_count'], 0)
        self.assertFalse(response.context['active_reminders_menu'].exists())
        self.assertFalse(response.context['scheduled_reminders_menu'].exists())

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
        self.assertIn(url, self.client.get(reverse("contacts:reminder-snapshot")).json()["html"])
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
        self.assertContains(response, 'class="rec-actions"')
        response = self.client.get(self.company.get_absolute_url())
        self.assertContains(response, 'class="rec-actions"')
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

        # Ask for every data column, not just the default view — the registry
        # codes are still sortable, they simply are not shown out of the box.
        every_column = ["company_code", "vat_code", "address", "city", "phone", "email", "contacts", "owner"]
        response = self.client.get(reverse("contacts:company-list"),
                                   {"sort": "id", "direction": "desc", "columns": every_column})

        self.assertEqual(response.context["sort"], "id")
        self.assertEqual(list(response.context["page"])[0], other)
        self.assertEqual(response.context["page"].paginator.count, Company.objects.filter(deleted_at__isnull=True).count())
        self.assertContains(response, 'class="sort-control"', count=11)
        for key in ("name", "company_code", "vat_code", "address", "city", "phone", "email",
                    "contacts", "owner", "category", "tags", "id"):
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

    def test_company_list_defaults_to_columns_people_actually_scan(self):
        """Registry codes belong on an invoice, not in the first screen of a
        list — they stay one click away in "Stulpeliai" and in full on the card."""
        self.client.force_login(self.user)
        response = self.client.get(reverse("contacts:company-list"))
        self.assertEqual(response.context["columns"], ["city", "phone", "email", "contacts", "owner"])
        self.assertNotContains(response, "sort=company_code")
        # Still offered by the column picker, and still on the company card.
        self.assertContains(response, 'value="company_code"')
        self.assertContains(self.client.get(self.company.get_absolute_url()), "Įmonės kodas")

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
        self.assertContains(response, "rec-warn")
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
        self.assertNotContains(response, "rec-warn")

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

        self.assertContains(self.client.get(self.person.get_absolute_url()), "<b>Rasa Jonaitė</b>")
        self.assertContains(self.client.get(self.company.get_absolute_url()), "<b>Rasa Jonaitė</b>")

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
        scan_duplicates()
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
        scan_duplicates()
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
        scan_duplicates()
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
        scan_duplicates()
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
        from contacts.models import DuplicateCandidate
        scan_duplicates()
        self.assertFalse(DuplicateCandidate.objects.exists())

    def test_strict_review_detects_exact_full_name(self):
        self.client.force_login(self.user)
        DuplicateSettings.objects.update_or_create(pk=1, defaults={"enabled": True})
        other = Person.objects.create(first_name=self.person.first_name, last_name=self.person.last_name)
        scan_duplicates()

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
        scan_duplicates()

        low, high = sorted((self.person.pk, twin.pk))
        self.client.post(reverse("contacts:duplicate-dismiss", args=["person", low, high]))
        self.assertEqual(DuplicateException.objects.filter(kind="person", left_id=low, right_id=high).count(), 1)

        # Gone at once, and the next scan does not bring it back.
        self.assertContains(self.client.get(reverse("contacts:duplicate-list")), "Galimų dublikatų nerasta")
        scan_duplicates()
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
        # Import and export are one settings section, and the read settings live
        # in a fold on it.
        page = self.client.get(reverse("contacts:import-export"))
        self.assertContains(page, "CSV skaitymo nustatymai")
        self.assertTrue(reverse("contacts:import-export").startswith("/settings/"))
        self.assertContains(page, 'class="settings-nav"')
        self.client.post(reverse("contacts:import-export"),
                         {"op": "read_settings", "import_delimiter": "auto", "import_encoding": "auto"})
        system = SystemSettings.load()
        self.assertEqual((system.import_delimiter, system.import_encoding), ("auto", "auto"))
        content = "Vardas;Pavardė;Pareigos\nJonas;Kęstutaitis;Vadovas\n".encode("cp1257")
        self._import_file(SimpleUploadedFile("kontaktai.csv", content, content_type="text/csv"))
        person = Person.objects.get(first_name="Jonas", last_name="Kęstutaitis")
        self.assertEqual(person.job_title, "Vadovas")

    def test_import_reports_a_real_phone_duplicate(self):
        self.client.force_login(self.user)
        content = "Vardas,Pavardė,Telefonai\nKitas,Asmuo,+370 645 21 987\n".encode()
        _preview, response = self._import_file(SimpleUploadedFile("contacts.csv", content, content_type="text/csv"))
        self.assertContains(response, "Galimi dublikatai: 1")
        imported = Person.objects.get(first_name="Kitas", last_name="Asmuo")
        scan_duplicates()
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

    def test_the_journal_gets_the_whole_page_width(self):
        """Seven columns in a 680px form column left 29px each for Objektas, Buvo
        and Tapo. It asks for the wide layout; every other settings page keeps
        the narrow one, which is the right measure for a form."""
        self.client.force_login(self.user)
        self.user.is_superuser = True
        self.user.save()
        journal = self.client.get(reverse("contacts:settings-audit"))
        self.assertTrue(journal.context["settings_wide"])
        self.assertContains(journal, 'class="settings-layout is-wide"')
        profile = self.client.get(reverse("contacts:settings"))
        self.assertNotContains(profile, "is-wide")

    def test_each_user_shapes_their_own_side_menu(self):
        """Unticked entries leave the menu, and up to five shortcuts sit right
        after the core entries."""
        from contacts.models import UserProfile

        self.client.force_login(self.user)
        page = self.client.get(reverse("contacts:settings-menu"))
        self.assertEqual(page.status_code, 200)

        response = self.client.post(reverse("contacts:settings-menu"), {
            "visible": ["calendar", "analytics"],
            "shortcut_kind": ["page", "person", "action"],
            "shortcut_value": ["archive", str(self.person.pk), "person-create"],
        })
        self.assertRedirects(response, reverse("contacts:settings-menu"))
        config = UserProfile.objects.get(user=self.user).menu_config
        self.assertEqual(sorted(config["hidden"]), ["archive", "duplicates", "import-export"])
        self.assertEqual(config["shortcuts"], [
            {"kind": "page", "value": "archive"},
            {"kind": "person", "value": str(self.person.pk)},
            {"kind": "action", "value": "person-create"},
        ])

        menu = self.client.get(reverse("contacts:list")).context["crm_menu"]
        self.assertEqual([item.key for item in menu["core"]],
                         ["home", "contacts", "companies", "calendar", "analytics"])
        # The record shortcut carries the record's own name and link.
        self.assertEqual([item.label for item in menu["shortcuts"]][1], str(self.person))
        self.assertEqual(menu["shortcuts"][1].url, self.person.get_absolute_url())
        # The unticked entries are gone from the menu, and nothing is folded away.
        self.assertNotIn("more", menu)
        for key in ("archive", "duplicates", "import-export"):
            self.assertNotIn(key, [item.key for item in menu["core"]])
        # Their pages stay reachable: hiding a menu row is not a permission.
        self.assertEqual(self.client.get(reverse("contacts:archive-list")).status_code, 200)

    def test_menu_shortcuts_are_capped_and_drop_targets_that_disappeared(self):
        from contacts.models import UserProfile

        self.client.force_login(self.user)
        response = self.client.post(reverse("contacts:settings-menu"), {
            "visible": ["calendar"],
            "shortcut_kind": ["page"] * 6,
            "shortcut_value": ["archive", "calendar", "analytics", "duplicates", "import-export", "companies"],
        })
        self.assertContains(response, "ne daugiau kaip")
        # A shortcut whose record is archived simply stops being rendered.
        profile, _ = UserProfile.objects.get_or_create(user=self.user)
        profile.menu_config = {"hidden": [], "shortcuts": [{"kind": "person", "value": str(self.person.pk)}]}
        profile.save()
        self.assertEqual(len(self.client.get(reverse("contacts:list")).context["crm_menu"]["shortcuts"]), 1)
        self.person.deleted_at = timezone.now()
        self.person.save()
        self.assertEqual(self.client.get(reverse("contacts:list")).context["crm_menu"]["shortcuts"], [])

    def test_the_reminder_list_page_is_gone_and_the_bell_leads_to_the_calendar(self):
        """Reminders live in the bell, the calendar and the record cards now."""
        from django.urls import NoReverseMatch

        self.client.force_login(self.user)
        with self.assertRaises(NoReverseMatch):
            reverse("contacts:reminder-list")
        self.assertEqual(self.client.get("/reminders/").status_code, 404)
        page = self.client.get(reverse("contacts:list"))
        self.assertNotContains(page, ">Priminimai</a>")
        # The bell still opens them, and its footer now points at the calendar.
        self.assertContains(page, 'id="reminders"')
        self.assertContains(page, reverse("contacts:reminder-mark-read"))
        self.assertIn(reverse("contacts:calendar"),
                      self.client.get(reverse("contacts:reminder-snapshot")).json()["html"])

    def test_the_bell_lists_both_tabs_and_opening_it_marks_them_read(self):
        self.client.force_login(self.user)
        active = Reminder.objects.create(person=self.person, text="Dabar", due_at=timezone.now() - timedelta(minutes=1), created_by=self.user)
        Reminder.objects.create(person=self.person, text="Rytoj", due_at=timezone.now() + timedelta(days=1), created_by=self.user)
        snapshot = self.client.get(reverse("contacts:reminder-snapshot")).json()
        self.assertIn("Dabar", snapshot["html"])
        self.assertIn("Rytoj", snapshot["html"])
        self.assertEqual(snapshot["count"], 1)
        # Reading the bell must not clear it; only opening it does.
        active.refresh_from_db()
        self.assertIsNone(active.read_at)
        self.assertEqual(self.client.post(reverse("contacts:reminder-mark-read")).status_code, 200)
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
            # Secondary context moved to the rail; audit metadata is the quiet card.
            self.assertContains(page, 'class="rec-rail"')
            self.assertContains(page, 'class="detail-card meta-card"')
            self.assertContains(page, "Paskutinis kontaktas")
            # One composer above the tabs; the tabs only filter the feed.
            self.assertContains(page, 'id="composer"')
            self.assertContains(page, 'data-tab="all"')
            self.assertContains(page, 'data-tab="comments"')
            self.assertContains(page, 'data-tab="reminders"')
            self.assertContains(page, 'data-tab="files"')
            self.assertNotContains(page, 'data-tab="activity"')

    def test_record_header_carries_the_primary_actions_and_hides_archiving(self):
        """Logging an entry or a reminder must not need a scroll; archiving must."""
        self.client.force_login(self.user)
        page = self.client.get(self.person.get_absolute_url())
        self.assertContains(page, "data-focus-composer")
        self.assertContains(page, 'data-open-tab="reminders"')
        # Archiving lives in the overflow menu, not beside the primary buttons.
        self.assertContains(page, 'class="rec-menu-panel"')
        head = page.content.decode().split('class="rec-menu-panel"')[0]
        self.assertNotIn("Archyvuoti", head)

    def test_feed_entry_shows_the_author_and_a_relative_time(self):
        self.client.force_login(self.user)
        Activity.objects.create(person=self.person, activity_type="call",
                                text="Skambinta", created_by=self.user)
        page = self.client.get(self.person.get_absolute_url())
        self.assertContains(page, 'class="feed-icon act-call"')
        self.assertContains(page, 'class="feed-when"')

    def test_short_since_uses_one_unit_from_the_crm_catalogue(self):
        from django.utils import translation

        from contacts.templatetags.crm_format import short_since

        now = timezone.now()
        self.assertEqual(short_since(None), "")
        self.assertEqual(short_since(now - timedelta(seconds=5)), "ką tik")
        self.assertEqual(short_since(now - timedelta(hours=2, minutes=30)), "prieš 2 val.")
        self.assertEqual(short_since(now - timedelta(days=3, hours=4)), "prieš 3 d.")
        # The wording is ours, not Django's, so it follows the active language.
        with translation.override("en"):
            self.assertEqual(short_since(now - timedelta(days=3)), "3 d ago")

    def test_feed_shows_every_entry_and_the_comments_tab_only_notes(self):
        self.client.force_login(self.user)
        Activity.objects.create(person=self.person, activity_type="note", text="Vidinis komentaras", created_by=self.user)
        Activity.objects.create(person=self.person, activity_type="call", text="Skambučio įrašas", created_by=self.user)
        page = self.client.get(self.person.get_absolute_url())
        self.assertEqual(sorted(a.text for a in page.context["all_entries"]),
                         ["Skambučio įrašas", "Vidinis komentaras"])
        self.assertEqual([a.text for a in page.context["comment_entries"]], ["Vidinis komentaras"])

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

    def test_only_a_post_can_clear_the_reminder_badge(self):
        """Marking read used to ride on a GET, guarded by Sec-Fetch-Site. It is a
        POST now, so Django's CSRF protection does that job instead."""
        self.client.force_login(self.member)
        Reminder.objects.create(person=self.person, text="Priminimas", created_by=self.member, assigned_to=self.member,
                                due_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(self.client.get(reverse("contacts:reminder-mark-read")).status_code, 405)
        self.assertTrue(Reminder.objects.filter(read_at__isnull=True).exists())
        self.client.post(reverse("contacts:reminder-mark-read"))
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

    # --- contacts/notifications.py at the function level -------------------

    def test_effective_digest_time_prefers_the_users_own_setting(self):
        from contacts.models import SystemSettings, UserProfile
        from contacts.notifications import effective_digest_time
        sys = SystemSettings.load()
        sys.digest_default_time = time(7, 0)
        sys.save()
        UserProfile.objects.filter(user=self.admin).update(digest_time=time(9, 30))
        self.admin.refresh_from_db()  # clear the cached crm_profile from setUp's own create()
        self.assertEqual(effective_digest_time(self.admin, sys), time(9, 30))

    def test_effective_digest_time_falls_back_to_the_system_default(self):
        from contacts.models import SystemSettings
        from contacts.notifications import effective_digest_time
        sys = SystemSettings.load()
        sys.digest_default_time = time(7, 0)
        sys.save()
        self.assertEqual(effective_digest_time(self.mate, sys), time(7, 0))  # no digest_time on the profile
        no_profile = get_user_model().objects.create_user("bepr", password="very-secure-password")
        self.assertEqual(effective_digest_time(no_profile, sys), time(7, 0))  # no profile at all

    def test_send_returns_false_immediately_when_the_user_has_no_email(self):
        from contacts.notifications import _send
        no_email = get_user_model().objects.create_user("bepr2", password="very-secure-password")
        self.assertFalse(_send("digest", "Tema", no_email, {"overdue": [], "today": []}, audit_label="x"))

    def test_send_logs_to_the_audit_trail_and_returns_false_on_smtp_failure(self):
        from contacts.models import AuditLog
        from contacts.notifications import _send
        with patch("django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("smtp down")):
            result = _send("digest", "Tema", self.admin, {"overdue": [], "today": []}, audit_label="siusti-nepavyko")
        self.assertFalse(result)
        entry = AuditLog.objects.get(target_label="siusti-nepavyko")
        self.assertIn("smtp down", entry.new_value)

    @override_settings(RUNNING_TESTS=False)
    def test_connection_picks_the_smtp_backend_when_email_is_configured(self):
        from contacts.integrations import EmailConfig
        from contacts.notifications import _connection
        cfg = EmailConfig(host="smtp.example.lt", port=587, user="a@b.lt", password="s3cret",
                          use_tls=True, use_ssl=False, from_email="a@b.lt", enabled=True)
        conn = _connection(cfg)
        self.assertEqual((conn.host, conn.port), ("smtp.example.lt", 587))

    @override_settings(RUNNING_TESTS=False)
    def test_connection_falls_back_to_the_console_backend_when_unconfigured(self):
        from contacts.integrations import EmailConfig
        from contacts.notifications import _connection
        cfg = EmailConfig(host="", port=0, user="", password="", use_tls=False, use_ssl=False,
                          from_email="crm@example.lt", enabled=False)
        conn = _connection(cfg)
        self.assertIn("console", type(conn).__module__)


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


class RecurrenceHelpersTests(TestCase):
    """contacts/recurrence.py at the function level. The view-level tests
    above only ever exercise weekly and daily; monthly/yearly rely on
    _add_months's month-length clamping, which is real date arithmetic —
    easy to get subtly wrong and easy to miss without a direct test."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("recur", password="very-secure-password")
        self.person = Person.objects.create(first_name="R", last_name="S")

    def test_add_months_clamps_to_the_shorter_target_month(self):
        from contacts.recurrence import _add_months
        jan31 = timezone.make_aware(datetime(2027, 1, 31, 9, 0))
        result = _add_months(jan31, 1)
        self.assertEqual((result.month, result.day), (2, 28))  # 2027: not a leap year

    def test_add_months_handles_a_leap_february(self):
        from contacts.recurrence import _add_months
        jan31 = timezone.make_aware(datetime(2028, 1, 31, 9, 0))
        result = _add_months(jan31, 1)
        self.assertEqual((result.month, result.day), (2, 29))  # 2028: a leap year

    def test_add_months_rolls_the_year_over(self):
        from contacts.recurrence import _add_months
        december = timezone.make_aware(datetime(2027, 12, 15, 9, 0))
        result = _add_months(december, 1)
        self.assertEqual((result.year, result.month, result.day), (2028, 1, 15))

    def test_step_covers_every_frequency_and_rejects_an_unknown_one(self):
        from contacts.recurrence import _step
        start = timezone.make_aware(datetime(2027, 1, 31, 9, 0))
        self.assertEqual(_step(start, "daily", 2), start + timedelta(days=2))
        self.assertEqual(_step(start, "weekly", 1), start + timedelta(weeks=1))
        monthly = _step(start, "monthly", 1)
        self.assertEqual((monthly.month, monthly.day), (2, 28))
        yearly = _step(start, "yearly", 1)
        self.assertEqual((yearly.year, yearly.month, yearly.day), (2028, 1, 31))
        self.assertIsNone(_step(start, "not-a-real-frequency", 1))

    def test_occurrences_yields_nothing_without_a_frequency(self):
        from contacts.recurrence import occurrences
        root = Reminder(due_at=timezone.now(), recurrence_freq="")
        self.assertEqual(list(occurrences(root)), [])

    def test_occurrences_stops_at_the_recurrence_count(self):
        from contacts.recurrence import occurrences
        now = timezone.now()
        root = Reminder(due_at=now, recurrence_freq="daily", recurrence_interval=1, recurrence_count=3)
        self.assertEqual(len(list(occurrences(root, now=now))), 3)

    def test_occurrences_stops_at_the_until_date(self):
        from contacts.recurrence import occurrences
        now = timezone.now()
        until = (now + timedelta(days=5)).date()
        root = Reminder(due_at=now, recurrence_freq="daily", recurrence_interval=1, recurrence_until=until)
        results = list(occurrences(root, now=now))
        self.assertTrue(all(dt.date() <= until for dt in results))
        self.assertGreaterEqual(len(results), 1)

    def test_extend_does_nothing_for_a_non_recurring_reminder(self):
        from contacts.recurrence import extend
        plain = Reminder.objects.create(
            person=self.person, text="Vienkartinis", due_at=timezone.now(), created_by=self.user)
        self.assertEqual(extend(plain), 0)
        self.assertEqual(plain.recurrence_children.count(), 0)

    def test_extend_does_nothing_for_a_child_occurrence(self):
        from contacts.recurrence import extend
        root = Reminder.objects.create(
            person=self.person, text="Serija", due_at=timezone.now(), created_by=self.user,
            recurrence_freq="daily", recurrence_count=3)
        extend(root)
        child = root.recurrence_children.first()
        self.assertIsNotNone(child)
        self.assertEqual(extend(child), 0)

    def test_a_monthly_series_started_on_the_31st_lands_on_valid_dates(self):
        """Each occurrence steps from the *previous* one, so a short month's
        clamp carries forward — Feb 28 stays 28 in March, it does not jump
        back to 31. That is the current, deliberate behaviour; this test is
        here so a future change to it is a conscious decision, not a surprise."""
        from contacts.recurrence import extend
        due = timezone.make_aware(datetime(2027, 1, 31, 10, 0))
        root = Reminder.objects.create(
            person=self.person, text="Mėnesinis", due_at=due, created_by=self.user,
            recurrence_freq="monthly", recurrence_interval=1, recurrence_count=4)
        created = extend(root)
        children = list(root.recurrence_children.order_by("due_at"))
        self.assertEqual(created, 3)
        self.assertEqual([(c.due_at.month, c.due_at.day) for c in children], [(2, 28), (3, 28), (4, 28)])


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

    # --- header decoding --------------------------------------------------

    def test_dec_falls_back_to_the_raw_value_when_header_decoding_fails(self):
        from contacts.mailfetch import _dec
        garbled = "=?utf-8?B?%%%not-base64%%%?="
        self.assertEqual(_dec(garbled), garbled)
        self.assertEqual(_dec(None), "")

    # --- body extraction ----------------------------------------------------

    def test_body_prefers_plain_text_and_skips_attachment_parts(self):
        from email.mime.application import MIMEApplication
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        from contacts.mailfetch import _body
        msg = MIMEMultipart()
        attachment = MIMEApplication(b"%PDF-1.4", _subtype="pdf")
        attachment.add_header("Content-Disposition", "attachment", filename="failas.pdf")
        msg.attach(attachment)  # walked first — must be skipped, not mistaken for the body
        msg.attach(MIMEText("<p>Nesvarbu</p>", "html"))
        msg.attach(MIMEText("Grynas tekstas", "plain"))
        self.assertEqual(_body(msg), "Grynas tekstas")

    def test_body_falls_back_to_stripped_html_when_there_is_no_plain_text(self):
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        from contacts.mailfetch import _body
        msg = MIMEMultipart()
        msg.attach(MIMEText("<p>Sveiki <b>visi</b></p>", "html"))
        body = _body(msg)
        self.assertIn("Sveiki", body)
        self.assertIn("visi", body)
        self.assertNotIn("<p>", body)
        self.assertNotIn("<b>", body)

    def test_body_skips_a_part_with_an_unreadable_charset_and_uses_the_next(self):
        from email.message import Message
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        from contacts.mailfetch import _body
        unreadable = Message()
        unreadable.set_type("text/plain")
        unreadable.set_param("charset", "totally-bogus-charset")
        unreadable.set_payload("nebus perskaityta")
        msg = MIMEMultipart()
        msg.attach(unreadable)
        msg.attach(MIMEText("Geras tekstas", "plain"))
        self.assertEqual(_body(msg), "Geras tekstas")

    def test_body_of_a_non_multipart_message_reads_the_message_itself(self):
        from email.message import EmailMessage

        from contacts.mailfetch import _body
        m = EmailMessage()
        m.set_content("Paprastas laiškas")
        self.assertEqual(_body(m).strip(), "Paprastas laiškas")

    # --- default author fallback chain -----------------------------------

    def test_default_author_falls_back_from_superuser_to_any_active_user(self):
        from contacts.mailfetch import _default_author
        get_user_model().objects.all().delete()
        self.assertIsNone(_default_author())
        only_member = get_user_model().objects.create_user("tik-narys", password="very-secure-password")
        self.assertEqual(_default_author(), only_member)
        admin = get_user_model().objects.create_user(
            "admin2", password="very-secure-password", is_superuser=True)
        self.assertEqual(_default_author(), admin)

    # --- attachments ---------------------------------------------------------

    def test_save_attachments_keeps_only_allowed_small_named_attachments(self):
        from email.mime.application import MIMEApplication
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        from contacts.mailfetch import _save_attachments
        msg = MIMEMultipart()
        msg.attach(MIMEText("tekstas", "plain"))

        good = MIMEApplication(b"%PDF-1.4 mazas", _subtype="pdf")
        good.add_header("Content-Disposition", "attachment", filename="sutartis.pdf")
        msg.attach(good)

        unnamed = MIMEApplication(b"data", _subtype="pdf")
        unnamed.add_header("Content-Disposition", "attachment")  # no filename
        msg.attach(unnamed)

        inline_image = MIMEApplication(b"inline-not-an-attachment", _subtype="pdf")
        inline_image.add_header("Content-Disposition", "inline", filename="logo.pdf")
        msg.attach(inline_image)

        disallowed_ext = MIMEApplication(b"#!/bin/sh\n", _subtype="octet-stream")
        disallowed_ext.add_header("Content-Disposition", "attachment", filename="skriptas.sh")
        msg.attach(disallowed_ext)

        empty = MIMEApplication(b"", _subtype="pdf")
        empty.add_header("Content-Disposition", "attachment", filename="tuscias.pdf")
        msg.attach(empty)

        too_big = MIMEApplication(b"x" * (10 * 1024 * 1024 + 1), _subtype="pdf")
        too_big.add_header("Content-Disposition", "attachment", filename="didelis.pdf")
        msg.attach(too_big)

        activity = Activity.objects.create(person=self.person, text="su priedais", created_by=self.staffer)
        _save_attachments(msg, activity)

        self.assertEqual(list(activity.attachments.values_list("original_name", flat=True)), ["sutartis.pdf"])

    def test_save_attachments_does_nothing_for_a_non_multipart_message(self):
        from email.message import EmailMessage

        from contacts.mailfetch import _save_attachments
        m = EmailMessage()
        m.set_content("be priedų")
        activity = Activity.objects.create(person=self.person, text="be priedų", created_by=self.staffer)
        _save_attachments(m, activity)
        self.assertEqual(activity.attachments.count(), 0)

    # --- process_message edge cases -------------------------------------------

    def test_a_message_with_no_message_id_is_skipped(self):
        from contacts.mailfetch import process_message
        from email.message import EmailMessage
        m = EmailMessage()
        m["From"] = "darbuotojas@imone.lt"
        m["To"] = "klientas@example.lt"
        m.set_content("Be Message-ID")
        self.assertEqual(process_message(m.as_bytes()), "skipped")
        self.assertFalse(Activity.objects.exists())

    def test_an_unparseable_date_header_falls_back_to_now_without_raising(self):
        from contacts.mailfetch import process_message
        from email.message import EmailMessage
        m = EmailMessage()
        m["Message-ID"] = "<bad-date@x>"
        m["From"] = "nezinomas@x.lt"
        m["To"] = "nezinomas-adresatas@x.lt"
        m["Date"] = "this is not a date"
        m.set_content("Turinys")
        self.assertEqual(process_message(m.as_bytes()), "unmatched")
        from contacts.models import IncomingMail
        mail = IncomingMail.objects.get(message_id="<bad-date@x>")
        self.assertIsNotNone(mail.received_at)

    # --- fetch(): the real IMAP loop, against a fake connection ---------------

    class _FakeImapConnection:
        def __init__(self, raw_messages, fail_on=None, empty_fetch_on=None, logout_raises=False):
            self._raw = raw_messages
            self._fail_on = fail_on
            self._empty_fetch_on = empty_fetch_on
            self._logout_raises = logout_raises
            self.logged_out = False
            self.stored = []

        def login(self, user, password):
            pass

        def select(self, folder):
            pass

        def search(self, charset, criteria):
            ids = [str(i + 1).encode() for i in range(len(self._raw))]
            return "OK", [b" ".join(ids)]

        def fetch(self, num, parts):
            index = int(num) - 1
            if index == self._fail_on:
                raise OSError("connection reset")
            if index == self._empty_fetch_on:
                return "OK", [b"no message data, just a status line"]
            return "OK", [(b"1 (RFC822 {%d}" % index, self._raw[index])]

        def store(self, num, flag, value):
            self.stored.append((num, flag, value))

        def logout(self):
            self.logged_out = True
            if self._logout_raises:
                raise OSError("already disconnected")

    def _enable_imap(self, user="crm@example.lt"):
        from contacts.crypto import encrypt
        from contacts.models import SystemSettings
        system = SystemSettings.load()
        system.imap_enabled = True
        system.imap_host = "imap.example.lt"
        system.imap_user = user
        system.imap_password = encrypt("s3cret")
        system.save()

    def test_fetch_processes_every_unseen_message_and_marks_it_seen(self):
        from contacts import mailfetch
        self._enable_imap()
        fake = self._FakeImapConnection([
            self._raw(mid="<f1@x>"),
            self._raw(mid="<f2@x>", to="nezinomas@x.lt"),
        ])
        with patch("imaplib.IMAP4_SSL", return_value=fake):
            counts = mailfetch.fetch()
        self.assertEqual(counts, {"activity": 1, "unmatched": 1})
        self.assertEqual(len(fake.stored), 2)
        self.assertTrue(fake.logged_out)

    def test_fetch_logs_out_even_when_a_message_fetch_fails(self):
        from contacts import mailfetch
        self._enable_imap()
        fake = self._FakeImapConnection([self._raw(mid="<f3@x>")], fail_on=0)
        with patch("imaplib.IMAP4_SSL", return_value=fake):
            with self.assertRaises(OSError):
                mailfetch.fetch()
        self.assertTrue(fake.logged_out)

    def test_fetch_skips_a_message_whose_fetch_response_carries_no_data(self):
        from contacts import mailfetch
        self._enable_imap()
        fake = self._FakeImapConnection([
            self._raw(mid="<empty@x>"),
            self._raw(mid="<f4@x>"),
        ], empty_fetch_on=0)
        with patch("imaplib.IMAP4_SSL", return_value=fake):
            counts = mailfetch.fetch()
        self.assertEqual(counts, {"activity": 1})
        self.assertFalse(Activity.objects.filter(message_id="<empty@x>").exists())

    def test_fetch_swallows_a_failure_to_log_out(self):
        from contacts import mailfetch
        self._enable_imap()
        fake = self._FakeImapConnection([self._raw(mid="<f5@x>")], logout_raises=True)
        with patch("imaplib.IMAP4_SSL", return_value=fake):
            counts = mailfetch.fetch()  # must not raise, even though logout() did
        self.assertEqual(counts, {"activity": 1})
        self.assertTrue(fake.logged_out)


class EntraLoginTests(TestCase):
    def test_username_helper_prefers_upn_then_email(self):
        # Called the way mozilla-django-oidc's get_username() actually calls a
        # two-argument OIDC_USERNAME_ALGO: (claims["email"], claims).
        from contacts.oidc import username_from_claims
        self.assertEqual(username_from_claims("a@b.lt", {"preferred_username": "A@B.LT"}), "a@b.lt")
        self.assertEqual(username_from_claims("c@d.lt", {"email": "c@d.lt"}), "c@d.lt")
        self.assertEqual(username_from_claims("", {}), "")

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

    def test_filter_users_by_claims_with_no_email_matches_nobody(self):
        from contacts.oidc import EntraOIDCBackend
        self.assertEqual(list(EntraOIDCBackend().filter_users_by_claims({})), [])

    def test_filter_users_by_claims_excludes_deactivated_accounts(self):
        from contacts.oidc import EntraOIDCBackend
        get_user_model().objects.create_user(
            "neaktyvus", email="neaktyvus@imone.lt", password="very-secure-password", is_active=False)
        self.assertEqual(
            list(EntraOIDCBackend().filter_users_by_claims({"email": "neaktyvus@imone.lt"})), [])

    def test_verify_claims_requires_an_email(self):
        from contacts.oidc import EntraOIDCBackend
        backend = EntraOIDCBackend()
        self.assertTrue(backend.verify_claims({"email": "a@b.lt"}))
        self.assertTrue(backend.verify_claims({"upn": "a@b.lt"}))
        self.assertFalse(backend.verify_claims({}))

    def test_create_user_provisions_an_account_only_when_the_switch_is_on(self):
        from contacts.models import SystemSettings, UserProfile
        from contacts.oidc import EntraOIDCBackend
        system = SystemSettings.load()
        system.oidc_create_users = True
        system.save()

        user = EntraOIDCBackend().create_user(
            {"email": "naujas2@imone.lt", "given_name": "Jonas", "family_name": "Jonaitis"})
        self.assertEqual(user.email, "naujas2@imone.lt")
        self.assertEqual((user.first_name, user.last_name), ("Jonas", "Jonaitis"))
        self.assertFalse(user.has_usable_password())
        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_update_user_overwrites_only_changed_non_blank_claims(self):
        from contacts.oidc import EntraOIDCBackend
        user = get_user_model().objects.create_user(
            "keiciamas", email="k@imone.lt", first_name="Sena", last_name="Pavardė",
            password="very-secure-password")
        EntraOIDCBackend().update_user(user, {"given_name": "Nauja", "family_name": ""})
        user.refresh_from_db()
        self.assertEqual(user.first_name, "Nauja")
        self.assertEqual(user.last_name, "Pavardė")  # blank claim never overwrites an existing value

    def test_update_user_does_not_write_when_nothing_changed(self):
        from contacts.oidc import EntraOIDCBackend
        user = get_user_model().objects.create_user(
            "nekeiciamas", email="n@imone.lt", first_name="Ana", last_name="Anaitė",
            password="very-secure-password")
        with patch("django.contrib.auth.models.User.save") as mock_save:
            EntraOIDCBackend().update_user(user, {"given_name": "Ana", "family_name": "Anaitė"})
            mock_save.assert_not_called()


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

        # Funnel is available to a staging instance, but only as a decision
        # stated twice: the serve file AND CRM_STAGING_PUBLIC=1 in its .env.
        # One of the two alone must not be enough, or a copied line publishes a
        # clone of production data by accident.
        funnel = root / "deploy" / "tailscale" / "serve-staging-funnel.json"
        self.assertIn("AllowFunnel", funnel.read_text())
        deploy = (root / "scripts" / "deploy-staging.sh").read_text()
        self.assertIn("serve-staging-funnel.json", deploy)
        self.assertIn("CRM_STAGING_PUBLIC=1", deploy)
        # And a serve file nobody vetted is still refused outright.
        self.assertIn("exit 1", deploy.split("serve-staging-funnel.json")[-1])
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

    def test_never_contacted_trigger_matches_a_contact_with_no_activity(self):
        from contacts.models import AutomationRule
        self._rule(trigger=AutomationRule.NEVER, threshold=5)
        self.assertEqual(self._run(), 1)

    def test_overdue_reminder_trigger_matches_and_notifies(self):
        from contacts.models import AutomationRule
        from django.core import mail
        Reminder.objects.create(person=self.person, text="Vėluoja", due_at=timezone.now() - timedelta(days=10),
                                created_by=self.admin)
        self._rule(trigger=AutomationRule.OVERDUE, threshold=3, action=AutomationRule.NOTIFY, action_user=self.admin)
        self.assertEqual(self._run(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_notify_action_is_logged_as_an_error_when_sending_fails(self):
        from contacts.models import AutomationLog
        self._rule()
        with patch("contacts.notifications.send_rule_notice", return_value=False):
            self._run()
        self.assertTrue(AutomationLog.objects.filter(status="error", detail__error="email not sent").exists())

    def test_assign_owner_action_errors_on_a_target_that_is_not_a_contact(self):
        from contacts.models import AutomationLog, AutomationRule
        Reminder.objects.create(person=self.person, text="Vėluoja", due_at=timezone.now() - timedelta(days=10),
                                created_by=self.admin)
        self._rule(trigger=AutomationRule.OVERDUE, threshold=3, action=AutomationRule.ASSIGN, action_user=self.admin)
        self._run()
        self.assertTrue(AutomationLog.objects.filter(status="error").exists())

    def test_add_tag_action_adds_the_tag_once_and_stops_re_adding_it(self):
        from contacts.models import AuditLog, AutomationRule
        tag = Tag.objects.create(name="Rizika")
        self._rule(action=AutomationRule.ADD_TAG, action_user=None, action_tag=tag)
        self._run()
        self.assertIn(tag, self.person.tags.all())
        self.assertTrue(AuditLog.objects.filter(
            target_id=str(self.person.pk), field="Žyma", detail__automation="Taisyklė").exists())

        audits_before = AuditLog.objects.filter(field="Žyma").count()
        self._run()  # tag already there — no duplicate add, no new audit entry
        self.assertEqual(self.person.tags.filter(pk=tag.pk).count(), 1)
        self.assertEqual(AuditLog.objects.filter(field="Žyma").count(), audits_before)

    def test_add_tag_action_fails_without_a_configured_tag(self):
        from contacts.models import AutomationLog, AutomationRule
        self._rule(action=AutomationRule.ADD_TAG, action_user=None, action_tag=None)
        self._run()
        self.assertTrue(AutomationLog.objects.filter(status="error").exists())

    def test_add_tag_action_fails_once_the_contact_already_has_three_tags(self):
        from contacts.models import AutomationLog, AutomationRule
        for name in ("A", "B", "C"):
            self.person.tags.add(Tag.objects.create(name=name))
        fourth = Tag.objects.create(name="Ketvirta")
        self._rule(action=AutomationRule.ADD_TAG, action_user=None, action_tag=fourth)
        self._run()
        self.assertTrue(AutomationLog.objects.filter(status="error").exists())
        self.assertNotIn(fourth, self.person.tags.all())

    def test_run_all_skips_a_rule_whose_trigger_is_not_registered(self):
        """Defence in depth: the form blocks this, but a rule already in the
        database (an old trigger, a hand-edited row) must not crash the loop."""
        from contacts.models import AutomationRule
        rule = self._rule()
        AutomationRule.objects.filter(pk=rule.pk).update(trigger="not-a-real-trigger")
        self.assertEqual(self._run(), 0)


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


class SecretsEncryptionTests(TestCase):
    """contacts/crypto.py — the Fernet wrapper around integration passwords.

    CRM_SECRETS_KEY lives only in the environment (never the database), so
    every path here is exercised through os.environ, not Django settings.
    """

    def test_roundtrip_when_a_key_is_configured(self):
        token = crypto.encrypt("s3cret-imap-password")
        self.assertTrue(token.startswith("enc:v1:"))
        self.assertNotIn("s3cret-imap-password", token)
        self.assertEqual(crypto.decrypt(token), "s3cret-imap-password")

    def test_encrypting_an_empty_value_returns_empty_not_a_token(self):
        self.assertEqual(crypto.encrypt(""), "")
        self.assertEqual(crypto.encrypt(None), "")

    def test_encrypt_without_a_key_raises_so_the_caller_cannot_silently_lose_the_password(self):
        with patch.dict(os.environ, {"CRM_SECRETS_KEY": ""}):
            with self.assertRaises(RuntimeError):
                crypto.encrypt("would be lost")

    def test_decrypt_without_a_key_returns_empty_rather_than_raising(self):
        """The real scenario: a value was encrypted, then CRM_SECRETS_KEY was
        unset (or lost) before it was read back — the UI must show "not set",
        not a 500."""
        token = crypto.encrypt("stored-earlier")
        with patch.dict(os.environ, {"CRM_SECRETS_KEY": ""}):
            self.assertEqual(crypto.decrypt(token), "")

    def test_decrypt_of_a_tampered_token_returns_empty_rather_than_raising(self):
        token = crypto.encrypt("original")
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        self.assertEqual(crypto.decrypt(tampered), "")

    def test_decrypt_ignores_a_value_that_was_never_encrypted(self):
        self.assertEqual(crypto.decrypt("plain-text-password"), "")
        self.assertEqual(crypto.decrypt(""), "")
        self.assertEqual(crypto.decrypt(None), "")

    def test_a_malformed_key_is_treated_as_no_key_configured(self):
        with patch.dict(os.environ, {"CRM_SECRETS_KEY": "not-a-valid-fernet-key"}):
            self.assertFalse(crypto.secrets_available())
            with self.assertRaises(RuntimeError):
                crypto.encrypt("x")

    def test_secrets_available_reflects_whether_a_key_is_set(self):
        self.assertTrue(crypto.secrets_available())
        with patch.dict(os.environ, {"CRM_SECRETS_KEY": ""}):
            self.assertFalse(crypto.secrets_available())

    def test_looks_encrypted_detects_the_prefix_only(self):
        self.assertTrue(crypto.looks_encrypted(crypto.encrypt("x")))
        self.assertFalse(crypto.looks_encrypted("x"))
        self.assertFalse(crypto.looks_encrypted(""))
        self.assertFalse(crypto.looks_encrypted(None))


class RecordVisibilityTests(TestCase):
    """contacts/permissions.py — role, capability and record-visibility rules.

    These gate what a user (and, through the same functions, an API token)
    may see and do, so a mistake here is a data leak, not a cosmetic bug.
    """

    def setUp(self):
        self.admin = get_user_model().objects.create_user("admin", password="x", is_superuser=True)
        self.staff_no_profile = get_user_model().objects.create_user("staffer", password="x", is_staff=True)
        self.member = get_user_model().objects.create_user("member", password="x")
        self.restricted = get_user_model().objects.create_user("restricted", password="x")
        UserProfile.objects.create(user=self.member, role=UserProfile.ROLE_MEMBER)
        UserProfile.objects.create(user=self.restricted, role=UserProfile.ROLE_RESTRICTED)

    # --- role_of / is_admin -------------------------------------------------

    def test_role_of_anonymous_user_is_none(self):
        self.assertIsNone(perm.role_of(AnonymousUser()))
        self.assertFalse(perm.is_admin(AnonymousUser()))

    def test_role_of_superuser_is_admin_even_without_a_profile(self):
        self.assertEqual(perm.role_of(self.admin), UserProfile.ROLE_ADMIN)
        self.assertTrue(perm.is_admin(self.admin))

    def test_role_of_staff_without_a_profile_falls_back_to_admin(self):
        self.assertEqual(perm.role_of(self.staff_no_profile), UserProfile.ROLE_ADMIN)

    def test_role_of_plain_user_without_a_profile_falls_back_to_member(self):
        plain = get_user_model().objects.create_user("plain", password="x")
        self.assertEqual(perm.role_of(plain), UserProfile.ROLE_MEMBER)

    def test_role_of_honours_the_stored_profile_role(self):
        self.assertEqual(perm.role_of(self.restricted), UserProfile.ROLE_RESTRICTED)

    # --- has_capability / capability_matrix ---------------------------------

    def test_admin_has_every_capability_regardless_of_role_defaults(self):
        for key, _label in perm.CAPABILITIES:
            self.assertTrue(perm.has_capability(self.admin, key))

    def test_anonymous_user_has_no_capability(self):
        for key, _label in perm.CAPABILITIES:
            self.assertFalse(perm.has_capability(AnonymousUser(), key))

    def test_member_and_restricted_defaults_differ_on_import(self):
        self.assertTrue(perm.has_capability(self.member, "can_import"))
        self.assertFalse(perm.has_capability(self.restricted, "can_import"))

    def test_a_stored_role_permission_overrides_the_default(self):
        RolePermissions.objects.create(role=UserProfile.ROLE_MEMBER, permissions={"can_delete": False})
        self.assertFalse(perm.has_capability(self.member, "can_delete"))
        # Untouched capabilities on the same role keep their default.
        self.assertTrue(perm.has_capability(self.member, "can_export"))

    def test_capability_matrix_reflects_defaults_and_overrides(self):
        RolePermissions.objects.create(role=UserProfile.ROLE_RESTRICTED, permissions={"can_export": False})
        matrix = perm.capability_matrix()
        self.assertFalse(matrix[UserProfile.ROLE_RESTRICTED]["can_export"])
        self.assertTrue(matrix[UserProfile.ROLE_MEMBER]["can_import"])
        self.assertFalse(matrix[UserProfile.ROLE_RESTRICTED]["can_import"])

    def test_a_manager_sees_every_record_but_configures_nothing(self):
        """The role an organisation's "manager" AD group maps to: the whole base
        to supervise, none of the settings."""
        manager = get_user_model().objects.create_user("vadovas", password="very-secure-password")
        UserProfile.objects.create(user=manager, role=UserProfile.ROLE_MANAGER,
                                   record_visibility=UserProfile.VISIBILITY_OWN)
        # Even "own records only" on the profile does not narrow a manager.
        self.assertTrue(perm.sees_all_records(manager))
        self.assertFalse(perm.is_admin(manager))
        self.assertTrue(perm.has_capability(manager, "can_view_audit"))
        self.assertFalse(perm.has_capability(manager, "can_manage_automations"))
        # The settings pages an admin owns stay shut.
        self.client.force_login(manager)
        self.assertEqual(self.client.get(reverse("contacts:settings-users")).status_code, 404)
        self.assertEqual(self.client.get(reverse("contacts:settings-permissions")).status_code, 404)

    # --- record_visibility ---------------------------------------------------

    def test_anonymous_and_admin_see_everything(self):
        self.assertEqual(perm.record_visibility(AnonymousUser()), UserProfile.VISIBILITY_ALL)
        self.assertEqual(perm.record_visibility(self.admin), UserProfile.VISIBILITY_ALL)
        self.assertTrue(perm.sees_all_records(self.admin))

    def test_own_profile_setting_is_honoured(self):
        self.member.crm_profile.record_visibility = UserProfile.VISIBILITY_OWN
        self.member.crm_profile.save()
        self.assertEqual(perm.record_visibility(self.member), UserProfile.VISIBILITY_OWN)
        self.assertFalse(perm.sees_all_records(self.member))

    def test_restricted_role_floors_visibility_at_own_even_if_profile_says_all(self):
        self.restricted.crm_profile.record_visibility = UserProfile.VISIBILITY_ALL
        self.restricted.crm_profile.save()
        self.assertEqual(perm.record_visibility(self.restricted), UserProfile.VISIBILITY_OWN)

    def test_team_marked_team_only_narrows_a_members_all_setting(self):
        team = Team.objects.create(name="Pardavimai", visibility=Team.VISIBILITY_TEAM)
        team.members.add(self.member)
        self.assertEqual(perm.record_visibility(self.member), UserProfile.VISIBILITY_TEAM)

    def test_membership_in_an_all_visibility_team_does_not_narrow_anything(self):
        team = Team.objects.create(name="Visi", visibility=Team.VISIBILITY_TEAM)
        team.members.add(self.member)
        team2 = Team.objects.create(name="Rinkodara", visibility=Team.VISIBILITY_ALL)
        team2.members.add(self.member)
        # Still team-restricted: one team-only membership is enough to narrow it.
        self.assertEqual(perm.record_visibility(self.member), UserProfile.VISIBILITY_TEAM)

    def test_restricted_role_stays_own_even_inside_a_team(self):
        """own is stricter than team, so it must win regardless of order."""
        team = Team.objects.create(name="Aptarnavimas", visibility=Team.VISIBILITY_TEAM)
        team.members.add(self.restricted)
        self.assertEqual(perm.record_visibility(self.restricted), UserProfile.VISIBILITY_OWN)

    # --- teammate_ids / responsible_*_ids -------------------------------------

    def test_teammate_ids_includes_self_and_shared_team_members_only(self):
        team = Team.objects.create(name="A")
        team.members.add(self.member, self.restricted)
        outsider = get_user_model().objects.create_user("outsider", password="x")
        ids = perm.teammate_ids(self.member)
        self.assertIn(self.member.pk, ids)
        self.assertIn(self.restricted.pk, ids)
        self.assertNotIn(outsider.pk, ids)

    def test_responsible_person_ids_accepts_a_single_id_or_a_list(self):
        person = Person.objects.create(first_name="R", last_name="P")
        person.responsibles.add(self.member)
        self.assertIn(person.pk, list(perm.responsible_person_ids(self.member.pk)))
        self.assertIn(person.pk, list(perm.responsible_person_ids([self.member.pk])))

    # --- visible_people / visible_companies / visible_reminders ---------------

    def test_visible_people_none_user_returns_the_queryset_unfiltered(self):
        Person.objects.create(first_name="A", last_name="B")
        self.assertEqual(perm.visible_people(None).count(), 1)

    def test_visible_companies_none_user_returns_the_queryset_unfiltered(self):
        Company.objects.create(name="X")
        self.assertEqual(perm.visible_companies(None).count(), 1)

    def test_own_visibility_sees_owned_responsible_and_ownerless_but_not_others(self):
        self.member.crm_profile.record_visibility = UserProfile.VISIBILITY_OWN
        self.member.crm_profile.save()
        mine = Person.objects.create(first_name="Mano", last_name="K", owner=self.member)
        responsible_for = Person.objects.create(first_name="Atsak", last_name="K")
        responsible_for.responsibles.add(self.member)
        ownerless = Person.objects.create(first_name="Niekieno", last_name="K")
        someone_elses = Person.objects.create(first_name="Kito", last_name="K", owner=self.restricted)

        visible_ids = set(perm.visible_people(self.member).values_list("pk", flat=True))
        self.assertEqual(visible_ids, {mine.pk, responsible_for.pk, ownerless.pk})
        self.assertNotIn(someone_elses.pk, visible_ids)

    def test_team_visibility_sees_teammates_records_but_not_outsiders(self):
        team = Team.objects.create(name="B", visibility=Team.VISIBILITY_TEAM)
        team.members.add(self.member, self.restricted)
        teammates_company = Company.objects.create(name="Komandos", owner=self.restricted)
        outsider = get_user_model().objects.create_user("outsider2", password="x")
        outsiders_company = Company.objects.create(name="Svetima", owner=outsider)

        visible_ids = set(perm.visible_companies(self.member).values_list("pk", flat=True))
        self.assertIn(teammates_company.pk, visible_ids)
        self.assertNotIn(outsiders_company.pk, visible_ids)

    def test_visible_reminders_follows_the_linked_records_visibility(self):
        self.restricted.crm_profile.record_visibility = UserProfile.VISIBILITY_OWN
        self.restricted.crm_profile.save()
        mine = Person.objects.create(first_name="M", last_name="N", owner=self.restricted)
        someone_elses = Person.objects.create(first_name="O", last_name="P", owner=self.member)
        r_mine = Reminder.objects.create(person=mine, text="a", due_at=timezone.now(), created_by=self.admin)
        r_other = Reminder.objects.create(person=someone_elses, text="b", due_at=timezone.now(), created_by=self.admin)

        visible_ids = set(perm.visible_reminders(self.restricted).values_list("pk", flat=True))
        self.assertIn(r_mine.pk, visible_ids)
        self.assertNotIn(r_other.pk, visible_ids)

    def test_visible_reminders_with_no_record_is_private_to_creator_or_assignee(self):
        self.restricted.crm_profile.record_visibility = UserProfile.VISIBILITY_OWN
        self.restricted.crm_profile.save()
        own_calendar_entry = Reminder.objects.create(text="calendar", due_at=timezone.now(), created_by=self.restricted)
        someone_elses_entry = Reminder.objects.create(text="calendar2", due_at=timezone.now(), created_by=self.member)
        assigned_to_me = Reminder.objects.create(text="calendar3", due_at=timezone.now(), created_by=self.member, assigned_to=self.restricted)

        visible_ids = set(perm.visible_reminders(self.restricted).values_list("pk", flat=True))
        self.assertIn(own_calendar_entry.pk, visible_ids)
        self.assertIn(assigned_to_me.pk, visible_ids)
        self.assertNotIn(someone_elses_entry.pk, visible_ids)

    def test_visible_reminders_none_user_returns_the_queryset_unfiltered(self):
        Reminder.objects.create(text="x", due_at=timezone.now(), created_by=self.admin)
        self.assertEqual(perm.visible_reminders(None).count(), 1)

    # --- can_see_person / can_see_company -------------------------------------

    def test_can_see_person_and_company_respect_own_visibility(self):
        self.restricted.crm_profile.record_visibility = UserProfile.VISIBILITY_OWN
        self.restricted.crm_profile.save()
        mine = Person.objects.create(first_name="M", last_name="N", owner=self.restricted)
        someone_elses = Person.objects.create(first_name="O", last_name="P", owner=self.member)
        self.assertTrue(perm.can_see_person(self.restricted, mine))
        self.assertFalse(perm.can_see_person(self.restricted, someone_elses))

        mine_co = Company.objects.create(name="Mano įmonė", owner=self.restricted)
        others_co = Company.objects.create(name="Kito įmonė", owner=self.member)
        self.assertTrue(perm.can_see_company(self.restricted, mine_co))
        self.assertFalse(perm.can_see_company(self.restricted, others_co))

    def test_admin_can_see_any_record(self):
        someone_elses = Person.objects.create(first_name="O", last_name="P", owner=self.member)
        self.assertTrue(perm.can_see_person(self.admin, someone_elses))

    # --- user_label / assignable_users(_for) ----------------------------------

    def test_user_label_prefers_full_name_over_username(self):
        self.member.first_name, self.member.last_name = "Jonas", "Jonaitis"
        self.member.save()
        self.assertEqual(perm.user_label(self.member), "Jonas Jonaitis")
        self.assertEqual(perm.user_label(self.restricted), "restricted")
        self.assertEqual(perm.user_label(None), "")

    def test_assignable_users_excludes_inactive_accounts(self):
        inactive = get_user_model().objects.create_user("gone", password="x", is_active=False)
        names = {u.username for u in perm.assignable_users()}
        self.assertNotIn(inactive.username, names)
        self.assertIn(self.member.username, names)

    def test_assignable_users_for_a_restricted_viewer_is_limited_to_teammates(self):
        self.restricted.crm_profile.record_visibility = UserProfile.VISIBILITY_OWN
        self.restricted.crm_profile.save()
        team = Team.objects.create(name="C")
        team.members.add(self.restricted, self.member)
        outsider = get_user_model().objects.create_user("outsider3", password="x")
        names = {u.username for u in perm.assignable_users_for(self.restricted)}
        self.assertIn(self.member.username, names)
        self.assertNotIn(outsider.username, names)

    def test_assignable_users_for_an_admin_is_everyone(self):
        names = {u.username for u in perm.assignable_users_for(self.admin)}
        self.assertIn(self.member.username, names)
        self.assertIn(self.restricted.username, names)

    # --- active_admin_ids -------------------------------------------------

    def test_active_admin_ids_includes_superusers_and_excludes_members(self):
        ids = perm.active_admin_ids()
        self.assertIn(self.admin.pk, ids)
        self.assertIn(self.staff_no_profile.pk, ids)
        self.assertNotIn(self.member.pk, ids)


class ApiTests(TestCase):
    """The hand-rolled JSON API (contacts/api.py), /api/v1/ — bearer-token
    auth, scope enforcement and the same record visibility as the UI."""

    def setUp(self):
        self.owner = get_user_model().objects.create_user("api-owner", password="x")
        self.raw_write_token, write_hash = ApiToken.new()
        self.write_token = ApiToken.objects.create(
            name="write", token_hash=write_hash, prefix=self.raw_write_token[:12],
            scope=ApiToken.READ_WRITE, created_by=self.owner)
        self.raw_read_token, read_hash = ApiToken.new()
        self.read_token = ApiToken.objects.create(
            name="read", token_hash=read_hash, prefix=self.raw_read_token[:12],
            scope=ApiToken.READ, created_by=self.owner)

    def _auth(self, raw):
        return {"HTTP_AUTHORIZATION": f"Bearer {raw}"}

    def _post_json(self, url, payload, raw_token, **extra):
        return self.client.post(url, data=json.dumps(payload), content_type="application/json",
                                 **self._auth(raw_token), **extra)

    # --- authentication -----------------------------------------------------

    def test_missing_authorization_header_is_rejected(self):
        response = self.client.get(reverse("api:me"))
        self.assertEqual(response.status_code, 401)

    def test_garbage_bearer_token_is_rejected(self):
        response = self.client.get(reverse("api:me"), **self._auth("not-a-real-token"))
        self.assertEqual(response.status_code, 401)

    def test_revoked_token_is_rejected(self):
        self.write_token.revoked_at = timezone.now()
        self.write_token.save()
        response = self.client.get(reverse("api:me"), **self._auth(self.raw_write_token))
        self.assertEqual(response.status_code, 401)

    def test_token_of_a_deactivated_user_is_rejected(self):
        self.owner.is_active = False
        self.owner.save()
        response = self.client.get(reverse("api:me"), **self._auth(self.raw_write_token))
        self.assertEqual(response.status_code, 401)

    def test_me_reports_the_token_owner_and_scope(self):
        response = self.client.get(reverse("api:me"), **self._auth(self.raw_read_token))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["username"], "api-owner")
        self.assertEqual(data["scope"], ApiToken.READ)

    # --- scope enforcement ----------------------------------------------------

    def test_a_read_only_token_cannot_create_a_contact(self):
        response = self._post_json(reverse("api:contacts"), {"first_name": "X"}, self.raw_read_token)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Person.objects.exists())

    def test_a_read_only_token_cannot_delete_a_contact(self):
        person = Person.objects.create(first_name="A", last_name="B")
        response = self.client.delete(
            reverse("api:contact", args=[person.pk]), **self._auth(self.raw_read_token))
        self.assertEqual(response.status_code, 403)
        person.refresh_from_db()
        self.assertIsNone(person.deleted_at)

    # --- contacts collection --------------------------------------------------

    def test_creating_a_contact_requires_a_name(self):
        response = self._post_json(reverse("api:contacts"), {}, self.raw_write_token)
        self.assertEqual(response.status_code, 400)

    def test_create_then_fetch_a_contact_round_trips_through_the_api(self):
        response = self._post_json(reverse("api:contacts"),
                                    {"first_name": "Jonas", "last_name": "Jonaitis", "emails": ["j@example.lt"]},
                                    self.raw_write_token)
        self.assertEqual(response.status_code, 201)
        created = response.json()
        self.assertEqual(created["first_name"], "Jonas")
        self.assertEqual(created["emails"], ["j@example.lt"])

        fetched = self.client.get(reverse("api:contact", args=[created["id"]]), **self._auth(self.raw_read_token))
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["last_name"], "Jonaitis")

    def test_creating_a_likely_duplicate_is_refused_unless_forced(self):
        Person.objects.create(first_name="Ona", last_name="Onaitė")
        EmailAddress.objects.create(person=Person.objects.get(first_name="Ona"), email="ona@example.lt", is_primary=True)
        response = self._post_json(reverse("api:contacts"),
                                    {"first_name": "Ona", "last_name": "Onaitė", "emails": ["ona@example.lt"]},
                                    self.raw_write_token)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Person.objects.count(), 1)

        forced = self._post_json(reverse("api:contacts") + "?force=1",
                                  {"first_name": "Ona", "last_name": "Onaitė", "emails": ["ona@example.lt"]},
                                  self.raw_write_token)
        self.assertEqual(forced.status_code, 201)
        self.assertEqual(Person.objects.count(), 2)

    def test_fetching_an_unknown_contact_is_a_404(self):
        response = self.client.get(reverse("api:contact", args=[999999]), **self._auth(self.raw_read_token))
        self.assertEqual(response.status_code, 404)

    def test_a_restricted_tokens_owner_cannot_reach_someone_elses_contact(self):
        restricted_user = get_user_model().objects.create_user("api-restricted", password="x")
        UserProfile.objects.create(user=restricted_user, role=UserProfile.ROLE_RESTRICTED)
        raw, digest = ApiToken.new()
        ApiToken.objects.create(name="r", token_hash=digest, prefix=raw[:12],
                                 scope=ApiToken.READ_WRITE, created_by=restricted_user)
        someone_elses = Person.objects.create(first_name="Kito", last_name="Kontaktas", owner=self.owner)

        response = self.client.get(reverse("api:contact", args=[someone_elses.pk]), **self._auth(raw))
        self.assertEqual(response.status_code, 404)

        listing = self.client.get(reverse("api:contacts"), **self._auth(raw))
        self.assertEqual(listing.json()["count"], 0)

    def test_deleting_a_contact_requires_the_can_delete_capability(self):
        RolePermissions.objects.create(role=UserProfile.ROLE_MEMBER, permissions={"can_delete": False})
        UserProfile.objects.create(user=self.owner, role=UserProfile.ROLE_MEMBER)
        person = Person.objects.create(first_name="A", last_name="B")

        response = self.client.delete(reverse("api:contact", args=[person.pk]), **self._auth(self.raw_write_token))
        self.assertEqual(response.status_code, 403)
        person.refresh_from_db()
        self.assertIsNone(person.deleted_at)

    def test_patching_a_contact_updates_it(self):
        person = Person.objects.create(first_name="A", last_name="B")
        response = self._patch_json(reverse("api:contact", args=[person.pk]), {"job_title": "Vadovė"})
        self.assertEqual(response.status_code, 200)
        person.refresh_from_db()
        self.assertEqual(person.job_title, "Vadovė")

    def _patch_json(self, url, payload):
        return self.client.patch(url, data=json.dumps(payload), content_type="application/json",
                                  **self._auth(self.raw_write_token))

    def test_deleting_a_contact_archives_rather_than_erases_it(self):
        person = Person.objects.create(first_name="A", last_name="B")
        response = self.client.delete(reverse("api:contact", args=[person.pk]), **self._auth(self.raw_write_token))
        self.assertEqual(response.status_code, 200)
        person.refresh_from_db()
        self.assertIsNotNone(person.deleted_at)
        # Archived records drop out of both the API and the (deleted_at-filtered) UI queryset.
        self.assertEqual(self.client.get(reverse("api:contact", args=[person.pk]), **self._auth(self.raw_read_token)).status_code, 404)

    # --- companies --------------------------------------------------------

    def test_creating_a_company_requires_a_name(self):
        response = self._post_json(reverse("api:companies"), {}, self.raw_write_token)
        self.assertEqual(response.status_code, 400)

    def test_create_then_patch_a_company(self):
        created = self._post_json(reverse("api:companies"), {"name": "UAB Bandymas", "website": "example.lt"},
                                   self.raw_write_token).json()
        self.assertEqual(created["website"], "https://example.lt")
        response = self.client.patch(reverse("api:company", args=[created["id"]]),
                                      data=json.dumps({"city": "Vilnius"}), content_type="application/json",
                                      **self._auth(self.raw_write_token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["city"], "Vilnius")

    # --- activities ---------------------------------------------------------

    def test_creating_an_activity_requires_a_valid_type_and_a_linked_record(self):
        person = Person.objects.create(first_name="A", last_name="B")
        missing_record = self._post_json(reverse("api:activities"),
                                          {"activity_type": "note", "text": "x"}, self.raw_write_token)
        self.assertEqual(missing_record.status_code, 400)

        bad_type = self._post_json(reverse("api:activities"),
                                    {"activity_type": "not-a-type", "text": "x", "person_id": person.pk},
                                    self.raw_write_token)
        self.assertEqual(bad_type.status_code, 400)

        ok = self._post_json(reverse("api:activities"),
                              {"activity_type": "note", "text": "Skambinta", "person_id": person.pk},
                              self.raw_write_token)
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(person.activities.count(), 1)

    # --- reminders ------------------------------------------------------------

    def test_creating_a_reminder_requires_text_and_a_valid_due_at(self):
        bad = self._post_json(reverse("api:reminders"), {"text": "x", "due_at": "not-a-date"}, self.raw_write_token)
        self.assertEqual(bad.status_code, 400)

        ok = self._post_json(reverse("api:reminders"),
                              {"text": "Paskambinti", "due_at": "2030-01-01T10:00:00Z"}, self.raw_write_token)
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(ok.json()["assigned_to_id"], self.owner.pk)

    def test_the_api_carries_the_whole_event_both_ways(self):
        """A meeting made over the API has to come back as a meeting: kind, its
        description and the joining link, not just a line of text and a date."""
        body = {"text": "Susitikimas", "kind": "meeting", "due_at": "2030-01-01T10:00:00Z",
                "end_at": "2030-01-01T11:00:00Z", "description": "Dienotvarkė",
                "meeting_url": "https://meet.example.lt/abc"}
        created = self._post_json(reverse("api:reminders"), body, self.raw_write_token)
        self.assertEqual(created.status_code, 201)
        payload = created.json()
        self.assertEqual(payload["kind"], "meeting")
        self.assertEqual(payload["description"], "Dienotvarkė")
        self.assertEqual(payload["meeting_url"], "https://meet.example.lt/abc")
        self.assertEqual(payload["end_at"][:16], "2030-01-01T11:00")

        listed = self.client.get(reverse("api:reminders"), **self._auth(self.raw_read_token)).json()
        self.assertEqual([r["kind"] for r in listed["results"]], ["meeting"])

    def test_a_joining_link_belongs_to_a_meeting_and_an_end_cannot_precede_the_start(self):
        call = self._post_json(reverse("api:reminders"),
                               {"text": "Skambutis", "kind": "call", "due_at": "2030-01-01T10:00:00Z",
                                "meeting_url": "https://meet.example.lt/abc"}, self.raw_write_token)
        self.assertEqual(call.status_code, 201)
        self.assertEqual(call.json()["meeting_url"], "")

        backwards = self._post_json(reverse("api:reminders"),
                                    {"text": "Atbulas", "due_at": "2030-01-01T10:00:00Z",
                                     "end_at": "2030-01-01T09:00:00Z"}, self.raw_write_token)
        self.assertEqual(backwards.status_code, 400)

    def test_an_unknown_kind_falls_back_to_a_plain_reminder(self):
        response = self._post_json(reverse("api:reminders"),
                                   {"text": "Kažkas", "kind": "šventė", "due_at": "2030-01-01T10:00:00Z"},
                                   self.raw_write_token)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["kind"], "reminder")

    # --- pagination -----------------------------------------------------------

    def test_pagination_limit_is_capped_and_offset_is_respected(self):
        for i in range(3):
            Person.objects.create(first_name=f"P{i}", last_name="Test")
        response = self.client.get(reverse("api:contacts") + "?limit=500", **self._auth(self.raw_read_token))
        self.assertEqual(response.json()["limit"], 100)  # MAX_PAGE

        page = self.client.get(reverse("api:contacts") + "?limit=1&offset=1", **self._auth(self.raw_read_token))
        self.assertEqual(len(page.json()["results"]), 1)
        self.assertEqual(page.json()["count"], 3)

    def test_bad_pagination_params_are_a_400_not_a_500(self):
        response = self.client.get(reverse("api:contacts") + "?limit=abc", **self._auth(self.raw_read_token))
        self.assertEqual(response.status_code, 400)

    # --- request body and unhandled errors -------------------------------------

    def test_malformed_json_body_is_a_400(self):
        response = self.client.post(reverse("api:contacts"), data="{not json",
                                    content_type="application/json", **self._auth(self.raw_write_token))
        self.assertEqual(response.status_code, 400)

    def test_a_json_body_that_is_not_an_object_is_a_400(self):
        response = self.client.post(reverse("api:contacts"), data=json.dumps(["a", "b"]),
                                    content_type="application/json", **self._auth(self.raw_write_token))
        self.assertEqual(response.status_code, 400)

    def test_an_unhandled_error_is_a_500_without_leaking_a_traceback(self):
        person = Person.objects.create(first_name="A", last_name="B")
        with patch("contacts.api.serialize_person", side_effect=RuntimeError("boom")):
            response = self.client.get(reverse("api:contact", args=[person.pk]), **self._auth(self.raw_read_token))
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"error": "internal error"})
        self.assertNotIn("boom", response.content.decode())

    def test_an_unsupported_method_is_a_405(self):
        person = Person.objects.create(first_name="A", last_name="B")
        response = self.client.put(reverse("api:contact", args=[person.pk]), **self._auth(self.raw_write_token))
        self.assertEqual(response.status_code, 405)

    # --- searching and filtering the contacts collection ------------------------

    def test_contacts_collection_search_matches_name_and_email(self):
        match = Person.objects.create(first_name="Living", last_name="Stone")
        EmailAddress.objects.create(person=match, email="living@example.lt", is_primary=True)
        Person.objects.create(first_name="Kitas", last_name="Žmogus")
        response = self.client.get(reverse("api:contacts") + "?q=living", **self._auth(self.raw_read_token))
        ids = {row["id"] for row in response.json()["results"]}
        self.assertEqual(ids, {match.pk})

    def test_contacts_collection_filters_by_updated_since(self):
        old = Person.objects.create(first_name="Senas", last_name="Įrašas")
        Person.objects.filter(pk=old.pk).update(updated_at=timezone.now() - timedelta(days=2))
        cutoff = timezone.now() - timedelta(days=1)
        recent = Person.objects.create(first_name="Naujas", last_name="Įrašas")
        response = self.client.get(
            reverse("api:contacts"), {"since": cutoff.isoformat()}, **self._auth(self.raw_read_token))
        ids = {row["id"] for row in response.json()["results"]}
        self.assertEqual(ids, {recent.pk})

    def test_contacts_collection_filters_by_owner(self):
        mine = Person.objects.create(first_name="A", last_name="M", owner=self.owner)
        Person.objects.create(first_name="B", last_name="N")
        response = self.client.get(
            reverse("api:contacts") + f"?owner={self.owner.pk}", **self._auth(self.raw_read_token))
        ids = {row["id"] for row in response.json()["results"]}
        self.assertEqual(ids, {mine.pk})

    def test_writing_emails_deduplicates_within_the_same_request(self):
        created = self._post_json(reverse("api:contacts"), {
            "first_name": "A", "last_name": "Z",
            "emails": ["dup@example.lt", "DUP@example.lt", "dup@example.lt"],
        }, self.raw_write_token).json()
        self.assertEqual(created["emails"], ["dup@example.lt"])

    def test_patching_a_contact_sets_description_favourite_tags_and_categories(self):
        person = Person.objects.create(first_name="A", last_name="B")
        response = self._patch_json(reverse("api:contact", args=[person.pk]), {
            "description": "Apie jį", "favourite": True, "tags": ["VIP"], "categories": ["Partneris"],
        })
        self.assertEqual(response.status_code, 200)
        person.refresh_from_db()
        self.assertEqual(person.description, "Apie jį")
        self.assertTrue(person.favourite)
        self.assertEqual(list(person.tags.values_list("name", flat=True)), ["VIP"])
        self.assertEqual(list(person.categories.values_list("name", flat=True)), ["Partneris"])

    def test_patching_a_contact_can_link_it_to_a_visible_company(self):
        person = Person.objects.create(first_name="A", last_name="B")
        company = Company.objects.create(name="UAB Susieta")
        response = self._patch_json(reverse("api:contact", args=[person.pk]), {"company_id": company.pk})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(person.company_links.filter(company=company).exists())

    # --- companies collection ---------------------------------------------------

    def test_companies_collection_search_matches_name(self):
        match = Company.objects.create(name="UAB Rasta")
        Company.objects.create(name="Kita")
        response = self.client.get(reverse("api:companies") + "?q=rasta", **self._auth(self.raw_read_token))
        ids = {row["id"] for row in response.json()["results"]}
        self.assertEqual(ids, {match.pk})

    def test_companies_collection_filters_by_updated_since(self):
        old = Company.objects.create(name="Sena")
        Company.objects.filter(pk=old.pk).update(updated_at=timezone.now() - timedelta(days=2))
        cutoff = timezone.now() - timedelta(days=1)
        recent = Company.objects.create(name="Nauja")
        response = self.client.get(
            reverse("api:companies"), {"since": cutoff.isoformat()}, **self._auth(self.raw_read_token))
        ids = {row["id"] for row in response.json()["results"]}
        self.assertEqual(ids, {recent.pk})

    def test_patching_a_company_sets_description_tags_and_categories(self):
        company = Company.objects.create(name="UAB X")
        response = self.client.patch(reverse("api:company", args=[company.pk]), data=json.dumps({
            "description": "Aprašymas", "tags": ["Rizika"], "categories": ["A"],
        }), content_type="application/json", **self._auth(self.raw_write_token))
        self.assertEqual(response.status_code, 200)
        company.refresh_from_db()
        self.assertEqual(company.description, "Aprašymas")
        self.assertEqual(list(company.tags.values_list("name", flat=True)), ["Rizika"])

    def test_deleting_a_company_requires_the_can_delete_capability(self):
        RolePermissions.objects.create(role=UserProfile.ROLE_MEMBER, permissions={"can_delete": False})
        UserProfile.objects.create(user=self.owner, role=UserProfile.ROLE_MEMBER)
        company = Company.objects.create(name="UAB Saugoma")
        response = self.client.delete(reverse("api:company", args=[company.pk]), **self._auth(self.raw_write_token))
        self.assertEqual(response.status_code, 403)

    def test_deleting_a_company_archives_it(self):
        company = Company.objects.create(name="UAB Trinama")
        response = self.client.delete(reverse("api:company", args=[company.pk]), **self._auth(self.raw_write_token))
        self.assertEqual(response.status_code, 200)
        company.refresh_from_db()
        self.assertIsNotNone(company.deleted_at)

    # --- activities: visibility, filtering ---------------------------------------

    def test_creating_an_activity_against_an_invisible_person_is_a_404(self):
        restricted_user = get_user_model().objects.create_user("api-restricted2", password="x")
        UserProfile.objects.create(user=restricted_user, role=UserProfile.ROLE_RESTRICTED)
        raw, digest = ApiToken.new()
        ApiToken.objects.create(name="r2", token_hash=digest, prefix=raw[:12],
                                scope=ApiToken.READ_WRITE, created_by=restricted_user)
        someone_elses = Person.objects.create(first_name="Kito", last_name="K", owner=self.owner)
        response = self._post_json(reverse("api:activities"),
                                   {"activity_type": "note", "text": "x", "person_id": someone_elses.pk}, raw)
        self.assertEqual(response.status_code, 404)

    def test_activities_collection_can_be_filtered_by_person_or_company(self):
        person = Person.objects.create(first_name="A", last_name="B")
        company = Company.objects.create(name="UAB C")
        for_person = Activity.objects.create(person=person, text="p", created_by=self.owner)
        for_company = Activity.objects.create(company=company, text="c", created_by=self.owner)

        by_person = self.client.get(
            reverse("api:activities") + f"?person_id={person.pk}", **self._auth(self.raw_read_token))
        self.assertEqual({r["id"] for r in by_person.json()["results"]}, {for_person.pk})

        by_company = self.client.get(
            reverse("api:activities") + f"?company_id={company.pk}", **self._auth(self.raw_read_token))
        self.assertEqual({r["id"] for r in by_company.json()["results"]}, {for_company.pk})

    def test_activities_collection_without_a_filter_lists_every_visible_activity(self):
        person = Person.objects.create(first_name="A", last_name="B")
        Activity.objects.create(person=person, text="p", created_by=self.owner)
        response = self.client.get(reverse("api:activities"), **self._auth(self.raw_read_token))
        self.assertGreaterEqual(response.json()["count"], 1)

    # --- reminders: filtering -----------------------------------------------------

    # --- the remaining write-helper and 404/405 branches -------------------------

    def test_patching_a_contact_assigns_an_owner_by_id(self):
        person = Person.objects.create(first_name="A", last_name="B")
        response = self._patch_json(reverse("api:contact", args=[person.pk]), {"owner_id": self.owner.pk})
        self.assertEqual(response.status_code, 200)
        person.refresh_from_db()
        self.assertEqual(person.owner_id, self.owner.pk)

    def test_patching_a_contact_syncs_phones_addresses_and_urls(self):
        person = Person.objects.create(first_name="A", last_name="B")
        response = self._patch_json(reverse("api:contact", args=[person.pk]), {
            "phones": ["+370 600 00000"], "addresses": ["Gedimino pr. 1"], "urls": ["example.lt"],
        })
        data = response.json()
        self.assertEqual(data["phones"], ["+370 600 00000"])
        self.assertEqual(data["addresses"], ["Gedimino pr. 1"])
        self.assertEqual(data["urls"], ["https://example.lt"])

    def test_patching_a_company_assigns_an_owner_by_id(self):
        company = Company.objects.create(name="UAB Y")
        response = self.client.patch(reverse("api:company", args=[company.pk]),
                                     data=json.dumps({"owner_id": self.owner.pk}),
                                     content_type="application/json", **self._auth(self.raw_write_token))
        self.assertEqual(response.status_code, 200)
        company.refresh_from_db()
        self.assertEqual(company.owner_id, self.owner.pk)

    def test_duplicate_check_is_skipped_while_duplicate_detection_is_disabled(self):
        DuplicateSettings.objects.update_or_create(pk=1, defaults={"enabled": False})
        Person.objects.create(first_name="Ona", last_name="Onaitė")
        response = self._post_json(reverse("api:contacts"), {"first_name": "Ona", "last_name": "Onaitė"},
                                   self.raw_write_token)
        self.assertEqual(response.status_code, 201)

    def test_fetching_an_unknown_company_is_a_404(self):
        response = self.client.get(reverse("api:company", args=[999999]), **self._auth(self.raw_read_token))
        self.assertEqual(response.status_code, 404)

    def test_fetching_an_existing_company_returns_it(self):
        company = Company.objects.create(name="UAB Z")
        response = self.client.get(reverse("api:company", args=[company.pk]), **self._auth(self.raw_read_token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "UAB Z")

    def test_creating_a_reminder_against_an_invisible_company_is_a_404(self):
        restricted_user = get_user_model().objects.create_user("api-restricted3", password="x")
        UserProfile.objects.create(user=restricted_user, role=UserProfile.ROLE_RESTRICTED)
        raw, digest = ApiToken.new()
        ApiToken.objects.create(name="r3", token_hash=digest, prefix=raw[:12],
                                scope=ApiToken.READ_WRITE, created_by=restricted_user)
        someone_elses_company = Company.objects.create(name="UAB Kito", owner=self.owner)
        response = self._post_json(reverse("api:reminders"),
                                   {"text": "x", "due_at": "2030-01-01T10:00:00Z",
                                    "company_id": someone_elses_company.pk}, raw)
        self.assertEqual(response.status_code, 404)

    def test_creating_an_activity_with_a_linked_record_but_empty_text_is_a_400(self):
        person = Person.objects.create(first_name="A", last_name="B")
        response = self._post_json(reverse("api:activities"),
                                   {"activity_type": "note", "text": "   ", "person_id": person.pk},
                                   self.raw_write_token)
        self.assertEqual(response.status_code, 400)

    def test_activities_collection_filters_by_updated_since(self):
        person = Person.objects.create(first_name="A", last_name="B")
        old = Activity.objects.create(person=person, text="senas", created_by=self.owner)
        Activity.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=2))
        cutoff = timezone.now() - timedelta(days=1)
        recent = Activity.objects.create(person=person, text="naujas", created_by=self.owner)
        response = self.client.get(
            reverse("api:activities"), {"since": cutoff.isoformat()}, **self._auth(self.raw_read_token))
        self.assertEqual({r["id"] for r in response.json()["results"]}, {recent.pk})

    def test_every_collection_endpoint_rejects_an_unsupported_method(self):
        company = Company.objects.create(name="UAB W")
        auth = self._auth(self.raw_write_token)
        cases = [
            (self.client.delete, reverse("api:contacts")),
            (self.client.delete, reverse("api:companies")),
            (self.client.post, reverse("api:company", args=[company.pk])),
            (self.client.delete, reverse("api:activities")),
            (self.client.delete, reverse("api:reminders")),
        ]
        for method, url in cases:
            with self.subTest(url=url):
                self.assertEqual(method(url, **auth).status_code, 405)

    def test_reminders_collection_open_filter_excludes_completed_ones(self):
        person = Person.objects.create(first_name="A", last_name="B")
        open_reminder = Reminder.objects.create(person=person, text="Atviras", due_at=timezone.now(),
                                                created_by=self.owner)
        Reminder.objects.create(person=person, text="Baigtas", due_at=timezone.now(),
                                created_by=self.owner, completed_at=timezone.now())
        response = self.client.get(reverse("api:reminders") + "?open=1", **self._auth(self.raw_read_token))
        self.assertEqual({r["id"] for r in response.json()["results"]}, {open_reminder.pk})


class MergeRecordsTests(TestCase):
    """contacts/merging.py's guard rails and data movement, at the function
    level — the view-level tests already cover the label-limit rollback and
    the happy path with history; these target what was still unexercised:
    the self-merge/missing/already-merged/deleted guards, and whether a
    person's phones, emails, addresses and links actually survive a merge."""

    def setUp(self):
        self.actor = get_user_model().objects.create_user("merger", password="very-secure-password")

    # --- guard rails, shared shape between people and companies ---------------

    def test_cannot_merge_a_person_with_itself(self):
        from contacts.merging import merge_people
        person = Person.objects.create(first_name="A", last_name="B")
        with self.assertRaises(ValidationError):
            merge_people(person.pk, person.pk)

    def test_merging_a_missing_person_raises(self):
        from contacts.merging import merge_people
        person = Person.objects.create(first_name="A", last_name="B")
        with self.assertRaises(ValidationError):
            merge_people(person.pk, 999999)

    def test_merging_an_already_merged_source_into_the_same_target_is_a_noop(self):
        from contacts.merging import merge_people
        source = Person.objects.create(first_name="S", last_name="1")
        target = Person.objects.create(first_name="T", last_name="1")
        source.merged_into = target
        source.save()
        self.assertEqual(merge_people(source.pk, target.pk), target)

    def test_merging_an_already_merged_source_into_a_different_target_raises(self):
        from contacts.merging import merge_people
        source = Person.objects.create(first_name="S", last_name="2")
        first_target = Person.objects.create(first_name="T", last_name="2")
        other_target = Person.objects.create(first_name="T", last_name="3")
        source.merged_into = first_target
        source.save()
        with self.assertRaises(ValidationError):
            merge_people(source.pk, other_target.pk)

    def test_cannot_merge_a_deleted_source_or_target_person(self):
        from contacts.merging import merge_people
        deleted_source = Person.objects.create(first_name="S", last_name="3", deleted_at=timezone.now())
        target = Person.objects.create(first_name="T", last_name="4")
        with self.assertRaises(ValidationError):
            merge_people(deleted_source.pk, target.pk)

        source = Person.objects.create(first_name="S", last_name="4")
        deleted_target = Person.objects.create(first_name="T", last_name="5", deleted_at=timezone.now())
        with self.assertRaises(ValidationError):
            merge_people(source.pk, deleted_target.pk)

    def test_cannot_merge_into_a_target_that_is_itself_already_merged_away(self):
        from contacts.merging import merge_people
        source = Person.objects.create(first_name="S", last_name="5")
        target = Person.objects.create(first_name="T", last_name="6")
        elsewhere = Person.objects.create(first_name="T", last_name="7")
        target.merged_into = elsewhere
        target.save()
        with self.assertRaises(ValidationError):
            merge_people(source.pk, target.pk)

    def test_company_merge_has_the_same_self_and_missing_record_guards(self):
        from contacts.merging import merge_companies
        company = Company.objects.create(name="Solo")
        with self.assertRaises(ValidationError):
            merge_companies(company.pk, company.pk)
        with self.assertRaises(ValidationError):
            merge_companies(company.pk, 999999)

    # --- person merge: field fill-in, favourite, ownership --------------------

    def test_merge_fills_blank_target_fields_from_source(self):
        from contacts.merging import merge_people
        source = Person.objects.create(first_name="Rūta", last_name="Latecka", job_title="Vadovė", description="Apie ją")
        target = Person.objects.create(first_name="Rūta", last_name="Latecka")
        merge_people(source.pk, target.pk)
        target.refresh_from_db()
        self.assertEqual(target.job_title, "Vadovė")
        self.assertEqual(target.description, "Apie ją")

    def test_merge_does_not_overwrite_a_target_field_that_is_already_set(self):
        from contacts.merging import merge_people
        source = Person.objects.create(first_name="A", last_name="B", job_title="Šaltinio pareigos")
        target = Person.objects.create(first_name="A", last_name="B", job_title="Tikslo pareigos")
        merge_people(source.pk, target.pk)
        target.refresh_from_db()
        self.assertEqual(target.job_title, "Tikslo pareigos")

    def test_merge_propagates_a_favourite_flag_but_never_clears_one(self):
        from contacts.merging import merge_people
        source = Person.objects.create(first_name="A", last_name="C", favourite=True)
        target = Person.objects.create(first_name="A", last_name="C", favourite=False)
        merge_people(source.pk, target.pk)
        target.refresh_from_db()
        self.assertTrue(target.favourite)

    def test_merge_keeps_targets_owner_and_folds_source_owner_in_as_responsible(self):
        from contacts.merging import merge_people
        owner_a = get_user_model().objects.create_user("owner-a", password="very-secure-password")
        owner_b = get_user_model().objects.create_user("owner-b", password="very-secure-password")
        source = Person.objects.create(first_name="A", last_name="D", owner=owner_b)
        target = Person.objects.create(first_name="A", last_name="D", owner=owner_a)
        merge_people(source.pk, target.pk)
        target.refresh_from_db()
        self.assertEqual(target.owner_id, owner_a.pk)
        self.assertIn(owner_b, target.responsibles.all())

    def test_merge_gives_the_target_the_sources_owner_when_target_has_none(self):
        from contacts.merging import merge_people
        owner = get_user_model().objects.create_user("owner-c", password="very-secure-password")
        source = Person.objects.create(first_name="A", last_name="E", owner=owner)
        target = Person.objects.create(first_name="A", last_name="E")
        merge_people(source.pk, target.pk)
        target.refresh_from_db()
        self.assertEqual(target.owner_id, owner.pk)

    # --- person merge: phones/emails/addresses/links/activities/reminders -----

    def test_merge_moves_the_sources_unique_contact_details_onto_the_target(self):
        from contacts.merging import merge_people
        source = Person.objects.create(first_name="A", last_name="F")
        target = Person.objects.create(first_name="A", last_name="F")
        PhoneNumber.objects.create(person=source, number="+370 611 22333", is_primary=True)
        EmailAddress.objects.create(person=source, email="rusva@example.lt", is_primary=True)
        PostalAddress.objects.create(person=source, address="Gedimino pr. 1")
        WebLink.objects.create(person=source, url="https://example.lt")
        # Already on the target, same number in different spacing — must not duplicate.
        PhoneNumber.objects.create(person=target, number="370-611-22333", is_primary=True)

        merge_people(source.pk, target.pk)

        self.assertEqual(list(target.phones.values_list("number", flat=True)), ["370-611-22333"])
        self.assertEqual(list(target.emails.values_list("email", flat=True)), ["rusva@example.lt"])
        self.assertEqual(list(target.addresses.values_list("address", flat=True)), ["Gedimino pr. 1"])
        self.assertEqual(list(target.web_links.values_list("url", flat=True)), ["https://example.lt"])

    def test_merge_reassigns_the_sources_activities_and_reminders_to_the_target(self):
        from contacts.merging import merge_people
        source = Person.objects.create(first_name="A", last_name="G")
        target = Person.objects.create(first_name="A", last_name="G")
        activity = Activity.objects.create(person=source, text="Skambutis", created_by=self.actor)
        reminder = Reminder.objects.create(person=source, text="Perskambinti", due_at=timezone.now(), created_by=self.actor)

        merge_people(source.pk, target.pk)

        activity.refresh_from_db()
        reminder.refresh_from_db()
        self.assertEqual(activity.person_id, target.pk)
        self.assertEqual(reminder.person_id, target.pk)

    def test_merge_moves_the_sources_company_links_onto_the_target(self):
        from contacts.merging import merge_people
        source = Person.objects.create(first_name="A", last_name="H")
        target = Person.objects.create(first_name="A", last_name="H")
        company = Company.objects.create(name="Bendra įmonė")
        PersonCompanyLink.objects.create(person=source, company=company, role="Analitikas", is_primary=True)

        merge_people(source.pk, target.pk)

        link = target.company_links.get(company=company)
        self.assertEqual(link.role, "Analitikas")
        self.assertTrue(link.is_primary)

    def test_merge_folds_a_shared_company_link_instead_of_duplicating_it(self):
        """Both source and target already work at the same company: the link
        must be merged in place (role/primary filled in), not duplicated."""
        from contacts.merging import merge_people
        source = Person.objects.create(first_name="A", last_name="H2")
        target = Person.objects.create(first_name="A", last_name="H2")
        company = Company.objects.create(name="Abi dirba čia")
        PersonCompanyLink.objects.create(person=source, company=company, role="Vadovė", is_primary=True)
        target_link = PersonCompanyLink.objects.create(person=target, company=company, role="", is_primary=False)

        merge_people(source.pk, target.pk)

        self.assertEqual(target.company_links.filter(company=company).count(), 1)
        target_link.refresh_from_db()
        self.assertEqual(target_link.role, "Vadovė")
        self.assertTrue(target_link.is_primary)

    def test_merged_source_is_archived_and_points_at_the_target(self):
        from contacts.merging import merge_people
        source = Person.objects.create(first_name="A", last_name="I")
        target = Person.objects.create(first_name="A", last_name="I")
        merge_people(source.pk, target.pk)
        source.refresh_from_db()
        self.assertEqual(source.merged_into_id, target.pk)
        self.assertIsNotNone(source.deleted_at)

    # --- company merge: fields, links, activities ------------------------------

    def test_company_merge_fills_blank_fields_and_moves_activities(self):
        from contacts.merging import merge_companies
        source = Company.objects.create(name="UAB Šaltinis", company_code="123", phone="+37060000000")
        target = Company.objects.create(name="UAB Šaltinis")
        activity = Activity.objects.create(company=source, text="Susitikimas", created_by=self.actor)

        merge_companies(source.pk, target.pk)

        target.refresh_from_db()
        activity.refresh_from_db()
        self.assertEqual(target.company_code, "123")
        self.assertEqual(target.phone, "+37060000000")
        self.assertEqual(activity.company_id, target.pk)

    def test_company_merge_moves_the_sources_people_links(self):
        from contacts.merging import merge_companies
        source = Company.objects.create(name="UAB Perkeliama")
        target = Company.objects.create(name="UAB Perkeliama")
        person = Person.objects.create(first_name="A", last_name="J")
        PersonCompanyLink.objects.create(person=person, company=source, role="Vadovas")

        merge_companies(source.pk, target.pk)

        self.assertTrue(target.person_links.filter(person=person, role="Vadovas").exists())

    def test_company_merge_folds_a_shared_person_link_instead_of_duplicating_it(self):
        from contacts.merging import merge_companies
        source = Company.objects.create(name="UAB Bendra1")
        target = Company.objects.create(name="UAB Bendra2")
        person = Person.objects.create(first_name="A", last_name="K")
        PersonCompanyLink.objects.create(person=person, company=source, role="Buhalterė", is_primary=True)
        target_link = PersonCompanyLink.objects.create(person=person, company=target, role="", is_primary=False)

        merge_companies(source.pk, target.pk)

        self.assertEqual(target.person_links.filter(person=person).count(), 1)
        target_link.refresh_from_db()
        self.assertEqual(target_link.role, "Buhalterė")
        self.assertTrue(target_link.is_primary)

    def test_company_merge_refuses_deleted_records_and_already_merged_chains(self):
        from contacts.merging import merge_companies
        deleted_source = Company.objects.create(name="A", deleted_at=timezone.now())
        target = Company.objects.create(name="B")
        with self.assertRaises(ValidationError):
            merge_companies(deleted_source.pk, target.pk)

        source = Company.objects.create(name="C")
        deleted_target = Company.objects.create(name="D", deleted_at=timezone.now())
        with self.assertRaises(ValidationError):
            merge_companies(source.pk, deleted_target.pk)

        already_merged_source = Company.objects.create(name="E")
        first_target = Company.objects.create(name="F")
        other_target = Company.objects.create(name="G")
        already_merged_source.merged_into = first_target
        already_merged_source.save()
        self.assertEqual(merge_companies(already_merged_source.pk, first_target.pk), first_target)
        with self.assertRaises(ValidationError):
            merge_companies(already_merged_source.pk, other_target.pk)


class CustomFieldHelperTests(TestCase):
    """contacts/custom_fields.py at the function level. View-level tests
    elsewhere only ever use text/select/multiselect fields — bool and
    textarea, and an invalid select choice, were never exercised."""

    def setUp(self):
        self.person = Person.objects.create(first_name="A", last_name="B")

    def _bool_field(self):
        return CustomField.objects.create(entity=CustomField.PERSON, name="Aktyvus", field_type=CustomField.BOOL)

    def _select_field(self):
        return CustomField.objects.create(
            entity=CustomField.PERSON, name="Šaltinis", field_type=CustomField.SELECT, options=["Web", "Renginys"])

    def _textarea_field(self):
        return CustomField.objects.create(entity=CustomField.PERSON, name="Pastabos", field_type=CustomField.TEXTAREA)

    @staticmethod
    def _posted(value):
        from django.http import QueryDict
        data = QueryDict(mutable=True)
        data["value"] = value
        return data

    # --- _decode / _encode / display ---------------------------------------

    def test_bool_field_decodes_and_encodes_through_the_stored_marker(self):
        from contacts.custom_fields import _decode, _encode
        field = self._bool_field()
        self.assertEqual(_encode(field, True), "1")
        self.assertEqual(_encode(field, False), "")
        self.assertTrue(_decode(field, "1"))
        self.assertFalse(_decode(field, ""))
        self.assertFalse(_decode(field, None))

    def test_text_field_encode_strips_whitespace(self):
        from contacts.custom_fields import _encode
        field = self._textarea_field()
        self.assertEqual(_encode(field, "  su tarpais  "), "su tarpais")
        self.assertEqual(_encode(field, None), "")

    def test_bool_field_displays_as_yes_or_no(self):
        from contacts.custom_fields import display
        field = self._bool_field()
        self.assertEqual(display(field, True), "Taip")
        self.assertEqual(display(field, False), "Ne")

    # --- single_context ------------------------------------------------------

    def test_single_context_returns_none_for_an_unknown_field(self):
        from contacts.custom_fields import single_context
        self.assertIsNone(single_context(self.person, "cf_999999"))

    def test_single_context_returns_none_for_a_field_of_the_other_entity(self):
        from contacts.custom_fields import single_context
        company_field = CustomField.objects.create(entity=CustomField.COMPANY, name="X", field_type=CustomField.TEXT)
        self.assertIsNone(single_context(self.person, company_field.key))

    # --- clean_and_store -------------------------------------------------------

    def test_clean_and_store_rejects_a_select_value_outside_the_options(self):
        from contacts.custom_fields import clean_and_store
        field = self._select_field()
        decoded = clean_and_store(self.person, field, self._posted("Kažkas kito"))
        self.assertEqual(decoded, "")
        self.assertEqual(CustomValue.objects.get(field=field, person=self.person).value, "")

    def test_clean_and_store_accepts_a_valid_select_value(self):
        from contacts.custom_fields import clean_and_store
        field = self._select_field()
        decoded = clean_and_store(self.person, field, self._posted("Web"))
        self.assertEqual(decoded, "Web")

    def test_clean_and_store_parses_a_bool_field_from_several_truthy_spellings(self):
        from contacts.custom_fields import clean_and_store
        field = self._bool_field()
        for spelling in ("1", "on", "true"):
            self.assertTrue(clean_and_store(self.person, field, self._posted(spelling)))
        self.assertFalse(clean_and_store(self.person, field, self._posted("false")))
        self.assertFalse(clean_and_store(self.person, field, self._posted("")))

    def test_clean_and_store_truncates_a_textarea_to_1000_characters(self):
        from contacts.custom_fields import clean_and_store
        field = self._textarea_field()
        long_text = "x" * 1500
        decoded = clean_and_store(self.person, field, self._posted(long_text))
        self.assertEqual(len(decoded), 1000)

    def test_clean_and_store_truncates_a_plain_text_field_to_200_characters(self):
        from contacts.custom_fields import clean_and_store
        field = CustomField.objects.create(entity=CustomField.PERSON, name="Trumpas", field_type=CustomField.TEXT)
        decoded = clean_and_store(self.person, field, self._posted("y" * 300))
        self.assertEqual(len(decoded), 200)

    def test_clean_and_store_updates_rather_than_duplicates_the_value_row(self):
        from contacts.custom_fields import clean_and_store
        field = self._select_field()
        clean_and_store(self.person, field, self._posted("Web"))
        clean_and_store(self.person, field, self._posted("Renginys"))
        self.assertEqual(CustomValue.objects.filter(field=field, person=self.person).count(), 1)
        self.assertEqual(CustomValue.objects.get(field=field, person=self.person).value, "Renginys")


class RichTextEscapingTests(TestCase):
    """rich_text is the one filter that returns mark_safe; hostile notes must stay inert."""

    def render(self, value):
        from contacts.templatetags.crm_format import rich_text
        return str(rich_text(value))

    def test_markup_and_attribute_breakouts_are_escaped(self):
        cases = {
            "<script>alert(1)</script>": "<script",
            "**<img src=x onerror=alert(1)>**": "<img",
            'http://x.lt/"onmouseover=alert(1)': '"onmouseover',
            'a@b.lt"><svg onload=alert(1)>': "<svg",
            "_http://e.lt\" x=\"y_": '" x="',
        }
        for value, forbidden in cases.items():
            with self.subTest(value=value):
                self.assertNotIn(forbidden, self.render(value))

    def test_javascript_scheme_is_never_linked(self):
        self.assertNotIn("href", self.render("javascript:alert(1)"))

    def test_supported_formatting_still_renders(self):
        html = self.render("**bold** _it_\nhttps://example.lt")
        self.assertIn("<strong>bold</strong>", html)
        self.assertIn("<em>it</em>", html)
        self.assertIn('<a href="https://example.lt"', html)
        self.assertIn("<br>", html)


class DirectoryAccessTests(TestCase):
    """AD / Entra group based access: token validation, group mapping, UI locks."""

    TENANT = "11111111-2222-3333-4444-555555555555"

    def setUp(self):
        from contacts.crypto import encrypt
        from contacts.models import DirectoryGroupMapping, SystemSettings
        system = SystemSettings.load()
        system.oidc_enabled, system.oidc_tenant_id = True, self.TENANT
        system.oidc_client_id, system.oidc_client_secret = "cid", encrypt("csecret")
        system.oidc_create_users = True
        system.oidc_sync_groups = True
        system.save()
        self.sales = Team.objects.create(name="Pardavimai")
        self.support = Team.objects.create(name="Aptarnavimas")
        self.manual = Team.objects.create(name="Rankinė")
        DirectoryGroupMapping.objects.create(group="CRM-Admins", role=UserProfile.ROLE_ADMIN)
        DirectoryGroupMapping.objects.create(group="CRM-Users", role=UserProfile.ROLE_MEMBER)
        DirectoryGroupMapping.objects.create(group="CRM-Own", role=UserProfile.ROLE_RESTRICTED)
        DirectoryGroupMapping.objects.create(group="CRM-Sales", team=self.sales)
        DirectoryGroupMapping.objects.create(group="CRM-Support", team=self.support)

    def claims(self, groups, email="jonas@imone.lt", oid="oid-1", **extra):
        return {"email": email, "preferred_username": email, "tid": self.TENANT, "oid": oid,
                "given_name": "Jonas", "family_name": "Jonaitis", "groups": groups, **extra}

    def backend(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory
        from contacts.oidc import EntraOIDCBackend
        request = RequestFactory().get("/oidc/callback/")
        request.session = self.client.session
        request._messages = FallbackStorage(request)
        backend = EntraOIDCBackend()
        backend.request = request
        return backend

    def sign_in(self, claims):
        backend = self.backend()
        with patch("mozilla_django_oidc.auth.OIDCAuthenticationBackend.get_userinfo", return_value={}):
            user = backend.get_or_create_user("access", "id", claims)
        return user, [str(m) for m in backend.request._messages]

    # --- ID token validation
    def payload(self, **overrides):
        import time as _time
        payload = {"aud": "cid", "exp": _time.time() + 600, "tid": self.TENANT,
                   "iss": "https://login.microsoftonline.com/%s/v2.0" % self.TENANT}
        payload.update(overrides)
        return payload

    def test_id_token_claims_are_validated(self):
        from django.core.exceptions import SuspiciousOperation
        from contacts.integrations import oidc_config
        from contacts.oidc import validate_id_token_claims
        config = oidc_config()
        self.assertTrue(validate_id_token_claims(self.payload(), config))
        self.assertTrue(validate_id_token_claims(self.payload(aud=["other", "cid"]), config))
        other = "99999999-2222-3333-4444-555555555555"
        for bad in (self.payload(aud="other"), self.payload(exp=1), self.payload(exp=None),
                    self.payload(iss="https://evil.example/v2.0"),
                    self.payload(tid=other, iss="https://login.microsoftonline.com/%s/v2.0" % other)):
            with self.subTest(bad=bad), self.assertRaises(SuspiciousOperation):
                validate_id_token_claims(bad, config)

    def test_generic_provider_checks_the_configured_issuer(self):
        from django.core.exceptions import SuspiciousOperation
        from contacts.integrations import OIDCConfig
        from contacts.oidc import validate_id_token_claims
        config = OIDCConfig(enabled=True, tenant_id="", client_id="cid", client_secret="s", create_users=False,
                            provider="generic", issuer="https://adfs.imone.lt/adfs")
        self.assertTrue(validate_id_token_claims(self.payload(iss="https://adfs.imone.lt/adfs"), config))
        with self.assertRaises(SuspiciousOperation):
            validate_id_token_claims(self.payload(iss="https://adfs.kita.lt/adfs"), config)

    def test_multi_tenant_entra_authority_is_not_usable(self):
        from contacts.integrations import OIDCConfig
        for tenant in ("", "common", "organizations"):
            config = OIDCConfig(enabled=True, tenant_id=tenant, client_id="c", client_secret="s", create_users=False)
            self.assertFalse(config.usable)

    def test_userinfo_is_completed_by_the_verified_token_claims(self):
        with patch("mozilla_django_oidc.auth.OIDCAuthenticationBackend.get_userinfo",
                   return_value={"email": "from-userinfo@imone.lt", "name": "Jonas"}):
            merged = self.backend().get_userinfo("a", "i", {"email": "jonas@imone.lt", "groups": ["CRM-Users"]})
        self.assertEqual(merged["email"], "jonas@imone.lt")
        self.assertEqual(merged["groups"], ["CRM-Users"])
        self.assertEqual(merged["name"], "Jonas")

    # --- group evaluation
    def test_strongest_role_wins_and_teams_add_up(self):
        from contacts.directory import evaluate
        from contacts.integrations import oidc_config
        result = evaluate(self.claims(["crm-own", "CRM-USERS", "CRM-Sales", "CRM-Support", "Unrelated"]), oidc_config())
        self.assertEqual(result.role, UserProfile.ROLE_MEMBER)
        self.assertEqual(result.teams, [self.support, self.sales])
        self.assertEqual(result.denied, "")

    def test_a_manager_group_outranks_a_user_group_but_not_an_admin_one(self):
        """The three groups an organisation actually keeps: admins, managers,
        users — and a person in several gets the strongest."""
        from contacts.directory import evaluate
        from contacts.integrations import oidc_config
        from contacts.models import DirectoryGroupMapping

        DirectoryGroupMapping.objects.create(group="CRM-Managers", role=UserProfile.ROLE_MANAGER)
        config = oidc_config()
        self.assertEqual(evaluate(self.claims(["CRM-Managers"]), config).role, UserProfile.ROLE_MANAGER)
        self.assertEqual(evaluate(self.claims(["CRM-Managers", "CRM-Users"]), config).role,
                         UserProfile.ROLE_MANAGER)
        self.assertEqual(evaluate(self.claims(["CRM-Managers", "CRM-Admins"]), config).role,
                         UserProfile.ROLE_ADMIN)

    def test_single_string_group_claim_is_accepted(self):
        from contacts.directory import evaluate
        from contacts.integrations import oidc_config
        self.assertEqual(evaluate({"groups": "CRM-Admins"}, oidc_config()).role, UserProfile.ROLE_ADMIN)

    def test_no_role_group_or_group_overage_is_refused(self):
        from contacts.directory import evaluate
        from contacts.integrations import oidc_config
        self.assertTrue(evaluate(self.claims(["CRM-Sales"]), oidc_config()).denied)
        overage = self.claims([], _claim_names={"groups": "src1"})
        self.assertTrue(evaluate(overage, oidc_config()).denied)

    # --- sign-in
    def test_first_sign_in_creates_the_user_with_role_teams_and_no_local_password(self):
        from contacts.models import AuditLog
        user, notes = self.sign_in(self.claims(["CRM-Admins", "CRM-Sales"]))
        self.assertEqual(notes, [])
        profile = user.crm_profile
        self.assertEqual(profile.role, UserProfile.ROLE_ADMIN)
        self.assertTrue(profile.directory_managed)
        self.assertEqual(profile.directory_subject, "%s:oid-1" % self.TENANT)
        self.assertTrue(user.is_staff)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(list(user.crm_teams.all()), [self.sales])
        self.assertTrue(AuditLog.objects.filter(target_type="user", field="Rolė").exists())

    def test_group_changes_follow_at_next_sign_in_and_manual_teams_are_kept(self):
        user, _ = self.sign_in(self.claims(["CRM-Admins", "CRM-Sales"]))
        self.manual.members.add(user)
        user, _ = self.sign_in(self.claims(["CRM-Own", "CRM-Support"]))
        user.refresh_from_db()
        self.assertEqual(user.crm_profile.role, UserProfile.ROLE_RESTRICTED)
        self.assertFalse(user.is_staff)
        self.assertEqual(set(user.crm_teams.all()), {self.support, self.manual})

    def test_existing_local_user_loses_the_local_password_when_linked(self):
        local = get_user_model().objects.create_user("jonas", email="jonas@imone.lt", password="very-secure-password")
        user, _ = self.sign_in(self.claims(["CRM-Users"]))
        self.assertEqual(user.pk, local.pk)
        local.refresh_from_db()
        self.assertFalse(local.has_usable_password())

    def test_user_without_a_role_group_is_refused_and_not_created(self):
        user, notes = self.sign_in(self.claims(["CRM-Sales"], email="be-grupes@imone.lt"))
        self.assertIsNone(user)
        self.assertTrue(notes)
        self.assertFalse(get_user_model().objects.filter(email="be-grupes@imone.lt").exists())

    def test_removed_from_groups_is_refused_for_an_existing_user(self):
        user, _ = self.sign_in(self.claims(["CRM-Users"]))
        refused, notes = self.sign_in(self.claims([]))
        self.assertIsNone(refused)
        self.assertTrue(notes)

    def test_local_superuser_cannot_be_taken_over_through_the_directory(self):
        get_user_model().objects.create_superuser("root", email="jonas@imone.lt", password="very-secure-password")
        user, notes = self.sign_in(self.claims(["CRM-Users"]))
        self.assertIsNone(user)
        self.assertTrue(notes)

    def test_reassigned_email_with_another_directory_identity_is_refused(self):
        self.sign_in(self.claims(["CRM-Users"], oid="oid-1"))
        user, notes = self.sign_in(self.claims(["CRM-Users"], oid="oid-2"))
        self.assertIsNone(user)
        self.assertTrue(notes)

    def test_linked_identity_survives_an_email_change(self):
        first, _ = self.sign_in(self.claims(["CRM-Users"], oid="oid-1"))
        again, _ = self.sign_in(self.claims(["CRM-Users"], email="jonas.naujas@imone.lt", oid="oid-1"))
        self.assertEqual(first.pk, again.pk)

    def test_deactivated_user_is_refused_instead_of_crashing_on_create(self):
        get_user_model().objects.create_user("jonas@imone.lt", email="jonas@imone.lt", is_active=False)
        user, notes = self.sign_in(self.claims(["CRM-Users"]))
        self.assertIsNone(user)
        self.assertTrue(notes)

    # --- settings UI
    def admin_client(self):
        admin = get_user_model().objects.create_superuser("root", email="root@local", password="very-secure-password")
        self.client.force_login(admin)

    def test_mappings_are_added_deduplicated_and_removed_from_settings(self):
        from contacts.models import DirectoryGroupMapping
        self.admin_client()
        url = reverse("contacts:settings-login")
        self.client.post(url, {"op": "add_mapping", "group": " CRM-Readers ", "role": UserProfile.ROLE_RESTRICTED})
        mapping = DirectoryGroupMapping.objects.get(group="CRM-Readers")
        response = self.client.post(url, {"op": "add_mapping", "group": "crm-readers", "role": UserProfile.ROLE_MEMBER})
        self.assertContains(response, "Ši grupė jau susieta.")
        response = self.client.post(url, {"op": "add_mapping", "group": "CRM-Nothing"})
        self.assertContains(response, "Grupei priskirkite rolę, komandą arba abi.")
        self.client.post(url, {"op": "delete_mapping", "mapping_id": mapping.pk})
        self.assertFalse(DirectoryGroupMapping.objects.filter(pk=mapping.pk).exists())

    def test_claims_tester_shows_the_resulting_access(self):
        self.admin_client()
        url = reverse("contacts:settings-login")
        response = self.client.post(url, {"op": "test_claims", "claims": json.dumps(self.claims(["CRM-Users", "CRM-Sales"]))})
        self.assertContains(response, "Naudotojas (visi įrašai)")
        self.assertContains(response, "Pardavimai")
        response = self.client.post(url, {"op": "test_claims", "claims": json.dumps(self.claims(["Kita"]))})
        self.assertContains(response, "Prisijungti neleidžiama")
        self.assertContains(self.client.post(url, {"op": "test_claims", "claims": "ne json"}), "JSON")

    def test_generic_provider_reads_endpoints_from_discovery(self):
        from unittest.mock import MagicMock
        from contacts.integrations import oidc_config
        from contacts.models import SystemSettings
        self.admin_client()
        document = {"issuer": "https://adfs.imone.lt/adfs",
                    "authorization_endpoint": "https://adfs.imone.lt/adfs/oauth2/authorize/",
                    "token_endpoint": "https://adfs.imone.lt/adfs/oauth2/token/",
                    "userinfo_endpoint": "https://adfs.imone.lt/adfs/userinfo",
                    "jwks_uri": "https://adfs.imone.lt/adfs/discovery/keys"}
        response_mock = MagicMock(json=MagicMock(return_value=document))
        form = {"op": "save", "oidc_enabled": "on", "oidc_provider": "generic", "oidc_issuer": "https://adfs.imone.lt/adfs/",
                "oidc_client_id": "cid", "oidc_groups_claim": "group"}
        with patch("requests.get", return_value=response_mock) as get:
            self.client.post(reverse("contacts:settings-login"), form)
        get.assert_called_once_with("https://adfs.imone.lt/adfs/.well-known/openid-configuration", timeout=10)
        config = oidc_config(SystemSettings.load())
        self.assertEqual(config.token_endpoint, document["token_endpoint"])
        self.assertEqual(config.expected_issuer, "https://adfs.imone.lt/adfs")
        self.assertEqual(config.groups_claim, "group")
        self.assertTrue(config.usable)

        document["issuer"] = "https://kitas.lt/adfs"
        form["oidc_issuer"] = "https://adfs2.imone.lt/adfs"
        with patch("requests.get", return_value=response_mock):
            response = self.client.post(reverse("contacts:settings-login"), form)
        self.assertContains(response, "nesutampa")
        self.assertEqual(SystemSettings.load().oidc_issuer, "https://adfs.imone.lt/adfs")

    def test_role_of_a_directory_managed_user_cannot_be_changed_locally(self):
        user, _ = self.sign_in(self.claims(["CRM-Own"]))
        self.admin_client()
        response = self.client.get(reverse("contacts:settings-users"))
        self.assertContains(response, "Valdoma per katalogo grupę")
        self.client.post(reverse("contacts:settings-users"), {
            "action": "update", "user_id": user.pk, "role": UserProfile.ROLE_ADMIN, "active": "1"})
        user.refresh_from_db()
        self.assertEqual(user.crm_profile.role, UserProfile.ROLE_RESTRICTED)
        self.client.post(reverse("contacts:settings-users"), {
            "action": "update", "user_id": user.pk, "role": UserProfile.ROLE_RESTRICTED})
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_team_page_keeps_directory_memberships_of_mapped_teams(self):
        user, _ = self.sign_in(self.claims(["CRM-Users", "CRM-Sales"]))
        self.admin_client()
        self.client.post(reverse("contacts:settings-teams"), {
            "action": "update", "team_id": self.sales.pk, "name": "Pardavimai", "visibility": "all", "members": []})
        self.assertIn(user, self.sales.members.all())
        self.client.post(reverse("contacts:settings-teams"), {
            "action": "update", "team_id": self.manual.pk, "name": "Rankinė", "visibility": "all", "members": [user.pk]})
        self.assertIn(user, self.manual.members.all())

    def test_refused_sign_in_reason_is_shown_on_the_login_page(self):
        from django.contrib import messages as django_messages

        def refuse(backend, request, **kwargs):
            django_messages.error(request, "Nepriklausote CRM grupei")
            return None

        session = self.client.session
        session["oidc_states"] = {"state-1": {"nonce": "n", "code_verifier": None}}
        session.save()
        with patch("contacts.oidc.EntraOIDCBackend.authenticate", autospec=True, side_effect=refuse):
            response = self.client.get("/oidc/callback/?code=c&state=state-1", follow=True)
        self.assertEqual(response.request["PATH_INFO"], reverse("login"))
        self.assertContains(response, "Nepriklausote CRM grupei")
        self.assertContains(response, "Prisijungti su Microsoft")


class PasswordResetTests(TestCase):
    """Forgotten passwords: a link by e-mail that says nothing about who exists."""

    PASSWORD = "very-secure-password"
    NEW = "another-very-secure-password"

    def setUp(self):
        from django.core import mail
        User = get_user_model()
        self.user = User.objects.create_user("jonas", email="jonas@imone.lt", password=self.PASSWORD)
        mail.outbox.clear()

    def _ask(self, identifier):
        return self.client.post(reverse("password-reset"), {"identifier": identifier}, follow=True)

    def _link(self):
        from django.core import mail
        body = mail.outbox[-1].body
        start = body.index("/slaptazodis/")
        return body[start:].split()[0]

    def test_a_link_arrives_and_sets_a_new_password(self):
        from django.core import mail
        response = self._ask("jonas@imone.lt")
        self.assertEqual(len(mail.outbox), 1)
        self.assertContains(response, "Jei tokia paskyra yra")

        link = self._link()
        self.assertEqual(self.client.get(link).status_code, 200)
        self.client.post(link, {"new_password1": self.NEW, "new_password2": self.NEW})
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.NEW))

    def test_the_username_works_too_and_the_link_is_single_use(self):
        self._ask("jonas")
        link = self._link()
        self.client.post(link, {"new_password1": self.NEW, "new_password2": self.NEW})
        # The token is derived from the password hash, so it dies with the change.
        again = self.client.post(link, {"new_password1": self.PASSWORD, "new_password2": self.PASSWORD})
        self.assertContains(again, "nebegalioja")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.NEW))

    def test_an_unknown_address_is_answered_exactly_like_a_known_one(self):
        from django.core import mail
        known = self._ask("jonas@imone.lt")
        mail.outbox.clear()
        unknown = self._ask("niekas@imone.lt")
        self.assertEqual(len(mail.outbox), 0)
        self.assertContains(unknown, "Jei tokia paskyra yra")
        self.assertEqual(known.status_code, unknown.status_code)

    def test_an_inactive_account_gets_nothing(self):
        from django.core import mail
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self._ask("jonas")
        self.assertEqual(len(mail.outbox), 0)

    def test_the_directory_owns_its_accounts(self):
        """With group sync on, a directory user has no local password to reset —
        setting one would readmit somebody the organisation removed."""
        from django.core import mail
        from contacts.crypto import encrypt
        from contacts.models import SystemSettings, UserProfile

        UserProfile.objects.create(user=self.user, directory_managed=True)
        system = SystemSettings.load()
        system.oidc_enabled, system.oidc_tenant_id = True, DirectoryAccessTests.TENANT
        system.oidc_client_id, system.oidc_client_secret = "cid", encrypt("csecret")
        system.oidc_sync_groups = True
        system.save()

        self._ask("jonas")
        self.assertEqual(len(mail.outbox), 0)

    def test_the_mails_stop_after_five_in_an_hour(self):
        from django.core import mail
        for _ in range(7):
            self._ask("jonas")
        self.assertEqual(len(mail.outbox), 5)

    def test_sso_only_sends_nothing_and_points_at_the_directory(self):
        from django.core import mail
        from contacts.crypto import encrypt
        from contacts.models import SystemSettings

        system = SystemSettings.load()
        system.oidc_enabled, system.oidc_tenant_id = True, DirectoryAccessTests.TENANT
        system.oidc_client_id, system.oidc_client_secret = "cid", encrypt("csecret")
        system.sso_only = True
        system.save()

        page = self.client.get(reverse("password-reset"))
        self.assertContains(page, "organizacijos katalogas")
        self._ask("jonas")
        self.assertEqual(len(mail.outbox), 0)

    def test_every_step_is_in_the_audit_log(self):
        from contacts.models import AuditLog

        self._ask("jonas")
        self.assertTrue(AuditLog.objects.filter(field="Slaptažodžio atkūrimas", new_value="sent").exists())
        link = self._link()
        self.client.post(link, {"new_password1": self.NEW, "new_password2": self.NEW})
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.UPDATE, target_type="user",
                                                new_value__contains="atkūrimo nuorodą").exists())

    def test_the_login_page_offers_the_way_in(self):
        page = self.client.get(reverse("login"))
        self.assertContains(page, reverse("password-reset"))


class SsoOnlyAndSessionRefreshTests(TestCase):
    """SSO-only sign-in with break-glass accounts, and directory session re-checks."""

    PASSWORD = "very-secure-password"

    def configure(self, sso_only=True, minutes=15, sync=True):
        from contacts.crypto import encrypt
        from contacts.models import SystemSettings
        system = SystemSettings.load()
        system.oidc_enabled, system.oidc_tenant_id = True, DirectoryAccessTests.TENANT
        system.oidc_client_id, system.oidc_client_secret = "cid", encrypt("csecret")
        system.oidc_sync_groups, system.sso_only, system.oidc_session_check_minutes = sync, sso_only, minutes
        system.save()

    def setUp(self):
        User = get_user_model()
        self.root = User.objects.create_superuser("root", email="root@local", password=self.PASSWORD)
        self.plain = User.objects.create_user("plain", email="plain@imone.lt", password=self.PASSWORD)

    def login(self, username):
        return self.client.post(reverse("login"), {"username": username, "password": self.PASSWORD})

    def test_local_passwords_work_until_sso_only_is_enforced(self):
        self.configure(sso_only=False)
        self.assertEqual(self.login("plain").status_code, 302)

    def test_sso_only_refuses_local_passwords_except_break_glass(self):
        self.configure()
        self.assertEqual(self.login("plain").status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.login("root").status_code, 302)

    @override_settings(CRM_BREAK_GLASS_USERS=["plain"])
    def test_break_glass_list_replaces_the_superuser_default(self):
        self.configure()
        self.assertEqual(self.login("root").status_code, 200)
        self.assertEqual(self.login("plain").status_code, 302)

    def test_sso_only_is_ignored_while_the_provider_is_not_usable(self):
        from contacts.models import SystemSettings
        self.configure()
        system = SystemSettings.load()
        system.oidc_client_id = ""
        system.save()
        self.assertEqual(self.login("plain").status_code, 302)

    def test_switching_sso_only_on_ends_open_local_sessions(self):
        self.configure(sso_only=False)
        self.login("plain")
        self.assertEqual(self.client.get(reverse("contacts:list")).status_code, 200)
        self.configure(sso_only=True)
        self.assertEqual(self.client.get(reverse("contacts:list")).status_code, 302)

    def test_login_page_puts_sso_first_and_hides_the_local_form(self):
        self.configure()
        response = self.client.get(reverse("login"))
        self.assertContains(response, "Avarinis vietinis prisijungimas")
        # The directory is the primary button; the local form is folded away.
        self.assertContains(response, 'class="btn primary login-directory" href="/oidc/authenticate/"')
        self.assertLess(response.content.index(b"login-directory"), response.content.index(b"login-break-glass"))

    def test_sso_only_needs_a_break_glass_account_with_a_password(self):
        from contacts.models import SystemSettings
        self.configure(sso_only=False)
        self.client.force_login(self.root)
        form = {"op": "save", "oidc_enabled": "on", "oidc_tenant_id": DirectoryAccessTests.TENANT,
                "oidc_client_id": "cid", "oidc_session_check_minutes": "15", "sso_only": "on"}
        self.root.set_unusable_password()
        self.root.save()
        self.client.force_login(self.root)  # a password change ends the session
        response = self.client.post(reverse("contacts:settings-login"), form)
        self.assertContains(response, "Nėra avarinės vietinės paskyros")
        self.assertFalse(SystemSettings.load().sso_only)
        self.root.set_password(self.PASSWORD)
        self.root.save()
        self.client.force_login(self.root)
        self.client.post(reverse("contacts:settings-login"), form)
        self.assertTrue(SystemSettings.load().sso_only)

    # --- session re-check
    def oidc_session(self, expired=True):
        import time as _time
        self.client.force_login(self.plain, backend="contacts.oidc.EntraOIDCBackend")
        session = self.client.session
        session["oidc_id_token_expiration"] = _time.time() + (-10 if expired else 600)
        session.save()

    def test_expired_directory_session_is_silently_rechecked(self):
        from urllib.parse import parse_qs, urlparse
        self.configure(sso_only=False)
        self.oidc_session()
        response = self.client.get(reverse("contacts:list"))
        self.assertEqual(response.status_code, 302)
        target = urlparse(response["Location"])
        self.assertEqual(target.path, "/%s/oauth2/v2.0/authorize" % DirectoryAccessTests.TENANT)
        query = parse_qs(target.query)
        self.assertEqual(query["prompt"], ["none"])
        self.assertEqual(query["client_id"], ["cid"])

    def test_background_requests_get_a_refresh_signal_instead_of_a_redirect(self):
        self.configure(sso_only=False)
        self.oidc_session()
        response = self.client.get(reverse("contacts:list"), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 403)
        self.assertIn("refresh_url", response)

    def test_recheck_skips_fresh_sessions_local_sessions_api_and_disabled_interval(self):
        self.configure(sso_only=False)
        self.oidc_session(expired=False)
        self.assertEqual(self.client.get(reverse("contacts:list")).status_code, 200)
        self.oidc_session()
        self.assertNotEqual(self.client.get("/api/v1/contacts/").status_code, 302)
        self.assertEqual(self.client.get("/health/live").status_code, 200)
        self.client.logout()
        self.client.force_login(self.plain, backend="contacts.oidc.LocalAccountBackend")
        self.assertEqual(self.client.get(reverse("contacts:list")).status_code, 200)
        self.configure(sso_only=False, minutes=0)
        self.oidc_session()
        self.assertEqual(self.client.get(reverse("contacts:list")).status_code, 200)

    def test_callback_sets_the_configured_recheck_interval(self):
        from contacts.oidc import _resolve
        self.configure(sso_only=False, minutes=7)
        self.assertEqual(_resolve("OIDC_RENEW_ID_TOKEN_EXPIRY_SECONDS", 900), 420)

    def test_refused_recheck_ends_the_open_session(self):
        self.configure(sso_only=False)
        self.oidc_session(expired=False)
        session = self.client.session
        session["oidc_states"] = {"s": {"nonce": "n", "code_verifier": None}}
        session.save()
        with patch("contacts.oidc.EntraOIDCBackend.authenticate", return_value=None):
            response = self.client.get("/oidc/callback/?code=c&state=s")
        self.assertEqual(response["Location"], "/login/")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_idp_error_on_recheck_logs_out(self):
        self.configure(sso_only=False)
        self.oidc_session(expired=False)
        self.client.get("/oidc/callback/?error=login_required")
        self.assertNotIn("_auth_user_id", self.client.session)

    # --- local passwords for directory users
    def test_admin_cannot_give_a_directory_user_a_local_password(self):
        from contacts.models import UserProfile
        self.configure(sso_only=False)
        UserProfile.objects.create(user=self.plain, directory_managed=True)
        self.plain.set_unusable_password()
        self.plain.save()
        self.client.force_login(self.root)
        response = self.client.post(reverse("contacts:settings-users"), {
            "action": "reset", "user_id": self.plain.pk, "password": "Another-long-passphrase-9"}, follow=True)
        self.assertContains(response, "vietinio slaptažodžio nustatyti negalima")
        self.plain.refresh_from_db()
        self.assertFalse(self.plain.has_usable_password())

    def test_profile_hides_password_change_without_a_local_password(self):
        self.plain.set_unusable_password()
        self.plain.save()
        self.client.force_login(self.plain)
        response = self.client.get(reverse("contacts:settings"))
        self.assertContains(response, "slaptažodis keičiamas ten, ne CRM")
        self.assertNotContains(response, "Pakeisti slaptažodį")


class ReadOnlyRoleTests(TestCase):
    """The "Skaitytojas" role sees records but changes nothing shared."""

    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user("owner", password="very-secure-password")
        self.reader = User.objects.create_user("reader", password="very-secure-password")
        UserProfile.objects.create(user=self.reader, role=UserProfile.ROLE_READONLY)
        self.person = Person.objects.create(first_name="Jonas", last_name="Jonaitis", created_by=self.owner, owner=self.owner)
        self.company = Company.objects.create(name="UAB Bandymas", created_by=self.owner, owner=self.owner)
        self.client.force_login(self.reader)

    def test_reader_can_open_every_viewing_page(self):
        for name, args in (("home", []), ("list", []), ("company-list", []), ("detail", [self.person.pk]),
                           ("company-detail", [self.company.pk]), ("calendar", []), ("analytics-overview", []),
                           ("search", []), ("archive-list", []), ("settings", [])):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse("contacts:" + name, args=args)).status_code, 200)

    def test_viewing_pages_offer_no_editing_controls(self):
        pages = {
            reverse("contacts:list"): ["+ Pridėti kontaktą"],
            reverse("contacts:company-list"): ["+ Pridėti įmonę"],
            reverse("contacts:home"): ['class="quick-add"'],
            reverse("contacts:detail", args=[self.person.pk]): ['id="composer"', "field-editor", "Redaguoti visus laukus", 'id="reminder-add"'],
            reverse("contacts:company-detail", args=[self.company.pk]): ['id="composer"', "field-editor"],
            reverse("contacts:calendar"): ["data-cal-new"],
        }
        for url, markers in pages.items():
            response = self.client.get(url)
            self.assertContains(response, 'data-read-only="1"')
            for marker in markers:
                with self.subTest(url=url, marker=marker):
                    self.assertNotContains(response, marker)

    def test_editors_see_the_controls(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("contacts:detail", args=[self.person.pk]))
        self.assertContains(response, 'id="composer"')
        self.assertNotContains(response, "data-read-only")

    def test_editing_pages_and_writes_are_refused_server_side(self):
        from contacts.models import AuditLog
        refused = [
            ("get", reverse("contacts:person-create"), {}),
            ("get", reverse("contacts:edit", args=[self.person.pk]), {}),
            ("post", reverse("contacts:edit", args=[self.person.pk]), {"first_name": "Pakeista"}),
            ("post", reverse("contacts:inline-update", args=["person", self.person.pk]), {"field": "favourite", "value": "true"}),
            ("post", reverse("contacts:field-edit", args=[self.person.pk]), {"field": "first_name", "value": "Pakeista"}),
            ("post", reverse("contacts:activity-create", args=[self.person.pk]), {"note": "x"}),
            ("post", reverse("contacts:archive", args=[self.person.pk]), {}),
            ("post", reverse("contacts:bulk-action"), {"selected": [self.person.pk], "action": "archive"}),
            ("post", reverse("contacts:calendar-event-create"), {"text": "x"}),
            ("post", reverse("contacts:import-export"), {}),
        ]
        for method, url, data in refused:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, data)
                self.assertEqual(response.status_code, 302)
                self.assertNotEqual(response["Location"], url)
        self.person.refresh_from_db()
        self.assertEqual(self.person.first_name, "Jonas")
        self.assertIsNone(self.person.deleted_at)
        self.assertFalse(self.person.favourite)
        self.assertEqual(Activity.objects.count(), 0)
        self.assertTrue(AuditLog.objects.filter(target_type="access", detail__refused="read_only").exists())

    def test_background_writes_get_a_json_refusal(self):
        response = self.client.post(reverse("contacts:inline-update", args=["person", self.person.pk]),
                                    {"field": "favourite", "value": "true"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 403)
        self.assertIn("peržiūrėti", response.json()["error"])

    def test_personal_settings_stay_writable(self):
        response = self.client.post(reverse("contacts:settings-menu"), {"visible": ["calendar"]})
        self.assertRedirects(response, reverse("contacts:settings-menu"))
        self.assertEqual(self.client.post(reverse("contacts:reminder-mark-read")).status_code, 200)
        response = self.client.post(reverse("contacts:settings-password"), {
            "old_password": "very-secure-password", "new_password1": "Another-long-passphrase-9",
            "new_password2": "Another-long-passphrase-9"})
        self.assertRedirects(response, reverse("contacts:settings"))

    def test_capabilities_are_capped_whatever_the_table_says(self):
        from contacts import permissions as perm
        from contacts.models import RolePermissions
        RolePermissions.objects.create(role=UserProfile.ROLE_READONLY,
                                       permissions={"can_delete": True, "can_import": True, "can_export": True})
        self.assertFalse(perm.has_capability(self.reader, "can_delete"))
        self.assertFalse(perm.has_capability(self.reader, "can_import"))
        self.assertTrue(perm.has_capability(self.reader, "can_export"))
        self.assertEqual(perm.capability_matrix()[UserProfile.ROLE_READONLY]["can_delete"], False)

    def test_permissions_page_only_grants_read_side_capabilities_to_readers(self):
        from contacts import permissions as perm
        admin = get_user_model().objects.create_superuser("root", email="r@local", password="very-secure-password")
        self.client.force_login(admin)
        response = self.client.get(reverse("contacts:settings-permissions"))
        self.assertContains(response, "Skaitytojas (tik peržiūra)")
        self.client.post(reverse("contacts:settings-permissions"), {"cap_readonly": ["can_export", "can_delete"]})
        matrix = perm.capability_matrix()[UserProfile.ROLE_READONLY]
        self.assertTrue(matrix["can_export"])
        self.assertFalse(matrix["can_delete"])

    def test_read_write_api_token_of_a_reader_cannot_write(self):
        raw, digest = ApiToken.new()
        ApiToken.objects.create(name="rw", token_hash=digest, prefix=raw[:13], scope=ApiToken.READ_WRITE, created_by=self.reader)
        auth = {"HTTP_AUTHORIZATION": "Bearer " + raw}
        self.assertEqual(self.client.get("/api/v1/contacts", **auth).status_code, 200)
        response = self.client.post("/api/v1/contacts", data=json.dumps({"first_name": "Naujas", "last_name": "Asmuo"}),
                                    content_type="application/json", **auth)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Person.objects.filter(first_name="Naujas").exists())

    def test_create_shortcuts_are_left_out_of_a_readers_menu(self):
        profile = self.reader.crm_profile
        profile.menu_config = {"shortcuts": [{"kind": "action", "value": "person-create"}]}
        profile.save()
        response = self.client.get(reverse("contacts:list"))
        self.assertNotContains(response, reverse("contacts:person-create"))
        self.assertNotContains(response, reverse("contacts:duplicate-list"))

    def test_directory_reader_group_is_the_weakest_role(self):
        from contacts.directory import evaluate
        from contacts.integrations import OIDCConfig
        from contacts.models import DirectoryGroupMapping
        config = OIDCConfig(enabled=True, tenant_id="t", client_id="c", client_secret="s", create_users=False)
        readers = DirectoryGroupMapping(group="CRM-Readers", role=UserProfile.ROLE_READONLY)
        own = DirectoryGroupMapping(group="CRM-Own", role=UserProfile.ROLE_RESTRICTED)
        self.assertEqual(evaluate({"groups": ["CRM-Readers"]}, config, [readers, own]).role, UserProfile.ROLE_READONLY)
        self.assertEqual(evaluate({"groups": ["CRM-Readers", "CRM-Own"]}, config, [readers, own]).role, UserProfile.ROLE_RESTRICTED)


class InactiveAccountTests(TestCase):
    """Unused accounts are switched off; directory users come back when AD still allows them."""

    def setUp(self):
        from datetime import timedelta
        from contacts.models import SystemSettings
        User = get_user_model()
        old = timezone.now() - timedelta(days=120)
        recent = timezone.now() - timedelta(days=5)
        self.stale = User.objects.create_user("stale", email="stale@imone.lt", last_login=old)
        self.fresh = User.objects.create_user("fresh", last_login=recent)
        self.never = User.objects.create_user("never")
        User.objects.filter(pk=self.never.pk).update(date_joined=old)
        self.root = User.objects.create_superuser("root", email="root@local", password="very-secure-password", last_login=old)
        system = SystemSettings.load()
        system.deactivate_inactive_days = 90
        system.save()

    def run_command(self):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("deactivate_inactive_users", stdout=out)
        return out.getvalue()

    def active(self, user):
        user.refresh_from_db()
        return user.is_active

    def test_unused_accounts_are_switched_off_and_audited(self):
        from contacts.models import AuditLog
        output = self.run_command()
        self.assertIn("deactivated 2", output)
        self.assertFalse(self.active(self.stale))
        self.assertFalse(self.active(self.never))
        self.assertTrue(self.active(self.fresh))
        self.assertEqual(self.stale.crm_profile.deactivated_reason, "inactivity")
        self.assertTrue(AuditLog.objects.filter(target_type="user", target_id=str(self.stale.pk), detail__reason="inactivity").exists())

    def test_break_glass_accounts_are_never_switched_off(self):
        self.run_command()
        self.assertTrue(self.active(self.root))
        with override_settings(CRM_BREAK_GLASS_USERS=["fresh"]):
            self.run_command()
        self.assertFalse(self.active(self.root))

    def test_zero_days_disables_it(self):
        from contacts.models import SystemSettings
        system = SystemSettings.load()
        system.deactivate_inactive_days = 0
        system.save()
        self.assertIn("deactivated 0", self.run_command())
        self.assertTrue(self.active(self.stale))

    def test_deactivated_users_api_tokens_stop_working(self):
        raw, digest = ApiToken.new()
        ApiToken.objects.create(name="t", token_hash=digest, prefix=raw[:13], scope=ApiToken.READ, created_by=self.stale)
        self.assertEqual(self.client.get("/api/v1/contacts", HTTP_AUTHORIZATION="Bearer " + raw).status_code, 200)
        self.run_command()
        self.assertEqual(self.client.get("/api/v1/contacts", HTTP_AUTHORIZATION="Bearer " + raw).status_code, 401)

    def directory_sign_in(self, groups):
        from contacts.crypto import encrypt
        from contacts.models import DirectoryGroupMapping, SystemSettings
        from contacts.oidc import EntraOIDCBackend
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory
        system = SystemSettings.load()
        system.oidc_enabled, system.oidc_tenant_id = True, DirectoryAccessTests.TENANT
        system.oidc_client_id, system.oidc_client_secret = "cid", encrypt("csecret")
        system.oidc_sync_groups = True
        system.save()
        DirectoryGroupMapping.objects.get_or_create(group="CRM-Users", defaults={"role": UserProfile.ROLE_MEMBER})
        request = RequestFactory().get("/oidc/callback/")
        request.session = self.client.session
        request._messages = FallbackStorage(request)
        backend = EntraOIDCBackend()
        backend.request = request
        claims = {"email": "stale@imone.lt", "tid": DirectoryAccessTests.TENANT, "oid": "o1", "groups": groups}
        with patch("mozilla_django_oidc.auth.OIDCAuthenticationBackend.get_userinfo", return_value={}) as userinfo:
            user = backend.get_or_create_user("access", "id", claims)
        return user, userinfo

    def test_directory_sign_in_brings_back_an_account_switched_off_for_inactivity(self):
        self.run_command()
        user, userinfo = self.directory_sign_in(["CRM-Users"])
        self.assertEqual(user.pk, self.stale.pk)
        self.assertTrue(self.active(self.stale))
        self.assertEqual(self.stale.crm_profile.deactivated_reason, "")
        self.assertLessEqual(userinfo.call_count, 1)

    def test_directory_does_not_bring_back_without_groups_or_after_manual_switch_off(self):
        self.run_command()
        self.assertIsNone(self.directory_sign_in([])[0])
        self.assertFalse(self.active(self.stale))
        admin = self.root
        admin.last_login = timezone.now()
        admin.save()
        self.client.force_login(admin)
        self.client.post(reverse("contacts:settings-users"), {"action": "update", "user_id": self.stale.pk, "role": UserProfile.ROLE_MEMBER})
        self.stale.crm_profile.refresh_from_db()
        self.assertEqual(self.stale.crm_profile.deactivated_reason, "manual")
        self.assertIsNone(self.directory_sign_in(["CRM-Users"])[0])
        self.assertFalse(self.active(self.stale))

    def test_admin_reactivation_clears_the_reason(self):
        self.run_command()
        self.client.force_login(self.root)
        self.client.post(reverse("contacts:settings-users"), {"action": "update", "user_id": self.stale.pk,
                                                               "role": UserProfile.ROLE_MEMBER, "active": "1"})
        self.assertTrue(self.active(self.stale))
        self.stale.crm_profile.refresh_from_db()
        self.assertEqual(self.stale.crm_profile.deactivated_reason, "")

    def test_worker_and_kubernetes_run_it(self):
        compose = (settings.BASE_DIR / "compose.yaml").read_text()
        values = (settings.BASE_DIR / "deploy" / "helm" / "crm" / "values.yaml").read_text()
        self.assertIn("manage.py deactivate_inactive_users", compose)
        self.assertIn("command: deactivate_inactive_users", values)


class AuditTrailTests(TestCase):
    """Append-only audit rows, retention purge and CSV export."""

    def setUp(self):
        from contacts.audit import log as audit_log
        from contacts.models import AuditLog
        self.admin = get_user_model().objects.create_superuser("root", email="r@local", password="very-secure-password")
        self.entry = audit_log(AuditLog.UPDATE, actor=self.admin, target_type="person", target_id="7",
                               target_label="=HYPERLINK(\"x\")", field="first_name", old="A", new="B")

    def test_rows_cannot_be_changed_or_deleted_through_the_application(self):
        from contacts.models import AuditLog, AuditLogImmutable
        self.entry.new_value = "tampered"
        with self.assertRaises(AuditLogImmutable):
            self.entry.save()
        with self.assertRaises(AuditLogImmutable):
            self.entry.delete()
        with self.assertRaises(AuditLogImmutable):
            AuditLog.objects.filter(pk=self.entry.pk).update(new_value="tampered")
        with self.assertRaises(AuditLogImmutable):
            AuditLog.objects.all().delete()
        self.assertEqual(AuditLog.objects.get(pk=self.entry.pk).new_value, "B")

    def test_deleting_a_user_keeps_their_audit_rows(self):
        from contacts.models import AuditLog
        user = get_user_model().objects.create_user("leaver", password="very-secure-password")
        from contacts.audit import log as audit_log
        row = audit_log(AuditLog.LOGIN, actor=user, target_type="auth")
        user.delete()
        row = AuditLog.objects.get(pk=row.pk)
        self.assertIsNone(row.actor_id)
        self.assertEqual(row.actor_label, "leaver")

    def old_entry(self, days):
        """An audit row written ``days`` ago (auto_now_add reads timezone.now)."""
        from datetime import timedelta
        from contacts.audit import log as audit_log
        from contacts.models import AuditLog
        with patch("django.utils.timezone.now", return_value=timezone.now() - timedelta(days=days)):
            return audit_log(AuditLog.LOGIN, actor=self.admin, target_type="auth")

    def set_retention(self, days):
        from contacts.models import SystemSettings
        system = SystemSettings.load()
        system.audit_retention_days = days
        system.save()

    def test_purge_removes_only_expired_rows_and_leaves_a_summary(self):
        from io import StringIO
        from django.core.management import call_command
        from contacts.models import AuditLog
        old = self.old_entry(400)
        out = StringIO()
        call_command("purge_audit_log", stdout=out)
        self.assertIn("purged 0", out.getvalue())
        self.set_retention(365)
        call_command("purge_audit_log", stdout=out)
        self.assertFalse(AuditLog.objects.filter(pk=old.pk).exists())
        self.assertTrue(AuditLog.objects.filter(pk=self.entry.pk).exists())
        summary = AuditLog.objects.get(target_type="audit_log", action=AuditLog.DELETE)
        self.assertEqual(summary.detail["purged"], 1)

    def test_retention_below_the_minimum_is_never_applied(self):
        from contacts.audit import purge_expired
        from contacts.models import AuditLog
        row = self.old_entry(100)
        self.set_retention(30)  # e.g. written straight to the database
        purge_expired()
        self.assertTrue(AuditLog.objects.filter(pk=row.pk).exists())

    def test_only_admins_set_retention_and_the_minimum_is_enforced(self):
        from contacts.models import SystemSettings
        url = reverse("contacts:settings-audit")
        self.client.force_login(self.admin)
        response = self.client.post(url, {"audit_retention_days": "30"}, follow=True)
        self.assertContains(response, "bent 180")
        self.assertEqual(SystemSettings.load().audit_retention_days, 0)
        self.client.post(url, {"audit_retention_days": "730"})
        self.assertEqual(SystemSettings.load().audit_retention_days, 730)
        viewer = get_user_model().objects.create_user("viewer", password="very-secure-password")
        from contacts.models import RolePermissions
        RolePermissions.objects.create(role=UserProfile.ROLE_MEMBER, permissions={"can_view_audit": True})
        self.client.force_login(viewer)
        self.client.post(url, {"audit_retention_days": "0"})
        self.assertEqual(SystemSettings.load().audit_retention_days, 730)

    def test_csv_export_follows_filters_neutralises_formulas_and_is_audited(self):
        import csv
        from io import StringIO
        from contacts.models import AuditLog
        self.client.force_login(self.admin)
        response = self.client.get(reverse("contacts:settings-audit"), {"action": "update", "format": "csv"})
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        body = b"".join(response.streaming_content).decode("utf-8-sig")
        rows = list(csv.DictReader(StringIO(body)))
        self.assertEqual({row["action"] for row in rows}, {"update"})
        self.assertEqual(rows[0]["target_label"], "'=HYPERLINK(\"x\")")
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.EXPORT, target_type="audit_log").exists())

    def test_export_needs_the_audit_capability(self):
        self.client.force_login(get_user_model().objects.create_user("plain", password="very-secure-password"))
        self.assertEqual(self.client.get(reverse("contacts:settings-audit"), {"format": "csv"}).status_code, 404)

    def test_worker_and_kubernetes_run_the_purge(self):
        self.assertIn("manage.py purge_audit_log", (settings.BASE_DIR / "compose.yaml").read_text())
        self.assertIn("command: purge_audit_log", (settings.BASE_DIR / "deploy/helm/crm/values.yaml").read_text())


class PostgresAuditGuardTests(TestCase):
    """The database refuses what the application refuses (PostgreSQL only)."""

    def setUp(self):
        from django.db import connection
        if connection.vendor != "postgresql":
            self.skipTest("the database guard exists on PostgreSQL only")
        from contacts.audit import log as audit_log
        from contacts.models import AuditLog
        self.entry = audit_log(AuditLog.LOGIN, target_type="auth", target_label="x")

    def test_raw_update_and_delete_are_refused(self):
        from django.db import DatabaseError, connection, transaction
        for sql in ("UPDATE contacts_auditlog SET new_value = 'tampered' WHERE id = %s",
                    "DELETE FROM contacts_auditlog WHERE id = %s"):
            with self.subTest(sql=sql), self.assertRaises(DatabaseError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(sql, [self.entry.pk])

    def test_purge_closes_the_guard_again_when_it_is_done(self):
        from django.db import DatabaseError, connection, transaction
        from contacts.audit import purge_expired
        from contacts.models import SystemSettings
        system = SystemSettings.load()
        system.audit_retention_days = 365
        system.save()
        purge_expired()  # inside this test's transaction, like a nested call would be
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("DELETE FROM contacts_auditlog WHERE id = %s", [self.entry.pk])


@override_settings(CRM_ENVIRONMENT="staging", CRM_ISOLATED=True)
class StagingAnonymisationTests(TestCase):
    """A staging clone keeps the data's shape but nothing that identifies a person."""

    SECRETS = ["Jonas", "Jonaitis", "+37061234567", "jonas@imone.lt", "Gedimino pr. 1", "https://jonas.lt",
               "Slaptas pokalbis", "Paskambinti Jonui", "Asmens kodas 38001010000", "UAB Tikra", "302000000",
               "jonas.tikras@regitra.lt", "Tikras Darbuotojas", "Laiško turinys"]

    def setUp(self):
        from contacts.audit import log as audit_log
        from contacts.models import AuditLog, IncomingMail, PersonCompanyLink, PostalAddress, SavedFilter, WebLink
        self.media = TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media.name)
        self.override.enable()
        User = get_user_model()
        self.root = User.objects.create_superuser("root", email="root@local", password="very-secure-password")
        self.employee = User.objects.create_user("jonas.tikras@regitra.lt", email="jonas.tikras@regitra.lt",
                                                 first_name="Tikras", last_name="Darbuotojas")
        self.person = Person.objects.create(first_name="Jonas", last_name="Jonaitis", description="Asmens kodas 38001010000",
                                            created_by=self.employee, owner=self.employee)
        PhoneNumber.objects.create(person=self.person, number="+37061234567")
        EmailAddress.objects.create(person=self.person, email="jonas@imone.lt")
        PostalAddress.objects.create(person=self.person, address="Gedimino pr. 1")
        WebLink.objects.create(person=self.person, url="https://jonas.lt")
        self.company = Company.objects.create(name="UAB Tikra", company_code="302000000", email="jonas@imone.lt",
                                              created_by=self.employee)
        PersonCompanyLink.objects.create(person=self.person, company=self.company, role="Jonaitis direktorius")
        activity = Activity.objects.create(person=self.person, text="Slaptas pokalbis", created_by=self.employee)
        self.attachment = Attachment.objects.create(activity=activity, original_name="Jonaitis-sutartis.pdf",
                                                    file=SimpleUploadedFile("Jonaitis.pdf", b"Jonas Jonaitis sutartis"))
        Reminder.objects.create(person=self.person, text="Paskambinti Jonui", due_at=timezone.now(), created_by=self.employee)
        field = CustomField.objects.create(entity=CustomField.PERSON, name="Pastaba", field_type=CustomField.TEXT)
        CustomValue.objects.create(field=field, person=self.person, value="Jonaitis mėgsta kavą")
        IncomingMail.objects.create(message_id="<m1>", from_addr="jonas@imone.lt", subject="Jonas",
                                    body="Laiško turinys", received_at=timezone.now())
        SavedFilter.objects.create(user=self.employee, name="Jonaitis", filters={"q": "Jonaitis"})
        audit_log(AuditLog.UPDATE, actor=self.employee, target=self.person, field="first_name", old="Jonas", new="Jonas")
        self.people_before, self.activities_before = Person.objects.count(), Activity.objects.count()

    def tearDown(self):
        self.override.disable()
        self.media.cleanup()

    def everything_as_text(self):
        from django.core import serializers
        from contacts.models import AuditLog, IncomingMail, PersonCompanyLink, PostalAddress, SavedFilter, WebLink
        models = [Person, PhoneNumber, EmailAddress, PostalAddress, WebLink, Company, PersonCompanyLink, Activity,
                  Attachment, Reminder, CustomValue, IncomingMail, SavedFilter, AuditLog, get_user_model()]
        text = "".join(serializers.serialize("json", model.objects.all()) for model in models)
        self.attachment.refresh_from_db()
        with self.attachment.file.open("rb") as handle:
            text += handle.read().decode("utf-8", "replace")
        return text

    def test_personal_data_is_gone_but_the_shape_stays(self):
        from io import StringIO
        from django.core.management import call_command
        before = self.everything_as_text()
        self.assertTrue(all(secret in before for secret in self.SECRETS))
        out = StringIO()
        call_command("sanitize_staging", stdout=out)
        self.assertIn("anonymised:", out.getvalue())
        after = self.everything_as_text()
        for secret in self.SECRETS + ["Jonaitis"]:
            with self.subTest(secret=secret):
                self.assertNotIn(secret, after)
        self.assertEqual(Person.objects.count(), self.people_before)
        self.assertEqual(Activity.objects.count(), self.activities_before)
        self.assertEqual(self.person.company_links.count(), 1)
        self.assertEqual(Reminder.objects.count(), 1)

    def test_break_glass_login_survives_and_other_usernames_are_replaced(self):
        from io import StringIO
        from django.core.management import call_command
        call_command("sanitize_staging", stdout=StringIO())
        self.root.refresh_from_db()
        self.assertEqual(self.root.username, "root")
        self.assertTrue(self.root.check_password("very-secure-password"))
        response = self.client.post(reverse("login"), {"username": "root", "password": "very-secure-password"})
        self.assertEqual(response.status_code, 302)
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.username, "naudotojas%d" % self.employee.pk)

    def test_keep_personal_data_flag_skips_anonymisation(self):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("sanitize_staging", "--keep-personal-data", stdout=out)
        self.assertIn("KEPT", out.getvalue())
        self.assertTrue(Person.objects.filter(first_name="Jonas").exists())

    def test_refresh_script_copies_media_before_anonymising(self):
        script = (settings.BASE_DIR / "scripts" / "refresh-staging.sh").read_text()
        self.assertLess(script.index("copying media"), script.index("manage.py sanitize_staging"))



class DataSubjectRequestTests(TestCase):
    """Access/portability export and erasure of one contact person."""

    def setUp(self):
        from contacts.audit import log as audit_log
        from contacts.models import AuditLog, IncomingMail, PostalAddress
        self.media = TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media.name)
        self.override.enable()
        self.admin = get_user_model().objects.create_superuser("root", email="r@local", password="very-secure-password")
        self.person = Person.objects.create(first_name="Ona", last_name="Onaitė", created_by=self.admin, owner=self.admin)
        EmailAddress.objects.create(person=self.person, email="ona@imone.lt")
        PhoneNumber.objects.create(person=self.person, number="+37069999999")
        PostalAddress.objects.create(person=self.person, address="Vilniaus g. 5")
        self.other = Person.objects.create(first_name="Kitas", last_name="Asmuo", created_by=self.admin)
        self.activity = Activity.objects.create(person=self.person, text="Ona prašė pasiūlymo", created_by=self.admin)
        self.attachment = Attachment.objects.create(activity=self.activity, original_name="pasiulymas.txt",
                                                    file=SimpleUploadedFile("p.txt", b"Onos pasiulymas"))
        Reminder.objects.create(person=self.person, text="Perskambinti Onai", due_at=timezone.now(), created_by=self.admin)
        IncomingMail.objects.create(message_id="<ona>", from_addr="Ona <ona@imone.lt>", subject="Klausimas",
                                    body="Sveiki", received_at=timezone.now())
        IncomingMail.objects.create(message_id="<kitas>", from_addr="kitas@imone.lt", subject="Kita", body="x",
                                    received_at=timezone.now())
        self.audit_person = audit_log(AuditLog.UPDATE, actor=self.admin, target=self.person, field="first_name",
                                      old="Onutė", new="Ona")
        self.audit_mention = audit_log(AuditLog.UPDATE, actor=self.admin, target=self.other, field="note",
                                       old="", new="susijęs su ona@imone.lt")
        self.audit_unrelated = audit_log(AuditLog.UPDATE, actor=self.admin, target=self.other, field="first_name",
                                         old="Kitoks", new="Kitas")
        self.client.force_login(self.admin)
        self.url = reverse("contacts:settings-privacy-person", args=[self.person.pk])

    def tearDown(self):
        self.override.disable()
        self.media.cleanup()

    def test_only_admins_reach_it(self):
        self.client.force_login(get_user_model().objects.create_user("plain", password="very-secure-password"))
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.get(reverse("contacts:settings-privacy")).status_code, 404)

    def test_search_finds_active_and_archived_people_by_name_email_or_phone(self):
        self.person.deleted_at = timezone.now()
        self.person.save()
        for query in ("Onaitė", "ona onaitė", "ona@imone", "69999999"):
            with self.subTest(query=query):
                self.assertContains(self.client.get(reverse("contacts:settings-privacy"), {"q": query}), self.url)

    def test_export_contains_everything_and_is_audited(self):
        import io
        import zipfile
        from contacts.models import AuditLog
        response = self.client.get(self.url, {"format": "zip"})
        self.assertEqual(response["Content-Type"], "application/zip")
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        data = json.loads(archive.read("data.json"))
        self.assertEqual(data["person"]["last_name"], "Onaitė")
        self.assertEqual(data["emails"][0]["email"], "ona@imone.lt")
        self.assertEqual(data["addresses"][0]["address"], "Vilniaus g. 5")
        self.assertEqual(data["activities"][0]["text"], "Ona prašė pasiūlymo")
        self.assertEqual(data["reminders"][0]["text"], "Perskambinti Onai")
        self.assertEqual([m["subject"] for m in data["incoming_mail"]], ["Klausimas"])
        self.assertEqual(data["audit_trail"][0]["old"], "Onutė")
        self.assertEqual(archive.read("attachments/%d-pasiulymas.txt" % self.attachment.pk), b"Onos pasiulymas")
        entry = AuditLog.objects.filter(action=AuditLog.EXPORT, target_id=str(self.person.pk)).get()
        self.assertNotIn("Ona", entry.target_label)

    def test_erasure_needs_the_exact_name(self):
        self.client.post(self.url, {"op": "erase", "confirm_name": "Ona"})
        self.assertTrue(Person.objects.filter(pk=self.person.pk).exists())

    def test_erasure_removes_the_person_everywhere_and_redacts_the_audit_trail(self):
        import os
        from contacts.models import AuditLog, IncomingMail
        path = self.attachment.file.path
        self.assertTrue(os.path.exists(path))
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.url, {"op": "erase", "confirm_name": "Ona Onaitė"}, follow=True)
        self.assertContains(response, "Asmens duomenys ištrinti")
        self.assertFalse(Person.objects.filter(pk=self.person.pk).exists())
        self.assertFalse(EmailAddress.objects.filter(email="ona@imone.lt").exists())
        self.assertFalse(Activity.objects.filter(pk=self.activity.pk).exists())
        self.assertFalse(Reminder.objects.filter(text="Perskambinti Onai").exists())
        self.assertFalse(Attachment.objects.filter(pk=self.attachment.pk).exists())
        self.assertFalse(os.path.exists(path))
        self.assertEqual(list(IncomingMail.objects.values_list("message_id", flat=True)), ["<kitas>"])
        self.assertTrue(Person.objects.filter(pk=self.other.pk).exists())
        for row in (self.audit_person, self.audit_mention):
            row = AuditLog.objects.get(pk=row.pk)
            with self.subTest(row=row.pk):
                self.assertEqual((row.target_label, row.old_value, row.new_value), ("[ištrinta]", "", ""))
                self.assertEqual((row.action, row.actor_id, row.field), (AuditLog.UPDATE, self.admin.pk, row.field))
        self.assertEqual(AuditLog.objects.get(pk=self.audit_unrelated.pk).old_value, "Kitoks")
        erasure = AuditLog.objects.get(action=AuditLog.DELETE, detail__reason="data_subject_erasure")
        self.assertEqual(erasure.target_id, str(self.person.pk))
        everything = json.dumps(list(AuditLog.objects.values()), default=str)
        for secret in ("Ona", "Onaitė", "ona@imone.lt", "Onutė", "69999999"):
            self.assertNotIn(secret, everything)

    def test_detail_menu_links_admins_to_the_request_page(self):
        self.assertContains(self.client.get(reverse("contacts:detail", args=[self.person.pk])), self.url)


class PostgresAuditRedactionGuardTests(TestCase):
    """Redaction may strip values but never rewrite who, what or when (PostgreSQL only)."""

    def setUp(self):
        from django.db import connection
        if connection.vendor != "postgresql":
            self.skipTest("the database guard exists on PostgreSQL only")
        from contacts.audit import log as audit_log
        from contacts.models import AuditLog
        self.entry = audit_log(AuditLog.UPDATE, target_type="person", target_id="1", target_label="Ona", old="a", new="b")

    def test_redaction_switch_allows_values_but_not_facts(self):
        from django.db import DatabaseError, connection, transaction
        from contacts.audit import sanctioned_redact
        from contacts.models import AuditLog
        self.assertEqual(sanctioned_redact(AuditLog.objects.filter(pk=self.entry.pk)), 1)
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL crm.audit_redact = 'on'")
            cursor.execute("UPDATE contacts_auditlog SET action = 'login' WHERE id = %s", [self.entry.pk])
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("UPDATE contacts_auditlog SET old_value = 'x' WHERE id = %s", [self.entry.pk])


class RetentionTests(TestCase):
    """Archived records and incoming mail past retention are erased like a data subject request."""

    def setUp(self):
        from datetime import timedelta
        from contacts.models import IncomingMail
        self.admin = get_user_model().objects.create_superuser("root", email="r@local", password="very-secure-password")
        now = timezone.now()
        self.old_person = Person.objects.create(first_name="Senas", last_name="Archyvas", created_by=self.admin,
                                                deleted_at=now - timedelta(days=400))
        Activity.objects.create(person=self.old_person, text="sena veikla", created_by=self.admin)
        self.new_person = Person.objects.create(first_name="Naujas", last_name="Archyvas", created_by=self.admin,
                                                deleted_at=now - timedelta(days=10))
        self.active = Person.objects.create(first_name="Aktyvus", last_name="Asmuo", created_by=self.admin)
        self.old_company = Company.objects.create(name="UAB Sena", created_by=self.admin, deleted_at=now - timedelta(days=400))
        Activity.objects.create(company=self.old_company, text="įmonės veikla", created_by=self.admin)
        IncomingMail.objects.create(message_id="<old>", from_addr="a@b.lt", received_at=now - timedelta(days=200))
        IncomingMail.objects.create(message_id="<new>", from_addr="a@b.lt", received_at=now - timedelta(days=2))

    def configure(self, archived=0, mail=0):
        from contacts.models import SystemSettings
        system = SystemSettings.load()
        system.archived_retention_days, system.incoming_mail_retention_days = archived, mail
        system.save()

    def run_command(self, *args):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("apply_retention", *args, stdout=out)
        return out.getvalue()

    def test_nothing_happens_while_retention_is_off(self):
        self.assertIn("people=0, companies=0, mail=0", self.run_command())
        self.assertTrue(Person.objects.filter(pk=self.old_person.pk).exists())

    def test_dry_run_reports_without_deleting(self):
        self.configure(archived=365, mail=90)
        self.assertIn("people=1, companies=1, mail=1", self.run_command("--dry-run"))
        self.assertTrue(Person.objects.filter(pk=self.old_person.pk).exists())

    def test_expired_records_and_mail_are_erased_and_audited(self):
        from contacts.models import AuditLog, IncomingMail
        self.configure(archived=365, mail=90)
        self.assertIn("people=1, companies=1, mail=1", self.run_command())
        self.assertFalse(Person.objects.filter(pk=self.old_person.pk).exists())
        self.assertFalse(Company.objects.filter(pk=self.old_company.pk).exists())
        self.assertFalse(Activity.objects.filter(text__in=["sena veikla", "įmonės veikla"]).exists())
        self.assertTrue(Person.objects.filter(pk=self.new_person.pk).exists())
        self.assertTrue(Person.objects.filter(pk=self.active.pk).exists())
        self.assertEqual(list(IncomingMail.objects.values_list("message_id", flat=True)), ["<new>"])
        self.assertEqual(AuditLog.objects.filter(action=AuditLog.DELETE, detail__reason="retention").count(), 3)

    def test_short_periods_are_raised_to_the_minimum(self):
        from datetime import timedelta
        self.new_person.deleted_at = timezone.now() - timedelta(days=20)
        self.new_person.save()
        self.configure(archived=1)  # e.g. written straight to the database
        self.run_command()
        self.assertTrue(Person.objects.filter(pk=self.new_person.pk).exists())

    def test_settings_page_saves_validates_and_previews(self):
        from contacts.models import SystemSettings
        self.client.force_login(self.admin)
        url = reverse("contacts:settings-privacy")
        response = self.client.post(url, {"archived_retention_days": "5", "incoming_mail_retention_days": "0"}, follow=True)
        self.assertContains(response, "bent 30")
        self.client.post(url, {"archived_retention_days": "365", "incoming_mail_retention_days": "90"})
        system = SystemSettings.load()
        self.assertEqual((system.archived_retention_days, system.incoming_mail_retention_days), (365, 90))
        self.assertContains(self.client.get(url), "1 kontaktų, 1 įmonių, 1 laiškų")

    def test_worker_and_kubernetes_run_it(self):
        self.assertIn("manage.py apply_retention", (settings.BASE_DIR / "compose.yaml").read_text())
        self.assertIn("command: apply_retention", (settings.BASE_DIR / "deploy/helm/crm/values.yaml").read_text())


class FakeClamd:
    """A minimal clamd speaking INSTREAM on a free port; flags the EICAR test string."""

    EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"

    def __init__(self, reply=None):
        import socketserver
        import struct
        import threading
        fixed = reply

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                command = b""
                while not command.endswith(b"\0"):
                    command += self.request.recv(1)
                data = b""
                while True:
                    size = struct.unpack("!L", self._exact(4))[0]
                    if not size:
                        break
                    data += self._exact(size)
                if fixed is not None:
                    self.request.sendall(fixed)
                elif FakeClamd.EICAR in data:
                    self.request.sendall(b"stream: Eicar-Test-Signature FOUND\0")
                else:
                    self.request.sendall(b"stream: OK\0")

            def _exact(self, size):
                buffer = b""
                while len(buffer) < size:
                    buffer += self.request.recv(size - len(buffer))
                return buffer

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class AntivirusTests(TestCase):
    """Uploads are scanned by clamd before they are stored or parsed."""

    def setUp(self):
        self.clamd = FakeClamd()
        self.media = TemporaryDirectory()
        self.overrides = override_settings(CRM_CLAMAV_HOST="127.0.0.1", CRM_CLAMAV_PORT=self.clamd.port,
                                           CRM_CLAMAV_REQUIRED=True, MEDIA_ROOT=self.media.name)
        self.overrides.enable()
        self.user = get_user_model().objects.create_superuser("av", email="av@local", password="very-secure-password")
        self.person = Person.objects.create(first_name="Failų", last_name="Tikrinimas", created_by=self.user, owner=self.user)
        self.client.force_login(self.user)

    def tearDown(self):
        self.overrides.disable()
        self.clamd.close()
        self.media.cleanup()

    def test_protocol_verdicts(self):
        from io import BytesIO
        from contacts.antivirus import scan_file
        self.assertTrue(scan_file(BytesIO(b"hello " * 50000)).clean)
        verdict = scan_file(BytesIO(b"prefix " + FakeClamd.EICAR))
        self.assertFalse(verdict.clean)
        self.assertEqual(verdict.signature, "Eicar-Test-Signature")

    def test_infected_attachment_is_refused_audited_and_logged(self):
        from contacts.models import AuditLog
        url = reverse("contacts:activity-create", args=[self.person.pk])
        with self.assertLogs("crm.security", level="WARNING") as captured:
            self.client.post(url, {"activity_type": "note", "text": "su failais", "attachments": [
                SimpleUploadedFile("eicar.txt", FakeClamd.EICAR), SimpleUploadedFile("ok.txt", b"clean file")]})
        self.assertEqual(list(Attachment.objects.values_list("original_name", flat=True)), ["ok.txt"])
        self.assertTrue(AuditLog.objects.filter(target_type="upload", detail__signature="Eicar-Test-Signature").exists())
        self.assertTrue(any(r.event == "upload.malware" for r in captured.records))

    def test_unreachable_scanner_fails_closed_unless_told_otherwise(self):
        from io import BytesIO
        from contacts.antivirus import check_upload
        self.clamd.close()
        with self.assertLogs("crm.security", level="ERROR"):
            self.assertFalse(check_upload(BytesIO(b"x"), name="x.txt", source="test"))
        with override_settings(CRM_CLAMAV_REQUIRED=False), self.assertLogs("crm.security", level="WARNING"):
            self.assertTrue(check_upload(BytesIO(b"x"), name="x.txt", source="test"))
        self.clamd = FakeClamd()  # tearDown closes it

    def test_error_reply_is_not_mistaken_for_clean(self):
        from io import BytesIO
        from contacts.antivirus import ScanUnavailable, scan_file
        broken = FakeClamd(reply=b"INSTREAM size limit exceeded. ERROR\0")
        try:
            with override_settings(CRM_CLAMAV_PORT=broken.port), self.assertRaises(ScanUnavailable):
                scan_file(BytesIO(b"x"))
        finally:
            broken.close()

    def test_import_and_incoming_mail_attachments_are_scanned(self):
        from email.message import EmailMessage
        from contacts.mailfetch import _save_attachments
        response = self.client.post(reverse("contacts:import-export"),
                                    {"file": SimpleUploadedFile("kontaktai.csv", FakeClamd.EICAR)}, follow=True)
        self.assertContains(response, "nepraėjo antivirusinės patikros")
        activity = Activity.objects.create(person=self.person, text="laiškas", created_by=self.user)
        message = EmailMessage()
        message.set_content("body")
        message.add_attachment(FakeClamd.EICAR, maintype="application", subtype="pdf", filename="virus.pdf")
        message.add_attachment(b"%PDF-1.4 clean", maintype="application", subtype="pdf", filename="clean.pdf")
        _save_attachments(message, activity)
        self.assertEqual(list(activity.attachments.values_list("original_name", flat=True)), ["clean.pdf"])

    def test_scanning_is_off_without_a_host(self):
        from io import BytesIO
        from contacts.antivirus import check_upload
        with override_settings(CRM_CLAMAV_HOST=""):
            self.assertTrue(check_upload(BytesIO(FakeClamd.EICAR), name="e.txt", source="test"))


from django.test import TransactionTestCase  # noqa: E402


class PostgresReportingRoleTests(TransactionTestCase):
    """The reporting role reads the reporting views and nothing else (PostgreSQL only)."""

    ROLE = "crm_reporting_test"
    PASSWORD = "reporting-password-0123456789"

    def setUp(self):
        from django.db import connection
        if connection.vendor != "postgresql":
            self.skipTest("the reporting schema exists on PostgreSQL only")
        user = get_user_model().objects.create_user("reporter", password="very-secure-password")
        Person.objects.create(first_name="Ataskaitų", last_name="Asmuo", created_by=user, description="slapta pastaba")

    def tearDown(self):
        from django.db import connection
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [self.ROLE])
                if cursor.fetchone():
                    cursor.execute("DROP OWNED BY %s" % self.ROLE)
                    cursor.execute("DROP ROLE %s" % self.ROLE)

    def connect_as_role(self):
        import psycopg
        from django.db import connection
        params = connection.settings_dict
        return psycopg.connect(host=params["HOST"], port=params["PORT"] or 5432, dbname=params["NAME"],
                               user=self.ROLE, password=self.PASSWORD, autocommit=True)

    def test_role_reads_views_but_not_application_tables(self):
        import psycopg
        from io import StringIO
        from django.core.management import call_command
        with patch.dict(os.environ, {"REPORTING_PASSWORD": self.PASSWORD}):
            out = StringIO()
            call_command("create_reporting_role", "--name", self.ROLE, stdout=out)
            self.assertIn("created role", out.getvalue())
            call_command("create_reporting_role", "--name", self.ROLE, stdout=out)  # idempotent
        with self.connect_as_role() as conn:
            self.assertEqual(conn.execute("SELECT last_name FROM reporting.people").fetchall(), [("Asmuo",)])
            columns = [d.name for d in conn.execute("SELECT * FROM reporting.people LIMIT 0").description]
            self.assertNotIn("description", columns)
            for query in ("SELECT * FROM contacts_person", "SELECT password FROM auth_user",
                          "SELECT * FROM django_session", "SELECT * FROM contacts_apitoken",
                          "SELECT * FROM contacts_systemsettings"):
                with self.subTest(query=query), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    conn.execute(query)
            with self.assertRaises((psycopg.errors.ReadOnlySqlTransaction, psycopg.errors.InsufficientPrivilege)):
                conn.execute("DELETE FROM reporting.tags")

    def test_the_reminder_view_carries_the_event_shape_but_no_free_text(self):
        from io import StringIO
        from django.core.management import call_command
        with patch.dict(os.environ, {"REPORTING_PASSWORD": self.PASSWORD}):
            call_command("create_reporting_role", "--name", self.ROLE, stdout=StringIO())
        with self.connect_as_role() as conn:
            columns = [d.name for d in conn.execute("SELECT * FROM reporting.reminders LIMIT 0").description]
        self.assertIn("kind", columns)
        self.assertIn("end_at", columns)
        for free_text in ("text", "description", "meeting_url"):
            self.assertNotIn(free_text, columns)

    def test_weak_password_is_refused(self):
        from django.core.management import CommandError, call_command
        with patch.dict(os.environ, {"REPORTING_PASSWORD": "short"}), self.assertRaises(CommandError):
            call_command("create_reporting_role", "--name", self.ROLE)


class ReportingViewDefinitionTests(TestCase):
    """The reporting SQL is checked here too, because the role tests above only
    run where PostgreSQL does — on SQLite they skip, and a wrong view would then
    reach the warehouse unnoticed."""

    def test_the_reminder_view_adds_the_event_columns_and_keeps_text_out(self):
        import importlib
        import pkgutil

        from contacts import migrations

        # Found by suffix: the regitra branch numbers its migrations differently,
        # and a hard-coded number would only break on the next cherry-pick.
        name = next(module.name for module in pkgutil.iter_modules(migrations.__path__)
                    if module.name.endswith("_reporting_reminder_kind"))
        sql = importlib.import_module("contacts.migrations." + name).REMINDERS.lower()
        for column in ("kind", "end_at", "due_at", "completed_at"):
            self.assertIn(column, sql)
        for free_text in (" text", "description", "meeting_url"):
            self.assertNotIn(free_text, sql)


class TranslationStorageTests(TestCase):
    """Overrides are unique per msgid without an index on the unbounded text."""

    def test_long_msgids_are_stored_and_duplicates_refused(self):
        from django.db import IntegrityError, transaction
        from contacts.models import Translation
        long_msgid = "Ilgas dokumentacijos tekstas. " * 400  # ~12 kB: past PostgreSQL's btree row limit
        row = Translation.objects.create(msgid=long_msgid, en="Long")
        self.assertEqual(row.msgid_hash, Translation.hash_of(long_msgid))
        with self.assertRaises(IntegrityError), transaction.atomic():
            Translation.objects.create(msgid=long_msgid, en="Again")
        self.assertEqual(Translation.objects.get(msgid_hash=Translation.hash_of(long_msgid)).en, "Long")


class QueryScalingTests(TestCase):
    """Page cost must not grow with the data: guards against N+1 queries and unbounded markup."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("scale", password="very-secure-password")
        self.client.force_login(self.user)
        self.company = Company.objects.create(name="UAB Mastas", created_by=self.user, owner=self.user)

    def add_people(self, count):
        from contacts.models import PersonCompanyLink, PostalAddress
        for index in range(count):
            person = Person.objects.create(first_name="Asmuo", last_name="Nr%04d" % Person.objects.count(),
                                           created_by=self.user, owner=self.user)
            PhoneNumber.objects.create(person=person, number="+3706000%04d" % person.pk)
            PostalAddress.objects.create(person=person, address="Gatvė %d" % person.pk)
            PersonCompanyLink.objects.create(person=person, company=self.company)
            Reminder.objects.create(person=person, text="Priminimas", due_at=timezone.now() + timedelta(hours=index + 1),
                                    created_by=self.user)

    def queries_for(self, url):
        """The page's queries, with literals folded away so two runs compare by
        shape — a mismatch then names the query that appeared."""
        import re
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        self.client.get(url)  # warm per-process caches
        with CaptureQueriesContext(connection) as captured:
            self.assertEqual(self.client.get(url).status_code, 200)
        return [re.sub(r"\d+", "N", query["sql"])[:160] for query in captured.captured_queries]

    def test_list_calendar_and_dashboard_queries_do_not_grow_with_rows(self):
        # Both sizes non-empty: a prefetch that runs only when there are rows is constant, not growth.
        from collections import Counter
        self.add_people(10)
        small = {url: self.queries_for(url) for url in ("/contacts/", "/calendar/", "/")}
        self.add_people(30)
        for url, before in small.items():
            with self.subTest(url=url):
                after = self.queries_for(url)
                added = Counter(after) - Counter(before)
                self.assertEqual(len(after), len(before), "added: %s" % sorted(added.elements()))

    def test_bell_lists_a_bounded_number_of_reminders(self):
        from contacts.context_processors import BELL_LIMIT
        self.add_people(BELL_LIMIT + 10)
        response = self.client.get("/calendar/")
        self.assertEqual(response.content.decode().count('class="reminder-menu-item"'), BELL_LIMIT)
        self.assertContains(response, "Rodomi %d artimiausi iš %d." % (BELL_LIMIT, BELL_LIMIT + 10))


class ListPageAggregateTests(TestCase):
    """Last contact and contact counts are computed for the visible page with the same results."""

    def setUp(self):
        from contacts.models import PersonCompanyLink
        User = get_user_model()
        self.boss = User.objects.create_user("boss", password="very-secure-password")
        self.own = User.objects.create_user("own", password="very-secure-password")
        UserProfile.objects.create(user=self.own, role=UserProfile.ROLE_RESTRICTED)
        self.company = Company.objects.create(name="UAB Skaičius", created_by=self.boss, owner=self.own)
        self.mine = Person.objects.create(first_name="Mano", last_name="Kontaktas", created_by=self.own, owner=self.own)
        self.other = Person.objects.create(first_name="Svetimas", last_name="Kontaktas", created_by=self.boss, owner=self.boss)
        for person in (self.mine, self.other):
            PersonCompanyLink.objects.create(person=person, company=self.company)
        old = Activity.objects.create(person=self.mine, text="senas", created_by=self.own)
        Activity.objects.filter(pk=old.pk).update(created_at=timezone.make_aware(datetime(2026, 1, 5, 10, 0)))
        newest = Activity.objects.create(person=self.mine, text="naujas", created_by=self.own)
        Activity.objects.filter(pk=newest.pk).update(created_at=timezone.make_aware(datetime(2026, 3, 7, 10, 0)))
        archived = Activity.objects.create(person=self.mine, text="archyvuotas", created_by=self.own)
        Activity.objects.filter(pk=archived.pk).update(created_at=timezone.make_aware(datetime(2026, 5, 1, 10, 0)),
                                                       deleted_at=timezone.now())

    def test_last_contact_column_matches_with_and_without_sorting_by_it(self):
        self.client.force_login(self.boss)
        for params in ({"columns": ["last_contact"]}, {"columns": ["last_contact"], "sort": "last_contact"}):
            with self.subTest(params=params):
                response = self.client.get(reverse("contacts:list"), params)
                rows = {p.pk: p.last_contact_at for p in response.context["page"].object_list}
                self.assertEqual(rows[self.mine.pk].date(), datetime(2026, 3, 7).date())
                self.assertIsNone(rows[self.other.pk])

    def test_company_contact_count_respects_visibility_with_and_without_sorting(self):
        for user, expected in ((self.boss, 2), (self.own, 1)):
            self.client.force_login(user)
            for params in ({}, {"sort": "contacts"}):
                with self.subTest(user=user.username, params=params):
                    response = self.client.get(reverse("contacts:company-list"), params)
                    company = next(c for c in response.context["page"].object_list if c.pk == self.company.pk)
                    self.assertEqual(company.contact_count, expected)


class ClientAddressTests(TestCase):
    """Behind a proxy the real client address drives audit and lockout, and cannot be spoofed."""

    def ip(self, remote, forwarded=None):
        from django.test import RequestFactory
        from contacts.audit import client_ip
        extra = {"REMOTE_ADDR": remote}
        if forwarded is not None:
            extra["HTTP_X_FORWARDED_FOR"] = forwarded
        return client_ip(RequestFactory().get("/", **extra))

    def test_without_trusted_proxies_the_header_is_ignored(self):
        self.assertEqual(self.ip("203.0.113.9", "1.2.3.4"), "203.0.113.9")

    @override_settings(CRM_TRUSTED_PROXY_NETWORKS=(__import__("ipaddress").ip_network("10.0.0.0/8"),))
    def test_trusted_proxy_header_is_read_from_the_right(self):
        self.assertEqual(self.ip("10.0.0.2", "198.51.100.7"), "198.51.100.7")
        # A client-supplied hop to the left of the real one is not believed.
        self.assertEqual(self.ip("10.0.0.2", "6.6.6.6, 198.51.100.7"), "198.51.100.7")
        self.assertEqual(self.ip("10.0.0.2", "198.51.100.7, 10.0.0.9"), "198.51.100.7")
        # A direct, untrusted connection cannot choose its address.
        self.assertEqual(self.ip("203.0.113.9", "198.51.100.7"), "203.0.113.9")
        # A malformed header falls back to the connection address (the audit column is an IP type).
        self.assertEqual(self.ip("10.0.0.2", "garbage"), "10.0.0.2")
        self.assertEqual(self.ip("10.0.0.2", "198.51.100.7, <script>"), "10.0.0.2")

    @override_settings(CRM_TRUSTED_PROXY_NETWORKS=(__import__("ipaddress").ip_network("10.0.0.0/8"),))
    def test_lockout_is_per_client_not_per_proxy(self):
        get_user_model().objects.create_user("victim", password="very-secure-password")
        for _ in range(6):
            self.client.post(reverse("login"), {"username": "attacker", "password": "wrong-password-123"},
                             REMOTE_ADDR="10.0.0.2", HTTP_X_FORWARDED_FOR="198.51.100.66")
        blocked = self.client.post(reverse("login"), {"username": "attacker", "password": "wrong-password-123"},
                                   REMOTE_ADDR="10.0.0.2", HTTP_X_FORWARDED_FOR="198.51.100.66")
        self.assertEqual(blocked.status_code, 429)
        response = self.client.post(reverse("login"), {"username": "victim", "password": "very-secure-password"},
                                    REMOTE_ADDR="10.0.0.2", HTTP_X_FORWARDED_FOR="198.51.100.7")
        self.assertEqual(response.status_code, 302)


class CalendarFeedSwitchTests(TestCase):
    def test_admin_can_turn_subscription_links_off(self):
        from contacts.models import SystemSettings
        user = get_user_model().objects.create_user("feed", password="very-secure-password")
        profile = UserProfile.objects.create(user=user)
        url = "/calendar/feed/%s.ics" % profile.calendar_token
        self.assertEqual(self.client.get(url).status_code, 200)
        system = SystemSettings.load()
        system.calendar_feed_enabled = False
        system.save()
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(user)
        self.assertNotContains(self.client.get(reverse("contacts:settings")), "Kalendoriaus prenumerata")


class ReviewHardeningTests(TestCase):
    """Findings of the pre-presentation security review."""

    def test_production_like_start_refuses_the_development_secret_key(self):
        import subprocess
        import sys
        env = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "DB_"))}
        env.update({"DB_HOST": "db.invalid", "DJANGO_SETTINGS_MODULE": "config.settings"})
        probe = "import django; django.setup(); from django.conf import settings; print(settings.DEBUG)"
        result = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True,
                                cwd=settings.BASE_DIR)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY is not set", result.stderr)
        env["DJANGO_SECRET_KEY"] = "a-real-secret-0123456789abcdefghijklmnopqrstuvwxyzABCDEF"
        result = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True,
                                cwd=settings.BASE_DIR)
        self.assertEqual(result.stdout.strip(), "False")  # DEBUG defaults off with a real database

    def test_django_admin_is_off_by_default_and_superuser_only_when_enabled(self):
        import importlib
        from django.urls import clear_url_caches
        import config.urls
        staff = get_user_model().objects.create_user("crmadmin", password="very-secure-password", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get("/admin/").status_code, 404)
        try:
            with self.settings(CRM_DJANGO_ADMIN=True):
                importlib.reload(config.urls)
                clear_url_caches()
                self.assertNotEqual(self.client.get("/admin/").status_code, 200)  # staff is not enough
                root = get_user_model().objects.create_superuser("root", email="r@local", password="very-secure-password")
                self.client.force_login(root)
                self.assertEqual(self.client.get("/admin/").status_code, 200)
        finally:
            importlib.reload(config.urls)
            clear_url_caches()

    def test_avatar_must_really_be_an_image_and_is_never_served_as_html(self):
        from contacts.views import avatar_image_type
        from io import BytesIO
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        self.assertEqual(avatar_image_type(BytesIO(png)), "image/png")
        self.assertEqual(avatar_image_type(BytesIO(b"RIFF\x00\x00\x00\x00WEBPVP8 ")), "image/webp")
        self.assertIsNone(avatar_image_type(BytesIO(b"<html><script>alert(1)</script>")))
        media = TemporaryDirectory()
        try:
            with self.settings(MEDIA_ROOT=media.name):
                user = get_user_model().objects.create_user("pic", password="very-secure-password", first_name="A")
                self.client.force_login(user)
                disguised = SimpleUploadedFile("evil.png", b"<html><script>alert(1)</script></html>", content_type="image/png")
                self.client.post(reverse("contacts:settings"), {"first_name": "A", "last_name": "B", "email": "a@b.lt",
                                                               "language": "lt", "timezone": "Europe/Vilnius", "avatar": disguised})
                profile = UserProfile.objects.get(user=user)
                self.assertFalse(profile.avatar)
                profile.avatar.save("legacy.html", SimpleUploadedFile("legacy.html", b"<html>x</html>"))
                response = self.client.get(reverse("contacts:profile-avatar"))
                self.assertEqual(response["Content-Type"], "application/octet-stream")
                self.assertIn("attachment", response["Content-Disposition"])
        finally:
            media.cleanup()


class ExtraAppsTests(TestCase):
    """`CRM_EXTRA_APPS` is how an app installed beside the CRM is switched on,
    so an integration can be a separate package instead of a patch."""

    def test_the_setting_reads_a_comma_separated_list_and_ignores_blanks(self):
        import importlib
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"CRM_EXTRA_APPS": " regitra , , kita "}):
            settings_module = importlib.reload(importlib.import_module("config.settings"))
        try:
            apps = settings_module.INSTALLED_APPS
            # Whitespace trimmed, the empty entry dropped, order kept.
            self.assertEqual([name for name in apps if name in ("regitra", "kita")], ["regitra", "kita"])
            self.assertNotIn("", apps)
        finally:
            # Leave the imported module as the running process found it.
            importlib.reload(settings_module)

    def test_nothing_is_added_when_the_variable_is_unset(self):
        self.assertNotIn("regitra", settings.INSTALLED_APPS)


class ErrorPageTests(TestCase):
    """What a person is told when something fails.

    Before these pages existed the product had no error templates at all, so
    with DEBUG off Django answered with an unstyled English line — "Not Found" —
    and nothing else: no cause, no next step, no way back. These tests hold the
    three things each page must do rather than its wording, which will change.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="err-qa", password="x" * 14)

    def _assert_helpful(self, response, status):
        html = response.content.decode()
        self.assertEqual(response.status_code, status)
        self.assertIn("<main", html)
        self.assertIn("<ul>", html)               # why it happened
        self.assertIn('href="/"', html)                   # a way back
        self.assertNotIn("<h1>Not Found</h1>", html)

    def test_a_missing_page_says_what_became_of_the_record(self):
        self.client.force_login(self.user)
        response = self.client.get("/contacts/999999/")
        self._assert_helpful(response, 404)
        self.assertIn("Archyve", response.content.decode())

    def test_an_unknown_address_is_answered_the_same_way(self):
        self.client.force_login(self.user)
        self._assert_helpful(self.client.get("/no-such-page/"), 404)

    def test_the_server_error_page_carries_the_request_id(self):
        """It is the only handle an administrator has on one failure in a log."""
        from contacts.errors import server_error
        request = RequestFactory().get("/")
        request.request_id = "abc123"
        response = server_error(request)
        self.assertEqual(response.status_code, 500)
        html = response.content.decode()
        self.assertIn("abc123", html)
        self.assertIn("reference", html)

    def test_the_server_error_page_needs_no_request_context(self):
        """Django renders handler500 with no context processors: a page that
        reached for `user` or `request` would render blank exactly here."""
        from contacts.errors import server_error
        response = server_error(RequestFactory().get("/"))
        self.assertEqual(response.status_code, 500)
        self.assertIn("<main", response.content.decode())

    def test_a_refused_form_explains_itself_rather_than_cookies(self):
        from contacts.errors import csrf_failure
        response = csrf_failure(RequestFactory().post("/"), reason="CSRF token missing")
        self.assertEqual(response.status_code, 403)
        html = response.content.decode()
        self.assertIn("<ul>", html)
        self.assertIn("Niekas nepakeista", html)

    def test_forbidden_names_where_the_roles_are_listed(self):
        from contacts.errors import permission_denied
        html = permission_denied(RequestFactory().get("/")).content.decode()
        self.assertIn("Rolės ir teisės", html)

    def test_every_handler_is_registered(self):
        """A page nobody wired up is a page Django never reaches for."""
        import config.urls as urls
        for name in ("handler400", "handler403", "handler404", "handler500"):
            self.assertTrue(getattr(urls, name, "").startswith("contacts.errors."), name)
        self.assertEqual(settings.CSRF_FAILURE_VIEW, "contacts.errors.csrf_failure")


class StagingPublicSwitchTests(TestCase):
    """Turning Funnel on is a switch somebody will reach for in a hurry.

    It writes the two lines deploy-staging.sh insists on, and it must never be
    able to point at production — the guard is the whole safety of the thing.
    """

    @property
    def script(self):
        return (settings.BASE_DIR / "scripts" / "staging-public.sh").read_text()

    def test_it_refuses_anything_that_is_not_an_isolated_copy(self):
        self.assertIn("CRM_ENVIRONMENT=staging", self.script)
        self.assertIn("compose\\.staging\\.yaml", self.script)
        self.assertEqual(self.script.count("exit 1"), 4)

    def test_both_lines_are_written_together_and_removed_together(self):
        """Either one alone is refused by the deploy, so a switch that wrote
        only one would leave the instance undeployable and look like a bug."""
        script = self.script
        self.assertIn("serve-staging-funnel.json\\nCRM_STAGING_PUBLIC=1", script)
        # Off removes both and restores the tailnet-only file.
        self.assertIn("-e '^TS_SERVE_CONFIG=' -e '^CRM_STAGING_PUBLIC='", script)
        off = script.split("  off)")[1].split(";;")[0]
        self.assertIn("serve-staging.json", off)
        self.assertNotIn("CRM_STAGING_PUBLIC", off)

    def test_the_env_file_keeps_its_permissions(self):
        """It holds this instance's secret key and database password."""
        self.assertIn('chmod 600 "$ENV_FILE"', self.script)

    def test_the_workflow_offers_both_directions_and_defaults_to_tailnet(self):
        workflow = (settings.BASE_DIR / ".github" / "workflows"
                    / "regitra-staging-public.yml").read_text()
        self.assertIn('options: ["tailnet", "public"]', workflow)
        self.assertIn('default: "tailnet"', workflow)
        self.assertIn("sanitize_staging", workflow)


class DuplicateScanTests(TestCase):
    """The review list is built in the background; the save-time check uses indexes."""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("dublikatai", password="very-secure-password")
        self.client.force_login(self.admin)

    def _pair(self, **fields):
        first = Person.objects.create(first_name="Ona", last_name="Onaitė", **fields)
        second = Person.objects.create(first_name="Ona", last_name="Onaitė", **fields)
        return first, second

    def test_matching_ignores_case_spaces_and_phone_formatting(self):
        person = Person.objects.create(first_name="Rūta", last_name="Žukaitė")
        EmailAddress.objects.create(person=person, email="Ruta.Z@Example.LT")
        PhoneNumber.objects.create(person=person, number="+370 (645) 21-987")
        data = {"first_name": " rūta ", "last_name": "ŽUKAITĖ", "email": "ruta.z@example.lt ",
                "phone": "37064521987", "companies": []}
        [match] = find_person_duplicates(data)
        self.assertEqual((match["record"], match["reasons"]), (person, ["name", "email", "phone"]))
        company = Company.objects.create(name="UAB Pavyzdys", phone="+370 5 212 3456")
        [match] = find_company_duplicates({"name": "uab pavyzdys ", "phone": "852123456 ", "email": "",
                                           "vat_code": "", "company_code": ""})
        self.assertEqual((match["record"], match["reasons"]), (company, ["name"]))
        [match] = find_company_duplicates({"name": "", "phone": "(370) 5 212 3456", "email": "",
                                           "vat_code": "", "company_code": ""})
        self.assertEqual(match["reasons"], ["phone"])

    def test_phone_digits_follow_every_save(self):
        company = Company.objects.create(name="Skaitmenys", phone="+370 600 00001")
        self.assertEqual(company.phone_digits, "37060000001")
        company.phone = "8 600 00002"
        company.save(update_fields=["phone"])
        company.refresh_from_db()
        self.assertEqual(company.phone_digits, "860000002")
        phone = PhoneNumber.objects.create(person=Person.objects.create(first_name="A", last_name="B"), number="+370 1")
        phone.number = "+370 600 12345"
        phone.save(update_fields=["number"])
        phone.refresh_from_db()
        self.assertEqual(phone.digits, "37060012345")

    def test_the_list_only_reads_what_the_background_scan_found(self):
        from django.core.management import call_command
        from contacts.models import JobHeartbeat

        first, second = self._pair()
        page = self.client.get(reverse("contacts:duplicate-list"))
        self.assertNotContains(page, second.get_absolute_url())
        self.assertContains(page, "Pirmasis patikrinimas dar neatliktas")
        call_command("find_duplicates", stdout=StringIO())
        self.assertTrue(JobHeartbeat.objects.get(name="find_duplicates").last_success_at)
        page = self.client.get(reverse("contacts:duplicate-list"))
        self.assertContains(page, second.get_absolute_url())
        self.assertContains(page, "Paskutinį kartą patikrinta")

    def test_a_rescan_drops_pairs_that_no_longer_match(self):
        from contacts.models import DuplicateCandidate

        first, second = self._pair()
        self.assertEqual(scan_duplicates()["person"]["added"], 1)
        second.last_name = "Kitokia"
        second.save()
        self.assertEqual(scan_duplicates()["person"]["removed"], 1)
        self.assertFalse(DuplicateCandidate.objects.exists())

    def test_a_value_shared_by_too_many_records_is_not_a_pair(self):
        from contacts import duplicates

        for index in range(3):
            person = Person.objects.create(first_name="Centras", last_name="Nr%d" % index)
            PhoneNumber.objects.create(person=person, number="+370 5 200 0000")
        with patch.object(duplicates, "MAX_GROUP", 2):
            summary = scan_duplicates()
        self.assertEqual((summary["person"]["pairs"], summary["person"]["skipped_groups"]), (0, 1))
        self.assertEqual(scan_duplicates()["person"]["pairs"], 3)

    def test_merging_removes_the_pair_at_once(self):
        from contacts.models import DuplicateCandidate

        first, second = self._pair()
        scan_duplicates()
        response = self.client.post(reverse("contacts:duplicate-merge", args=["person", second.pk, first.pk]))
        self.assertRedirects(response, first.get_absolute_url())
        self.assertFalse(DuplicateCandidate.objects.exists())

    def test_merge_rejects_a_pair_the_rule_no_longer_matches(self):
        first = Person.objects.create(first_name="Ona", last_name="Onaitė")
        other = Person.objects.create(first_name="Kita", last_name="Asmenybė")
        response = self.client.post(reverse("contacts:duplicate-merge", args=["person", other.pk, first.pk]))
        self.assertEqual(response.status_code, 400)

    def test_a_restricted_user_sees_only_pairs_of_their_own_records(self):
        member = get_user_model().objects.create_user("savi", password="very-secure-password")
        UserProfile.objects.create(user=member, role=UserProfile.ROLE_RESTRICTED,
                                   record_visibility=UserProfile.VISIBILITY_OWN)
        mine = self._pair(owner=member)
        theirs = self._pair(owner=self.admin)
        scan_duplicates()
        self.client.force_login(member)
        page = self.client.get(reverse("contacts:duplicate-list"))
        self.assertContains(page, mine[1].get_absolute_url())
        self.assertNotContains(page, theirs[1].get_absolute_url())

    def test_merge_all_works_in_batches(self):
        from contacts import views

        self._pair()
        Person.objects.create(first_name="Jonas", last_name="Jonaitis")
        Person.objects.create(first_name="Jonas", last_name="Jonaitis")
        scan_duplicates()
        with patch.object(views, "MERGE_ALL_BATCH", 1):
            response = self.client.post(reverse("contacts:duplicate-merge-all"), follow=True)
        self.assertContains(response, "Sujungta dublikatų porų: 1")
        self.assertContains(response, "Liko daugiau porų")
        self.client.post(reverse("contacts:duplicate-merge-all"))
        self.assertEqual(Person.objects.filter(deleted_at__isnull=True).count(), 2)

    def test_merge_all_skips_a_pair_that_changed_since_the_scan(self):
        first, second = self._pair()
        scan_duplicates()
        second.last_name = "Pasikeitė"
        second.save()
        response = self.client.post(reverse("contacts:duplicate-merge-all"), follow=True)
        self.assertContains(response, "Sujungiamų dublikatų nerasta")
        second.refresh_from_db()
        self.assertIsNone(second.deleted_at)

    def test_worker_and_kubernetes_run_the_scan(self):
        self.assertIn("manage.py find_duplicates", (settings.BASE_DIR / "compose.yaml").read_text())
        self.assertIn("command: find_duplicates", (settings.BASE_DIR / "deploy/helm/crm/values.yaml").read_text())


class LargeVolumeSearchTests(TestCase):
    """Search and pickers that stay fast with hundreds of thousands of records."""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("paieska", password="very-secure-password")
        self.client.force_login(self.admin)

    def test_search_reaches_related_tables_and_lists_each_contact_once(self):
        person = Person.objects.create(first_name="Ieva", last_name="Paieškaitė")
        EmailAddress.objects.create(person=person, email="ieva@ryšys.lt")
        EmailAddress.objects.create(person=person, email="ieva.ryšys@example.lt")
        PhoneNumber.objects.create(person=person, number="+370 699 12345")
        tag = Tag.objects.create(name="Žymėtas")
        person.tags.add(tag)
        company = Company.objects.create(name="Ryšio UAB")
        PersonCompanyLink.objects.create(person=person, company=company)
        Person.objects.create(first_name="Kitas", last_name="Nesusijęs")
        for term in ("ryšys", "699 123", "Žymėt", "Ryšio UAB", "Paieškaitė"):
            page = self.client.get(reverse("contacts:list"), {"q": term}).context["page"]
            self.assertEqual([p.pk for p in page.object_list], [person.pk], term)
        companies = self.client.get(reverse("contacts:company-list"), {"q": "Paieškaitė"}).context["page"]
        self.assertEqual([c.pk for c in companies.object_list], [company.pk])

    def test_company_lookup_finds_visible_companies_by_name_or_code(self):
        member = get_user_model().objects.create_user("ieskotojas", password="very-secure-password")
        UserProfile.objects.create(user=member, role=UserProfile.ROLE_RESTRICTED,
                                   record_visibility=UserProfile.VISIBILITY_OWN)
        mine = Company.objects.create(name="Mano Paieška UAB", company_code="301234567", owner=member)
        Company.objects.create(name="Svetima Paieška UAB", owner=self.admin)
        url = reverse("contacts:company-lookup")
        self.assertEqual(self.client.get(url, {"q": "p"}).json(), {"results": []})
        self.assertEqual(len(self.client.get(url, {"q": "paieška"}).json()["results"]), 2)
        self.client.force_login(member)
        self.assertEqual(self.client.get(url, {"q": "paieška"}).json()["results"], [{"id": mine.pk, "name": mine.name}])
        self.assertEqual(self.client.get(url, {"q": "3012345"}).json()["results"][0]["id"], mine.pk)

    def test_pickers_carry_only_the_chosen_companies(self):
        chosen = Company.objects.create(name="Pasirinkta UAB")
        Company.objects.create(name="Nepasirinkta UAB")
        form = self.client.get(reverse("contacts:person-create"))
        self.assertContains(form, "company-search")
        self.assertNotContains(form, "Nepasirinkta UAB")
        person = Person.objects.create(first_name="Su", last_name="Įmone")
        PersonCompanyLink.objects.create(person=person, company=chosen)
        card = self.client.get(person.get_absolute_url())
        self.assertContains(card, 'value="%d" checked' % chosen.pk)
        self.assertNotContains(card, "Nepasirinkta UAB")
        edit = self.client.get(reverse("contacts:edit", args=[person.pk]))
        self.assertContains(edit, "Pasirinkta UAB")
        self.assertNotContains(edit, "Nepasirinkta UAB")
        # A company picked through the search box is saved like any other choice.
        other = Company.objects.get(name="Nepasirinkta UAB")
        self.client.post(reverse("contacts:person-create"), {"first_name": "Naujas", "last_name": "Asmuo",
                                                            "companies": [other.pk]})
        self.assertEqual(list(Person.objects.get(last_name="Asmuo").companies.all()), [other])

    def test_a_rejected_form_does_not_echo_a_hidden_company(self):
        member = get_user_model().objects.create_user("slepiamas", password="very-secure-password")
        UserProfile.objects.create(user=member, role=UserProfile.ROLE_RESTRICTED,
                                   record_visibility=UserProfile.VISIBILITY_OWN)
        hidden = Company.objects.create(name="Paslėpta UAB", owner=self.admin)
        self.client.force_login(member)
        response = self.client.post(reverse("contacts:person-create"), {"first_name": "", "companies": [hidden.pk]})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Paslėpta UAB")

    def test_visible_activities_follow_record_visibility(self):
        from contacts.permissions import visible_activities

        member = get_user_model().objects.create_user("veiklos", password="very-secure-password")
        UserProfile.objects.create(user=member, role=UserProfile.ROLE_RESTRICTED,
                                   record_visibility=UserProfile.VISIBILITY_OWN)
        own = Person.objects.create(first_name="Savas", last_name="Asmuo", owner=member)
        other = Person.objects.create(first_name="Kito", last_name="Asmuo", owner=self.admin)
        gone = Person.objects.create(first_name="Archyvuotas", last_name="Asmuo", owner=member,
                                     deleted_at=timezone.now())
        firm = Company.objects.create(name="Sava UAB", owner=member)
        mine = [Activity.objects.create(person=own, text="a", created_by=member),
                Activity.objects.create(company=firm, text="b", created_by=member)]
        Activity.objects.create(person=other, text="c", created_by=self.admin)
        Activity.objects.create(person=gone, text="d", created_by=member)
        self.assertEqual(set(visible_activities(member, Activity.objects.all())), set(mine))
        self.assertEqual(visible_activities(self.admin, Activity.objects.all()).count(), 3)


class AnalyticsSnapshotTests(TestCase):
    """Heavy analytics numbers are stored and reused instead of recounted per view."""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("skaiciai", password="very-secure-password")
        self.client.force_login(self.admin)
        self.person = Person.objects.create(first_name="Skaičių", last_name="Asmuo")

    def _activity(self, days_ago=0, person=None):
        activity = Activity.objects.create(person=person or self.person, text="x", created_by=self.admin)
        Activity.objects.filter(pk=activity.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
        return activity

    def test_a_fresh_snapshot_is_reused_and_a_stale_one_recounted(self):
        from contacts.models import AnalyticsSnapshot

        self._activity()
        first = self.client.get(reverse("contacts:analytics-overview"))
        self.assertEqual(first.context["kpis"]["activity_total"], 1)
        self.assertContains(first, "Veiklų skaičiai suskaičiuoti")
        self._activity()
        self.assertEqual(self.client.get(reverse("contacts:analytics-overview")).context["kpis"]["activity_total"], 1)
        AnalyticsSnapshot.objects.update(computed_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(self.client.get(reverse("contacts:analytics-overview")).context["kpis"]["activity_total"], 2)

    def test_restricted_users_get_their_own_numbers(self):
        from contacts.models import AnalyticsSnapshot

        member = get_user_model().objects.create_user("savi-skaiciai", password="very-secure-password")
        UserProfile.objects.create(user=member, role=UserProfile.ROLE_RESTRICTED,
                                   record_visibility=UserProfile.VISIBILITY_OWN)
        own = Person.objects.create(first_name="Savas", last_name="Kontaktas", owner=member)
        Person.objects.filter(pk=self.person.pk).update(owner=self.admin)
        self._activity(person=own)
        self._activity()
        self.client.get(reverse("contacts:analytics-communication"))
        self.client.force_login(member)
        page = self.client.get(reverse("contacts:analytics-communication"))
        self.assertEqual(page.context["total"], 1)
        self.assertEqual([row["label"] for row in page.context["top_people"]], [str(own)])
        self.assertEqual(set(AnalyticsSnapshot.objects.values_list("key", flat=True)),
                         {"communication:90:all", "communication:90:user-%d" % member.pk})

    def test_average_gap_and_top_people_are_counted_by_the_database(self):
        self._activity(days_ago=10)
        self._activity(days_ago=6)
        self._activity(days_ago=2)
        page = self.client.get(reverse("contacts:analytics-communication"))
        self.assertEqual(page.context["average_gap"], 4.0)
        self.assertEqual(page.context["top_people"][0]["total"], 3)
        self.assertEqual(page.context["total"], 3)

    def test_refresh_command_updates_the_shared_numbers_only_when_old(self):
        from django.core.management import call_command
        from contacts.models import AnalyticsSnapshot

        out = StringIO()
        call_command("refresh_analytics", stdout=out)
        self.assertIn("refreshed=overview,communication", out.getvalue())
        call_command("refresh_analytics", stdout=out)
        self.assertIn("refreshed=-", out.getvalue())
        AnalyticsSnapshot.objects.create(key="overview:30:user-99", payload={},
                                         computed_at=timezone.now() - timedelta(days=2))
        call_command("refresh_analytics", stdout=out)
        self.assertIn("dropped=1", out.getvalue())

    def test_care_lists_use_exists_and_keep_their_meaning(self):
        from contacts.analytics_views import _care_querysets

        silent = Person.objects.create(first_name="Nutilęs", last_name="A", owner=self.admin)
        self._activity(days_ago=100, person=silent)
        recent = Person.objects.create(first_name="Neseniai", last_name="B", owner=self.admin)
        self._activity(days_ago=1, person=recent)
        PhoneNumber.objects.create(person=recent, number="+37060000000")
        lists = _care_querysets(self.admin, 60)
        self.assertEqual(list(lists["silent"]), [silent])
        self.assertEqual(lists["silent"][0].last_contact_at.date(), (timezone.now() - timedelta(days=100)).date())
        self.assertEqual(set(lists["never"]), {self.person})
        self.assertEqual(set(lists["no_owner"]), {self.person})
        self.assertEqual(set(lists["no_details"]), {self.person, silent})

    def test_a_snapshot_that_cannot_be_stored_still_shows_the_numbers(self):
        from django.db import OperationalError
        from contacts.models import AnalyticsSnapshot

        self._activity()
        with patch.object(AnalyticsSnapshot.objects, "update_or_create", side_effect=OperationalError("locked")), \
                self.assertLogs("contacts.analytics_views", "WARNING"):
            page = self.client.get(reverse("contacts:analytics-overview"))
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["kpis"]["activity_total"], 1)

    def test_worker_and_kubernetes_run_the_refresh(self):
        self.assertIn("manage.py refresh_analytics", (settings.BASE_DIR / "compose.yaml").read_text())
        self.assertIn("command: refresh_analytics", (settings.BASE_DIR / "deploy/helm/crm/values.yaml").read_text())


class CardFeedPagingTests(TestCase):
    """A long history is shown newest first, a page at a time."""

    def setUp(self):
        from contacts import views

        self.admin = get_user_model().objects.create_superuser("istorija", password="very-secure-password")
        self.client.force_login(self.admin)
        self.person = Person.objects.create(first_name="Ilga", last_name="Istorija")
        patcher = patch.object(views, "FEED_PAGE", 3)
        patcher.start()
        self.addCleanup(patcher.stop)
        for index in range(7):
            activity = Activity.objects.create(person=self.person, text="Įrašas %d" % index, created_by=self.admin,
                                               activity_type="note" if index % 2 else "call")
            Activity.objects.filter(pk=activity.pk).update(created_at=timezone.now() - timedelta(days=7 - index))

    def test_the_card_shows_the_newest_page_and_the_full_counts(self):
        page = self.client.get(self.person.get_absolute_url())
        self.assertEqual([a.text for a in page.context["all_entries"]], ["Įrašas 6", "Įrašas 5", "Įrašas 4"])
        self.assertEqual(page.context["feed_totals"], {"all": 7, "comments": 3, "files": 0})
        self.assertContains(page, 'href="?all=6#feed-all"')
        self.assertContains(page, "Rodyti senesnius (liko 4)")
        self.assertEqual(page.context["last_activity"].text, "Įrašas 6")
        self.assertIsNone(page.context["feed_more"]["comments"])

    def test_show_older_adds_a_page_and_stops_at_the_end(self):
        page = self.client.get(self.person.get_absolute_url(), {"all": "6"})
        self.assertEqual(len(page.context["all_entries"]), 6)
        page = self.client.get(self.person.get_absolute_url(), {"all": "9"})
        self.assertEqual(len(page.context["all_entries"]), 7)
        self.assertIsNone(page.context["feed_more"]["all"])
        self.assertEqual(len(self.client.get(self.person.get_absolute_url(), {"all": "x"}).context["all_entries"]), 3)

    def test_the_company_card_pages_its_history_too(self):
        company = Company.objects.create(name="Istorijos UAB")
        PersonCompanyLink.objects.create(person=self.person, company=company)
        page = self.client.get(company.get_absolute_url())
        self.assertEqual(page.context["feed_totals"]["all"], 7)
        self.assertEqual(len(page.context["all_entries"]), 3)


class PersonIdentityTests(TestCase):
    """Personal code: found by keyed hash, shown masked, revealed only with the right, never logged."""

    CODE = "38703181745"

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("tapatybe", password="very-secure-password")
        self.member = get_user_model().objects.create_user("operatorius", password="very-secure-password")
        UserProfile.objects.create(user=self.member, role=UserProfile.ROLE_MEMBER)
        self.person = Person.objects.create(first_name="Jonas", last_name="Kodas")

    def _with_code(self, person=None, code=None):
        from contacts import identity

        person = person or self.person
        identity.assign(person, identity.LT, code or self.CODE)
        person.save()
        return person

    def test_codes_are_validated_normalised_and_date_the_birth(self):
        from contacts import identity

        self.assertEqual(identity.normalize(identity.LT, " 3870318 1745 "), self.CODE)
        for bad in ("38703181746", "3870318174", "abc"):
            with self.assertRaises(ValidationError):
                identity.normalize(identity.LT, bad)
        self.assertEqual(identity.normalize(identity.OTHER, "ab 123 45"), "AB12345")
        self.assertIsNone(identity.birth_date("50502291232"))  # 29 February 2005 does not exist
        self.assertEqual(identity.birth_date("49001011238").isoformat(), "1990-01-01")
        person = self._with_code()
        self.assertEqual(person.birth_date.isoformat(), "1987-03-18")

    def test_the_code_is_stored_encrypted_and_hashed_never_plain(self):
        from contacts import identity

        person = self._with_code()
        row = Person.objects.filter(pk=person.pk).values().get()
        self.assertNotIn(self.CODE, json.dumps(row, default=str))
        self.assertEqual(identity.reveal(person), self.CODE)
        self.assertEqual(identity.masked(person), "3•••••••745")
        self.assertEqual(len(person.personal_code_hash), 64)

    def test_search_finds_a_person_by_code_or_external_id(self):
        self._with_code()
        Person.objects.filter(pk=self.person.pk).update(external_source="regitra", external_id="R77")
        self.client.force_login(self.member)
        for term in (self.CODE, "R77"):
            page = self.client.get(reverse("contacts:list"), {"q": term}).context["page"]
            self.assertEqual([p.pk for p in page.object_list], [self.person.pk], term)
        suggest = self.client.get(reverse("contacts:search-suggest"), {"q": self.CODE}).json()
        self.assertEqual(suggest["groups"][0]["items"][0]["label"], str(self.person))

    def test_the_card_masks_the_code_and_only_the_right_reveals_it_with_an_audit_row(self):
        from contacts.models import AuditLog

        self._with_code()
        self.client.force_login(self.member)
        card = self.client.get(self.person.get_absolute_url())
        self.assertContains(card, "3•••••••745")
        self.assertNotContains(card, self.CODE)
        url = reverse("contacts:personal-code-reveal", args=[self.person.pk])
        self.assertNotContains(card, url)
        self.assertEqual(self.client.post(url).status_code, 404)
        RolePermissions.objects.update_or_create(role=UserProfile.ROLE_MEMBER,
                                                 defaults={"permissions": {"can_view_personal_code": True}})
        self.assertContains(self.client.get(self.person.get_absolute_url()), url)
        self.assertEqual(self.client.post(url).json(), {"value": self.CODE})
        entry = AuditLog.objects.filter(action=AuditLog.VIEW, field="personal_code").get()
        self.assertEqual(entry.actor, self.member)
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_a_reader_granted_the_right_can_reveal(self):
        self._with_code()
        reader = get_user_model().objects.create_user("skaitytojas-kodas", password="very-secure-password")
        UserProfile.objects.create(user=reader, role=UserProfile.ROLE_READONLY)
        RolePermissions.objects.update_or_create(role=UserProfile.ROLE_READONLY,
                                                 defaults={"permissions": {"can_view_personal_code": True}})
        self.client.force_login(reader)
        url = reverse("contacts:personal-code-reveal", args=[self.person.pk])
        self.assertEqual(self.client.post(url).json(), {"value": self.CODE})

    def test_the_form_sets_the_code_write_only_and_the_audit_trail_never_holds_it(self):
        from contacts.models import AuditLog

        self.client.force_login(self.admin)
        edit = reverse("contacts:edit", args=[self.person.pk])
        response = self.client.post(edit, {"first_name": "Jonas", "last_name": "Kodas", "personal_code_type": "lt",
                                           "personal_code": "12345678901"})
        self.assertContains(response, "Neteisingas asmens kodas")
        self.client.post(edit, {"first_name": "Jonas", "last_name": "Kodas", "personal_code_type": "lt",
                                "personal_code": self.CODE})
        self.person.refresh_from_db()
        self.assertTrue(self.person.personal_code_hash)
        form = self.client.get(edit)
        self.assertNotContains(form, self.CODE)
        self.assertContains(form, "3•••••••745")
        self.assertFalse(AuditLog.objects.filter(new_value__contains=self.CODE).exists())
        # Without the right the field is not offered at all.
        self.client.force_login(self.member)
        self.assertNotContains(self.client.get(edit), 'name="personal_code"')

    def test_the_same_code_is_a_duplicate_and_merging_keeps_it(self):
        from contacts.merging import merge_people

        self._with_code()
        twin = self._with_code(Person.objects.create(first_name="Kitas", last_name="Vardas"))
        summary = scan_duplicates()
        self.assertEqual(summary["person"]["pairs"], 1)
        from contacts.models import DuplicateCandidate
        self.assertEqual(DuplicateCandidate.objects.get().reasons, "personal_code")
        Person.objects.filter(pk=twin.pk).update(external_source="regitra", external_id="R1")
        Person.objects.filter(pk=self.person.pk).update(personal_code_type="", personal_code_encrypted="",
                                                         personal_code_hash="")
        kept = merge_people(twin.pk, self.person.pk)
        self.assertEqual((kept.personal_code_hash, kept.external_id), (twin.personal_code_hash, "R1"))

    def test_api_lookup_by_code_or_external_id_audits_and_never_returns_the_code(self):
        from contacts.models import AuditLog

        self._with_code()
        Person.objects.filter(pk=self.person.pk).update(external_source="regitra", external_id="R77")
        raw, digest = ApiToken.new()
        ApiToken.objects.create(name="genesys", token_hash=digest, prefix=raw[:12], scope=ApiToken.READ,
                                created_by=self.admin)
        auth = {"HTTP_AUTHORIZATION": "Bearer " + raw}
        url = reverse("api:contacts-lookup")
        post = lambda payload: self.client.post(url, data=json.dumps(payload), content_type="application/json", **auth)  # noqa: E731
        found = post({"personal_code": self.CODE}).json()["results"]
        self.assertEqual([row["id"] for row in found], [self.person.pk])
        self.assertEqual(post({"external_source": "regitra", "external_id": "R77"}).json()["results"][0]["id"],
                         self.person.pk)
        self.assertEqual(post({"personal_code": "49001011238"}).json()["results"], [])
        self.assertEqual(post({"personal_code": "123"}).status_code, 400)
        self.assertEqual(self.client.get(url, **auth).status_code, 405)
        self.assertEqual(AuditLog.objects.filter(action=AuditLog.VIEW, field="API lookup").count(), 2)
        payload = self.client.get(reverse("api:contact", args=[self.person.pk]), **auth).json()
        self.assertTrue(payload["has_personal_code"])
        self.assertNotIn(self.CODE, json.dumps(payload))

    def test_bulk_import_creates_updates_and_reports_without_the_code(self):
        from io import StringIO as Text
        from django.core.management import call_command

        csv_text = ("external_id,first_name,last_name,personal_code,email,phone\n"
                    "R1,Ona,Pirmoji,%s,ona@example.lt,+370 600 00001\n"
                    "R2,Petras,Antrasis,,petras@example.lt,\n"
                    "R3,,,,,\n"
                    "R4,Blogas,Kodas,12345678901,,\n" % self.CODE)
        path = settings.BASE_DIR / "runtime" / "test-import.csv"
        path.parent.mkdir(exist_ok=True)
        path.write_text(csv_text, encoding="utf-8")
        self.addCleanup(path.unlink)
        out, err = Text(), Text()
        call_command("import_people", str(path), "--source", "regitra", stdout=out, stderr=err)
        self.assertIn("created=2 updated=0 unchanged=0 errors=2", out.getvalue())
        self.assertIn("line 4: first_name or last_name is required", err.getvalue())
        self.assertIn("line 5: invalid personal_code", err.getvalue())
        self.assertNotIn("12345678901", err.getvalue())
        ona = Person.objects.get(external_source="regitra", external_id="R1")
        self.assertEqual(ona.birth_date.isoformat(), "1987-03-18")
        self.assertEqual(ona.phones.get().digits, "37060000001")
        call_command("import_people", str(path), "--source", "regitra", stdout=out, stderr=Text())
        self.assertIn("created=0 updated=0 unchanged=2", out.getvalue())
        path.write_text(csv_text.replace("Pirmoji", "Pakeista"), encoding="utf-8")
        call_command("import_people", str(path), "--source", "regitra", stdout=out, stderr=Text())
        self.assertIn("created=0 updated=1 unchanged=1", out.getvalue())
        self.assertEqual(Person.objects.filter(external_id="R1").get().phones.count(), 1)

    def test_a_search_by_code_goes_by_post_and_never_echoes_the_code(self):
        self._with_code()
        self.client.force_login(self.member)
        page = self.client.get(self.person.get_absolute_url())
        self.assertContains(page, 'data-code-search-url="%s"' % reverse("contacts:search-personal-code"))
        url = reverse("contacts:search-personal-code")
        self.assertRedirects(self.client.post(url, {"code": "387 0318 1745"}), self.person.get_absolute_url())
        missing = self.client.post(url, {"code": "49001011238"})
        self.assertContains(missing, "Nieko nerasta")
        self.assertNotContains(missing, "49001011238")
        self.assertContains(missing, "••••••••238")
        self.assertRedirects(self.client.get(url), reverse("contacts:search"))
        suggest = self.client.post(reverse("contacts:search-suggest"), {"q": self.CODE}).json()
        self.assertIsNone(suggest["url"])
        self.assertEqual(suggest["groups"][0]["items"][0]["url"], self.person.get_absolute_url())

    def test_a_reader_may_search_by_code(self):
        self._with_code()
        reader = get_user_model().objects.create_user("skaitytojas-paieska", password="very-secure-password")
        UserProfile.objects.create(user=reader, role=UserProfile.ROLE_READONLY)
        self.client.force_login(reader)
        response = self.client.post(reverse("contacts:search-personal-code"), {"code": self.CODE})
        self.assertRedirects(response, self.person.get_absolute_url())

    def test_the_privacy_page_finds_by_code_sent_by_post(self):
        self._with_code()
        self.client.force_login(self.admin)
        page = self.client.post(reverse("contacts:settings-privacy"), {"q": self.CODE})
        self.assertEqual(list(page.context["people"]), [self.person])

    def test_the_data_subject_export_carries_the_code(self):
        from contacts.privacy import find_people, person_data

        self._with_code()
        self.assertEqual(person_data(self.person)["person"]["personal_code"], self.CODE)
        self.assertEqual(list(find_people(self.CODE)), [self.person])

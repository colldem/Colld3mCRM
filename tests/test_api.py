import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from contacts.models import (
    Activity, ApiToken, AuditLog, Company, Person, PersonCompanyLink, Reminder, UserProfile,
)


class ApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("apiowner", password="very-secure-password", email="a@b.lt")
        self.person = Person.objects.create(first_name="Jonas", last_name="Jonaitis", created_by=self.user, owner=self.user)
        self.company = Company.objects.create(name="UAB Testas", owner=self.user)
        PersonCompanyLink.objects.create(person=self.person, company=self.company, is_primary=True, role="Vadovas")
        self.raw, digest = ApiToken.new()
        self.token = ApiToken.objects.create(name="rw", token_hash=digest, prefix=self.raw[:13],
                                             scope=ApiToken.READ_WRITE, created_by=self.user)
        self.raw_read, digest_r = ApiToken.new()
        ApiToken.objects.create(name="ro", token_hash=digest_r, prefix=self.raw_read[:13],
                                scope=ApiToken.READ, created_by=self.user)

    def _get(self, path, tok=None):
        return self.client.get(path, HTTP_AUTHORIZATION="Bearer " + (tok or self.raw))

    def _send(self, method, path, body, tok=None):
        return getattr(self.client, method)(
            path, data=json.dumps(body), content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + (tok or self.raw))

    def test_missing_or_bad_token_is_401(self):
        self.assertEqual(self.client.get("/api/v1/contacts").status_code, 401)
        self.assertEqual(self._get("/api/v1/contacts", tok="crmk_wrong").status_code, 401)

    def test_list_contacts_is_paginated_with_total_header(self):
        response = self._get("/api/v1/contacts?limit=1")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        row = payload["results"][0]
        self.assertEqual(row["last_name"], "Jonaitis")
        self.assertEqual(row["companies"][0]["name"], "UAB Testas")
        self.assertEqual(row["companies"][0]["role"], "Vadovas")
        self.assertEqual(response["X-Total-Count"], "1")

    def test_read_token_cannot_write(self):
        response = self._send("post", "/api/v1/contacts", {"first_name": "Nauja", "last_name": "Byla"}, tok=self.raw_read)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Person.objects.filter(last_name="Byla").exists())

    def test_create_contact_runs_the_duplicate_check(self):
        clash = self._send("post", "/api/v1/contacts", {"first_name": "Jonas", "last_name": "Jonaitis"})
        self.assertEqual(clash.status_code, 409)
        self.assertIn("matches", clash.json())
        forced = self._send("post", "/api/v1/contacts?force=1",
                            {"first_name": "Jonas", "last_name": "Jonaitis", "emails": ["j@x.lt"], "tags": ["VIP"]})
        self.assertEqual(forced.status_code, 201)
        created = Person.objects.get(pk=forced.json()["id"])
        self.assertEqual(list(created.emails.values_list("email", flat=True)), ["j@x.lt"])
        self.assertIn("VIP", list(created.tags.values_list("name", flat=True)))

    def test_patch_then_archive_a_contact(self):
        patched = self._send("patch", "/api/v1/contacts/%s" % self.person.pk, {"job_title": "CTO"})
        self.assertEqual(patched.status_code, 200)
        self.person.refresh_from_db()
        self.assertEqual(self.person.job_title, "CTO")
        deleted = self.client.delete("/api/v1/contacts/%s" % self.person.pk, HTTP_AUTHORIZATION="Bearer " + self.raw)
        self.assertEqual(deleted.status_code, 200)
        self.person.refresh_from_db()
        self.assertIsNotNone(self.person.deleted_at)

    def test_api_writes_are_audited_with_a_marker(self):
        self._send("post", "/api/v1/contacts?force=1", {"first_name": "Audit", "last_name": "Test"})
        self.assertTrue(AuditLog.objects.filter(detail__via="api", detail__token="rw").exists())

    def test_create_activity_and_reminder_against_a_contact(self):
        act = self._send("post", "/api/v1/activities",
                         {"person_id": self.person.pk, "activity_type": "call", "text": "labas"})
        self.assertEqual(act.status_code, 201)
        self.assertTrue(Activity.objects.filter(person=self.person, text="labas", created_by=self.user).exists())
        rem = self._send("post", "/api/v1/reminders",
                         {"person_id": self.person.pk, "text": "skambutis", "due_at": "2026-12-31T09:00:00Z"})
        self.assertEqual(rem.status_code, 201)
        self.assertTrue(Reminder.objects.filter(person=self.person, text="skambutis").exists())

    def test_visibility_of_the_token_owner_is_enforced(self):
        other = get_user_model().objects.create_user("kitas", password="very-secure-password")
        hidden = Person.objects.create(first_name="Slapta", last_name="Byla", owner=other)
        UserProfile.objects.update_or_create(user=self.user, defaults={"role": UserProfile.ROLE_RESTRICTED})
        self.assertEqual(self._get("/api/v1/contacts/%s" % hidden.pk).status_code, 404)
        self.assertEqual(self._get("/api/v1/contacts").json()["count"], 1)

    def test_revoked_token_is_rejected(self):
        self.token.revoked_at = timezone.now()
        self.token.save(update_fields=["revoked_at"])
        self.assertEqual(self._get("/api/v1/contacts").status_code, 401)

    def test_me_endpoint_reports_scope(self):
        self.assertEqual(self._get("/api/v1/me").json()["scope"], "read_write")

    def test_writes_respect_model_field_lengths(self):
        r = self._send("post", "/api/v1/contacts?force=1",
                       {"first_name": "A" * 250, "last_name": "B", "emails": ["x" * 400 + "@y.lt"]})
        self.assertEqual(r.status_code, 201)
        created = Person.objects.get(pk=r.json()["id"])
        self.assertLessEqual(len(created.first_name), 100)
        self.assertTrue(all(len(e) <= 254 for e in created.emails.values_list("email", flat=True)))

    def test_owner_id_must_be_assignable_to_the_token_owner(self):
        stranger = get_user_model().objects.create_user("nepazistamas", password="very-secure-password")
        UserProfile.objects.update_or_create(user=self.user, defaults={"role": UserProfile.ROLE_RESTRICTED})
        r = self._send("patch", "/api/v1/contacts/%s" % self.person.pk, {"owner_id": stranger.pk})
        self.assertEqual(r.status_code, 200)
        self.person.refresh_from_db()
        self.assertIsNone(self.person.owner)  # not a teammate -> silently dropped

    def test_integrations_page_is_admin_only_and_creates_a_token_once(self):
        self.client.force_login(get_user_model().objects.create_user("plain", password="very-secure-password"))
        self.assertEqual(self.client.get("/settings/integrations/").status_code, 404)
        admin = get_user_model().objects.create_user("boss", password="very-secure-password", is_superuser=True, is_staff=True)
        self.client.force_login(admin)
        response = self.client.post("/settings/integrations/", {"op": "create", "name": "Zapier", "scope": "read"})
        self.assertContains(response, "crmk_")
        self.assertTrue(ApiToken.objects.filter(name="Zapier", scope="read").exists())


class WebhookTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(
            "wadmin", password="very-secure-password", is_superuser=True, is_staff=True)
        self.person = Person.objects.create(first_name="Web", last_name="Hook", owner=self.admin)

    def _hook(self, events=("contact.created", "reminder.completed"), target_url="https://example.test/hook", **kw):
        from contacts.models import Webhook
        return Webhook.objects.create(target_url=target_url, events=list(events), **kw)

    def test_emit_queues_a_delivery_only_for_subscribers(self):
        from contacts.models import WebhookDelivery
        self._hook(events=["contact.created"])
        self._hook(events=["company.created"])
        Person.objects.create(first_name="Naujas", last_name="Zmogus")
        self.assertEqual(WebhookDelivery.objects.filter(event="contact.created").count(), 1)

    def test_archive_and_complete_events_fire(self):
        from contacts.models import WebhookDelivery
        self._hook(events=["contact.archived", "reminder.completed"])
        self.person.deleted_at = timezone.now()
        self.person.save(update_fields=["deleted_at", "updated_at"])
        reminder = Reminder.objects.create(person=self.person, text="x", due_at=timezone.now(), created_by=self.admin)
        self.client.force_login(self.admin)
        self.client.post("/reminders/%s/complete/" % reminder.pk)
        events = set(WebhookDelivery.objects.values_list("event", flat=True))
        self.assertIn("contact.archived", events)
        self.assertIn("reminder.completed", events)

    def test_delivery_succeeds_signs_and_marks_delivered(self):
        from unittest.mock import patch
        from contacts.crypto import encrypt
        from contacts.models import WebhookDelivery
        from contacts.webhooks import deliver_pending
        self._hook(secret=encrypt("s3cr3t"))
        Person.objects.create(first_name="Sign", last_name="Me")
        captured = {}

        class FakeResp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_open(req, timeout=None):
            captured["sig"] = req.headers.get("X-crm-signature")
            captured["event"] = req.headers.get("X-crm-event")
            return FakeResp()

        with patch("contacts.webhooks._OPENER.open", fake_open):
            self.assertEqual(deliver_pending(), 1)
        self.assertTrue(captured["sig"].startswith("sha256="))
        self.assertEqual(captured["event"], "contact.created")
        self.assertIsNotNone(WebhookDelivery.objects.first().delivered_at)

    def test_blocked_loopback_target_is_not_delivered(self):
        from contacts.webhooks import deliver_pending, target_is_allowed
        self.assertFalse(target_is_allowed("http://127.0.0.1:9002/x"))
        self.assertFalse(target_is_allowed("http://169.254.169.254/latest/meta-data/"))
        self._hook(target_url="http://127.0.0.1:9002/x")
        Person.objects.create(first_name="Ssrf", last_name="Try")
        self.assertEqual(deliver_pending(), 0)

    def test_repeated_failure_backs_off_then_auto_disables(self):
        from unittest.mock import patch
        from contacts.models import WebhookDelivery
        from contacts.webhooks import deliver_pending, MAX_ATTEMPTS, AUTO_DISABLE_STREAK
        hook = self._hook()
        Person.objects.create(first_name="Fail", last_name="Case")
        delivery = WebhookDelivery.objects.get()

        def boom(req, timeout=None):
            raise OSError("nope")

        with patch("contacts.webhooks._OPENER.open", boom):
            for _ in range(MAX_ATTEMPTS):
                WebhookDelivery.objects.filter(pk=delivery.pk).update(next_attempt_at=timezone.now())
                deliver_pending()
            delivery.refresh_from_db()
            self.assertTrue(delivery.status.startswith("failed"))
            for _ in range(AUTO_DISABLE_STREAK):
                WebhookDelivery.objects.create(webhook=hook, event="contact.created", payload={},
                                               next_attempt_at=timezone.now(), attempts=MAX_ATTEMPTS - 1)
                deliver_pending()
        hook.refresh_from_db()
        self.assertFalse(hook.active)

    def test_integrations_page_creates_a_webhook_with_a_secret(self):
        from contacts.models import Webhook
        self.client.force_login(self.admin)
        response = self.client.post("/settings/integrations/", {
            "op": "create_webhook", "target_url": "https://hooks.example.test/x",
            "events": ["contact.created", "activity.created"],
        })
        self.assertEqual(response.status_code, 200)
        hook = Webhook.objects.get()
        self.assertEqual(sorted(hook.events), ["activity.created", "contact.created"])
        self.assertTrue(hook.secret.startswith("enc:v1:"))

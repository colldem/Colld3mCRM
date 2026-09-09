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

    def test_integrations_page_is_admin_only_and_creates_a_token_once(self):
        self.client.force_login(get_user_model().objects.create_user("plain", password="very-secure-password"))
        self.assertEqual(self.client.get("/settings/integrations/").status_code, 404)
        admin = get_user_model().objects.create_user("boss", password="very-secure-password", is_superuser=True, is_staff=True)
        self.client.force_login(admin)
        response = self.client.post("/settings/integrations/", {"op": "create", "name": "Zapier", "scope": "read"})
        self.assertContains(response, "crmk_")
        self.assertTrue(ApiToken.objects.filter(name="Zapier", scope="read").exists())

"""CRM load profile: people browsing lists, opening cards, searching, logging activity.

    locust -f scripts/loadtest/locustfile.py --host https://crm-staging.example \
      --headless -u 50 -r 5 -t 3m --csv load

Accounts load00..loadNN come from scripts/loadtest/seed.py. Never point this at
production.
"""
import os
import random
import re

from locust import HttpUser, between, task

USERS = int(os.environ.get("LOAD_USERS", "20"))
PASSWORD = os.environ.get("LOAD_PASSWORD", "load-test-password-123")
CSRF = re.compile(r'name="csrfmiddlewaretoken" value="([^"]+)"')
CARD = re.compile(r'href="/contacts/(\d+)/"')


class CrmUser(HttpUser):
    wait_time = between(1, 4)

    def on_start(self):
        page = self.client.get("/login/", name="/login/")
        token = CSRF.search(page.text).group(1)
        response = self.client.post("/login/", name="/login/ [POST]", allow_redirects=False, data={
            "username": "load%02d" % random.randrange(USERS), "password": PASSWORD, "csrfmiddlewaretoken": token},
            headers={"Referer": self.host + "/login/"})
        if response.status_code != 302:
            response.failure("sign-in failed")
        self.cards = []

    @task(5)
    def contact_list(self):
        page = self.client.get("/contacts/?page=%d" % random.randint(1, 20), name="/contacts/?page=N")
        self.cards = CARD.findall(page.text) or self.cards

    @task(4)
    def contact_card(self):
        if self.cards:
            self.client.get("/contacts/%s/" % random.choice(self.cards), name="/contacts/<id>/")

    @task(3)
    def search(self):
        self.client.get("/search/suggest/?q=Krovinys%03d" % random.randint(0, 499), name="/search/suggest/?q=")

    @task(2)
    def dashboard(self):
        self.client.get("/", name="/ (dashboard)")

    @task(2)
    def company_list(self):
        self.client.get("/companies/?city=Kaunas", name="/companies/?city=")

    @task(1)
    def calendar(self):
        self.client.get("/calendar/", name="/calendar/")

    @task(1)
    def analytics(self):
        self.client.get("/analytics/", name="/analytics/")

    @task(1)
    def log_activity(self):
        if not self.cards:
            return
        card = random.choice(self.cards)
        page = self.client.get("/contacts/%s/" % card, name="/contacts/<id>/")
        match = CSRF.search(page.text)
        token = re.search(r'name="submission_token" value="([^"]+)"', page.text)
        if match:
            self.client.post("/contacts/%s/activities/new/" % card, name="/contacts/<id>/activities/new/ [POST]",
                             data={"csrfmiddlewaretoken": match.group(1), "activity_type": "note",
                                   "text": "Load test note", "submission_token": token.group(1) if token else ""},
                             headers={"Referer": self.host + "/contacts/%s/" % card})

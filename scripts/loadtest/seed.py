"""Seed a realistic volume for the load test (run with manage.py shell).

    python manage.py shell -v 0 < scripts/loadtest/seed.py

Creates LOAD_USERS sign-in accounts and LOAD_PEOPLE contacts (default 20 and
5000) with companies (LOAD_COMPANIES, default a fifth of the people), links,
phones, e-mails, LOAD_ACTIVITIES activities (default three per person) and
reminders. LOAD_DUPLICATES (default 0.01) is the share of people who repeat an
earlier person's name, and the same share again repeats an earlier e-mail, so
the duplicate checks have real work to do. Rows are written in batches, so
800,000 people fit in the memory of a small container. Refuses to run on the
production tier.
"""
import os
import random
import time
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from contacts.models import Activity, Company, EmailAddress, Person, PersonCompanyLink, PhoneNumber, Reminder, Tag

if settings.CRM_ENVIRONMENT == "production" and os.environ.get("LOAD_ALLOW_PRODUCTION") != "yes":
    raise SystemExit("refusing to seed a production-tier database")

random.seed(7)
USERS = int(os.environ.get("LOAD_USERS", "20"))
PEOPLE = int(os.environ.get("LOAD_PEOPLE", "5000"))
COMPANIES = int(os.environ.get("LOAD_COMPANIES", str(PEOPLE // 5)))
ACTIVITIES = int(os.environ.get("LOAD_ACTIVITIES", str(PEOPLE * 3)))
DUPLICATES = float(os.environ.get("LOAD_DUPLICATES", "0.01"))
PASSWORD = os.environ.get("LOAD_PASSWORD", "load-test-password-123")
BATCH = 10000
FIRST_NAMES = ["Jonas", "Ona", "Petras", "Rūta", "Tomas", "Eglė"]
started = time.monotonic()
User = get_user_model()
users = []
for index in range(USERS):
    user, created = User.objects.get_or_create(username="load%02d" % index, defaults={"is_staff": index == 0})
    if created:
        user.set_password(PASSWORD)
        user.save()
    users.append(user)
tags = [Tag.objects.get_or_create(name="Load %d" % i)[0] for i in range(10)]
now = timezone.now()
company_ids = []
for start in range(0, COMPANIES, BATCH):
    company_ids += [company.pk for company in Company.objects.bulk_create([
        Company(name="Load company %05d" % i, city=random.choice(["Vilnius", "Kaunas", "Klaipėda"]),
                company_code=str(300000000 + i), owner=random.choice(users), created_by=users[0])
        for i in range(start, min(start + BATCH, COMPANIES))])]
TagLink = Person.tags.through
created_people = 0
for start in range(0, PEOPLE, BATCH):
    with transaction.atomic():
        size = min(BATCH, PEOPLE - start)
        names = []
        for i in range(start, start + size):
            if i > 0 and random.random() < DUPLICATES:
                names.append(names[-1] if names else (FIRST_NAMES[0], "Krovinys%05d" % random.randrange(i)))
            else:
                names.append((random.choice(FIRST_NAMES), "Krovinys%05d" % i))
        people = Person.objects.bulk_create([
            Person(first_name=first, last_name=last, job_title="Vadybininkas", owner=random.choice(users), created_by=users[0])
            for first, last in names])
        if company_ids:
            PersonCompanyLink.objects.bulk_create([PersonCompanyLink(person=p, company_id=random.choice(company_ids)) for p in people])
        PhoneNumber.objects.bulk_create([PhoneNumber(person=p, number="+3706%07d" % p.pk) for p in people])
        EmailAddress.objects.bulk_create([EmailAddress(
            person=p, email="load%d@example.invalid" % (random.randrange(1, p.pk) if p.pk > 1 and random.random() < DUPLICATES else p.pk))
            for p in people])
        share = ACTIVITIES * size // PEOPLE
        Activity.objects.bulk_create([
            Activity(person=random.choice(people), text="Load activity %d" % (start * 3 + i), created_by=random.choice(users))
            for i in range(share)], batch_size=BATCH)
        Reminder.objects.bulk_create([
            Reminder(person=random.choice(people), text="Load reminder %d" % (start + i),
                     due_at=now + timedelta(days=random.randint(-10, 30)), created_by=random.choice(users),
                     assigned_to=random.choice(users))
            for i in range(size // 2)])
        TagLink.objects.bulk_create([TagLink(person_id=p.pk, tag_id=random.choice(tags).pk) for p in people[::10]])
    created_people += size
    if PEOPLE > BATCH:
        print("  %d / %d people (%.0f s)" % (created_people, PEOPLE, time.monotonic() - started), flush=True)
print("seeded: %d users, %d people, %d companies, %d activities in %.0f s"
      % (len(users), created_people, len(company_ids), ACTIVITIES, time.monotonic() - started))

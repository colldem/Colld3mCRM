"""Seed a realistic volume for the load test (run with manage.py shell).

    python manage.py shell -v 0 < scripts/loadtest/seed.py

Creates LOAD_USERS sign-in accounts and LOAD_PEOPLE contacts (default 20 and
5000) with companies, links, phones, e-mails, activities and reminders.
Refuses to run on the production tier.
"""
import os
import random
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from contacts.models import Activity, Company, EmailAddress, Person, PersonCompanyLink, PhoneNumber, Reminder, Tag

if settings.CRM_ENVIRONMENT == "production" and os.environ.get("LOAD_ALLOW_PRODUCTION") != "yes":
    raise SystemExit("refusing to seed a production-tier database")

random.seed(7)
USERS = int(os.environ.get("LOAD_USERS", "20"))
PEOPLE = int(os.environ.get("LOAD_PEOPLE", "5000"))
PASSWORD = os.environ.get("LOAD_PASSWORD", "load-test-password-123")
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
companies = Company.objects.bulk_create([
    Company(name="Load company %05d" % i, city=random.choice(["Vilnius", "Kaunas", "Klaipėda"]),
            company_code=str(300000000 + i), owner=random.choice(users), created_by=users[0])
    for i in range(PEOPLE // 5)])
people = Person.objects.bulk_create([
    Person(first_name=random.choice(["Jonas", "Ona", "Petras", "Rūta", "Tomas", "Eglė"]),
           last_name="Krovinys%05d" % i, job_title="Vadybininkas", owner=random.choice(users), created_by=users[0])
    for i in range(PEOPLE)])
PersonCompanyLink.objects.bulk_create([PersonCompanyLink(person=p, company=random.choice(companies)) for p in people])
PhoneNumber.objects.bulk_create([PhoneNumber(person=p, number="+3706%07d" % p.pk) for p in people])
EmailAddress.objects.bulk_create([EmailAddress(person=p, email="load%d@example.invalid" % p.pk) for p in people])
Activity.objects.bulk_create([
    Activity(person=random.choice(people), text="Load activity %d" % i, created_by=random.choice(users))
    for i in range(PEOPLE * 3)])
Reminder.objects.bulk_create([
    Reminder(person=random.choice(people), text="Load reminder %d" % i,
             due_at=now + timedelta(days=random.randint(-10, 30)), created_by=random.choice(users),
             assigned_to=random.choice(users))
    for i in range(PEOPLE // 2)])
for person in people[::10]:
    person.tags.add(random.choice(tags))
print("seeded: %d users, %d people, %d companies" % (len(users), len(people), len(companies)))

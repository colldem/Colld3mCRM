import re
from collections import defaultdict
from itertools import combinations

from .models import Person


def _lines(value):
    return {item.strip().casefold() for item in (value or "").splitlines() if item.strip()}


def _phones(value):
    return {re.sub(r"\D", "", item) for item in (value or "").splitlines() if len(re.sub(r"\D", "", item)) >= 6}


def find_person_duplicates(data, *, exclude_pk=None, level="standard"):
    emails = _lines(data.get("email", ""))
    phones = _phones(data.get("phone", ""))
    first_name = (data.get("first_name") or "").strip().casefold()
    last_name = (data.get("last_name") or "").strip().casefold()
    company_ids = {item.pk for item in data.get("companies", [])}
    people = Person.objects.filter(deleted_at__isnull=True).prefetch_related("emails", "phones", "companies")
    if exclude_pk:
        people = people.exclude(pk=exclude_pk)
    matches = []
    for person in people:
        person_emails = {item.email.strip().casefold() for item in person.emails.all()}
        person_phones = {re.sub(r"\D", "", item.number) for item in person.phones.all()}
        same_email = bool(emails & person_emails)
        same_phone = bool(phones & person_phones)
        same_name = bool(first_name and last_name and first_name == person.first_name.strip().casefold() and last_name == person.last_name.strip().casefold())
        same_company = bool(company_ids & {item.pk for item in person.companies.all()})
        matched = same_email or same_phone
        if level == "standard":
            matched = matched or (same_name and same_company)
        elif level == "loose":
            matched = matched or same_name
        if matched:
            reasons = []
            if same_email:
                reasons.append("email")
            if same_phone:
                reasons.append("phone")
            if same_name:
                reasons.append("name")
            if same_company:
                reasons.append("company")
            matches.append({"person": person, "reasons": reasons})
    return matches


def all_person_duplicate_pairs(level="standard"):
    people = list(Person.objects.filter(deleted_at__isnull=True).prefetch_related("emails", "phones", "companies"))
    groups = defaultdict(list)
    for person in people:
        for email in {item.email.strip().casefold() for item in person.emails.all() if item.email.strip()}:
            groups[("email", email)].append(person)
        for phone in {re.sub(r"\D", "", item.number) for item in person.phones.all()}:
            if len(phone) >= 6:
                groups[("phone", phone)].append(person)
        name = (person.first_name.strip().casefold(), person.last_name.strip().casefold())
        if all(name):
            if level == "loose":
                groups[("name", *name)].append(person)
            elif level == "standard":
                for company in person.companies.all():
                    groups[("name_company", *name, company.pk)].append(person)
    pair_reasons = defaultdict(set)
    people_by_id = {person.pk: person for person in people}
    for key, members in groups.items():
        reason = key[0]
        for left, right in combinations({person.pk for person in members}, 2):
            pair = tuple(sorted((left, right)))
            if reason == "name_company":
                pair_reasons[pair].update(("name", "company"))
            else:
                pair_reasons[pair].add(reason)
    reason_order = ("email", "phone", "name", "company")
    return [
        {"left": people_by_id[left], "right": people_by_id[right], "reasons": [reason for reason in reason_order if reason in reasons]}
        for (left, right), reasons in sorted(pair_reasons.items())
    ]

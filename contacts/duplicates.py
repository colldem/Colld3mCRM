import re
from collections import defaultdict
from itertools import combinations

from .models import Company, Person


def _lines(value):
    return {item.strip().casefold() for item in (value or "").splitlines() if item.strip()}


def _phones(value):
    return {re.sub(r"\D", "", item) for item in (value or "").splitlines() if len(re.sub(r"\D", "", item)) >= 6}


def find_person_duplicates(data, *, exclude_pk=None, level="standard", viewer=None):
    emails = _lines(data.get("email", ""))
    phones = _phones(data.get("phone", ""))
    first_name = (data.get("first_name") or "").strip().casefold()
    last_name = (data.get("last_name") or "").strip().casefold()
    company_ids = {item.pk for item in data.get("companies", [])}
    people = Person.objects.filter(deleted_at__isnull=True).prefetch_related("emails", "phones", "companies")
    if viewer is not None:
        from .permissions import visible_people

        people = visible_people(viewer, people)
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
        # An exact full-name match is always worth reviewing. It remains a
        # candidate only, so the user still decides whether the records merge.
        matched = same_email or same_phone or same_name
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
            matches.append({"record": person, "reasons": reasons})
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
            groups[("name", *name)].append(person)
            if level == "standard":
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
        {"left": people_by_id[left], "right": people_by_id[right], "reasons": [reason for reason in reason_order if reason in reasons], "kind": "person"}
        for (left, right), reasons in sorted(pair_reasons.items())
    ]


def _company_signals(data, company):
    normalized_phone = re.sub(r"\D", "", data.get("phone") or "")
    company_phone = re.sub(r"\D", "", company.phone or "")
    return {
        "company_code": bool(data.get("company_code") and data["company_code"].strip().casefold() == company.company_code.strip().casefold()),
        "vat_code": bool(data.get("vat_code") and data["vat_code"].strip().casefold() == company.vat_code.strip().casefold()),
        "email": bool(data.get("email") and data["email"].strip().casefold() == company.email.strip().casefold()),
        "phone": bool(len(normalized_phone) >= 6 and normalized_phone == company_phone),
        "url": bool(data.get("url") and data["url"].strip().rstrip("/").casefold() == company.url.strip().rstrip("/").casefold()),
        "name": bool(data.get("name") and data["name"].strip().casefold() == company.name.strip().casefold()),
    }


def find_company_duplicates(data, *, exclude_pk=None, level="standard", viewer=None):
    companies = Company.objects.filter(deleted_at__isnull=True)
    if viewer is not None:
        from .permissions import visible_companies

        companies = visible_companies(viewer, companies)
    if exclude_pk:
        companies = companies.exclude(pk=exclude_pk)
    matches = []
    for company in companies:
        signals = _company_signals(data, company)
        matched = signals["company_code"] or signals["vat_code"] or signals["email"]
        if level in {"standard", "loose"}:
            matched = matched or signals["phone"] or signals["url"]
        if level == "loose":
            matched = matched or signals["name"]
        if matched:
            matches.append({"record": company, "reasons": [reason for reason, value in signals.items() if value]})
    return matches


def all_company_duplicate_pairs(level="standard"):
    companies = list(Company.objects.filter(deleted_at__isnull=True))
    groups = defaultdict(list)
    for company in companies:
        values = {
            "company_code": company.company_code.strip().casefold(),
            "vat_code": company.vat_code.strip().casefold(),
            "email": company.email.strip().casefold(),
        }
        if level in {"standard", "loose"}:
            values["phone"] = re.sub(r"\D", "", company.phone or "")
            values["url"] = company.url.strip().rstrip("/").casefold()
        if level == "loose":
            values["name"] = company.name.strip().casefold()
        for reason, value in values.items():
            if value and (reason != "phone" or len(value) >= 6):
                groups[(reason, value)].append(company)
    pair_reasons = defaultdict(set)
    company_by_id = {company.pk: company for company in companies}
    for (reason, _), members in groups.items():
        for left, right in combinations({company.pk for company in members}, 2):
            pair_reasons[tuple(sorted((left, right)))].add(reason)
    reason_order = ("company_code", "vat_code", "email", "phone", "url", "name")
    return [
        {"left": company_by_id[left], "right": company_by_id[right], "reasons": [reason for reason in reason_order if reason in reasons], "kind": "company"}
        for (left, right), reasons in sorted(pair_reasons.items())
    ]

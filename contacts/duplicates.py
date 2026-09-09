"""Duplicate detection.

One fixed rule, no levels:

* two **contacts** match on an exact first+last name, a shared email, or a
  shared phone number;
* two **companies** match on an exact name, a shared phone, email, VAT code or
  company code;
* a contact and a company are never compared against each other.

A pair an admin has marked "not a duplicate" (:class:`DuplicateException`) is
dropped from the list and stops warning on edit.
"""
import re
from collections import defaultdict
from itertools import combinations

from .models import Company, DuplicateException, Person


def _lines(value):
    return {item.strip().casefold() for item in (value or "").splitlines() if item.strip()}


def _phones(value):
    return {re.sub(r"\D", "", item) for item in (value or "").splitlines() if len(re.sub(r"\D", "", item)) >= 6}


def _dismissed(kind):
    """Sorted (id, id) tuples the admin marked as not duplicates."""
    return {(row.left_id, row.right_id) for row in DuplicateException.objects.filter(kind=kind)}


def _pair_key(a, b):
    return (a, b) if a < b else (b, a)


REASON_ORDER = ("name", "email", "phone", "vat_code", "company_code")


def find_person_duplicates(data, *, exclude_pk=None, viewer=None):
    emails = _lines(data.get("email", ""))
    phones = _phones(data.get("phone", ""))
    first_name = (data.get("first_name") or "").strip().casefold()
    last_name = (data.get("last_name") or "").strip().casefold()
    people = Person.objects.filter(deleted_at__isnull=True).prefetch_related("emails", "phones")
    if viewer is not None:
        from .permissions import visible_people

        people = visible_people(viewer, people)
    if exclude_pk:
        people = people.exclude(pk=exclude_pk)
    dismissed = _dismissed("person") if exclude_pk else set()
    matches = []
    for person in people:
        if exclude_pk and _pair_key(exclude_pk, person.pk) in dismissed:
            continue
        person_emails = {item.email.strip().casefold() for item in person.emails.all()}
        person_phones = {re.sub(r"\D", "", item.number) for item in person.phones.all()}
        reasons = []
        if first_name and last_name and first_name == person.first_name.strip().casefold() \
                and last_name == person.last_name.strip().casefold():
            reasons.append("name")
        if emails & person_emails:
            reasons.append("email")
        if phones & person_phones:
            reasons.append("phone")
        if reasons:
            matches.append({"record": person, "reasons": reasons})
    return matches


def all_person_duplicate_pairs():
    people = list(Person.objects.filter(deleted_at__isnull=True).prefetch_related("emails", "phones"))
    groups = defaultdict(list)
    for person in people:
        for email in {item.email.strip().casefold() for item in person.emails.all() if item.email.strip()}:
            groups[("email", email)].append(person.pk)
        for phone in {re.sub(r"\D", "", item.number) for item in person.phones.all()}:
            if len(phone) >= 6:
                groups[("phone", phone)].append(person.pk)
        first, last = person.first_name.strip().casefold(), person.last_name.strip().casefold()
        if first and last:
            groups[("name", first, last)].append(person.pk)
    return _pairs_from_groups(groups, {p.pk: p for p in people}, "person")


def _company_signals(data, company):
    normalized_phone = re.sub(r"\D", "", data.get("phone") or "")
    company_phone = re.sub(r"\D", "", company.phone or "")
    return {
        "name": bool(data.get("name") and data["name"].strip().casefold() == company.name.strip().casefold()),
        "email": bool(data.get("email") and data["email"].strip().casefold() == company.email.strip().casefold()),
        "phone": bool(len(normalized_phone) >= 6 and normalized_phone == company_phone),
        "vat_code": bool(data.get("vat_code") and data["vat_code"].strip().casefold() == company.vat_code.strip().casefold()),
        "company_code": bool(data.get("company_code") and data["company_code"].strip().casefold() == company.company_code.strip().casefold()),
    }


def find_company_duplicates(data, *, exclude_pk=None, viewer=None):
    companies = Company.objects.filter(deleted_at__isnull=True)
    if viewer is not None:
        from .permissions import visible_companies

        companies = visible_companies(viewer, companies)
    if exclude_pk:
        companies = companies.exclude(pk=exclude_pk)
    dismissed = _dismissed("company") if exclude_pk else set()
    matches = []
    for company in companies:
        if exclude_pk and _pair_key(exclude_pk, company.pk) in dismissed:
            continue
        signals = _company_signals(data, company)
        reasons = [reason for reason in REASON_ORDER if signals.get(reason)]
        if reasons:
            matches.append({"record": company, "reasons": reasons})
    return matches


def all_company_duplicate_pairs():
    companies = list(Company.objects.filter(deleted_at__isnull=True))
    groups = defaultdict(list)
    for company in companies:
        values = {
            "name": company.name.strip().casefold(),
            "email": company.email.strip().casefold(),
            "phone": re.sub(r"\D", "", company.phone or ""),
            "vat_code": company.vat_code.strip().casefold(),
            "company_code": company.company_code.strip().casefold(),
        }
        for reason, value in values.items():
            if value and (reason != "phone" or len(value) >= 6):
                groups[(reason, value)].append(company.pk)
    return _pairs_from_groups(groups, {c.pk: c for c in companies}, "company")


def _pairs_from_groups(groups, records, kind):
    """Turn {signal: [record ids]} into ordered, de-dismissed pairs."""
    dismissed = _dismissed(kind)
    pair_reasons = defaultdict(set)
    for key, ids in groups.items():
        for left, right in combinations(sorted(set(ids)), 2):
            if (left, right) in dismissed:
                continue
            pair_reasons[(left, right)].add(key[0])
    return [
        {"left": records[left], "right": records[right],
         "reasons": [reason for reason in REASON_ORDER if reason in reasons], "kind": kind}
        for (left, right), reasons in sorted(pair_reasons.items())
    ]

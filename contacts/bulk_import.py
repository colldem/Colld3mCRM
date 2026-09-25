"""Bulk load of people from another system (the Regitra CRM), in batches.

Keyed on ``(external_source, external_id)``: a row whose id is already known
updates that person, any other row creates one. Each batch is one transaction
and a handful of queries (bulk create / update), so hundreds of thousands of
rows load in minutes without the browser upload's 10 MB limit. Duplicates are
left to the background scan (find_duplicates), which also compares personal
codes. Errors name the line and the problem, never a personal code.

CSV columns (header, any order, case-insensitive): external_id (required),
first_name, last_name, job_title, birth_date (YYYY-MM-DD), personal_code,
personal_code_type (lt | other, default lt), email, phone.
"""
import csv
import time

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from . import identity
from .models import EmailAddress, Person, PhoneNumber, digits_only

PERSON_FIELDS = ["first_name", "last_name", "job_title", "birth_date", "personal_code_type",
                 "personal_code_encrypted", "personal_code_hash", "synced_at"]


def _row(raw):
    return {(key or "").strip().lower(): (value or "").strip() for key, value in raw.items()}


def _apply(person, row):
    """Copy a row onto a person and say whether anything changed.

    Raises ValidationError with a message safe to print. An unchanged code is
    not re-encrypted (Fernet output differs every time), so a repeated import
    of the same export rewrites nothing."""
    if not (row.get("first_name") or row.get("last_name")):
        raise ValidationError("first_name or last_name is required")
    before = [getattr(person, field) for field in PERSON_FIELDS[:-1]]
    person.first_name = row.get("first_name", "")[:100]
    person.last_name = row.get("last_name", "")[:100]
    person.job_title = row.get("job_title", "")[:160]
    if row.get("email"):
        try:
            validate_email(row["email"])
        except ValidationError:
            raise ValidationError("invalid email") from None
    if row.get("birth_date"):
        person.birth_date = parse_date(row["birth_date"])
        if person.birth_date is None:
            raise ValidationError("birth_date must be YYYY-MM-DD")
    if row.get("personal_code"):
        kind = row.get("personal_code_type") or identity.LT
        try:
            code_hash = identity.lookup_hash(kind, identity.normalize(kind, row["personal_code"]))
            if code_hash != person.personal_code_hash:
                identity.assign(person, kind, row["personal_code"])
        except ValidationError:
            raise ValidationError("invalid personal_code") from None
    person.synced_at = timezone.now()
    return person.pk is None or before != [getattr(person, field) for field in PERSON_FIELDS[:-1]]


@transaction.atomic
def _load_batch(rows, source, summary, dry_run):
    ids = [row["external_id"] for _line, row in rows]
    known = {p.external_id: p for p in Person.objects.filter(external_source=source, external_id__in=ids)}
    created, updated, unchanged, contacts = [], [], [], []
    for line, row in rows:
        person = known.get(row["external_id"]) or Person(external_source=source, external_id=row["external_id"][:64])
        try:
            changed = _apply(person, row)
        except ValidationError as error:
            summary["errors"].append((line, error.messages[0]))
            continue
        (created if person.pk is None else updated if changed else unchanged).append(person)
        contacts.append((person, row))
    summary["created"] += len(created)
    summary["updated"] += len(updated)
    summary["unchanged"] += len(unchanged)
    if dry_run:
        return
    Person.objects.bulk_create(created, batch_size=1000)
    Person.objects.bulk_update(updated, PERSON_FIELDS, batch_size=1000)
    # Still in the source: say so, in one statement for the whole batch.
    Person.objects.filter(pk__in=[person.pk for person in unchanged]).update(synced_at=timezone.now())
    people = [person for person, _row in contacts]
    have_email = set(EmailAddress.objects.filter(person__in=people).values_list("person_id", "email"))
    have_phone = set(PhoneNumber.objects.filter(person__in=people).values_list("person_id", "number"))
    with_email, with_phone = {pk for pk, _e in have_email}, {pk for pk, _n in have_phone}
    emails, phones = [], []
    for person, row in contacts:
        if row.get("email") and (person.pk, row["email"]) not in have_email:
            emails.append(EmailAddress(person=person, email=row["email"], is_primary=person.pk not in with_email))
        if row.get("phone") and (person.pk, row["phone"]) not in have_phone:
            phones.append(PhoneNumber(person=person, number=row["phone"][:80], digits=digits_only(row["phone"]),
                                      is_primary=person.pk not in with_phone))
    EmailAddress.objects.bulk_create(emails, batch_size=1000)
    PhoneNumber.objects.bulk_create(phones, batch_size=1000)


def import_people(stream, *, source, batch_size=2000, dry_run=False, delimiter=","):
    """Load a CSV stream; returns {"created", "updated", "unchanged", "errors": [(line, message)], "seconds"}."""
    started = time.monotonic()
    summary = {"created": 0, "updated": 0, "unchanged": 0, "errors": []}
    reader = csv.DictReader(stream, delimiter=delimiter)
    if "external_id" not in [(name or "").strip().lower() for name in reader.fieldnames or []]:
        raise ValueError("the file needs an external_id column")
    batch, seen = [], set()
    for line, raw in enumerate(reader, start=2):
        row = _row(raw)
        if not row.get("external_id"):
            summary["errors"].append((line, "external_id is empty"))
            continue
        if row["external_id"] in seen:
            summary["errors"].append((line, "external_id repeats an earlier line"))
            continue
        seen.add(row["external_id"])
        batch.append((line, row))
        if len(batch) == batch_size:
            _load_batch(batch, source, summary, dry_run)
            batch = []
    if batch:
        _load_batch(batch, source, summary, dry_run)
    summary["seconds"] = round(time.monotonic() - started, 1)
    return summary

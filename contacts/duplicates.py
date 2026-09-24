"""Duplicate detection.

One fixed rule, no levels:

* two **contacts** match on an exact first+last name, a shared email, or a
  shared phone number;
* two **companies** match on an exact name, a shared phone, email, VAT code or
  company code;
* a contact and a company are never compared against each other.

Case and surrounding spaces are ignored and phones compare by their digits (at
least six). Every comparison is an index lookup (``models.match_key`` and the
``digits`` columns), so checking one record as it is saved stays fast however
many records there are.

The review list is not worked out on request: the background command
``find_duplicates`` groups the whole table inside the database and keeps the
pairs as :class:`DuplicateCandidate`. A pair an admin has marked "not a
duplicate" (:class:`DuplicateException`) is dropped from the list and stops
warning on edit.
"""
from collections import defaultdict
from itertools import combinations

from django.db import transaction
from django.db.models import Count, F, Q, Window
from django.db.models.functions import Length

from .models import (Company, DuplicateCandidate, DuplicateException, DuplicateSettings, EmailAddress, Person,
                     PhoneNumber, digits_only, match_key)

REASON_ORDER = ("name", "email", "phone", "vat_code", "company_code")
MIN_PHONE_DIGITS = 6
# A value more records share than this (a switchboard number, info@...) says
# nothing about duplicates, and pairing them all would bury the real ones.
MAX_GROUP = 50
COMPANY_KEYS = ("name", "email", "vat_code", "company_code")


def _key(value):
    return (value or "").strip().lower()


def _lines(value):
    return {_key(item) for item in (value or "").splitlines() if item.strip()}


def _phones(value):
    return {digits for digits in map(digits_only, (value or "").splitlines()) if len(digits) >= MIN_PHONE_DIGITS}


def _dismissed(kind):
    """Sorted (id, id) tuples the admin marked as not duplicates."""
    return {(row.left_id, row.right_id) for row in DuplicateException.objects.filter(kind=kind)}


def _pair_key(a, b):
    return (a, b) if a < b else (b, a)


def find_person_duplicates(data, *, exclude_pk=None, viewer=None):
    emails = _lines(data.get("email", ""))
    phones = _phones(data.get("phone", ""))
    first_name = _key(data.get("first_name"))
    last_name = _key(data.get("last_name"))
    ids = set()
    if first_name and last_name:
        ids.update(Person.objects.alias(first_key=match_key("first_name"), last_key=match_key("last_name"))
                   .filter(first_key=first_name, last_key=last_name).values_list("pk", flat=True))
    if emails:
        ids.update(EmailAddress.objects.alias(key=match_key("email")).filter(key__in=emails)
                   .values_list("person_id", flat=True))
    if phones:
        ids.update(PhoneNumber.objects.filter(digits__in=phones).values_list("person_id", flat=True))
    ids.discard(exclude_pk)
    if not ids:
        return []
    people = Person.objects.filter(pk__in=ids, deleted_at__isnull=True).prefetch_related("emails", "phones")
    if viewer is not None:
        from .permissions import visible_people

        people = visible_people(viewer, people)
    dismissed = _dismissed("person") if exclude_pk else set()
    matches = []
    for person in people:
        if exclude_pk and _pair_key(exclude_pk, person.pk) in dismissed:
            continue
        reasons = []
        if first_name and last_name and (first_name, last_name) == (_key(person.first_name), _key(person.last_name)):
            reasons.append("name")
        if emails & {_key(item.email) for item in person.emails.all()}:
            reasons.append("email")
        if phones & {item.digits for item in person.phones.all()}:
            reasons.append("phone")
        if reasons:
            matches.append({"record": person, "reasons": reasons})
    return matches


def _company_signals(data, company):
    phone = digits_only(data.get("phone"))
    signals = {field: bool(_key(data.get(field)) and _key(data.get(field)) == _key(getattr(company, field)))
               for field in COMPANY_KEYS}
    signals["phone"] = len(phone) >= MIN_PHONE_DIGITS and phone == company.phone_digits
    return signals


def find_company_duplicates(data, *, exclude_pk=None, viewer=None):
    condition = Q()
    for field in COMPANY_KEYS:
        if _key(data.get(field)):
            condition |= Q(**{field + "_key": _key(data.get(field))})
    phone = digits_only(data.get("phone"))
    if len(phone) >= MIN_PHONE_DIGITS:
        condition |= Q(phone_digits=phone)
    if not condition:
        return []
    ids = set(Company.objects.alias(**{field + "_key": match_key(field) for field in COMPANY_KEYS})
              .filter(condition).values_list("pk", flat=True))
    ids.discard(exclude_pk)
    if not ids:
        return []
    companies = Company.objects.filter(pk__in=ids, deleted_at__isnull=True)
    if viewer is not None:
        from .permissions import visible_companies

        companies = visible_companies(viewer, companies)
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


def is_duplicate_pair(kind, source, target):
    """Whether the rule still matches these two records (checked before a merge)."""
    from .detail_editing import company_duplicate_data, person_duplicate_data

    if kind == "person":
        matches = find_person_duplicates(person_duplicate_data(source, field=None, value=None), exclude_pk=source.pk)
    else:
        matches = find_company_duplicates(company_duplicate_data(source, field=None, value=None), exclude_pk=source.pk)
    return any(match["record"].pk == target.pk for match in matches)


def count_new_person_pairs(person_ids):
    """How many duplicate pairs the given (just imported) contacts are part of."""
    from .detail_editing import person_duplicate_data

    pairs = set()
    for person in Person.objects.filter(pk__in=person_ids, deleted_at__isnull=True).iterator(chunk_size=500):
        for match in find_person_duplicates(person_duplicate_data(person, field=None, value=None), exclude_pk=person.pk):
            pairs.add(_pair_key(person.pk, match["record"].pk))
    return len(pairs)


# --- background scan ------------------------------------------------------

def _shared(queryset, owner, *keys):
    """(key values..., owner id) for every row whose key values another row shares."""
    named = {"k%d" % index: key for index, key in enumerate(keys)}
    rows = queryset.annotate(**named)
    for name in named:
        rows = rows.exclude(**{name: ""})
    rows = rows.annotate(copies=Window(Count("pk"), partition_by=[F(name) for name in named]))
    return rows.filter(copies__gt=1).values_list(*named, owner).iterator(chunk_size=2000)


def _person_groups():
    alive = Person.objects.filter(deleted_at__isnull=True)
    yield "name", _shared(alive, "pk", match_key("first_name"), match_key("last_name"))
    yield "email", _shared(EmailAddress.objects.filter(person__deleted_at__isnull=True), "person_id", match_key("email"))
    phones = PhoneNumber.objects.filter(person__deleted_at__isnull=True).alias(length=Length("digits"))
    yield "phone", _shared(phones.filter(length__gte=MIN_PHONE_DIGITS), "person_id", F("digits"))


def _company_groups():
    alive = Company.objects.filter(deleted_at__isnull=True)
    for field in COMPANY_KEYS:
        yield field, _shared(alive, "pk", match_key(field))
    phones = alive.alias(length=Length("phone_digits")).filter(length__gte=MIN_PHONE_DIGITS)
    yield "phone", _shared(phones, "pk", F("phone_digits"))


def _scan(kind):
    """{(left, right): {reasons}} and how many oversized groups were left out."""
    groups = defaultdict(set)
    for reason, rows in (_person_groups() if kind == "person" else _company_groups()):
        for *values, owner in rows:
            groups[(reason, *values)].add(owner)
    dismissed = _dismissed(kind)
    pairs, skipped = defaultdict(set), 0
    for (reason, *_values), ids in groups.items():
        if len(ids) > MAX_GROUP:
            skipped += 1
            continue
        for pair in combinations(sorted(ids), 2):
            if pair not in dismissed:
                pairs[pair].add(reason)
    return pairs, skipped


@transaction.atomic
def _store(kind, pairs):
    """Make the stored candidates of ``kind`` exactly ``pairs``; returns (added, removed)."""
    wanted = {pair: ",".join(reason for reason in REASON_ORDER if reason in reasons) for pair, reasons in pairs.items()}
    existing = {(left, right): (pk, reasons) for pk, left, right, reasons in
                DuplicateCandidate.objects.filter(kind=kind).values_list("pk", "left_id", "right_id", "reasons")}
    stale = [pk for pair, (pk, _reasons) in existing.items() if pair not in wanted]
    for start in range(0, len(stale), 1000):
        DuplicateCandidate.objects.filter(pk__in=stale[start:start + 1000]).delete()
    for pair, (pk, reasons) in existing.items():
        if pair in wanted and wanted[pair] != reasons:
            DuplicateCandidate.objects.filter(pk=pk).update(reasons=wanted[pair])
    added = [DuplicateCandidate(kind=kind, left_id=left, right_id=right, reasons=reasons)
             for (left, right), reasons in wanted.items() if (left, right) not in existing]
    DuplicateCandidate.objects.bulk_create(added, batch_size=1000, ignore_conflicts=True)
    return len(added), len(stale)


def scan_duplicates():
    """Rebuild the review list; None while duplicate checking is switched off."""
    if not DuplicateSettings.load().enabled:
        return None
    summary = {}
    for kind in ("person", "company"):
        pairs, skipped = _scan(kind)
        added, removed = _store(kind, pairs)
        summary[kind] = {"pairs": len(pairs), "added": added, "removed": removed, "skipped_groups": skipped}
    return summary

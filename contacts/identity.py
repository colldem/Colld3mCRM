"""A person's personal code (asmens kodas) or, for a foreigner, another identifier.

Found by, never linked by: systems are joined through ``Person.external_id``
(the Regitra record id); the personal code is what a caller or an operator
knows, so it is how a person is *looked up* (the call-centre screen pop, the
search box, the data-subject page).

Stored twice, neither readable on its own:

* ``personal_code_encrypted`` — Fernet with ``CRM_SECRETS_KEY`` (crypto.py),
  decrypted only to show it to someone allowed to see it;
* ``personal_code_hash`` — HMAC-SHA256 under a key derived from the same
  secret, indexed, for exact lookups. A plain hash would not do: there are so
  few personal codes that every one of them can be hashed and compared.

It never goes into URLs, logs, the audit trail, webhooks, the API's person
payload or the reporting views; the card shows it masked.
"""
import hashlib
import hmac
import os
import re
from datetime import date

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from . import crypto

LT = "lt"
OTHER = "other"
TYPE_CHOICES = ((LT, _("Lietuvos asmens kodas")), (OTHER, _("Kitas identifikatorius")))


def available():
    """Codes can be stored and looked up only with ``CRM_SECRETS_KEY`` set."""
    return crypto.secrets_available()


def _checksum(digits):
    """The 11th digit of a Lithuanian personal code (standard weights, then the second set)."""
    for weights in ((1, 2, 3, 4, 5, 6, 7, 8, 9, 1), (3, 4, 5, 6, 7, 8, 9, 1, 2, 3)):
        remainder = sum(int(d) * w for d, w in zip(digits, weights, strict=True)) % 11
        if remainder != 10:
            return remainder
    return 0


def normalize(kind, value):
    """The canonical form of a code, or ValidationError."""
    value = (value or "").strip()
    if kind == LT:
        digits = re.sub(r"\s", "", value)
        if not re.fullmatch(r"\d{11}", digits) or _checksum(digits[:10]) != int(digits[10]):
            raise ValidationError(_("Neteisingas asmens kodas."))
        return digits
    if kind == OTHER:
        cleaned = re.sub(r"\s", "", value).upper()
        if not 3 <= len(cleaned) <= 40:
            raise ValidationError(_("Identifikatorius turi būti 3–40 simbolių."))
        return cleaned
    raise ValidationError(_("Nežinomas identifikatoriaus tipas."))


def birth_date(code):
    """The birth date a Lithuanian personal code carries, or None (e.g. first digit 9)."""
    century = {"1": 1800, "2": 1800, "3": 1900, "4": 1900, "5": 2000, "6": 2000}.get(code[:1])
    if century is None:
        return None
    try:
        return date(century + int(code[1:3]), int(code[3:5]), int(code[5:7]))
    except ValueError:
        return None


def _hash_key():
    secret = (os.environ.get("CRM_SECRETS_KEY") or "").strip()
    return hashlib.sha256(b"crm-personal-code-v1:" + secret.encode()).digest()


def lookup_hash(kind, normalized):
    return hmac.new(_hash_key(), ("%s:%s" % (kind, normalized)).encode(), hashlib.sha256).hexdigest()


def candidate_hashes(text):
    """Hashes a free-text search term could match: as a personal code and as another id."""
    if not available():
        return []
    hashes = []
    for kind in (LT, OTHER):
        try:
            hashes.append(lookup_hash(kind, normalize(kind, text)))
        except ValidationError:
            pass
    return hashes


def assign(person, kind, value):
    """Set (or, with an empty value, clear) the code on an unsaved-change person.
    Returns the fields to save. Fills an empty birth date from a Lithuanian code."""
    fields = ["personal_code_type", "personal_code_encrypted", "personal_code_hash"]
    if not value:
        person.personal_code_type = person.personal_code_encrypted = person.personal_code_hash = ""
        return fields
    if not available():
        raise ValidationError(_("Asmens kodo saugoti negalima: nenustatytas CRM_SECRETS_KEY."))
    normalized = normalize(kind, value)
    person.personal_code_type = kind
    person.personal_code_encrypted = crypto.encrypt(normalized)
    person.personal_code_hash = lookup_hash(kind, normalized)
    if kind == LT and person.birth_date is None:
        person.birth_date = birth_date(normalized)
        fields.append("birth_date")
    return fields


def reveal(person):
    """The plain code, for someone allowed to see it ("" when none or no key)."""
    return crypto.decrypt(person.personal_code_encrypted)


def masked(person):
    """What the card shows everyone: 3*******987 — never more than the last three."""
    code = reveal(person)
    if not code:
        return ""
    head = code[:1] if person.personal_code_type == LT else ""
    return head + "•" * (len(code) - len(head) - 3) + code[-3:]

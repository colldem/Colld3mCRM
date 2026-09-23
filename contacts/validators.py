"""Field validators that are about the data itself, not about a form."""
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as tr

# Positional weights of the Lithuanian personal code's check digit, first pass
# and — when the first pass gives 10 — second pass.
_WEIGHTS_FIRST = (1, 2, 3, 4, 5, 6, 7, 8, 9, 1)
_WEIGHTS_SECOND = (3, 4, 5, 6, 7, 8, 9, 1, 2, 3)


def personal_code_check_digit(digits):
    """The eleventh digit of a Lithuanian personal code, from the first ten."""
    remainder = sum(d * w for d, w in zip(digits, _WEIGHTS_FIRST, strict=True)) % 11
    if remainder == 10:
        remainder = sum(d * w for d, w in zip(digits, _WEIGHTS_SECOND, strict=True)) % 11
    return 0 if remainder == 10 else remainder


# The century each leading digit stands for. 0 means the birth date is not
# known, and then the six digits after it carry no date to check.
_CENTURIES = {1: 1800, 2: 1800, 3: 1900, 4: 1900, 5: 2000, 6: 2000}


def _birth_date(value):
    """The birth date a personal code claims, or None when it claims none."""
    import datetime

    century = _CENTURIES.get(int(value[0]))
    if century is None:
        return None
    try:
        return datetime.date(century + int(value[1:3]), int(value[3:5]), int(value[5:7]))
    except ValueError:
        return None


def validate_personal_code(value):
    """A Lithuanian personal code: 11 digits, a sane century, a valid checksum.

    A wrong code is worse than none — the desk would open the wrong person's
    card — so it is rejected here rather than stored and wondered about later.
    """
    if not value:
        return
    if len(value) != 11 or not value.isdigit():
        raise ValidationError(tr("Asmens kodą sudaro 11 skaitmenų."))
    digits = [int(character) for character in value]
    # The first digit carries sex and century; 1–2 is the 19th, 3–4 the 20th,
    # 5–6 the 21st. 0 is reserved for a person whose birth date is unknown.
    if digits[0] > 6:
        raise ValidationError(tr("Neteisingas asmens kodas."))
    if digits[0] and not _birth_date(value):
        # The checksum does not look at the date, so 49913011235 — the 99th
        # month — adds up perfectly and would sit on the card looking real.
        raise ValidationError(tr("Neteisingas asmens kodas — tokios gimimo datos nėra."))
    if digits[10] != personal_code_check_digit(digits[:10]):
        raise ValidationError(tr("Neteisingas asmens kodas — nesutampa kontrolinis skaitmuo."))

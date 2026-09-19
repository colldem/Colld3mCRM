"""Sample rows for the record card's registry blocks, for looking at the layout.

The blocks are placeholders until the Regitra integration is installed, so
there is nothing to see in them. Switched on with ``CRM_DEMO_BLOCKS=1`` they
fill with invented rows — enough to judge how the column reads when the data
is really there. Never in production: the rows are made up, and made-up
registry data next to a real person is a trap.

The rows are derived from the record's id, so they stay the same between page
loads and differ between records.
"""
import os
from datetime import date, timedelta

from django.conf import settings
from django.utils import timezone

from .record_blocks import register_block

TEMPLATE = "contacts/_record_block_demo.html"
_MAKES = [("Volkswagen", "Passat"), ("Toyota", "Corolla"), ("Škoda", "Octavia"),
          ("BMW", "320d"), ("Renault", "Mégane")]


def enabled():
    """Demo rows are opt-in, and refused outside an isolated tier."""
    return (os.environ.get("CRM_DEMO_BLOCKS") == "1"
            and getattr(settings, "CRM_ENVIRONMENT", "production") != "production")


def _seed(record):
    return (getattr(record, "pk", 0) or 0) % 5


def _loader(person_rows, company_rows):
    """A loader that picks the row set matching the card it is rendered on."""
    def load(record):
        from .models import Company

        rows = (company_rows if isinstance(record, Company) else person_rows) or person_rows or company_rows
        return {"rows": [{"title": title, "detail": detail} for title, detail in rows(_seed(record))]}
    return load


def _plate(seed, offset=0):
    letters = "ABCDEFGHIJKLMNOP"
    index = (seed + offset) % 12
    return f"{letters[index]}{letters[index + 1]}{letters[index + 2]}{100 + index * 7}"


def _vin(seed, offset=0):
    return f"WVWZZZ1JZ{chr(ord('A') + seed)}W{300000 + seed * 1111 + offset * 7:06d}"


def _day(offset):
    return (timezone.localdate() + timedelta(days=offset)).isoformat()


def _person_rows():
    return {
        "licence": lambda seed: [
            (f"Nr. {20100000 + seed * 4321}", f"Kategorijos B, BE · galioja iki {date(2031, 4, 1 + seed)}"),
            ("Medicininė pažyma", f"galioja iki {date(2028, 9, 12)}"),
            ("Teisė vairuoti", "galioja" if seed % 3 else "sustabdyta (medicininė pažyma)"),
        ],
        "exams": lambda seed: [
            ("Teorijos egzaminas", f"{_day(-120 - seed)} · išlaikyta"),
            ("Praktikos egzaminas", f"{_day(-96 - seed)} · neišlaikyta (2 klaidos)"),
            ("Praktikos egzaminas", f"{_day(-74 - seed)} · išlaikyta"),
        ],
        "vehicles": lambda seed: [
            (_vin(seed, index), f"{make} {model} · {_plate(seed, index)} · pirmoji registracija {2014 + index}")
            for index, (make, model) in enumerate(_MAKES[: 2 + seed % 2])
        ],
        "plates": lambda seed: [
            (_plate(seed), "ant transporto priemonės"),
            (_plate(seed, 4), f"saugoma \u201eRegitroje\u201c iki {_day(180 - seed * 10)}"),
        ],
        "visits": lambda seed: [
            ("Vilniaus padalinys", f"{_day(3 + seed)} 10:20 · rezervuota"),
            ("Vilniaus padalinys", f"{_day(-41)} · transporto priemonės registravimas"),
        ],
        "requests": lambda seed: [
            ("Numerio ženklo keitimas", f"P-2026-{1100 + seed} · nagrinėjama"),
            ("Registracijos liudijimo dublikatas", f"P-2026-{900 + seed} · patenkinta"),
        ],
        "mandates": lambda seed: [
            (f"Atstovauti registruojant {_plate(seed)}", f"UAB \u201eVe\u017e\u0117jas\u201c \u00b7 iki {_day(240)}"),
            ("Atsiimti dokumentus", f"pasibaigęs {_day(-60 - seed)}"),
        ],
        "certificates": lambda seed: [
            ("Pažyma apie turimas transporto priemones", _day(-12 - seed)),
            ("Registro duomenų išrašas", _day(-200)),
        ],
        "services": lambda seed: [
            ("Transporto priemonės registravimas", f"{_day(-41)} · Vilnius · atlikta"),
            ("Numerio ženklų gamyba", f"{_day(-40)} · atlikta"),
            ("Vairuotojo pažymėjimo keitimas", f"{_day(-380 - seed)} · atlikta"),
        ],
        "payments": lambda seed: [
            ("Automobilių registracijos mokestis", f"{_day(-41)} · 52,00 € · apmokėta"),
            ("Numerio ženklų gamyba", f"{_day(-40)} · 14,40 € · apmokėta"),
            ("Pažymos išdavimas", f"{_day(-4)} · 6,66 € · neapmokėta"),
        ],
        "messages": lambda seed: [
            (f"+3706{1000000 + seed * 13:07d}", f"{_day(-4)} · Jūsų prašymas P-2026-{1100 + seed} priimtas."),
            (f"+3706{1000000 + seed * 13:07d}", f"{_day(-41)} · Transporto priemonė užregistruota."),
        ],
    }


def _company_rows():
    return {
        "fleet": lambda seed: [
            (_vin(seed, index), f"{make} {model} · {_plate(seed, index)}")
            for index, (make, model) in enumerate(_MAKES)
        ],
        "trade_plates": lambda seed: [
            (f"T{100 + seed}A", f"galioja iki {_day(120)}"),
            (f"T{101 + seed}A", f"galioja iki {_day(120)}"),
        ],
        "statuses": lambda seed: [
            ("Prekybininkas", "nuo 2019 m."),
            ("Lietuvos vežėjas", "nuo 2022 m." if seed % 2 else "nesuteiktas"),
        ],
        "contracts": lambda seed: [
            ("Duomenų teikimo sutartis", f"DS-{2019 + seed}/14 · galioja neterminuotai"),
            ("Vairavimo mokymo įstaigos sutartis", f"VM-2024/{7 + seed} · iki {_day(310)}"),
        ],
        "requests": lambda seed: [
            ("Laikinųjų numerių išdavimas", f"P-2026-{500 + seed} · nagrinėjama"),
        ],
        "representatives": lambda seed: [
            ("Ruslan Gorin", "vadovas · visi veiksmai"),
            ("Ona Kazlauskienė", f"įgaliota iki {_day(200 - seed)}"),
        ],
        "authenticity": lambda seed: [
            (_vin(seed), f"{_day(-9)} · patikrinta stovėjimo vietoje · atitinka"),
            (_vin(seed, 2), f"{_day(-2)} · užsakyta"),
        ],
        "services": lambda seed: [
            ("Transporto priemonių registravimas (3 vnt.)", f"{_day(-15)} · atlikta"),
            ("Autentiškumo patikrinimas", f"{_day(-9)} · atlikta"),
        ],
        "invoices": lambda seed: [
            (f"SF-2026-{300 + seed}", f"{_day(-15)} · 348,00 € · apmokėta"),
            (f"SF-2026-{301 + seed}", f"{_day(-2)} · 96,00 € · laukiama apmokėjimo"),
        ],
        "messages": lambda seed: [
            ("+37052000000", f"{_day(-9)} · Autentiškumo patikrinimas atliktas."),
        ],
    }


def install():
    """Fill every block with sample rows. Called from `ContactsConfig.ready`."""
    from .record_blocks import block

    people, companies = _person_rows(), _company_rows()
    for key in [*people, *(key for key in companies if key not in people)]:
        declared = block(key)
        if declared is None:
            continue
        register_block(key, declared["title"], hint=declared["hint"], template=TEMPLATE,
                       loader=_loader(people.get(key), companies.get(key)))

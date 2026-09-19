"""The record card's middle column — the seam an integration plugs into.

The CRM itself knows only each block's name, which kind of record it belongs to
and what it will hold. A separate Django app — the Regitra integration lives in
its own repository — calls :func:`register_block` with a template and a loader,
and the card renders whatever that hands back. Nothing here imports it, so the
plain CRM runs on its own with every block still saying what it is for.
"""
from django.utils.translation import gettext_lazy as tr_lazy

# A person's card and a company's card ask different questions of the registry,
# so a block says which of the two it belongs on.
PERSON = "person"
COMPANY = "company"
BOTH = (PERSON, COMPANY)

# The blocks, in the order they are registered. `template` and `loader` stay
# empty until an integration registers them, and an empty block shows its hint.
_BLOCKS = {}
_ORDER = []


def register_block(key, title, hint="", template=None, loader=None, kinds=None):
    """Add a block to the column, or fill one the CRM declared empty.

    `loader` is called with the record and returns the template's context;
    registering the same key again replaces it, which is how an integration
    takes over a placeholder. `kinds` defaults to whatever the block already
    had, so taking a placeholder over does not silently move it to the other
    card.
    """
    existing = _BLOCKS.get(key)
    if existing is None:
        _ORDER.append(key)
    _BLOCKS[key] = {"key": key, "title": title, "hint": hint,
                    "template": template, "loader": loader,
                    "kinds": tuple(kinds) if kinds else (existing or {}).get("kinds", BOTH)}


def block(key):
    """A registered block, or None — how a caller reads a declaration back."""
    return _BLOCKS.get(key)


def record_blocks(record):
    """What the middle column renders for `record`, in order."""
    from .models import Company

    kind = COMPANY if isinstance(record, Company) else PERSON
    blocks = []
    for key in _ORDER:
        block = _BLOCKS[key]
        if kind not in block["kinds"]:
            continue
        context = block["loader"](record) if block["loader"] else None
        blocks.append({**block, "context": context})
    return blocks


# What the registry data will fill, as placeholders. The order is the order the
# customer-service desk asks about them: what is on hold or expiring first, the
# history behind it after. Each is replaced by `register_block` once the
# integration is installed beside the CRM. The card itself adds the line saying
# the data is not connected yet, so the hints only have to name the contents.
_PLACEHOLDERS = [
    # (key, kinds, title, what the block will hold)
    ("licence", (PERSON,), tr_lazy("Vairuotojo pažymėjimas"),
     tr_lazy("Pažymėjimo numeris, kategorijos, galiojimas, medicininė pažyma ir teisės vairuoti būsena.")),
    ("exams", (PERSON,), tr_lazy("Egzaminai"),
     tr_lazy("Registracijos, laikyti teorijos ir praktikos egzaminai, rezultatai ir apeliacijos.")),
    ("vehicles", (PERSON,), tr_lazy("Automobiliai"),
     tr_lazy("Transporto priemonės pagal VIN su techniniais duomenimis.")),
    ("fleet", (COMPANY,), tr_lazy("Transporto priemonių parkas"),
     tr_lazy("Įmonės vardu registruotos transporto priemonės.")),
    ("plates", (PERSON,), tr_lazy("Valstybiniai numeriai"),
     tr_lazy("Turimi numerio ženklai ir jų saugojimo terminai.")),
    ("trade_plates", (COMPANY,), tr_lazy("Laikinieji (prekybiniai) numeriai"),
     tr_lazy("Įmonei priskirti laikinieji numerio ženklai ir jų galiojimas.")),
    ("statuses", (COMPANY,), tr_lazy("Statusai"),
     tr_lazy("Vežėjas, gamintojo atstovas, prekybininkas, vairavimo mokykla — nuo jų priklauso, kas įmonei prieinama.")),
    ("contracts", (COMPANY,), tr_lazy("Sutartys"),
     tr_lazy("Duomenų teikimo ir vairavimo mokymo sutartys bei jų terminai.")),
    ("visits", (PERSON,), tr_lazy("Vizitai padaliniuose"),
     tr_lazy("Artimiausia rezervacija ir praėję vizitai padaliniuose.")),
    ("requests", BOTH, tr_lazy("Prašymai"),
     tr_lazy("Pateikti prašymai ir jų būsena.")),
    ("mandates", (PERSON,), tr_lazy("Įgaliojimai"),
     tr_lazy("Galiojantys ir pasibaigę įgaliojimai.")),
    ("representatives", (COMPANY,), tr_lazy("Atstovai ir įgaliojimai"),
     tr_lazy("Asmenys, turintys teisę veikti įmonės vardu.")),
    ("authenticity", (COMPANY,), tr_lazy("Autentiškumo patikrinimai"),
     tr_lazy("Transporto priemonių autentiškumo patikrinimo užsakymai ir jų eiga.")),
    ("certificates", (PERSON,), tr_lazy("Pažymos ir išrašai"),
     tr_lazy("Išduotos pažymos ir registro duomenų išrašai.")),
    ("services", BOTH, tr_lazy("Neseniai suteiktos paslaugos"),
     tr_lazy("Paskutinės suteiktos paslaugos.")),
    ("payments", (PERSON,), tr_lazy("Mokėjimai ir skolos"),
     tr_lazy("Registracijos mokestis, apmokėtos ir neapmokėtos paslaugos.")),
    ("invoices", (COMPANY,), tr_lazy("Mokėjimai ir sąskaitos"),
     tr_lazy("Išrašytos sąskaitos, apmokėjimai ir įsiskolinimai.")),
    ("messages", BOTH, tr_lazy("Išsiųsti SMS"),
     tr_lazy("Neseniai į šio įrašo numerį siųsti pranešimai.")),
]
for _key, _kinds, _title, _holds in _PLACEHOLDERS:
    register_block(_key, _title, hint=_holds, kinds=_kinds)

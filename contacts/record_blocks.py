"""The record card's middle column — the seam an integration plugs into.

The CRM itself knows only each block's name and what it will hold. A separate
Django app — the Regitra integration lives in its own repository — calls
:func:`register_block` with a template and a loader, and the card renders
whatever that hands back. Nothing here imports it, so the plain CRM runs on
its own with every block still saying what it is for.
"""
from django.utils.translation import gettext_lazy as tr_lazy

# The blocks the card shows, in order. `template` and `loader` stay empty until
# an integration registers them, and an empty block shows its hint instead.
_BLOCKS = {}
_ORDER = []


def register_block(key, title, hint="", template=None, loader=None):
    """Add a block to the column, or fill one the CRM declared empty.

    `loader` is called with the record and returns the template's context;
    registering the same key again replaces it, which is how an integration
    takes over a placeholder.
    """
    if key not in _BLOCKS:
        _ORDER.append(key)
    _BLOCKS[key] = {"key": key, "title": title, "hint": hint,
                    "template": template, "loader": loader}


def record_blocks(record):
    """What the middle column renders for `record`, in order."""
    blocks = []
    for key in _ORDER:
        block = _BLOCKS[key]
        context = block["loader"](record) if block["loader"] else None
        blocks.append({**block, "context": context})
    return blocks


# The Regitra fields, as placeholders. Each is replaced by `register_block`
# once the integration is installed beside the CRM.
for _key, _title, _hint in [
    ("vehicles", tr_lazy("Automobiliai"),
     tr_lazy("Transporto priemonės pagal VIN su techniniais duomenimis. Bus rodoma prijungus Regitros duomenis.")),
    ("plates", tr_lazy("Valstybiniai numeriai"),
     tr_lazy("Turimi valstybinio numerio ženklai. Bus rodoma prijungus Regitros duomenis.")),
    ("services", tr_lazy("Neseniai suteiktos paslaugos"),
     tr_lazy("Paskutinės suteiktos paslaugos. Bus rodoma prijungus Regitros duomenis.")),
    ("messages", tr_lazy("Išsiųsti SMS"),
     tr_lazy("Neseniai į šio įrašo numerį siųsti pranešimai. Bus rodoma prijungus Regitros duomenis.")),
    ("mandates", tr_lazy("Įgaliojimai"),
     tr_lazy("Galiojantys ir pasibaigę įgaliojimai. Bus rodoma prijungus Regitros duomenis.")),
    ("requests", tr_lazy("Prašymai"),
     tr_lazy("Pateikti prašymai ir jų būsena. Bus rodoma prijungus Regitros duomenis.")),
]:
    register_block(_key, _title, _hint)

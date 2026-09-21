"""The pages people meet when something goes wrong.

Without these, Django serves its built-in replies once ``DEBUG`` is off: an
unstyled English line such as "Not Found" or "Server Error (500)", with no
account of what happened, no suggestion of what to do and no way back into the
CRM. Somebody who mistypes an address or opens a colleague's stale link is told
only that they have failed.

Each page here answers the same three questions — what happened, why it is
likely to have happened, and what to do next — and keeps the person signed in
and one click from the CRM. The server error also shows the request id, which is
the only thing that lets an administrator find that exact failure in the log
(``contacts/observability.py``); the person can read it out without knowing
anything about the system.

The causes are deliberately concrete. "Access denied" tells nobody anything;
"your role does not include this, and these are the roles that do" tells them
whether to ask an administrator or to stop trying.
"""
from django.http import HttpResponse
from django.template.loader import get_template
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as tr

from .observability import current_request_id


def _page(request, status, title, summary, causes, template="errors/error.html", **extra):
    """Render without a request, on purpose.

    ``render(request, ...)`` would run the context processors, and those read
    ``request.user``. On a 500 the failure may have happened before the
    authentication middleware ran, and then building the error page raises its
    own error and the person gets Django's bare fallback instead — the failure
    mode these pages exist to remove. Nothing here needs the request but the id.
    """
    context = {"status": status, "title": title, "summary": summary, "causes": causes,
               "request_id": getattr(request, "request_id", "") or current_request_id(),
               "LANGUAGE_CODE": get_language()}
    context.update(extra)
    return HttpResponse(get_template(template).render(context), status=status)


def bad_request(request, exception=None):
    return _page(
        request, 400, tr("Užklausa netinkama"),
        tr("Serveris gavo užklausą, kurios negali perskaityti, todėl jos neįvykdė. "
           "Jūsų duomenys nepakeisti."),
        [tr("Forma buvo atidaryta labai seniai ir jos laukai nebeatitinka dabartinių."),
         tr("Įkeliamas failas viršijo leidžiamą dydį arba failų skaičių."),
         tr("Adresas buvo redaguotas ranka arba ateina iš pasenusios nuorodos.")])


def permission_denied(request, exception=None):
    return _page(
        request, 403, tr("Neturite teisės to atlikti"),
        tr("Jūs prisijungęs, bet šis veiksmas jūsų rolei neprieinamas. Niekas nepakeista "
           "ir niekas neužfiksuota kaip pažeidimas — tiesiog trūksta teisės."),
        [tr("Jūsų rolė šios galimybės neturi. Ką kuri rolė gali, mato administratorius "
            "Nustatymai → Rolės ir teisės."),
         tr("Įrašas priklauso kitam naudotojui ar komandai, o jūsų matomumas apribotas savais įrašais."),
         tr("Jūs skaitytojas — ši rolė nieko nekeičia, tik peržiūri."),
         tr("Jei teisės tikrai reikia darbui, jos prašykite administratoriaus: pasakykite, "
            "kurį puslapį atvėrėte ir ką bandėte daryti.")])


def page_not_found(request, exception=None):
    return _page(
        request, 404, tr("Tokio puslapio nėra"),
        tr("Adresas teisingas savo forma, bet nieko neatitinka. Gali būti, kad įrašas buvo, "
           "bet jo nebeliko."),
        [tr("Įrašas suarchyvuotas arba ištrintas. Suarchyvuotus įrašus rasite Archyve."),
         tr("Įrašas sujungtas su kitu kaip dublikatas — atsidarykite tą, į kurį sujungta."),
         tr("Adrese yra rašybos klaida arba nuoroda pasenusi."),
         tr("Įrašas yra, bet jūsų rolė jo nemato — tokiu atveju sistema sąmoningai sako "
            "„nėra“, o ne „neleidžiama“, kad pats įrašo buvimas neatsiskleistų.")])


def server_error(request):
    return _page(
        request, 500, tr("Sistemos klaida"),
        tr("Nepavyko ne dėl jūsų — klaida įvyko serveryje. Veiksmas neįvykdytas, "
           "o duomenys liko tokie, kokie buvo prieš jį."),
        [tr("Pabandykite dar kartą po kelių minučių — dalis tokių klaidų laikinos."),
         tr("Jei kartojasi, praneškite administratoriui ir pasakykite žemiau esantį "
            "užklausos numerį: pagal jį jis žurnale randa būtent šią klaidą."),
         tr("Nekartokite mokėjimo ar siuntimo veiksmo daug kartų iš eilės — pirma "
            "patikrinkite, ar jis tikrai neįvyko.")])


def csrf_failure(request, reason=""):
    """Django's own CSRF page explains cookies to a person filling in a form."""
    return _page(
        request, 403, tr("Forma nebegalioja"),
        tr("Forma buvo atidaryta per seniai arba jūsų sesija baigėsi, todėl serveris "
           "negali patikrinti, kad ją siunčiate būtent jūs. Tai apsauga nuo svetimo "
           "puslapio, kuris bandytų atlikti veiksmą jūsų vardu. Niekas nepakeista."),
        [tr("Atsidarykite puslapį iš naujo ir pakartokite veiksmą — įvestą tekstą "
            "prieš tai nusikopijuokite, kad nedingtų."),
         tr("Jei buvote atsijungęs kitame lange, prisijunkite ir bandykite dar kartą."),
         tr("Jei naršyklė blokuoja slapukus šiai svetainei, juos reikia leisti — "
            "be jų prisijungimas neveiks iš viso.")],
        template="errors/error.html")

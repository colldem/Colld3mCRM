"""Time each heavy page on its own, one request at a time, against a seeded CRM.

    python scripts/loadtest/probe.py --host http://localhost:8080 --csv probe.csv

The load test (locustfile.py) says how the mix holds up under 50 users; this
says which single page is slow and by how much, so the scaling work can be
measured stage by stage. Signs in as load00 from seed.py. Never point this at
production.
"""
import argparse
import csv
import os
import re
import statistics
import sys
import time

import requests

PASSWORD = os.environ.get("LOAD_PASSWORD", "load-test-password-123")
CSRF = re.compile(r'name="csrfmiddlewaretoken" value="([^"]+)"')
CARD = re.compile(r'href="/contacts/(\d+)/"')
SLOW = 10.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="http://localhost:8080")
    parser.add_argument("--repeat", type=int, default=3, help="requests per page; a page slower than 10 s runs once")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--csv", default="")
    args = parser.parse_args()
    session = requests.Session()
    login = session.get(args.host + "/login/", timeout=args.timeout)
    session.post(args.host + "/login/", timeout=args.timeout, allow_redirects=False, headers={"Referer": args.host + "/login/"},
                 data={"username": "load00", "password": PASSWORD, "csrfmiddlewaretoken": CSRF.search(login.text).group(1)})
    listing = session.get(args.host + "/contacts/", timeout=args.timeout)
    card = CARD.search(listing.text)
    if not card:
        sys.exit("sign-in failed or the contact list is empty")
    card = int(card.group(1))
    csrf = {"X-CSRFToken": session.cookies.get("csrftoken", ""), "Referer": args.host + "/contacts/%d/" % card}
    probes = [
        ("Darbastalis", "GET", "/", None),
        ("Kontaktų sąrašas, 1 psl.", "GET", "/contacts/", None),
        ("Kontaktų sąrašas, 2000 psl.", "GET", "/contacts/?page=2000", None),
        ("Paieška kontaktų sąraše", "GET", "/contacts/?q=Krovinys04211", None),
        ("Paieškos pasiūlymai", "GET", "/search/suggest/?q=Krovinys04211", None),
        ("Globali paieška", "GET", "/search/?q=Krovinys04211", None),
        ("Įmonių sąrašas su filtru", "GET", "/companies/?city=Kaunas", None),
        ("Kontakto kortelė", "GET", "/contacts/%d/" % card, None),
        ("Analitika", "GET", "/analytics/", None),
        ("Naujo asmens forma", "GET", "/contacts/new/person/", None),
        ("Dublikatų tikrinimas išsaugant", "POST", "/contacts/%d/field/" % card,
         {"field": "emails", "value": "load%d@example.invalid" % (card + 1)}),
        ("Dublikatų sąrašas", "GET", "/duplicates/", None),
    ]
    rows = []
    for label, method, path, data in probes:
        times, status = [], ""
        for _ in range(args.repeat):
            started = time.monotonic()
            try:
                response = session.request(method, args.host + path, data=data, timeout=args.timeout,
                                           headers=csrf if method == "POST" else None)
                status = str(response.status_code)
            except requests.RequestException as error:
                status = type(error).__name__
            times.append(time.monotonic() - started)
            if times[-1] > SLOW or not status.isdigit():
                break
        rows.append({"page": label, "method": method, "path": path, "status": status, "runs": len(times),
                     "median_s": "%.2f" % statistics.median(times), "max_s": "%.2f" % max(times)})
        print("%-34s %-4s %6s s (max %6s s) status=%s" % (label, method, rows[-1]["median_s"], rows[-1]["max_s"], status),
              flush=True)
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    main()

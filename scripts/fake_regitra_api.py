"""A stand-in for Regitra's ORDS REST service, serving made-up data.

    python scripts/fake_regitra_api.py --port 8090 [--token secret] [--delay 0.5]
    CRM_REGITRA_API_URL=http://127.0.0.1:8090/ords/crm

Answers GET /ords/crm/persons/<external_id>/<services|visits|requests>/?offset=&limit=
with an ORDS collection ({"items", "hasMore", "offset", "limit", "count", "links"}).
The same external id always gets the same records; an id starting with "0" is one
Regitra does not know (404). Standard library only, so it runs anywhere Python does.
Never holds or returns real data.
"""
import argparse
import hashlib
import json
import random
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PREFIX = "/ords/crm/persons/"
OFFICES = ["Vilniaus padalinys", "Kauno padalinys", "Klaipėdos padalinys", "Šiaulių padalinys", "Panevėžio padalinys"]
SERVICES = ["Transporto priemonės registravimas", "Vairuotojo pažymėjimo keitimas", "Valstybinio numerio išdavimas",
            "Techninės apžiūros duomenų patikra", "Registracijos liudijimo dublikatas"]
PURPOSES = ["Praktinis vairavimo egzaminas", "Teorijos egzaminas", "Dokumentų pateikimas", "Konsultacija"]
REQUESTS = ["Prašymas išduoti pažymą", "Skundas dėl aptarnavimo", "Prašymas grąžinti įmoką", "Duomenų taisymas"]
STATUSES = {"services": ["Suteikta", "Suteikta", "Atšaukta"],
            "visits": ["Įvykęs", "Įvykęs", "Neatvyko"],
            "requests": ["Išnagrinėtas", "Nagrinėjamas", "Atmestas"]}
COUNTS = {"services": 23, "visits": 7, "requests": 4}
NOW = datetime(2026, 9, 25, 9, 0, tzinfo=timezone.utc)


def records(external_id, kind):
    """Every record of `kind` for one person, newest first — the same on every call."""
    rng = random.Random(hashlib.sha256(("%s/%s" % (external_id, kind)).encode()).hexdigest())  # nosec B311
    rows = []
    for index in range(COUNTS[kind]):
        moment = NOW - timedelta(days=index * 23 + rng.randint(0, 20), hours=rng.randint(0, 8))
        status = rng.choice(STATUSES[kind])
        if kind == "services":
            rows.append({"id": index + 1, "date": moment.date().isoformat(), "name": rng.choice(SERVICES),
                         "office": rng.choice(OFFICES), "status": status})
        elif kind == "visits":
            if index == 0:
                moment, status = NOW + timedelta(days=4, hours=2), "Užregistruotas"
            rows.append({"id": index + 1, "time": moment.isoformat().replace("+00:00", "Z"),
                         "office": rng.choice(OFFICES), "purpose": rng.choice(PURPOSES), "status": status})
        else:
            rows.append({"id": index + 1, "submitted": moment.isoformat().replace("+00:00", "Z"),
                         "type": rng.choice(REQUESTS), "number": "PR-%06d" % rng.randint(1, 999999), "status": status})
    return rows


class Handler(BaseHTTPRequestHandler):
    token = ""
    delay = 0.0

    def do_GET(self):  # noqa: N802 (http.server's naming)
        time.sleep(self.delay)
        url = urlparse(self.path)
        parts = url.path[len(PREFIX):].strip("/").split("/") if url.path.startswith(PREFIX) else []
        if self.token and self.headers.get("Authorization") != "Bearer " + self.token:
            return self._send(401, {"code": "Unauthorized", "message": "Unauthorized"})
        if len(parts) != 2 or parts[1] not in COUNTS or parts[0].startswith("0"):
            return self._send(404, {"code": "NotFound", "message": "Not Found"})
        query = parse_qs(url.query)
        offset = max(int((query.get("offset") or ["0"])[0]), 0)
        limit = min(max(int((query.get("limit") or ["25"])[0]), 1), 500)
        rows = records(parts[0], parts[1])
        items = rows[offset:offset + limit]
        more = offset + limit < len(rows)
        links = [{"rel": "self", "href": self.path}]
        if more:
            links.append({"rel": "next", "href": "%s?offset=%d&limit=%d" % (url.path, offset + limit, limit)})
        self._send(200, {"items": items, "hasMore": more, "offset": offset, "limit": limit,
                         "count": len(items), "links": links})

    def _send(self, status, body):
        payload = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def serve(host="127.0.0.1", port=8090, token="", delay=0.0):
    """A running server (call serve_forever), for the command line and for tests."""
    handler = type("ConfiguredHandler", (Handler,), {"token": token, "delay": delay})
    return ThreadingHTTPServer((host, port), handler)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--token", default="", help="require this bearer token")
    parser.add_argument("--delay", type=float, default=0.0, help="seconds to wait before each answer")
    args = parser.parse_args()
    server = serve(args.host, args.port, args.token, args.delay)
    print("Fake Regitra API on http://%s:%d/ords/crm" % (args.host, args.port), flush=True)
    server.serve_forever()

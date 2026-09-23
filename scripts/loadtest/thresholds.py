"""Decide whether a load run passed, and say why in numbers.

Two kinds of failure, and they are not the same kind of news:

* **hard** — requests that failed, or too few requests to mean anything. The
  code or the stack is broken, and running it again proves nothing.
* **slow** — the 95th percentile over budget. On a shared runner this is the
  one number that moves without the code moving: the aggregate mixes a 90 ms
  company list with a 600 ms dashboard, so it shifts with whichever pages the
  run happened to ask for. A real regression is slow every time, so the caller
  runs it a second time and only then fails.

Exit codes: 0 passed, 1 slow (worth another run), 2 hard (not worth one).
"""
import csv
import sys

# What the 95th percentile may reach before it counts as a regression. The
# aggregate is the whole run; the rest are per page, because "something got
# slower" is only useful if it names the page.
AGGREGATED = 2000
PER_ENDPOINT_DEFAULT = 2000

MINIMUM_REQUESTS = 1500
MAXIMUM_FAILURE_RATIO = 0.01


def report(path):
    rows = {row["Name"]: row for row in csv.DictReader(open(path))}
    total = rows["Aggregated"]
    requests, failures = int(total["Request Count"]), int(total["Failure Count"])
    print("requests=%d failures=%d p50=%sms p95=%sms rps=%s"
          % (requests, failures, total["50%"], total["95%"], total["Requests/s"]))
    for name, row in sorted(rows.items()):
        print("%-45s p50=%6s p95=%6s max=%8s n=%s"
              % (name, row["50%"], row["95%"], row["Max Response Time"], row["Request Count"]))
    return rows, requests, failures


def main(path):
    rows, requests, failures = report(path)
    if requests < MINIMUM_REQUESTS:
        print("FAIL (hard): only %d requests, expected at least %d" % (requests, MINIMUM_REQUESTS))
        return 2
    if failures / requests >= MAXIMUM_FAILURE_RATIO:
        print("FAIL (hard): %d of %d requests failed" % (failures, requests))
        return 2
    p95 = float(rows["Aggregated"]["95%"])
    if p95 >= AGGREGATED:
        print("SLOW: 95th percentile %sms, budget %dms" % (p95, AGGREGATED))
        return 1
    over = [(name, row["95%"]) for name, row in sorted(rows.items())
            if name != "Aggregated" and float(row["95%"]) >= PER_ENDPOINT_DEFAULT]
    if over:
        print("SLOW: over %dms — %s" % (PER_ENDPOINT_DEFAULT,
                                        ", ".join("%s %sms" % pair for pair in over)))
        return 1
    print("OK: 95th percentile %sms, budget %dms" % (p95, AGGREGATED))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))

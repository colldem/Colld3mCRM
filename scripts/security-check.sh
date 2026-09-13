#!/bin/sh
# Supply-chain and static security checks. Needs network (vulnerability DB).
#   PYTHON_BIN=.venv/bin/python sh scripts/security-check.sh
set -eu
PYTHON_BIN="${PYTHON_BIN:-python}"
# Known CVEs in the pinned runtime dependencies; any finding fails.
"$PYTHON_BIN" -m pip_audit --strict --requirement requirements.txt
# Static analysis of the application code; config in pyproject.toml [tool.bandit].
"$PYTHON_BIN" -m bandit -c pyproject.toml -r contacts config -q

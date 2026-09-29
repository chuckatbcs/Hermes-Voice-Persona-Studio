#!/usr/bin/env bash
# Run every offline check for Persona Studio.
#
#   ./scripts/check.sh
#
# Python: the backend + session/overlay/audit contract suite.
# JS:     node --test over the extracted desktop helpers, plus a parse check
#         of the plugin itself.
set -uo pipefail

cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
fail=0

echo "== python syntax =="
"$PY" -m compileall -q backend/ || fail=1

echo "== python tests =="
"$PY" -m unittest test_backend.py -q 2>&1 | tail -3 || fail=1
# unittest exits non-zero on failure; re-run for the real code.
"$PY" -m unittest test_backend.py -q >/dev/null 2>&1 || fail=1

if command -v node >/dev/null 2>&1; then
  echo "== plugin build =="
  node scripts/build-plugin.mjs || fail=1

  echo "== import allowlist (the desktop loader's gate) =="
  node scripts/check-imports.mjs desktop/dist/plugin.js || fail=1

  echo "== plugin parse =="
  node --check desktop/dist/plugin.js || fail=1

  echo "== js tests =="
  node --test tests/plugin.test.mjs 2>&1 | grep -E '^# (tests|pass|fail)' || fail=1
  node --test tests/plugin.test.mjs >/dev/null 2>&1 || fail=1
else
  echo "== node missing: skipping JS checks =="
fi

if [ "$fail" -ne 0 ]; then
  echo "FAILED"
  exit 1
fi
echo "ALL CHECKS PASSED"

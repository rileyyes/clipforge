#!/usr/bin/env bash
# Runs every automated check. Usage: scripts/verify_all.sh
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== frontend: engine unit + fuzz tests, typecheck, build"
(cd frontend && npm test --silent 2>&1 | grep -E "^# (pass|fail)" && npm run --silent typecheck && node build.mjs >/dev/null 2>&1 && echo "build ok")
echo "== backend <-> engine cross-check"
python3 scripts/crosscheck.py
echo "== backend: unit + integration + auto-edit"
(cd backend && python3 -m pytest -p no:randomly 2>&1 | tail -1)
echo "== browser E2E: manual editor"
python3 scripts/e2e_browser.py 2>&1 | grep -E "ERRORS|clips after reload"
echo "== browser E2E: AI auto editor"
python3 scripts/e2e_autoedit.py 2>&1 | grep -E "OK|validated|Error"
echo "ALL CHECKS PASSED"

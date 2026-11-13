#!/usr/bin/env bash
# Runs every automated check. Usage: scripts/verify_all.sh
set -euo pipefail
# real offline-voice tests when a local Piper copy is there (see CI)
[ -d /tmp/piper ] && export RJCLIP_TEST_PIPER_DIR=/tmp/piper
cd "$(dirname "$0")/.."
echo "== frontend: engine unit + fuzz tests, typecheck, build"
(cd frontend && npm test --silent 2>&1 | grep -E "^# (pass|fail)" && npm run --silent typecheck && node build.mjs >/dev/null 2>&1 && echo "build ok")
echo "== backend <-> engine cross-check"
python3 scripts/crosscheck.py
echo "== backend: unit + integration + auto-edit"
(cd backend && python3 -m pytest -p no:randomly -rf 2>&1 | grep -E "^FAILED|passed|failed" | tail -6)
echo "== browser E2E: manual editor"
python3 scripts/e2e_browser.py 2>&1 | grep -E "ERRORS|clips after reload"
echo "== browser E2E: AI auto editor"
python3 scripts/e2e_autoedit.py 2>&1 | grep -E "OK|validated|Error"
echo "== browser E2E: thumbnail maker"
python3 scripts/e2e_thumbnails.py 2>&1 | grep -E "OK|reopened|Error"
echo "== browser E2E: effects (bleeps, comedy edits, captions)"
python3 scripts/e2e_effects.py 2>&1 | grep -E "OK|persisted|Error"
echo "== browser E2E: audio (transitions, fades, ducking, loudness)"
python3 scripts/e2e_audio.py 2>&1 | grep -E "OK|LUFS|Error"
echo "== browser E2E: version history (save, compare, restore)"
python3 scripts/e2e_history.py 2>&1 | grep -E "OK|clips after|Error"
echo "== browser E2E: advanced editor (keyframes, rotation, crop, colour, meters, light preview, render cache)"
python3 scripts/e2e_phase6.py 2>&1 | grep -E "OK|cache:|Error"
echo "== browser E2E: my sounds & images (mic recording, import, custom bleep, export)"
python3 scripts/e2e_library.py 2>&1 | grep -E "OK|bleep window|Error"
echo "== browser E2E: Shorts (best moments, vertical, follows the subject)"
python3 scripts/e2e_shorts.py 2>&1 | grep -E "OK|made:|Error"
echo "== browser E2E: Publish (chapters/title/tags + YouTube upload vs a fake Google)"
python3 scripts/e2e_publish.py 2>&1 | grep -E "OK|uploaded:|Error"
echo "== browser E2E: face cam (sync by sound, corner circle, crop, background removal, hide) + smoother jump cuts"
python3 scripts/e2e_facecam.py 2>&1 | grep -E "OK|lined up|export validated|Error"
echo "== browser E2E: Phase 10 (edit by transcript, fillers/retakes, titles, privacy blur, beat sync)"
python3 scripts/e2e_phase10.py 2>&1 | grep -E "OK|after cleanup|song:|export validated|Error"
echo "== browser E2E: Phase 11 (fits 1280x720, timeline titles/blurs, transition preview, shortcuts, J/K/L, guides)"
python3 scripts/e2e_phase11.py 2>&1 | grep -E "OK|overflow|transition preview|Error"
echo "== browser E2E: Phase 12 (relink missing media, move several clips, link/unlink, markers, chapters from markers)"
python3 scripts/e2e_phase12.py 2>&1 | grep -E "OK|toolbar|group drag|markers|chapters|Error|assert"
echo "== browser E2E: Phase 13 (type a new time for an effect; nudge; to playhead; export check)"
python3 scripts/e2e_phase13.py 2>&1 | grep -E "OK|after|overflow|yellow|Error|assert"
echo "== browser E2E: Phase 14 (background music for a time range, caption preview, fix a misheard word, export check)"
python3 scripts/e2e_phase14.py 2>&1 | grep -E "OK|caption|music pieces|overflow|song vs|Error|assert"
echo "== browser E2E: Phase 15 (brand kit, shapes, green screen, layouts, freeze, speed ramp, reverse, export check)"
python3 scripts/e2e_phase15.py 2>&1 | grep -E "OK|brand kit|arrow at|V1 after|intro pixel|Error|assert"
echo "== browser E2E: Phase 16 (hook checker, teaser, B-roll from your clips, voiceover, songs matched to the video)"
python3 scripts/e2e_phase16.py 2>&1 | grep -E "OK|hook score|teaser|B-roll|voiceover|music plan|export ok|Error|assert"
echo "== browser E2E: Phase 17 (first-run tour, titles/markers/blurs follow moved clips)"
python3 scripts/e2e_phase17.py 2>&1 | grep -E "OK|tour steps|after dragging|after undo|Error|assert"
echo "== browser E2E: Phase 18 (fonts & text styles, counter, name tags, combos, funny moments, new looks)"
python3 scripts/e2e_phase18.py 2>&1 | grep -E "OK|my font|counter in|export ok|funny moments|keep only|Error|assert"
echo "== browser E2E: Phase 19 (timer & money counter, stamp, route, highlighter, key words, sound design, slow push, pacing checker)"
python3 scripts/e2e_phase19.py 2>&1 | grep -E "OK|sound design|pacing|after punch|export ok|Error|assert"
echo "== smoke test: import, export, cached re-export through a running server"
SMOKE_WS=$(mktemp -d)
pushd backend >/dev/null
RJCLIP_WORKSPACE="$SMOKE_WS" RJCLIP_PORT=8798 python3 -m app.main >/dev/null 2>&1 &
SMOKE_PID=$!   # the server itself (not a subshell), so kill really stops it
# stop it even if the smoke test fails (a leftover server on 8798 broke the next run's E2E tests)
trap 'kill $SMOKE_PID 2>/dev/null || true' EXIT
popd >/dev/null
for _ in $(seq 60); do curl -fs http://127.0.0.1:8798/api/health >/dev/null 2>&1 && break; sleep 0.5; done
python3 scripts/smoke_export.py --base http://127.0.0.1:8798 2>&1 | grep -E "export|all good|Error"
kill $SMOKE_PID; wait $SMOKE_PID 2>/dev/null || true; rm -rf "$SMOKE_WS"
echo "ALL CHECKS PASSED"

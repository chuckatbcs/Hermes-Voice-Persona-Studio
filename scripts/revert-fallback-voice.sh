#!/usr/bin/env bash
# Revert the mechanic fallback voice repoint.
#
#   ./revert-fallback-voice.sh          # restore from backup
#   ./revert-fallback-voice.sh --list   # show current + backup values first
#
# The repoint changed ONE value:
#   tts.providers.voicebox.voice
#   Flirty   13f20853-2a35-42d7-b214-f871588bdddb
#   -> Eric Cartman
#            83c6e6b8-73ac-4b9c-a4fb-b9cc07795d6a
#
# The ACTIVE voice (tts.provider: fish / hermes_eric_cartman) was NOT touched.
set -euo pipefail

BACKUP="/home/chuck/.hermes/profiles/mechanic/cache/scratch/mechanic-config-before-voice-repoint.yaml"
LIVE="/home/chuck/.hermes/profiles/mechanic/config.yaml"
PY="/home/chuck/.hermes/hermes-agent/venv/bin/python"

show() {
  "$PY" - "$1" <<'PY'
import sys, yaml
c = yaml.safe_load(open(sys.argv[1]))
t = (c.get('tts') or {}).get('providers') or {}
print(f"  active provider : {(c.get('tts') or {}).get('provider')}")
print(f"  active voice    : {(t.get('fish') or {}).get('voice')}")
print(f"  voicebox voice  : {(t.get('voicebox') or {}).get('voice')}")
PY
}

if [[ "${1:-}" == "--list" ]]; then
  echo "LIVE ($LIVE):";   show "$LIVE"
  echo "BACKUP:";         show "$BACKUP"
  exit 0
fi

if [[ ! -f "$BACKUP" ]]; then
  echo "✗ No backup at $BACKUP — nothing to revert to." >&2
  exit 1
fi

# Safety: only proceed if the live file still looks like ours.
if ! grep -q "83c6e6b8-73ac-4b9c-a4fb-b9cc07795d6a" "$LIVE"; then
  echo "✗ Live config does not contain the new voice id — refusing to clobber" >&2
  echo "  changes made since the repoint. Inspect manually: $LIVE" >&2
  exit 1
fi

cp -a "$BACKUP" "$LIVE"
echo "✓ Reverted. Active provider/voice unchanged; voicebox fallback restored."
show "$LIVE"

#!/usr/bin/env bash
# Run on Promax after: python3 install.py --no-sync-voices
set -euo pipefail
API="${API:-http://127.0.0.1:17495/api/studio}"
PACK_ID="${1:-amanda}"
ENGINE="${2:-chatterbox_turbo}"

echo "== Current pack matching $PACK_ID =="
curl -sS "$API/personas" | python3 -c "
import json,sys
packs=json.load(sys.stdin)
key='$PACK_ID'.lower()
for p in packs:
  blob=((p.get('id') or '')+' '+(p.get('name') or '')).lower()
  if key in blob or p.get('id')=='$PACK_ID':
    print(json.dumps({k:p.get(k) for k in ['id','name','provider','voice_id','voice_name','engine','speed','temperature']}, indent=2))
"

echo "== PUT engine=$ENGINE =="
python3 - <<PY
import json, urllib.request
api = "$API"
packs = json.load(urllib.request.urlopen(api + "/personas"))
key = "$PACK_ID".lower()
pack = next(
    (
        p
        for p in packs
        if p.get("id") == "$PACK_ID"
        or key in ((p.get("id") or "") + " " + (p.get("name") or "")).lower()
    ),
    None,
)
assert pack, "pack not found: $PACK_ID"
body = {
    "name": pack["name"],
    "avatar": pack.get("avatar") or "🤖",
    "system_prompt": pack.get("system_prompt") or "",
    "provider": pack.get("provider") or "voicebox",
    "voice_id": pack.get("voice_id"),
    "voice_name": pack.get("voice_name") or pack["name"],
    "speed": pack.get("speed", 1.0),
    "temperature": pack.get("temperature", 0.7),
    "character_strength": pack.get("character_strength", 25),
    "engine": "$ENGINE",
}
req = urllib.request.Request(
    api + f"/personas/{pack['id']}",
    data=json.dumps(body).encode(),
    headers={"Content-Type": "application/json"},
    method="PUT",
)
resp = json.load(urllib.request.urlopen(req))
persona = resp.get("persona") or {}
print(json.dumps({k: persona.get(k) for k in ["id", "name", "engine", "voice_id", "provider"]}, indent=2))
assert persona.get("engine") == "$ENGINE", persona
print("OK: pack engine persisted as", persona.get("engine"))
vid = pack.get("voice_id")
if vid and str(pack.get("provider") or "").lower().startswith("voice"):
    try:
        vb = json.load(urllib.request.urlopen(f"http://127.0.0.1:17493/profiles/{vid}"))
        print("Voicebox default_engine:", vb.get("default_engine"))
    except Exception as e:
        print("Voicebox check skipped:", e)
PY

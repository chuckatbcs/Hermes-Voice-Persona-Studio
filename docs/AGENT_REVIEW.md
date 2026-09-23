# Agent review: Persona Studio speaking-persona apply

**Do not merge this pull request without Charles Blackmon (`chuckatbcs`) approval.**

Review this brief and the diff, leave findings on the PR, and stop. Do not merge, enable auto-merge, tag, deploy, or start group-chat Desktop voice work.

---

## Summary

This PR makes Hermes Voice Persona Studio apply a **speaking persona** (style overlay + cloned TTS) to the **focused profile’s current chat**, then restore **profile stock** on New Chat. Profile soul (`SOUL.md` / `AGENTS.md` / job) stays unless Character strength is 100%. The plugin lives **outside** `~/.hermes/hermes-agent`. It does **not** patch Nous Hermes, Voicebox, or Desktop group-chat playback. **Assign voice to bot** only writes profile TTS keys; the Desktop group room has no Read aloud / Speak replies controls and does not play audio.

---

## In scope

- **Unified Apply** — titlebar pick and Studio **Apply to this chat** both run resolve-tts → `session/apply` → mid-session personality refresh. Style + voice together; no TTS-only early return.
- **Character strength 0–100%** — 0% = soul only (no style overlay); 1–99 blend; 100% = session eclipse (`You are X…` ephemeral personality). Not TTS Temperature. Titlebar uses the pack’s stored percent; Studio Apply persists the slider, then applies.
- **Mid-session refresh** — after apply/reset, refresh the focused live session so Desktop sticky `currentPersonality` updates. Prefer ambient `host.request` when `host.state.profile` matches the focused profile; `requestProfile(full PluginProfileRoute)` only when not gateway-safe. Never a bare profile string. Live-applied only if `result.info != null`. **No** `host.newChat`.
- **Fish `--fish-voice` pin + cache sync** — Fish bind writes `--fish-voice <id>` plus `--fish-label` / clones map, and syncs `~/.hermes/fish_voices.json` so a stale label cannot 400 a deleted model.
- **Studio labeled layout** — Target profile → Choose persona (Fish Audio (cloud) vs Voicebox (local GPU)) → Character strength → **Apply to this chat** → Current applied state. Preview / Save pack / Reset / clone are secondary.
- **Assign voice to bot** — quieter Studio control. Surgical profile TTS keys only. Not session Apply. Does **not** enable group-room playback.

Also in this PR (supporting, already landed): session stash/restore; per-profile titlebar state; complete packs only in the titlebar; Studio hydrate + PUT save; `host.notify` (not `host.toast`); stock TTS is Edge / `en-US-AriaNeural` (never Voicebox `voice: default`).

---

## Out of scope / parked

- **Hermes Desktop group-chat Read aloud / Speak replies.** The room UI has no voice controls. Studio **Assign voice to bot** binds TTS keys on the profile; it does **not** make @mentions or round-robin debate play audio in Desktop.
- Patching `~/.hermes/hermes-agent` or the Voicebox server.
- Recreating deleted stub packs (`hermes_default`, `hermes_kitt`, `hermes_porky_pig`, storyteller) via seed or `--sync-voices`.
- A separate local Hermes **speak-stream restore** hook (not this PR).
- Merge, deploy, or starting group-chat Desktop voice work.

---

## How to test

Environment: Hermes Desktop on Promax, companion `:17495`. Fish key already configured. Voicebox `:17493` only if testing local GPU.

1. **New Chat → stock.** Profile soul (mechanic = PC repair, not Cartman/KITT) + Edge / `en-US-AriaNeural` (or that profile’s stash).
2. **Titlebar Apply.** On mechanic, pick Cartman (Fish). Toast: live refresh vs config-only. Next reply in **this** chat is Mechanic that *speaks like* Cartman (job stays). No new session.
3. **New Chat → stock again.** Overlay gone; Edge / Aria (or stash).
4. **Profile switch.** Mechanic + Cartman, then focus Magellan without applying. Titlebar stock; Magellan research soul + stock TTS (no leaked Cartman voice). Re-pick Cartman on Magellan → apply hits **magellan**.
5. **Studio Save pack.** Open Studio → Cartman hydrates → Character strength **100%** → **Save pack**. No “enter a name” alert; Studio stays open; toast 100%.
6. **Studio Apply.** Open Studio → **Target profile** is the focused bot → pick a **Fish** persona → set strength → **Apply to this chat** → toast + **Current applied state**.
7. **Assign voice to bot.** Confirm it is secondary and only writes TTS keys. Do **not** expect Desktop group rooms to play audio.
8. Offline: `python3 -m unittest test_backend.py -q`. `git status` in `~/.hermes/hermes-agent` stays clean.

---

## Known risks

- **Persist-then-apply.** Studio **Apply to this chat** PUTs/POSTs the pack (slider strength) before `session/apply`. A failed apply can still leave the pack updated.
- **Live Desktop click-through** is still on Charles. Offline tests cover helpers and source contracts, not Promax UI.
- **Speak-stream restore** was a separate local Hermes hook, not this PR. Do not treat missing group-room audio as a Studio Apply bug.
- **No true session-scoped Hermes API.** Apply writes profile `config.yaml` for one chat, then restores. If the plugin is unloaded, stash restore waits until it remounts (`session/reset-all`).
- **PyYAML fallback** (when Hermes `atomic_roundtrip_yaml_update` cannot be imported) keeps sibling keys but can drop comments / original quoting. `--purge` reverts tracked keys only; it never deletes `config.yaml`.
- **Memories / `USER.md`** mentioning another profile can still bias replies (out of band).

---

## Reviewer map (where to look)

| Area | Path |
|---|---|
| Shared apply + Studio layout | `desktop/plugin.js` (`applySpeakingBundleToProfile`, `StudioModal`) |
| Stash / overlay / strength | `backend/session_overlay.py`, `backend/persona_sync.py` |
| Fish `--fish-voice` + cache | `backend/bot_profiles.py` |
| HTTP apply / PUT / resolve-tts | `backend/api.py` |
| Offline contracts | `test_backend.py` |
| User-facing labels | `README.md` |

Hard boundary: plugin + companion only. Paths: `~/.hermes/desktop-plugins/hermes-personastudio/`, `~/.hermes/personas/` (incl. `.studio-session.json`), surgical keys in `~/.hermes/config.yaml` and `~/.hermes/profiles/*/config.yaml`. Companion: `http://127.0.0.1:17495/api/studio`.

---

## Merge gate

**Do not merge without Charles approval.** Keep this PR draft. Cloud/background agents must not merge to `main`, force-push `main`, enable auto-merge, or start the next phase.

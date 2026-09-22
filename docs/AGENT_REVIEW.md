# Agent review: unify speaking-persona apply (prompt + voice)

**Do not merge this pull request without Charles Blackmon (`chuckatbcs`) approval.**

Other agents should review this document and the diff, leave findings on the PR, and stop. Do not merge, enable auto-merge, tag, or deploy.

---

## 1. Intent / architecture

**Amended 2026-09-22 (Charles, supersedes sticky profile apply).**

A **speaking persona** is three things bound together:

1. Display name (titlebar / Studio)
2. LLM system text (`~/.hermes/personas/<id>/prompt.md`, applied through Hermes `display.personality` + `agent.personalities`)
3. Bound TTS voice (Fish Audio or local Voicebox `voice_id`)

**Session vs design vs assign:**

| Surface | Role |
|---|---|
| **New chat / new session** | Always **stock Hermes**: empty `display.personality`, **empty `agent.system_prompt`** (or the stashed pre-apply prompt), and Nous default TTS **`edge` / `en-US-AriaNeural`**. Must not inherit Studio overlays, leftover KITT/Cartman `agent.system_prompt`, Voicebox Jarvis, Fish clones, or `voice: default`. |
| **Titlebar dropdown** | Assign/apply a designed speaking persona (prompt + voice) to **this chat session only**. Not a permanent default for every future session. |
| **Persona Studio modal** | Design: create, clone, edit voices and persona bundles. Does not auto-apply on startup or companion refresh. |
| **Studio “Apply Voice to Bot”** | Group-chat bot TTS bind (profile TTS keys). Not a titlebar session default. |

Hermes Desktop exposes `host.newChat`, `host.state.focusedSessionId` / `focusedStoredSessionId`, and config-file personality overlays. There is **no session-scoped personality or TTS API**. Overlay is therefore config-file + stash/restore:

1. Dropdown apply **stashes** pre-apply `display.personality`, **`agent.system_prompt`**, and TTS (`tts.provider`, `tts.edge.voice`, Fish/Voicebox keys).
2. Writes overlay so *this* chat can speak as the chosen persona: `display.personality` + session `agent.system_prompt` + Fish-prefer TTS. Catalog `agent.personalities.<name>` dicts are **not** themselves active. Fish-prefer runs **only** on this explicit pick.
3. The next **user-initiated** new chat restores the stash, including `agent.system_prompt` (or `''` if none). If there is no usable TTS stash, restore **Hermes Edge stock**. Never leave KITT/Cartman in `agent.system_prompt`.
4. Plugin startup calls `POST /session/reset-all` so a leftover overlay cannot stick. Studio-tagged catalog entries may remain; they do nothing unless `display.personality` selects them.

**Sticky `agent.system_prompt` (Promax mechanic retest):** Charles opened a “default” session with empty `display.personality` and Edge AriaNeural and still got KITT (“I am K.I.T.T. … Knight Rider”). `~/.hermes/profiles/mechanic/config.yaml` still had `agent.system_prompt: You are K.I.T.T. from Knight Rider...`. Hermes injects that field every session, so clearing only the personality overlay is insufficient. Studio-tagged `agent.personalities.kitt` was catalog-only (not a selector). Session apply now stashes/restores `agent.system_prompt`; stock/reset writes the stashed value or `''`. Memories/`USER.md` “Active profile: kitt” can still bias the model and is out of band for this PR (Mechanic scrubbed those on Promax).

**Hard boundary:** this plugin must stay *outside* `~/.hermes/hermes-agent`. Nous Hermes updates remain a clean checkout. Studio only reads/writes:

| Path | Role |
|---|---|
| `~/.hermes/desktop-plugins/hermes-personastudio/` | Installed plugin + companion copy |
| `~/.hermes/personas/` | Portable persona bundles + `.studio-managed.json` + `.studio-session.json` |
| `~/.hermes/config.yaml` and `~/.hermes/profiles/*/config.yaml` | Surgical personality + TTS keys (session overlay, then restored) |
| `~/.config/systemd/user/hermes-personastudio.service` | Optional companion unit (marker-guarded) |

Companion HTTP API remains `http://127.0.0.1:17495/api/studio`.

---

## 2. Gap analysis (verified against repo at `939cdb7`, 2026-09-22)

Mechanic field notes from Promax were treated as hypotheses and checked against this repository (not against a live Promax filesystem).

| # | Hypothesis | Verdict |
|---|---|---|
| 1 | Titlebar `onSelectPersona` checks Voicebox clones first and **returns after TTS-only assign**, skipping `set-persona` / `prompt.md` | **Confirmed** in `desktop/plugin.js` (voice `find` + early `return`) |
| 2 | `POST /api/studio/clone` creates a provider voice only, no `~/.hermes/personas/` bundle | **Confirmed** in `backend/api.py` |
| 3 | Seeded Jarvis/Storyteller stay on Fish `voice_id: default` while real clones exist | **Confirmed** in `seed_presets.py`; sync did not exist |
| 4 | `set_profile_persona` / `assign_voice_to_profile` full `yaml.safe_dump` of `config.yaml` | **Confirmed** in `backend/bot_profiles.py` |
| 5 | `install.py --uninstall` leaves systemd unit, `personas/`, and config side effects | **Confirmed**. Uninstall only rmtree'd the plugin dir and killed `:17495`. No systemd helper existed in-tree (Promax may still have a hand-made unit) |
| 6 | Stray misnamed `plugin.py`, ~8s polling, `host.newChat` after persona set is desirable | **Polling confirmed** (`8000`). **plugin.py** is not in this git tree; install now defends against it. **`host.newChat` was not in HEAD**; it is added on the unified apply path |
| 7 | Seed path hardcoded to `/home/chuck/.hermes/personas` | **Confirmed** extra bug; now uses `HERMES_HOME` / `Path.home()` |

Not treated as a license to patch Nous: `atomic_roundtrip_yaml_update` and `render_personality_prompt` were **read from upstream `NousResearch/hermes-agent`** for compatibility only. This PR does not vendor or edit that tree.

---

## 3. Change list (paths)

| Path | What changed |
|---|---|
| `desktop/plugin.js` | Unified apply through **session overlay**. Watcher resets **only** on `focusedStoredSessionId` non-null → null (user New Chat) — not `focusedSessionId` churn. After that reset, **no** extra `host.newChat`. `applyInProgress` gates several seconds and refreshes session atoms. Apply skips newChat on blank drafts; one newChat remains for persisted sessions so `agent.system_prompt` reloads. Startup `POST /session/reset-all`. Titlebar lists **Fish + Voicebox**. Poll 60s + focus refresh. |
| `backend/session_overlay.py` | **New.** `.studio-session.json` stashes pre-apply personality, **`agent.system_prompt`**, and TTS; restore on new session. Unusable stash / first-run stock → **edge / en-US-AriaNeural**. Never writes Voicebox `voice: default` or invents Jarvis as stock. Catalog personality dicts are not active. |
| `backend/bot_profiles.py` | Surgical writes; refuse Voicebox id `default`; Edge voice read from `tts.edge.voice`. |
| `backend/api.py` | Clone returns `{voice, persona}`. `POST /sync-from-voices`, `/resolve-tts`, `/session/reset-all`, `/profiles/{id}/session/apply`, `/profiles/{id}/session/reset`. Empty prompt gets a fallback. `GET /voices` without provider returns both engines. |
| `backend/persona_sync.py` | Scored name-match (strip Fish `Hermes ` prefix). `Eric Cartman` prefers `Hermes eric_cartman` over `Hermes cartman`. Profile Fish clone-map may win. Fish-prefer resolve; do not downgrade Fish bindings to Voicebox. |
| `backend/config_io.py` | **New.** Prefer Hermes `atomic_roundtrip_yaml_update`; else PyYAML mutate-only + atomic replace. |
| `backend/managed_index.py` | **New.** `~/.hermes/personas/.studio-managed.json` snapshots prior values for purge. |
| `backend/bot_profiles.py` | Surgical writes; personality stored as `{system_prompt, source: hermes-personastudio}`; `HERMES_HOME` injectable. |
| `backend/paths.py` | **New.** Hermes home / config path helpers including `.studio-session.json`. |
| `backend/storage.py` | Ignore hidden persona dirs / `.studio-managed.json` / `.studio-session.json`. |
| `install.py` | Deploy `plugin.js` only; delete stray `plugin.py`; optional `--systemd`; default `--sync-voices`; uninstall stops unit; `--purge` reverts tracked keys and removes `personas/` (**never deletes `config.yaml`**). |
| `seed_presets.py` | Portable storage root; do not clobber existing `prompt.md`; no in-place `PRESETS` mutation. |
| `test_backend.py` | Offline tests for sync, Fish name-score, session stash/restore, Edge stock, no Voicebox `default`, surgical YAML, purge, install hygiene, **double-blank session-watch race**. |
| `README.md` | Clone ≠ TTS-only; session vs sticky; Fish-prefer; uninstall vs purge. |
| `docs/AGENT_REVIEW.md` | This file. |

---

## 4. Non-destructive guarantees

- **Nous source untouched.** No files under `~/.hermes/hermes-agent` are read for patching or written. Import of `utils.atomic_roundtrip_yaml_update` is best-effort at runtime only.
- **Plugin lives in `desktop-plugins/`**, not the agent git checkout.
- **Persona bundles** are additive under `~/.hermes/personas/`.
- **Config.yaml is never deleted**, including on `--purge`.
- **Purge** restores snapshotted prior values for keys Studio wrote (`display.personality`, `agent.personalities.<name>`, TTS provider/voice). If a key did not exist before Studio wrote it, purge deletes that key only.
- **systemd:** only a unit containing `# Managed-by: hermes-personastudio-install` (or the Studio description string) is removed. Unknown units are left in place after stop/disable is attempted.
- **Seeded prompts** are not overwritten if `prompt.md` already has content. Sync rebinds `voice_id` when a clone name-matches a seeded persona still on `default`.

---

## 5. Update persistence matrix

| Action | Disk | Hermes session |
|---|---|---|
| Titlebar pick persona | Stash `display.personality` + **`agent.system_prompt`** + TTS; overlay personality + session system_prompt + Fish-prefer TTS. Catalog dicts are not active by themselves | **One** `host.newChat` only if this session is already persisted (prompt cache). Blank drafts skip it. First prompt must **not** open a second blank |
| Titlebar pick `Name · Fish` clone | Same session overlay; explicit Fish assign | Same apply reload rule; not sticky |
| Titlebar pick `Name · Voicebox` clone | Same session overlay; explicit local GPU (slow path; user-forced) | Same apply reload rule; not sticky |
| Titlebar Standard Hermes | Restore stash, or Edge stock if no usable stash. Never `voicebox.voice: default` | `newChat` only if the current session is persisted |
| User New Chat while overlay active | Restore stash (or Edge stock); plugin watches **`focusedStoredSessionId` non-null → null**, not `focusedSessionId` churn | **No** extra `newChat` — user already has the blank |
| Plugin / Desktop startup | `POST /session/reset-all`: restore stash; leftover Studio personality cleared; Voicebox `voice: default` → Edge stock. No auto-apply | `newChat` only if a leftover overlay was actually restored |
| Companion refresh | Same startup reset. Never auto-applies a Studio persona | — |
| Studio Save Persona | Bundle under `personas/` | Not auto-applied until titlebar |
| Studio Clone | Provider clone **and** matching persona bundle | Not auto-applied |
| `POST /sync-from-voices` or `install.py --sync-voices` | Missing bundles created; name-matched seeded personas rebound | No session change |
| Studio “Apply Voice to Bot” | TTS keys only (surgical, group-chat). Does **not** write session overlay | Existing session may still use old voice until new chat |
| Install | Plugin copy + optional systemd + seed + sync | N/A |
| Uninstall (default) | Plugin removed; companion stopped; personas + config kept | N/A |
| Uninstall `--purge` | Personas dir removed (includes session stash + managed index); tracked config keys reverted; `config.yaml` files remain | N/A |

Personality values are stored as mappings so Hermes `render_personality_prompt` (upstream) can read `system_prompt`, and so purge can recognize `source: hermes-personastudio`.

---

## 6. Uninstall / purge behavior

```bash
python3 install.py --uninstall           # plugin + companion + systemd unit we installed
python3 install.py --uninstall --purge   # plus personas/ + revert tracked config keys
```

Default uninstall:

1. `systemctl --user stop/disable hermes-personastudio.service` (ignored if absent)
2. Delete the unit file **only if** it is Studio-managed
3. Remove `~/.hermes/desktop-plugins/hermes-personastudio`
4. Kill listener on `:17495`
5. Leave `~/.hermes/personas/` and Hermes YAML in place

`--purge` additionally:

1. Read `.studio-managed.json`
2. Restore each snapshotted key (or delete keys whose previous value was `null`)
3. Delete `~/.hermes/personas/` (includes the index)
4. **Does not** `rm` `config.yaml` / profile yaml files

---

## 7. Promax manual test plan (reviewers / Charles)

Environment: Hermes Desktop on Promax, companion on `:17495`, Voicebox on `:17493` if GPU TTS is in use. Fish API key already configured.

### Session vs sticky (amended intent 2026-09-22) — **do this first**

1. **New chat → stock Hermes.** Open Hermes Desktop (or click New Chat). Send a short line.
   - Expect default Hermes **text** (no Cartman/KITT/Jarvis overlay, no leftover `agent.system_prompt`).
   - Expect **Edge TTS** `en-US-AriaNeural`. Audio should play.
2. **Dropdown apply is this session only.** Pick the **persona** row for Cartman (not `Cartman · Voicebox`).
   - Expect toast that prompt + **Fish** applied to **this chat**, and that the next new chat returns to stock Hermes.
   - This session should speak as Cartman. If a Fish twin exists (`Hermes eric_cartman` preferred over `Hermes cartman`), audio should land in about ≤5 seconds (Promax Fish baseline 2.5–3.4s).
   - **Do not** get a second blank chat when sending the first prompt. `focusedSessionId` persist is not New Chat.
3. **New chat again → stock Hermes.** Click New Chat. Send a short line.
   - Expect default Hermes text + **Edge / AriaNeural** again. Cartman overlay must be gone.
   - Repeat once with Jarvis and once with KITT if those persona rows exist (`Hermes jarvis` / `Hermes kitt` Fish names).

### Latency / Fish-prefer

4. Confirm titlebar clone list includes **both** `Cartman · Fish` and `Cartman · Voicebox` (and Jarvis / KITT if those clones exist). Not Voicebox-only.
5. Persona-row apply still prefers Fish. Optional slow path: pick `Cartman · Voicebox`. Confirm local GPU is used. Do not treat Voicebox latency as a Studio bug; do not patch Voicebox in this repo.
6. After New Chat restore, TTS must be **Edge / AriaNeural** (or the real pre-apply stash), never Voicebox `voice: default`, never an invented Jarvis UUID. Mechanic’s old Fish binds / Jarvis Voicebox backup are **not** stock. Fish-prefer is only for an explicit dropdown persona/clone pick.

### Original apply / hygiene

7. Titlebar persona or clone still applies **prompt + voice** (no TTS-only early return). Apply uses session overlay, not a sticky profile default.
8. Clone in Studio still writes a persona bundle. `python3 install.py --sync-voices` is idempotent; Fish twins should win stored `voice_id` over Voicebox.
9. Polling is 60s / focus, not 8s. Installed tree has `plugin.js` and no `plugin.py`. Plugin does **not** auto-apply a Studio persona on startup or companion refresh.
10. Uninstall dry-run: plugin gone, systemd stopped, personas remain, `config.yaml` still present. `--purge` only with Charles’ OK.
11. `git status` inside `~/.hermes/hermes-agent` stays clean.

---

## 8. Merge checklist for reviewers

- [ ] Diff stays inside this repo; no hermes-agent patches; no Voicebox server patches
- [ ] Titlebar clone path cannot return after TTS-only assign
- [ ] Titlebar fetches **Fish + Voicebox** voices (not `provider=voicebox` only)
- [ ] Persona apply prefers a Fish name-twin; `Name · Voicebox` remains an explicit local choice
- [ ] `Eric Cartman` resolves `Hermes eric_cartman` over `Hermes cartman`; Jarvis/KITT match `Hermes jarvis` / `Hermes kitt`
- [ ] New chat is stock Hermes **Edge / en-US-AriaNeural** with **empty `agent.system_prompt`**; dropdown apply is session-scoped; no auto-apply on startup
- [ ] Session watcher resets overlay **only** on `focusedStoredSessionId` non-null → null; first-prompt `focusedSessionId` churn does **not** wipe or open a second blank; user New Chat does **not** call `host.newChat` again
- [ ] Session reset never writes Voicebox `voice: default` or a Studio clone as stock
- [ ] Clone API creates/updates a persona bundle
- [ ] `POST /api/studio/sync-from-voices` is idempotent and does not downgrade Fish → Voicebox
- [ ] Config writes go through `backend/config_io.py` (Hermes atomic or documented PyYAML fallback)
- [ ] Residual PyYAML risk (comments/quoting may be lost; sibling keys kept) is accepted or Hermes atomic is confirmed on Promax
- [ ] Uninstall stops systemd; `--purge` never deletes whole `config.yaml`
- [ ] `plugin.py` cannot remain in the install tree
- [ ] Offline `python3 -m unittest test_backend.py -v` passes
- [ ] README documents session vs sticky apply and Fish-prefer
- [ ] **Charles (`chuckatbcs`) explicitly approves merge**

---

## 9. Explicit merge gate

**Do not merge without Charles approval.**

This PR is for human + agent review only. Cloud/background agents must not merge to `main`, force-push `main`, enable auto-merge, or start the next phase.

---

## 10. Latency finding (Promax 2026-09-22) — Fish-prefer policy

Charles verified PR #1 apply intent on Promax: `set-persona` + `assign-voice` both run. Spoken **audio latency** was still unacceptable when the titlebar bound **Voicebox / Qwen** clones.

| Observation | Detail |
|---|---|
| Titlebar voice refresh | Hit `GET /api/studio/voices?provider=voicebox` only — Fish clones were not offered |
| Same short Cartman line | Fish Audio ≈ 2.5–3.4s; Voicebox Qwen `/generate/stream` still generating after **2+ minutes** (GPU busy, open-end generation / code_predictor init) |
| Older Voicebox TTS | Historically 5–70s; current Qwen path can hang multi-minute |
| Mechanic interim (superseded) | Earlier Fish binds and a Voicebox Jarvis restore from backup were **not** stock. Charles corrected Promax default+mechanic to **edge / en-US-AriaNeural** with empty `display.personality`. Edge smoke TTS ~0.9s. |

**Policy now implemented**

1. Titlebar (and Studio option labels) list **Fish + Voicebox**, marked `Name · Fish` vs `Name · Voicebox`.
2. Applying a **persona** (or a non-explicit clone) resolves a Fish twin by name / explicit Fish `voice_id` before `assign-voice`. Fish-prefer is **only** for that explicit dropdown pick — it is not stock and must not run on new-chat restore.
3. Bundles that still store a Voicebox UUID are fine; apply-time resolve still binds Fish when a twin exists.
4. Choosing `Name · Voicebox` sets `explicit=true` and **forces** local GPU (Charles can opt in).
5. Sync/ensure will not downgrade an existing Fish bundle binding to Voicebox.
6. Voicebox **server** code is out of scope (lives elsewhere). This repo does not patch Nous `hermes-agent`.

Name matching for Fish twins (Promax catalog uses names like `Hermes jarvis`, `Hermes kitt`, `Hermes eric_cartman` / `Hermes cartman`):

- Strip a leading `hermes_` token before scoring.
- Exact slug / equal token set beat subsets, so persona **Eric Cartman** prefers `eric_cartman` when both `cartman` and `eric_cartman` exist.
- Profile `tts.providers.fish.clones` keys are consulted first when they score against the persona name.

---

## Residual risk (PyYAML fallback)

When `~/.hermes/hermes-agent/utils.py::atomic_roundtrip_yaml_update` cannot be imported (missing ruamel, import collision, etc.), Studio still mutates **only** the dotted keys it owns, then atomically replaces the file via `yaml.safe_dump`. That preserves unrelated mapping keys and values but **can drop comments and original scalar quoting**. It is still strictly better than the previous “load entire doc, dump entire doc with no strategy tag or prior-value index,” and `--purge` can revert the keys Studio recorded.

**Session overlay residual:** Hermes has no true session-scoped personality/TTS API. Apply still writes profile `config.yaml` for the duration of one chat, then restores. If the plugin is not loaded, a user-initiated New Chat will not restore the stash until the plugin mounts (startup `reset-all`). Opening a stored history session restores config without an extra `newChat`. First-prompt `focusedSessionId` persist must not look like New Chat. Apply on a blank draft skips `host.newChat`; if Hermes had already cached stock `agent.system_prompt` for that draft, the first turn might still be stock text until a later session — persisted threads still get one reload newChat (see §11).

**Silent TTS (Promax `20260922_094441_564b69`):** stock/reset wrote Voicebox `voice: default`. Command TTS used `--voice default`, 404'd a stale process-global active-voice UUID (`151b6710-8f59-4366-9410-0b3044ded982`), and played no audio. Reset must never emit that placeholder; first-run stock is Edge AriaNeural, not Voicebox Jarvis.

**False “default session is KITT” (Promax mechanic retest):** empty `display.personality` + Edge Aria was not enough. Leftover `agent.system_prompt` (KITT) is injected every session. Reset must stash/restore that key (or `''`). Do not treat `agent.personalities.kitt` as active. Memory files mentioning “Active profile: kitt” can still bias replies until scrubbed outside this plugin.

---

## 11. Double-blank session race (Promax 2026-09-22)

Companion log: dropdown `session/apply` then overlay **reset ~5–18s later** when the first user turn starts. Charles picked a persona (plugin called `host.newChat` after apply), sent the first prompt, and the plugin immediately opened **another** blank session.

### Root cause

`desktop/plugin.js` `onSessionChange` treated **any** `focusedSessionId` string change while `overlay.active` as user New Chat, then `resetSessionOverlay` and sometimes `host.newChat` again. Hermes **renumbers/persists** `focusedSessionId` on first prompt. `applyInProgress` was only **500ms**, so it had already expired → mid-turn wipe.

`focusedStoredSessionId` is the durable signal: it goes **non-null → null/empty** when the user actually clicks New Chat. First-prompt persist does the opposite (null → stored id) or only churns `focusedSessionId`.

### Required behavior (Mechanic Promax hotfix reconciled here)

| Event | Overlay | Extra `host.newChat` |
|---|---|---|
| User New Chat (`focusedStoredSessionId` non-null → null/empty) | Reset to stock Hermes | **No** — user already has the blank chat |
| First prompt persist (`focusedSessionId` churn; stored id null → uuid) | Keep speaking persona | **No** |
| Apply gate in progress (apply + optional one newChat, several seconds) | Refresh `sessionId` / `storedId`; do not reset | Only the optional apply reload below |
| Dropdown apply on a **blank draft** (no stored id) | Write overlay; keep this draft | **No** — yaml is current for the first turn |
| Dropdown apply on a **persisted** session | Write overlay | **One** `host.newChat` so Hermes reloads `agent.system_prompt` (injected at session start; no session-scoped API) |

`applyInProgress` stays true for `APPLY_GATE_MS` (**8000ms**, not 500ms) across apply + that optional one newChat, and the watcher **refreshes** `sessionId`/`storedId` while gated so apply’s own newChat (stored id S1 → null) is not mistaken for user New Chat.

Do **not** regress to “any `focusedSessionId` change while overlay.active ⇒ New Chat”.

### Why one newChat after apply can still happen

Hermes injects `agent.system_prompt` when a session starts. Overlay writes `config.yaml` after that. If the user is already in a **persisted** thread, skipping newChat would leave stock/cached prompt on the current history. Blank drafts skip newChat so picking a persona does not stack chats. Items (1)–(3) above still prevent the second blank when the first prompt persists the session.

Offline coverage: `TestPluginSessionWatchRace` in `test_backend.py` executes the JS helpers via `node` and asserts the watcher body never calls `startNewChat` after user New Chat.

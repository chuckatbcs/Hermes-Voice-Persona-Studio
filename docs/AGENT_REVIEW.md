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
| **New chat / new session** | Always **stock Hermes** text + voice. Must not inherit Voice Persona Studio overlays, Studio-managed `display.personality` / `agent.personalities` selection, or Studio-assigned Fish/Voicebox binds from a previous dropdown pick. |
| **Titlebar dropdown** | Assign/apply a designed speaking persona (prompt + voice) to **this chat session only**. Not a permanent default for every future session. |
| **Persona Studio modal** | Design: create, clone, edit voices and persona bundles. Does not auto-apply on startup or companion refresh. |
| **Studio “Apply Voice to Bot”** | Group-chat bot TTS bind (profile TTS keys). Not a titlebar session default. |

Hermes Desktop exposes `host.newChat`, `host.state.focusedSessionId` / `focusedStoredSessionId`, and config-file personality overlays. There is **no session-scoped personality or TTS API**. Overlay is therefore config-file + stash/restore:

1. Dropdown apply **stashes** pre-apply `display.personality` + TTS provider/voice.
2. Writes overlay so *this* chat can speak as the chosen persona (`host.newChat` refreshes Hermes prompt cache for that apply).
3. The next **user-initiated** new chat restores the stash (stock Hermes). Plugin watches `focusedSessionId` and ignores the apply’s own `newChat`.
4. Plugin startup calls `POST /session/reset-all` so a leftover overlay cannot stick across Desktop restarts. It does **not** auto-apply any Studio persona.

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
| `desktop/plugin.js` | Unified apply through **session overlay** (stash + apply + watch next new chat). Clone **or** persona → ensure bundle → Fish-prefer `resolve-tts` → `POST .../session/apply` → `host.newChat` for *this* session only. Startup `POST /session/reset-all` (no auto-apply). Titlebar lists **Fish + Voicebox**. Poll 60s + focus refresh. |
| `backend/session_overlay.py` | **New.** `~/.hermes/personas/.studio-session.json` stashes pre-apply personality + TTS; restore on new session / Standard Hermes / plugin startup. |
| `backend/api.py` | Clone returns `{voice, persona}`. `POST /sync-from-voices`, `/resolve-tts`, `/session/reset-all`, `/profiles/{id}/session/apply`, `/profiles/{id}/session/reset`. Empty prompt gets a fallback. `GET /voices` without provider returns both engines. |
| `backend/persona_sync.py` | Scored name-match (strip Fish `Hermes ` prefix). `Eric Cartman` prefers `Hermes eric_cartman` over `Hermes cartman`. Profile Fish clone-map may win. Fish-prefer resolve; do not downgrade Fish bindings to Voicebox. |
| `backend/config_io.py` | **New.** Prefer Hermes `atomic_roundtrip_yaml_update`; else PyYAML mutate-only + atomic replace. |
| `backend/managed_index.py` | **New.** `~/.hermes/personas/.studio-managed.json` snapshots prior values for purge. |
| `backend/bot_profiles.py` | Surgical writes; personality stored as `{system_prompt, source: hermes-personastudio}`; `HERMES_HOME` injectable. |
| `backend/paths.py` | **New.** Hermes home / config path helpers including `.studio-session.json`. |
| `backend/storage.py` | Ignore hidden persona dirs / `.studio-managed.json` / `.studio-session.json`. |
| `install.py` | Deploy `plugin.js` only; delete stray `plugin.py`; optional `--systemd`; default `--sync-voices`; uninstall stops unit; `--purge` reverts tracked keys and removes `personas/` (**never deletes `config.yaml`**). |
| `seed_presets.py` | Portable storage root; do not clobber existing `prompt.md`; no in-place `PRESETS` mutation. |
| `test_backend.py` | Offline tests for sync, Fish name-score, session stash/restore, leftover personality clear, surgical YAML, purge, install hygiene. |
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
| Titlebar pick persona | Stash stock personality + TTS into `.studio-session.json`; overlay `display.personality` + Fish-prefer TTS on the profile config | `host.newChat(profile)` so **this** chat picks up Cartman/Jarvis/KITT. Next **user** new chat restores stash → stock Hermes |
| Titlebar pick `Name · Fish` clone | Same session overlay; explicit Fish assign | Same apply `newChat`; not sticky |
| Titlebar pick `Name · Voicebox` clone | Same session overlay; explicit local GPU (slow path; user-forced) | Same apply `newChat`; not sticky |
| Titlebar Standard Hermes | Restore stash (clear overlay + prior TTS). TTS is not left on the Studio voice | `newChat` after restore |
| User New Chat while overlay active | Restore stash; plugin watches `focusedSessionId` (ignores apply’s own `newChat`; skips extra `newChat` when opening a stored history session) | New draft is stock Hermes |
| Plugin / Desktop startup | `POST /session/reset-all`: restore any active stash; if no stash, clear leftover Studio-tagged `display.personality` **without** touching TTS (Mechanic Fish binds stay) | No auto-apply. `newChat` only if a leftover overlay was actually restored |
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
   - Expect default Hermes **text** (no Cartman/KITT/Jarvis overlay).
   - Expect default Hermes **voice** (not a Studio dropdown bind from last time).
2. **Dropdown apply is this session only.** Pick the **persona** row for Cartman (not `Cartman · Voicebox`).
   - Expect toast that prompt + **Fish** applied to **this chat**, and that the next new chat returns to stock Hermes.
   - This session should speak as Cartman. If a Fish twin exists (`Hermes eric_cartman` preferred over `Hermes cartman`), audio should land in about ≤5 seconds (Promax Fish baseline 2.5–3.4s).
3. **New chat again → stock Hermes.** Click New Chat. Send a short line.
   - Expect default Hermes text + voice again. Cartman overlay must be gone.
   - Repeat once with Jarvis and once with KITT if those persona rows exist (`Hermes jarvis` / `Hermes kitt` Fish names).

### Latency / Fish-prefer

4. Confirm titlebar clone list includes **both** `Cartman · Fish` and `Cartman · Voicebox` (and Jarvis / KITT if those clones exist). Not Voicebox-only.
5. Persona-row apply still prefers Fish. Optional slow path: pick `Cartman · Voicebox`. Confirm local GPU is used. Do not treat Voicebox latency as a Studio bug; do not patch Voicebox in this repo.
6. Mechanic’s interim Fish binds on default (`eric_cartman`) and mechanic (`kitt`) must remain Fish after a **new chat restore** — stash/restore must put back the pre-dropdown TTS, not wipe Mechanic binds on leftover-reset-without-stash.

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
- [ ] New chat is stock Hermes; dropdown apply is session-scoped (stash/restore); no auto-apply on startup
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
| Mechanic interim | Switched `tts.provider` to `fish` for default (`eric_cartman`) and mechanic (`kitt`). **Do not revert that in code.** Product path must prefer Fish so later titlebar picks do not flip those profiles back to Voicebox |

**Policy now implemented**

1. Titlebar (and Studio option labels) list **Fish + Voicebox**, marked `Name · Fish` vs `Name · Voicebox`.
2. Applying a **persona** (or a non-explicit clone) resolves a Fish twin by name / explicit Fish `voice_id` before `assign-voice`.
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

**Session overlay residual:** Hermes has no true session-scoped personality/TTS API. Apply still writes profile `config.yaml` for the duration of one chat, then restores. If the plugin is not loaded, a user-initiated New Chat will not restore the stash until the plugin mounts (startup `reset-all`). Opening a stored history session restores config without an extra `newChat`, so continuing that history may use stock TTS while old messages stay as they were. Leftover overlay **without** a stash only clears Studio-tagged `display.personality` and leaves TTS (so Mechanic Fish binds are not guessed away).

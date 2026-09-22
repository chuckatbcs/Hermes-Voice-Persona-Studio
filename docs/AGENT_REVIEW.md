# Agent review: unify speaking-persona apply (prompt + voice)

**Do not merge this pull request without Charles Blackmon (`chuckatbcs`) approval.**

Other agents should review this document and the diff, leave findings on the PR, and stop. Do not merge, enable auto-merge, tag, or deploy.

---

## 1. Intent / architecture

A **speaking persona** is three things bound together:

1. Display name (titlebar / Studio)
2. LLM system text (`~/.hermes/personas/<id>/prompt.md`, applied through Hermes `display.personality` + `agent.personalities`)
3. Bound TTS voice (Fish Audio or local Voicebox `voice_id`)

Users switch it from the Hermes Desktop titlebar control and create it in Studio.

**Hard boundary:** this plugin must stay *outside* `~/.hermes/hermes-agent`. Nous Hermes updates remain a clean checkout. Studio only reads/writes:

| Path | Role |
|---|---|
| `~/.hermes/desktop-plugins/hermes-personastudio/` | Installed plugin + companion copy |
| `~/.hermes/personas/` | Portable persona bundles + `.studio-managed.json` |
| `~/.hermes/config.yaml` and `~/.hermes/profiles/*/config.yaml` | Surgical personality + TTS keys |
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
| `desktop/plugin.js` | Unified apply: clone **or** persona → ensure bundle → `set-persona` + `assign-voice` → `host.newChat`. Personas listed first. Poll 60s + focus refresh. Clone success refreshes personas. |
| `backend/api.py` | Clone returns `{voice, persona}`. `POST /api/studio/sync-from-voices`. Empty prompt gets a fallback. |
| `backend/persona_sync.py` | **New.** Slug/name-match, generic-description filter, idempotent ensure/sync. |
| `backend/config_io.py` | **New.** Prefer Hermes `atomic_roundtrip_yaml_update`; else PyYAML mutate-only + atomic replace. |
| `backend/managed_index.py` | **New.** `~/.hermes/personas/.studio-managed.json` snapshots prior values for purge. |
| `backend/bot_profiles.py` | Surgical writes; personality stored as `{system_prompt, source: hermes-personastudio}`; `HERMES_HOME` injectable. |
| `backend/paths.py` | **New.** Hermes home / config path helpers. |
| `backend/storage.py` | Ignore hidden persona dirs / `.studio-managed.json`. |
| `install.py` | Deploy `plugin.js` only; delete stray `plugin.py`; optional `--systemd`; default `--sync-voices`; uninstall stops unit; `--purge` reverts tracked keys and removes `personas/` (**never deletes `config.yaml`**). |
| `seed_presets.py` | Portable storage root; do not clobber existing `prompt.md`; no in-place `PRESETS` mutation. |
| `test_backend.py` | Offline tests for sync idempotence, rebind, surgical YAML, purge restore, install hygiene. |
| `README.md` | Clone ≠ TTS-only; titlebar apply; uninstall vs purge; new API. |
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
| Titlebar pick persona | `personas/<id>/` unchanged; profile `config.yaml` gets personality dict + `display.personality`; TTS voice keys if `voice_id` ≠ `default` | `host.newChat(profile)` after successful text write so prompt-cache/session overlay refreshes |
| Titlebar pick clone | If no matching bundle: `POST /personas` writes `prompt.md` + `manifest.json`. Then same as persona pick | Same `newChat` |
| Titlebar Standard Hermes | `display.personality: ""` (neutral). TTS left as-is | `newChat` after clear |
| Studio Save Persona | Bundle under `personas/` | Not auto-applied until titlebar/assign |
| Studio Clone | Provider clone **and** matching persona bundle | Not auto-applied |
| `POST /sync-from-voices` or `install.py --sync-voices` | Missing bundles created; name-matched seeded personas rebound | No session change |
| `assign-voice` / Studio “Apply Voice to Bot” | TTS keys only (surgical) | Existing session may still use old voice until new chat |
| Install | Plugin copy + optional systemd + seed + sync | N/A |
| Uninstall (default) | Plugin removed; companion stopped; personas + config kept | N/A |
| Uninstall `--purge` | Personas dir removed; tracked config keys reverted; `config.yaml` files remain | N/A |

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

Environment: Hermes Desktop on Promax, companion on `:17495`, Voicebox on `:17493` if GPU TTS is in use.

1. **Titlebar clone → both text and voice**
   - Open a chat on profile `default` (or mechanic).
   - Pick a Voicebox clone (Cartman / Jarvis / Voldemort) from the titlebar.
   - Expect toast “Prompt + voice applied”.
   - Confirm `~/.hermes/personas/<slug>/prompt.md` exists and is the session overlay (new chat opened).
   - Confirm profile `config.yaml` `display.personality` is the slug and `tts.providers.voicebox.voice` is the clone UUID — **not** TTS-only with an unchanged personality.
2. **Titlebar persona**
   - Pick seeded Jarvis / Storyteller / Cartman.
   - Expect prompt from disk `prompt.md` plus bound voice when `voice_id` ≠ `default`.
3. **Clone in Studio**
   - Clone a new name. Response / status should mention a speaking persona, not just a voice.
   - `GET /api/studio/personas` lists the new bundle with that `voice_id`.
4. **Sync existing clones**
   - `python3 install.py --sync-voices` (idempotent). Jarvis/Storyteller should rebind off Fish `default` if a matching clone exists.
5. **Polling / hygiene**
   - Titlebar should not hammer `/personas` every 8s (60s or window focus).
   - Installed plugin dir has `plugin.js` and **no** `plugin.py`.
6. **Uninstall dry-run / real**
   - `python3 install.py --uninstall` → plugin gone, systemd stopped, personas remain, `config.yaml` still present.
   - Only with Charles’ OK: `--purge` on a throwaway profile and confirm tracked keys revert and `personas/` is gone, yaml files still exist.
7. **Nous checkout**
   - `git status` inside `~/.hermes/hermes-agent` stays clean.

---

## 8. Merge checklist for reviewers

- [ ] Diff stays inside this repo; no hermes-agent patches
- [ ] Titlebar clone path cannot return after TTS-only assign
- [ ] Clone API creates/updates a persona bundle
- [ ] `POST /api/studio/sync-from-voices` is idempotent
- [ ] Config writes go through `backend/config_io.py` (Hermes atomic or documented PyYAML fallback)
- [ ] Residual PyYAML risk (comments/quoting may be lost; sibling keys kept) is accepted or Hermes atomic is confirmed on Promax
- [ ] Uninstall stops systemd; `--purge` never deletes whole `config.yaml`
- [ ] `plugin.py` cannot remain in the install tree
- [ ] Offline `python3 -m unittest test_backend.py -v` passes
- [ ] README does not claim that cloning a voice *alone* used to be a speaking persona; it documents the bundle
- [ ] **Charles (`chuckatbcs`) explicitly approves merge**

---

## 9. Explicit merge gate

**Do not merge without Charles approval.**

This PR is for human + agent review only. Cloud/background agents must not merge to `main`, force-push `main`, enable auto-merge, or start the next phase.

---

## Residual risk (PyYAML fallback)

When `~/.hermes/hermes-agent/utils.py::atomic_roundtrip_yaml_update` cannot be imported (missing ruamel, import collision, etc.), Studio still mutates **only** the dotted keys it owns, then atomically replaces the file via `yaml.safe_dump`. That preserves unrelated mapping keys and values but **can drop comments and original scalar quoting**. It is still strictly better than the previous “load entire doc, dump entire doc with no strategy tag or prior-value index,” and `--purge` can revert the keys Studio recorded.

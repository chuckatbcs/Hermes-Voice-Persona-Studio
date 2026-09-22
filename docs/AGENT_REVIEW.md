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
| `desktop/plugin.js` | Unified apply: clone **or** persona → ensure bundle → `set-persona` + Fish-prefer `assign-voice` → `host.newChat`. Titlebar lists **Fish + Voicebox** clones with `Name · Fish` / `Name · Voicebox` labels. Personas listed first. Poll 60s + focus refresh. |
| `backend/api.py` | Clone returns `{voice, persona}`. `POST /api/studio/sync-from-voices`. `POST /api/studio/resolve-tts`. Empty prompt gets a fallback. `GET /voices` without provider returns both engines. |
| `backend/persona_sync.py` | Slug/name-match, Fish-prefer resolve, do not downgrade Fish bindings to Voicebox, generic-description filter, idempotent ensure/sync. |
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
| Titlebar pick persona | `personas/<id>/` unchanged; profile `config.yaml` gets personality dict + `display.personality`; TTS prefers a **Fish** same-name clone when one exists | `host.newChat(profile)` after successful text write so prompt-cache/session overlay refreshes |
| Titlebar pick `Name · Fish` clone | Same as persona; explicit Fish assign | Same `newChat` |
| Titlebar pick `Name · Voicebox` clone | Explicit local GPU assign (slow path; user-forced) | Same `newChat` |
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

Environment: Hermes Desktop on Promax, companion on `:17495`, Voicebox on `:17493` if GPU TTS is in use. Fish API key already configured.

### Latency / Fish-prefer (2026-09-22 follow-up)

1. Confirm titlebar clone list includes **both** `Cartman · Fish` and `Cartman · Voicebox` (and Jarvis / KITT if those clones exist). Not Voicebox-only.
2. Pick the **persona** row for Cartman / Jarvis / KITT (not the Voicebox clone row).
   - Expect toast mentioning **Fish**.
   - Profile `config.yaml` has `tts.provider: fish` and a Fish clone label — not `voicebox` unless you picked the Voicebox row.
   - Spoken reply to a short line should land in **about ≤5 seconds** on Fish (Promax baseline 2.5–3.4s). Time it.
3. Optional slow path: pick `Cartman · Voicebox`. Confirm local GPU is used. This may take a long time (historically 5–70s; Qwen `/generate/stream` has hung 2+ minutes). Do not treat Voicebox latency as a Studio bug; do not patch Voicebox in this repo.
4. Mechanic’s interim Fish binds on default (`eric_cartman`) and mechanic (`kitt`) must remain Fish after a persona titlebar pick — this change must not silently flip them back to Voicebox.

### Original apply / hygiene

5. Titlebar persona or clone still applies **prompt + voice**, then `host.newChat`.
6. Clone in Studio still writes a persona bundle. `python3 install.py --sync-voices` is idempotent; Fish twins should win stored `voice_id` over Voicebox.
7. Polling is 60s / focus, not 8s. Installed tree has `plugin.js` and no `plugin.py`.
8. Uninstall dry-run: plugin gone, systemd stopped, personas remain, `config.yaml` still present. `--purge` only with Charles’ OK.
9. `git status` inside `~/.hermes/hermes-agent` stays clean.

---

## 8. Merge checklist for reviewers

- [ ] Diff stays inside this repo; no hermes-agent patches; no Voicebox server patches
- [ ] Titlebar clone path cannot return after TTS-only assign
- [ ] Titlebar fetches **Fish + Voicebox** voices (not `provider=voicebox` only)
- [ ] Persona apply prefers a Fish name-twin; `Name · Voicebox` remains an explicit local choice
- [ ] Clone API creates/updates a persona bundle
- [ ] `POST /api/studio/sync-from-voices` is idempotent and does not downgrade Fish → Voicebox
- [ ] Config writes go through `backend/config_io.py` (Hermes atomic or documented PyYAML fallback)
- [ ] Residual PyYAML risk (comments/quoting may be lost; sibling keys kept) is accepted or Hermes atomic is confirmed on Promax
- [ ] Uninstall stops systemd; `--purge` never deletes whole `config.yaml`
- [ ] `plugin.py` cannot remain in the install tree
- [ ] Offline `python3 -m unittest test_backend.py -v` passes
- [ ] README documents Fish-prefer apply and does not claim clone-alone is a speaking persona
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

---

## Residual risk (PyYAML fallback)

When `~/.hermes/hermes-agent/utils.py::atomic_roundtrip_yaml_update` cannot be imported (missing ruamel, import collision, etc.), Studio still mutates **only** the dotted keys it owns, then atomically replaces the file via `yaml.safe_dump`. That preserves unrelated mapping keys and values but **can drop comments and original scalar quoting**. It is still strictly better than the previous “load entire doc, dump entire doc with no strategy tag or prior-value index,” and `--purge` can revert the keys Studio recorded.

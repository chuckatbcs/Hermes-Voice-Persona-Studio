# Agent review: unify speaking-persona apply (prompt + voice)

**Do not merge this pull request without Charles Blackmon (`chuckatbcs`) approval.**

Other agents should review this document and the diff, leave findings on the PR, and stop. Do not merge, enable auto-merge, tag, or deploy.

---

## 1. Intent / architecture

**Amended 2026-09-22 (Charles, supersedes sticky profile apply *and* identity replacement).**

A **speaking persona** is three things bound together:

1. Display name (titlebar / Studio)
2. **Speaking-style overlay** (`~/.hermes/personas/<id>/prompt.md` mannerisms, applied through Hermes `display.personality` + `agent.personalities.<name>.system_prompt`)
3. Bound TTS voice (Fish Audio or local Voicebox `voice_id`)

**Profile soul stays primary. Studio does not replace who the bot is.**

| Surface | Role |
|---|---|
| **Profile selected** | **Stock profile identity.** Hermes profile defaults, `SOUL.md`, `AGENTS.md`, and stock persona modals. No Studio identity replacement. |
| **Titlebar dropdown apply** | **Style + voice overlay only** for **this chat session**. Keep the profile’s soul/job/skills. Overlay speaking mannerisms/tone from the Studio persona **and** bind the cloned TTS voice (Fish-prefer). Mechanic + Cartman ⇒ **Mechanic that speaks like Cartman** (snarky Cartman tone, still does PC repair). Research agent + Jarvis ⇒ **researches per its Hermes soul/AGENTS.md, replies/speaks like Jarvis**. |
| **New chat / no Studio overlay** | Back to **profile stock** (soul + Edge/`en-US-AriaNeural` or stashed profile TTS). Empty `display.personality`. User-owned `agent.system_prompt` restored from stash (or left alone). Must not inherit Studio style, leftover KITT/Cartman identity text, Voicebox Jarvis, or `voice: default`. |
| **Persona Studio modal** | Design: create, clone, edit voices and persona bundles. Does not auto-apply on startup or companion refresh. Bundles store **mannerism** text, not “You are X” identity. |
| **Studio “Apply Voice to Bot”** | Group-chat bot TTS bind (profile TTS keys). Not a titlebar session default. |

**Promax symptom (Charles, mechanic + Cartman):** TTS was Cartman voice; reply text stayed PC-Mechanic (SOUL) and was **not** snarky Cartman. Voice applied; speaking-style overlay did not land (or fought SOUL). Root cause: `apply_session_overlay` wrote full `agent.system_prompt` = “You are Eric Cartman…” which **replaces/competes** with identity instead of adding mannerisms. Cartman `prompt.md` was also full-identity text.

**Hermes mechanics (do not fight these)** — `hermes_cli/personality.py`:

- `display.personality` = selected NAME; empty = no overlay.
- Personality path must **not** own `agent.system_prompt` (user-owned). Hermes resolves ephemeral as the named personality prompt, else `agent.system_prompt`.
- Ephemeral overlays are injected at API-call time; **SOUL.md remains primary identity** in prompt assembly.

**Apply path now:**

1. Stash pre-apply `display.personality`, user-owned `agent.system_prompt`, and TTS.
2. Build session personality text from **Character strength 0–100** (not TTS Temperature). **0%** = no `SPEAKING STYLE OVERLAY` / clear `display.personality` (soul only; TTS may still bind). **1–40** soft mannerisms, SOUL primary. **41–70** medium blend. **71–99** character-heavy, SOUL job secondary. **100%** = full character eclipse (`You are X…` ephemeral personality; instruct the model that SOUL/AGENTS do not apply). Cannot patch Hermes prompt assembly — 100% is the strongest overlay this plugin can write. Persist 0–100 on the pack (legacy soft→25, medium→55, strong→85). **Do not** write character identity into user-owned `agent.system_prompt` (clear only if Studio-injected).
3. Bind Fish-prefer TTS as before.
4. Next **user** New Chat restores stash (personality + user `agent.system_prompt` + TTS). Catalog dicts may remain; they do nothing unless selected.
5. **Per-profile Studio state.** Switching `focusedSessionProfile` (mechanic → Magellan) does **not** imply the previous persona is active. Titlebar resets to `default` for the newly focused profile, or restores **that** profile’s own overlay if session state says it is active. Apply always writes the currently focused profile only. Re-selecting Cartman after a switch applies style + Fish-prefer voice on the **new** profile.

**Promax Magellan retest (Charles):** dropdown still showed Cartman after switching bots. Magellan replied as normal Magellan research soul (no snark); TTS sounded like Cartman. Companion `session/apply` only hit **mechanic**, never **magellan**. Magellan config had no `display.personality` / Studio catalog, leftover Voicebox Cartman id `c9da87b0-…`, leftover `agent.system_prompt` flirty text, and session state only tracked mechanic/eric_cartman. Cartman in the dropdown was **UI-only**; voice came from Magellan leftover Voicebox bind, not a successful Studio apply. Voice without speaking-style overlay is **unacceptable**. Profile-switch must not leave another profile’s persona selected without applying it, and must not leak that profile’s TTS onto the newly focused bot (stock until the user picks again). Mechanic already reset Magellan to Edge/AriaNeural + cleared personality/system_prompt for stock.

**Promax critic retest (Charles):** inverse of Magellan — **stock Edge voice** but **Cartman personality in the reply**. Critic `display.personality: cartman` (not `eric_cartman`), TTS already Edge/AriaNeural, leftover `agent.system_prompt` KITT text, and critic was **not** in `.studio-session.json`. Profile-switch `session/reset` ran, but leftover clear only emptied `display.personality` when `agent.personalities.<name>.source` was Studio-tagged. Untagged Hermes catalog name `cartman` survived → style without matching voice. No-stash stock now **always** sets `display.personality: ""` (catalog dicts stay). KITT leftover in `agent.system_prompt` is still only cleared when Studio-injected; Mechanic already stock-reset critic on Promax.

**Character strength (Charles, 2026-09-22, amended):** 0–100% slider. **0% = profile soul only** (no style overlay). **100% = character completely eclipses SOUL.md / AGENTS.md for this session.** Intermediate values blend. Soft/Medium/Heavy are snap labels only. Titlebar apply sends the pack’s stored percent. Temperature stays TTS-only. **100% overlay wording (Charles, Promax critic):** hardened name-lock + “this block wins” + closing “You are {label}. Your name is {label}.” so “Who are you?” answers Cartman/Jarvis, not Critic/Mechanic — still no Hermes SOUL patch.

**Studio save / layout (Charles, Promax):** selecting Cartman did not hydrate `name`, so Save Persona alerted “Please enter a name.” Studio now hydrates the selected pack (name, prompt, strength, voice), **PUT** `/personas/{id}` updates in place, empty name falls back to the pack name, and Studio stays open after save. Window is sectioned top→bottom: Pick pack → Personality (LLM + strength) → Voice (TTS) → Clone → Apply/save. Notifications use Hermes `host.notify({ kind, message, title })` (not `host.toast`); save success cannot throw after a successful PUT/POST.

**Titlebar packs only (Charles, 2026-09-22):** hide voice-only clones that are not backed by a persona pack. After Promax cleanup, complete packs are amanda, cartman, flirty, jarvis, sexy_girl, vincent_price, voldemort. Incomplete stubs (hermes_default, hermes_porky_pig, kitt, storyteller) were deleted — do not auto-reseed them. Titlebar lists **complete packs** (non-stub prompt + usable cloned `voice_id`, or a Fish twin of that pack) plus Standard Hermes + Open Studio. Voice-only orphans stay in Studio for cloning/editing. **`install.py --sync-voices` must not recreate those deleted stubs** from name-only Fish clones (`Hermes kitt`); sync/ensure only create a pack when `fallback_system_prompt` is non-stub, but still rebind `voice_id` on existing cartman/jarvis.

**Sticky leftover `agent.system_prompt` (earlier Promax mechanic retest):** empty `display.personality` + Edge Aria still answered as KITT because leftover `agent.system_prompt: You are K.I.T.T....` is used when no personality is named. Reset still stashes/restores that user-owned field (or `''` if the leftover matched a Studio catalog overlay). Studio must not put Cartman/KITT identity back into it on apply. Memories/`USER.md` “Active profile: kitt” can still bias the model (out of band).

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
| 6 | Stray misnamed `plugin.py`, ~8s polling, `host.newChat` after persona set is desirable | **Polling confirmed** (`8000`). **plugin.py** is not in this git tree; install now defends against it. **`host.newChat` after apply is not desired** (Charles 2026-09-22): apply stays in the current session |
| 7 | Seed path hardcoded to `/home/chuck/.hermes/personas` | **Confirmed** extra bug; now uses `HERMES_HOME` / `Path.home()` |

Not treated as a license to patch Nous: `atomic_roundtrip_yaml_update` and `render_personality_prompt` were **read from upstream `NousResearch/hermes-agent`** for compatibility only. This PR does not vendor or edit that tree.

---

## 3. Change list (paths)

| Path | What changed |
|---|---|
| `desktop/plugin.js` | Unified apply through **session overlay**. Apply / Standard Hermes / startup **never** call `host.newChat`. Watcher resets **only** on stored-id New Chat. **Per-profile titlebar.** Titlebar lists **complete persona packs only**. Studio is a top-to-bottom workflow; selecting a pack hydrates the form; Save **PUT**s existing packs (strength persists) and stays open. |
| `backend/session_overlay.py` | **New.** Stash/restore personality + user `agent.system_prompt` + TTS. Apply writes a **style overlay** catalog entry + `display.personality` + Fish-prefer TTS. Accepts **character_strength**. Does **not** clobber user `agent.system_prompt` with “You are Cartman”. Unusable stash → Edge AriaNeural. No-stash leftover reset **always** clears `display.personality` (untagged `cartman` included); `agent.system_prompt` only when Studio-injected. |
| `backend/bot_profiles.py` | Surgical writes; refuse Voicebox id `default`; catalog `system_prompt` is the style overlay (`source: hermes-personastudio`). |
| `backend/api.py` | Clone returns `{voice, persona}`. `PUT /personas/{id}` updates an existing pack (character strength, prompt, voice). `POST /sync-from-voices`, `/resolve-tts`, `/session/reset-all`, `/profiles/{id}/session/apply`, `/profiles/{id}/session/reset`. Empty prompt gets a fallback. `GET /voices` without provider returns both engines. |
| `backend/persona_sync.py` | `build_style_overlay_prompt` takes **0–100** strength (0 empty; 100 full eclipse). `is_listable_persona_pack` / stub helpers. `ensure`/`sync` skip creating stub packs from name-only Fish clones. Fallback/sync templates are mannerisms. Scored Fish name-match. Fish-prefer resolve. |
| `backend/config_io.py` | **New.** Prefer Hermes `atomic_roundtrip_yaml_update`; else PyYAML mutate-only + atomic replace. |
| `backend/managed_index.py` | **New.** `~/.hermes/personas/.studio-managed.json` snapshots prior values for purge. |
| `backend/paths.py` | **New.** Hermes home / config path helpers including `.studio-session.json`. |
| `backend/storage.py` | Ignore hidden persona dirs / `.studio-managed.json` / `.studio-session.json`. Manifest stores `character_strength` as **0–100** (legacy soft/medium/strong migrate). |
| `install.py` | Deploy `plugin.js` only; delete stray `plugin.py`; optional `--systemd`; default `--sync-voices`; uninstall stops unit; `--purge` reverts tracked keys and removes `personas/` (**never deletes `config.yaml`**). |
| `seed_presets.py` | Mannerism overlays (Jarvis / Cartman / Storyteller), not “You are X” identity. Portable storage root; do not clobber existing `prompt.md`. **Do not auto-create** presets whose `voice_id` is Fish `default` (won’t reinstall deleted storyteller / jarvis stubs). |
| `test_backend.py` | Offline tests for style overlay, role-preservation, **Soft/Medium/Strong overlay text**, listable packs, apply does not write bare Cartman identity, reset clears overlay, Fish name-score, Edge stock, session-watch race, **mechanic apply does not write Magellan**, profile-switch UI stock, seed skips incomplete presets. |
| `README.md` | Style overlay vs soul; session vs sticky; Fish-prefer; uninstall vs purge. |
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
| Titlebar pick complete persona pack | Stash `display.personality` + user `agent.system_prompt` + TTS; apply pack **character strength 0–100** (0 = no overlay; 1–99 style blend; 100 = eclipse identity). Fish-prefer TTS. | **Stay in this chat.** Next reply picks up ephemeral personality + cloned TTS. **No** `host.newChat` |
| Titlebar voice-only clone | **Not listed.** Orphans stay in Studio for clone/edit. No apply without a pack. | — |
| Titlebar Standard Hermes | Restore stash, or Edge stock if no usable stash. Never `voicebox.voice: default` | **No** `host.newChat`. Next reply uses stock profile soul |
| User New Chat while overlay active | Restore stash (or Edge stock); plugin watches **`focusedStoredSessionId` non-null → null**, not `focusedSessionId` churn | **No** extra `newChat` — user already has the blank |
| Plugin / Desktop startup | `POST /session/reset-all`: restore stash; leftover Studio personality cleared; Voicebox `voice: default` → Edge stock. No auto-apply | **No** `host.newChat` — Studio never starts sessions |
| Switch focused profile (mechanic → Magellan) | Session overlay is **per profile**. New profile with no own overlay is reset to stock: **always** `display.personality: ""` (even untagged `cartman`), leftover Voicebox → Edge. Previous profile’s overlay stays on its config | Titlebar `default` unless that profile has an active overlay. **No** `host.newChat`. Re-selecting a persona applies to the **new** focused profile |
| Companion refresh | Same startup reset. Never auto-applies a Studio persona | — |
| Studio Save Persona | Bundle under `personas/` including **character_strength** (LLM). Temperature stays TTS-only. | Not auto-applied until titlebar |
| Studio Clone | Provider clone **and** matching persona bundle | Not auto-applied |
| `POST /sync-from-voices` or `install.py --sync-voices` | Existing packs rebound; **no new pack** if the only prompt would be a stub fallback (name-only `Hermes kitt`). Rich Voicebox description may still create. | No session change |
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

1. **New chat → profile stock.** Open Hermes Desktop (or click New Chat). Send a short line.
   - Expect that **profile’s** default text (mechanic = PC repair / SOUL, not Cartman/KITT identity).
   - Expect **Edge TTS** `en-US-AriaNeural` (or that profile’s stashed TTS). Audio should play.
2. **Dropdown apply is style + voice on this session.** On **mechanic**, pick the **persona** row for Cartman (not `Cartman · Voicebox`).
   - Expect toast that style + **Fish** applied to **this chat**.
   - Expect **Mechanic that speaks like Cartman**: snarky Cartman tone, still does PC repair (SOUL/job stay). Not “I am only Eric Cartman.”
   - If a Fish twin exists (`Hermes eric_cartman` preferred over `Hermes cartman`), audio should land in about ≤5 seconds (Promax Fish baseline 2.5–3.4s).
   - Apply must **not** start a new session. Next reply in this chat should be Mechanic-that-speaks-like-Cartman.
3. **Research + Jarvis (if that profile exists).** Pick Jarvis on the research agent. Expect research behavior from that profile’s soul/AGENTS.md, replies/speaks like Jarvis.
4. **New chat again → profile stock.** Click New Chat. Send a short line.
   - Expect default profile text (mechanic = PC repair, not Cartman identity) + **Edge / AriaNeural** (or stashed profile TTS). Style overlay must be gone.
5. **Profile switch (Magellan).** On mechanic, pick Cartman, then switch the focused bot to **Magellan** without applying again.
   - Titlebar must **not** keep Cartman as an implied apply. Expect Magellan **research soul** + **stock TTS** (Edge/Aria or Magellan stash), not Cartman voice without Cartman style.
   - Re-select Cartman on Magellan → Magellan that *speaks like* Cartman (research job + snark + Fish). `session/apply` must hit **magellan**.
6. **Studio Save Persona (hydrate + PUT).** Open Studio → select Cartman → name/prompt/voice/strength must fill from the pack (no empty name). Set Character strength to **100%** → **Save/Update Persona**.
   - Must **not** alert “Please enter a name.”
   - Studio stays open; toast reports update + 100%.
   - Re-open / re-select Cartman still shows 100%. Titlebar apply of Cartman must send 100% eclipse.

### Latency / Fish-prefer

6. Confirm titlebar clone list includes **both** `Cartman · Fish` and `Cartman · Voicebox` (and Jarvis / KITT if those clones exist). Not Voicebox-only.
7. Persona-row apply still prefers Fish. Optional slow path: pick `Cartman · Voicebox`. Confirm local GPU is used. Do not treat Voicebox latency as a Studio bug; do not patch Voicebox in this repo.
8. After New Chat restore, TTS must be **Edge / AriaNeural** (or the real pre-apply stash), never Voicebox `voice: default`, never an invented Jarvis UUID. Mechanic’s old Fish binds / Jarvis Voicebox backup are **not** stock. Fish-prefer is only for an explicit dropdown persona/clone pick.

### Original apply / hygiene

8. Titlebar persona or clone still applies **style + voice** (no TTS-only early return). Apply uses session overlay, not a sticky identity replacement.
9. Clone in Studio still writes a persona bundle. `python3 install.py --sync-voices` is idempotent; Fish twins should win stored `voice_id` over Voicebox.
10. Polling is 60s / focus, not 8s. Installed tree has `plugin.js` and no `plugin.py`. Plugin does **not** auto-apply a Studio persona on startup or companion refresh.
11. Uninstall dry-run: plugin gone, systemd stopped, personas remain, `config.yaml` still present. `--purge` only with Charles’ OK.
12. `git status` inside `~/.hermes/hermes-agent` stays clean.

---

## 8. Merge checklist for reviewers

- [ ] Diff stays inside this repo; no hermes-agent patches; no Voicebox server patches
- [ ] Titlebar clone path cannot return after TTS-only assign
- [ ] Titlebar fetches **Fish + Voicebox** voices (not `provider=voicebox` only)
- [ ] Persona apply prefers a Fish name-twin; `Name · Voicebox` remains an explicit local choice
- [ ] `Eric Cartman` resolves `Hermes eric_cartman` over `Hermes cartman`; Jarvis/KITT match `Hermes jarvis` / `Hermes kitt`
- [ ] New chat is **profile stock** (soul + Edge/`en-US-AriaNeural` or stashed TTS); empty `display.personality`; user `agent.system_prompt` not replaced by Cartman/KITT identity
- [ ] Dropdown apply is a **style + voice overlay**; Mechanic+Cartman keeps PC-repair job with Cartman mannerisms; catalog prompt contains `SPEAKING STYLE OVERLAY` / SOUL.md role language
- [ ] **Character strength** is 0–100 (0 = no overlay / soul only; 100 = character eclipses soul); not TTS Temperature; titlebar apply sends pack percent
- [ ] Titlebar lists **complete persona packs only** (non-stub prompt + cloned voice); no voice-only CLONES section; seed does not recreate deleted stub packs
- [ ] Apply does **not** write bare `You are Cartman` as `agent.system_prompt`
- [ ] Apply and Standard Hermes clear do **not** call `host.newChat`; next reply in this chat picks up the overlay
- [ ] Switching profiles resets titlebar to stock (or that profile’s own overlay); Magellan must not keep mechanic’s Cartman selected without a Magellan apply; no voice-without-style leftover TTS
- [ ] No-stash leftover reset **always** clears `display.personality` (including untagged `cartman` on critic); catalog dicts may stay; stash restore still restores the stashed personality
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
- [ ] Studio pack select hydrates name/prompt/strength/voice; Save **PUT**s existing packs and **POST**s new ones; empty name falls back to the selected pack; Studio stays open with a success toast
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

**Session overlay residual:** Hermes has no true session-scoped personality/TTS API. Apply still writes profile `config.yaml` for the duration of one chat, then restores. Style overlay is `display.personality` + catalog prompt injected at **API-call time**; SOUL.md stays primary. Apply and Standard Hermes clear do **not** call `host.newChat` — the next turn in this chat should pick up the ephemeral overlay. If the plugin is not loaded, a user-initiated New Chat will not restore the stash until the plugin mounts (startup `reset-all`). First-prompt `focusedSessionId` persist must not look like New Chat. Existing Promax `prompt.md` files that still say “You are Cartman…” are rewritten at apply time; seed/sync only refresh empty prompt files.

**Silent TTS (Promax `20260922_094441_564b69`):** stock/reset wrote Voicebox `voice: default`. Command TTS used `--voice default`, 404'd a stale process-global active-voice UUID (`151b6710-8f59-4366-9410-0b3044ded982`), and played no audio. Reset must never emit that placeholder; first-run stock is Edge AriaNeural, not Voicebox Jarvis.

**False “default session is KITT” (Promax mechanic retest):** empty `display.personality` + Edge Aria was not enough. Leftover `agent.system_prompt` (KITT) is injected every session. Reset must stash/restore that key (or `''`). Do not treat `agent.personalities.kitt` as active. Memory files mentioning “Active profile: kitt” can still bias replies until scrubbed outside this plugin.

---

## 11. Double-blank session race (Promax 2026-09-22)

Companion log: dropdown `session/apply` then overlay **reset ~5–18s later** when the first user turn starts. Charles picked a persona (plugin called `host.newChat` after apply), sent the first prompt, and the plugin immediately opened **another** blank session.

### Root cause

`desktop/plugin.js` `onSessionChange` treated **any** `focusedSessionId` string change while `overlay.active` as user New Chat, then `resetSessionOverlay` and sometimes `host.newChat` again. Hermes **renumbers/persists** `focusedSessionId` on first prompt. `applyInProgress` was only **500ms**, so it had already expired → mid-turn wipe.

`focusedStoredSessionId` is the durable signal: it goes **non-null → null/empty** when the user actually clicks New Chat. First-prompt persist does the opposite (null → stored id) or only churns `focusedSessionId`.

### Required behavior (Mechanic Promax hotfix + Charles 2026-09-22 apply confirm)

| Event | Overlay | `host.newChat` |
|---|---|---|
| Dropdown apply (blank or persisted) | Write style overlay + TTS; stay in **this** chat | **No** — next reply picks up ephemeral personality |
| Titlebar Standard Hermes / default clear | Restore stock soul + TTS; stay in this chat | **No** |
| User New Chat (`focusedStoredSessionId` non-null → null/empty) | Reset to profile stock | **No** — user already has the blank chat |
| First prompt persist (`focusedSessionId` churn; stored id null → uuid) | Keep speaking-style overlay | **No** |
| Apply gate in progress (several seconds) | Refresh `sessionId` / `storedId`; do not reset | **No** |

`applyInProgress` stays true for `APPLY_GATE_MS` (**8000ms**) across apply, and the watcher **refreshes** `sessionId`/`storedId` while gated.

Do **not** regress to “any `focusedSessionId` change while overlay.active ⇒ New Chat”. Do **not** bring back apply-time `host.newChat` (the ef0d6f1 “reload when stored session already persisted” path is removed).

Hermes injects ephemeral personality at **API-call time**. Apply writes `display.personality` + catalog style overlay; the next turn in the current session should pick it up without starting a new chat.

Offline coverage: `TestPluginSessionWatchRace` asserts the watcher never calls `startNewChat` after user New Chat, `shouldReloadSessionAfterApply` is gone, and `onSelectPersona` does not call `host.newChat`.

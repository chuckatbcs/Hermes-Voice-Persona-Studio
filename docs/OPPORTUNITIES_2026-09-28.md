# Persona Studio — evaluation & opportunities

**Date:** 2026-09-28
**Reviewed:** `~/Projects/hermes-personastudio` @ `af5f854` (also cloned at `~/Documents/antigravity/Hermes-Voice-Persona-Studio`, same commit)
**Live state verified:** companion `:17495` active, 71/71 tests pass, deployed `plugin.js` byte-identical to repo, systemd unit active+enabled.

## Baseline health — good

- 71 offline tests pass in 1.16s.
- `backend/` compiles clean. No lint/type config at all (see O-8).
- Deployed plugin matches repo exactly — no drift.
- The restore/placeholder hardening is genuinely good: `_stash_restore_updates`
  refuses to restore Voicebox `default` or non-UUID ids, and always clears
  `agent.system_prompt`. Those were real Promax bugs and they're fixed.
- `name_match_score` (richest-needle-first) correctly stops `cartman` from
  beating `Eric Cartman`.

## Opportunities, highest value first

### O-1 — Slug drift: the catalog pack is `cartman`, everything downstream is `eric_cartman`
**Severity: high (live inconsistency, not cosmetic).**

- On disk: `~/.hermes/personas/cartman/` (`manifest.id: "cartman"`).
- `GET /personas?listable=true` returns `cartman`.
- Live `.studio-session.json` says `applied_persona: "eric_cartman"`.
- `mechanic/config.yaml` writes the overlay to `agent.personalities.eric_cartman`
  and sets `display.personality: eric_cartman`.

So the applied overlay names a key that does **not** exist in the persona
catalog. It only works because the *name* ("Eric Cartman") slugifies the same
way at apply time. The moment someone saves the pack under a different name, or
a pack is renamed, the applied overlay orphans and the titlebar's "current
applied" state can't map back to a pack.

**Fix:** one canonical slug function used by storage *and* by
`bot_profiles._clean_key`, plus a startup reconciliation that rewrites
`applied_persona` in `.studio-session.json` to the on-disk pack id.

### O-2 — `magellan` has a legacy overlay with a malformed style string
**Severity: medium.**

```text
mannerisms of Eric Cartman. Speak with aggressive defiance, ...
```

`mannerism_from_prompt` prefixed "mannerisms of {label}:" onto a prompt that was
*already* a mannerism sentence, producing the stutter. It also has
`character_strength: None` and no `(%N%)` marker, so `overlay_strength_percent`
can't read it back and the Studio slider will show the wrong default.

**Fix:** detect a prompt that is *already* mannerism-shaped (no leading
`You are`/`I am`, and already contains "mannerisms of") and pass it through
unrewritten. Add a migration that drops the duplicate prefix on existing packs.

### O-3 — Zero-length and duplicated clone keys in `fish_voices.json`
**Severity: medium — this is exactly the silent-fallback class you hate.**

`save_cached_voice` writes **both** `data[label] = voice_id` (flat) and
`data["voices"][label] = {...}` (nested), and *preserves whatever was already
there*. Result on disk right now:

```text
hermes_kitt -> {'voice_id': 'kitt-id', 'title': 'Hermes kitt', ...}   # not a real id
hermes_eric_cartman -> 0e142644ca7143f887a40f18977b695e               # flat string
cartman -> {'voice_id': '862bf...', 'title': 'Hermes cartman'}        # nested dict
```

`resolve_profile_tts` reads this file and has to handle **three** different
value shapes (str / dict-with-`voice_id` / dict-with-`id`). `hermes_kitt` holds
the literal string `"kitt-id"` — a placeholder that will 400 Fish.

**Fix:** one canonical shape, written atomically as a single full-file replace.
`hermes_kitt` must be dropped or repaired.

### O-4 — Pack manifests disagree with the live voice catalog
**Severity: medium.**

`cartman/manifest.json` is bound to Voicebox `c9da87b0-…` and the Voicebox
catalog still has a `Cartman` clone at that id. But the catalog *also* has a
second, richer Voicebox clone named **`Eric Cartman`**
(`83c6e6b8-73ac-4b9c-a4fb-b9cc07795d6a`) that no pack references.

Meanwhile `flirty` is bound to Voicebox `13f20853-…` (correct) but mechanic's
`tts.providers.voicebox.voice` is *also* `13f20853-…` — so if Fish ever fails,
mechanic silently falls back to Flirty's voice.

**Fix:** a `/api/studio/personas/audit` that reports, per pack: manifest id
drift, voice present in catalog, and any Voicebox id also pinned as a profile's
fallback voice.

### O-5 — `character_strength` is stored twice and can disagree
**Severity: low-medium.**

`manifest.json` has `character_strength`, and the applied
`agent.personalities.<key>` dict has its own `character_strength`, and the
`(%N%)` marker is embedded a *third* time in the prompt text. Three copies,
written at different times, no reconciliation. Magellan already drifted (O-2).

**Fix:** one source of truth (the manifest), and the config write is derived.

### O-6 — No session-scoped API means "session" leaks across restarts
**Severity: medium (known, documented, unfixed).**

`apply_session_overlay` writes to profile `config.yaml` and relies on the plugin
mounting + `session/reset-all` to restore. Unload the plugin mid-chat and the
overlay stays. There's no TTL, no pid binding, and no liveness check.

**Fix:** stamp `applied_at` + `pid` + session id in `.studio-session.json`, and
have `reset-all` also fire on a timer (e.g. reap entries older than N hours
whose session is gone).

### O-7 — 2945-line `plugin.js`, zero lint, zero tests
**Severity: medium. FIXED — and it immediately caught a shipped-code regression.**

Extracted the pure helpers (`slugifyName`, `nameTokens`, `nameMatchScore`,
`characterStrengthLabel`, `placeholderVoiceId`, `isGenericVoiceDescription`,
`pickTitlebarPack`) into `desktop/lib/persona-helpers.mjs` and wrote
`tests/plugin.test.mjs` (15 tests) that import and exercise the **real module**
rather than slicing `plugin.js` source text.

**The regression this exposed.** Importing `./lib/...` made the plugin fail to
load *entirely*, and the 🎭 Personas / 🎙️ Studio titlebar controls disappeared
from the desktop. Root cause is in the desktop runtime loader
(`apps/desktop/src/contrib/runtime-loader.ts`): plugins are evaluated from a
**Blob URL**, so relative imports cannot resolve, and the loader enforces an
allowlist of only `@hermes/plugin-sdk` and `react*`. A relative import kills
every UI surface the plugin registers, with nothing logged as an error.

Guard rails now in place:

- `scripts/build-plugin.mjs` inlines `desktop/lib/*` into one self-contained
  `desktop/dist/plugin.js` (strips `export` keywords). Source stays importable
  and testable; only the built file ships.
- `scripts/check-imports.mjs` replicates the loader's own regex + allowlist
  offline, so a non-loadable plugin fails a check instead of silently deleting
  a UI surface.
- `install.py deploy_plugin()` ships `desktop/dist/plugin.js` and **raises**
  if asked to ship a source `plugin.js` containing a relative import.
- `scripts/check.sh` runs build → import gate → parse → JS tests → Python.
- Regression test `test_deploy_ships_inlined_plugin_and_refuses_relative_import`
  pins the deploy contract.

**Lesson:** `node --check` passing is not "the plugin loads". The gate is the
import allowlist, and it must be checked against the *shipped* file.

Still missing: eslint/prettier config and a real desktop integration test.

### O-8 — Persist-then-apply can leave a half-applied pack
**Severity: low-medium (documented in AGENT_REVIEW.md).**

Studio Apply PUTs the pack (writing `character_strength`) *before* calling
`session/apply`. A failed apply leaves the slider persisted at a value the
session never used.

**Fix:** apply first, persist on success; or make it a single transaction key.

## Not a problem, for the record

- The duplicate repo clone at `~/Documents/antigravity/Hermes-Voice-Persona-Studio`
  is harmless (same commit, no uncommitted work) but is a footgun. Pick one.
- 9 `character_strength` references in `plugin.js` and 0 hardcoded `eric_cartman`
  — the plugin is correctly generic; the drift is purely in stored state.

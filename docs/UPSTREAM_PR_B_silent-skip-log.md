# Upstream PR B — log the auto-speak silent skip

**Follow-up to PR A.** Deliberately not bundled with it: PR A is a behavior
fix with red-on-base tests; PR B is observability for a 0.2% case.

## Problem

Desktop **auto-speak replies** silently speaks nothing when a reply's
speakable content is empty — typically a reply that is entirely a fenced code
block. The user gets no sound and no message.

## The path (verified)

`use-auto-speak-replies.ts:89` → `playSpeechText` (`voice-playback.ts:670`) →
`startSpeechText` (`voice-playback.ts:700`):

```ts
const speakableText = sanitizeTextForSpeech(text)
if (!speakableText) {
  return false
}
```

`sanitizeTextForSpeech` (`speech-text.ts:273`) strips fenced code blocks, so a
pure-code reply becomes `''`. `startSpeechText` returns `false` — a **normal
return, not a rejection** — and the hook takes the silent branch:

```ts
// use-auto-speak-replies.ts:96-100
started => {
  if (!started && attempt === attemptSeq) {
    releaseUnplayedSpokenReply(sessionId, marked)   // no signal
  }
},
error => { … notifyError(error, failureLabel) }     // only THIS notifies
```

`!started` and the error branch are explicitly distinct, so nothing surfaces.

The backend's `"Text is empty after TTS cleanup"` (`tools/tts_tool.py:438`)
does **not** cover this: the renderer short-circuits before any HTTP call.

## Change

`apps/desktop/src/lib/voice-playback.ts`, immediately before the `return
false` at line 703:

```ts
if (!speakableText) {
  console.warn('[speech] empty after sanitize', {
    original: text.length,
    turnKey: options.turnKey ?? null,
  })
  return false
}
```

Local logging only. **No metric, no telemetry** — the repo requires explicit
opt-in for outbound usage data, and this is none of that.

`console.warn` is idiomatic here: there is no logger abstraction in
`apps/desktop/src/lib`, and the tree already uses `console.warn` /
`console.error` widely, including in sibling voice code.

### Why a tag and `turnKey`

`use-auto-speak-replies.ts:113` re-enters `speakLatest` from both the
`$messages` and `$voicePlayback` subscriptions, so the same silent reply can
be attempted more than once per turn. The `[speech]` tag plus `turnKey` matches
the house idiom (cf. `'[submit-drift-abort]'`) and makes the log greppable and
correlatable without spamming a raw string per attempt.

## Tests

One test in the style of
`apps/desktop/src/lib/voice-playback.same-turn.test.ts`: spy on
`console.warn`, call `playSpeechText` with a pure-fenced-code string, assert
the warning fired. Spying on a call is behavioral, not source-reading, so the
`AGENTS.md` ban is not violated.

No change to `speech-text.test.ts` — the existing suite already pins
`sanitizeTextForSpeech` behavior, and this PR modifies no file it covers.

## Why no user-visible affordance

A toast on 0.2% of replies is noise, and `speech-text.ts:270-272` records a
deliberate decision that unspeakable content is silence rather than a
placeholder word:

> Unspeakable tokens are silence, never a placeholder word: an English
> "code block omitted" / "link" is wrong for every non-English voice.

There is no i18n layer anywhere on this path, so any hardcoded string would be
the only untranslated token in the pipeline. The log makes the class
measurable; a visible affordance is a product decision, not a bugfix.

## Risk

Low. Log-only, no contract change, no user-visible string, no new
dependency.

## Measurement that motivated this

Over 1,533 non-empty assistant replies in one local profile: **3 (0.2%)**
produced entirely empty spoken text; **126 (8.2%)** lost more than 10% of
their content to markdown stripping. The 0.2% is this PR. The 8.2% is the
follow-up product question.

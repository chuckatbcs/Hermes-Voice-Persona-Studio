# Upstream PR A — strip unterminated code fences from spoken text

**Split from the original draft.** This is the standalone, high-confidence
change. The observability log is a separate follow-up (PR B).

## Problem

`tools/tts_text_normalize.py:18` strips fenced code blocks with a pattern that
**requires a closing fence**:

```python
_MD_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")
```

A reply that is cut off mid-stream (gateway streaming, truncated generation,
or a model that opens a fence and stops) leaves the opener with no closer. The
strip does not fire, and **the raw source code is read aloud**:

```
in : "Here is the plan.\n```python\nprint('step one')"
out: "Here is the plan. ```python. print('step one')."     # code SPOKEN
```

Reproduced against `strip_markdown_for_tts` on this branch.

## The naive fix is wrong — do not use `(?:```|$)`

The obvious "align with the desktop regex" change
(`/```[\s\S]*?(?:```|$)/g` in `apps/desktop/src/lib/speech-text.ts:3`)
**destroys legitimate text**. Measured:

| input | current | with `(?:```\|$)` |
|---|---|---|
| `The syntax is three backticks ``` to open a block.` | unchanged | `The syntax is three backticks ` |
| `A table cell with ``` ticks in it` | unchanged | `A cell with ` |
| `Inline ```code``` span here.` | `Inline   span here.` | `Inline  span here.` |

The `(?:```|$)` alternative matches *any* run of three backticks and, absent a
later closer, consumes the rest of the string. That is a new truncation bug —
and it would hit exactly the user who discusses markdown fence syntax in chat.

## The change

Keep the existing pattern untouched and add a **second, anchored pass** for
the unterminated case:

```python
_MD_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")
# A reply cut off mid-generation leaves a fence opener with no closer, so the
# pass above never fires and the raw source is spoken aloud. This anchored
# alternative strips only that remainder: the opener must start a line, and
# the match must run to end-of-text, so a backtick run mid-sentence is never a
# trigger and a properly closed fence is never re-matched.
_MD_UNTERMINATED_CODE_RE = re.compile(r"(?ms)^[ \t]{0,3}```[^\n]*\n[\s\S]*\Z")
```

Applied in `strip_markdown_for_tts` as a second `.sub(" ", ...)` after the
existing code-block strip.

### Verified behavior (all cases executed)

| case | result |
|---|---|
| unterminated fence | code body removed ✅ **the bug** |
| closed fence + trailing prose | `` `Here is the plan.\n\nThat is it.` `` — trailing text **preserved** ✅ |
| inline ` ```code``` ` span | stripped, surrounding words intact ✅ |
| mid-sentence backtick run | text fully preserved ✅ |
| table cell containing backticks | text fully preserved ✅ |
| prose only | unchanged ✅ |

The anchoring matters: an unanchored `\Z` pass also fires on *closed* fences
and swallows the prose after them (`"That is it."` disappeared). The
`[^\n]*\n` opener requirement is what keeps closed fences out of the second
pass.

## Tests

Append to the **existing** `tests/tools/test_tts_text_normalize.py` (it
already has 6 tests; do not create a new file):

1. A reply ending inside an open fence leaves no code body in the output.
   *(red on base, green with this change)*
2. A mid-sentence backtick run keeps its trailing words.
   *(red against a naive `(?:```|$)` fix, green here — this pins the
   anti-over-strip property that is the entire risk of the change)*
3. A properly closed fence followed by prose keeps the trailing prose.
   *(red against an unanchored `\Z` variant, green here)*
4. Prose-only input is unchanged.

No assertions on chunk counts, character caps, or constants — per `AGENTS.md`,
change-detector tests are rejected.

## Callers

`strip_markdown_for_tts` is used by `gateway/run_voice.py:336`,
`gateway/streaming_tts_consumer.py:189`, `tools/tts_tool_speaker.py:364`, and
`hermes_cli/web_routers/audio.py:594`. All four benefit. The desktop renderer
is **not** one of them — it has its own implementation in
`apps/desktop/src/lib/speech-text.ts` and already handles the unterminated
case.

## Risk

Low. One new compiled pattern, one extra `.sub`, no behavior change on any
input that does not end inside an open fence.

## Out of scope

- The desktop's *silent skip* (empty speakable text) — a separate
  observability-only change, tracked as PR B.
- The partial-loss class (code stripped from an otherwise-spoken reply).
  `speech-text.ts:120` `summarizeMarkdownTables` is the precedent for
  summarizing rather than deleting, but that is a product decision.

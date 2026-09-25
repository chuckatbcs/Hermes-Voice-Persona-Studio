# Voice model Save-pack fix

## Root cause
**File/functions:** `desktop/plugin.js` → `personaSaveRequest` / `persistStudioPack`;
`backend/api.py` → `CreatePersonaRequest` / `UpdatePersonaRequest` / `save_persona` / `update_persona`;
`backend/storage.py` → `PersonaBundle`.

"Voice model" in Studio is the **Synthesis engine** dropdown (`selectedModel`:
`chatterbox_turbo` / `chatterbox` / `qwen` / `qwen_fast` / `kokoro`, or Fish
`s2.1-pro-free`, etc.). It was used for **audition** and **clone** only.

**Save pack never sent or stored `engine`.** On reload, `hydrateFormFromPack`
did not restore it, and `loadData` reset the dropdown to the recommended model.

Runtime Hermes/Voicebox TTS reads the Voicebox profile's `default_engine`, which
Save also never updated — so even a correct audition override would not stick for
Apply / speak.

## Fix
1. Persist `engine` on the persona manifest (`PersonaBundle.engine`).
2. Include `engine: selectedModel` in Save/PUT body.
3. Hydrate `selectedModel` from `pack.engine` (else voice `default_engine`).
4. Stop `loadData` from clobbering an in-list selection.
5. On Voicebox Save, `PUT /profiles/{voice_id}` with `default_engine` (Fish
   unchanged aside from storing preferred model on the pack).

## Deploy on Promax
```bash
cd ~/Projects/hermes-personastudio   # or sync this tree
# apply the 5-file dirty tree, then:
python3 install.py --no-sync-voices
# or restart hermes-personastudio.service after copying plugin + backend
bash scripts/verify_engine_save.sh amanda chatterbox_turbo
```

## Charles retest
1. Open Studio → Amanda.
2. Set **Synthesis engine (saved with pack)** to e.g. Chatterbox Turbo.
3. **Save pack**.
4. Close Studio, reopen, reselect Amanda → engine still Turbo.
5. Optional: `cat ~/.hermes/personas/amanda/manifest.json` → `"engine": "..."`.
6. Optional: Voicebox profile `default_engine` matches (GET `:17493/profiles/<voice_id>`).

## Upstream PR
Yes — this is a real bug on `main` at `11c3203`. Local fix verified offline
(69 tests OK). Push branch when ready; not committed from this session.

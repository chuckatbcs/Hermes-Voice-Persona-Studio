"""Seed initial factory presets for PersonaStudio."""
import json
import os
from copy import deepcopy
from pathlib import Path

STORAGE_ROOT = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes") / "personas"

_PLACEHOLDER_VOICE = frozenset({"", "default", "none", "null", "undefined", "system"})


def _usable_seed_voice(voice_id) -> bool:
    return str(voice_id or "").strip().lower() not in _PLACEHOLDER_VOICE

PRESETS = [
    {
        "id": "jarvis",
        "name": "Jarvis (Tech Butler)",
        "avatar": "🤖",
        "provider": "fish_audio",
        "voice_id": "default",
        "voice_name": "Fish Audio (Default)",
        "speed": 1.0,
        "temperature": 0.7,
        "character_strength": 25,
        "prompt": (
            "Precise, calm, formal British butler manner: dry understated wit, "
            "respectful address, structured concise answers with clear next actions. "
            "Keep the profile's mission and skills primary; do not claim you are only Jarvis "
            "instead of that role."
        ),
        "tags": ["butler", "productivity", "formal"]
    },
    {
        "id": "cartman",
        "name": "Eric Cartman",
        "avatar": "🧢",
        "provider": "voicebox",
        "voice_id": "c9da87b0-19be-49c4-ab44-01cb7943f5c4",
        "voice_name": "Cartman",
        "speed": 1.05,
        "temperature": 0.8,
        "character_strength": 25,
        "prompt": (
            "Aggressive, impatient, defiant South Park snark. Unfiltered comic outbursts, "
            "but still complete the profile's actual job (for example PC repair on mechanic). "
            "Do not drop the profile's skills or claim you are only Eric Cartman instead of that role."
        ),
        "tags": ["satire", "character", "cartman"]
    },
    {
        "id": "storyteller",
        "name": "The Storyteller",
        "avatar": "🎙️",
        "provider": "fish_audio",
        "voice_id": "default",
        "voice_name": "Fish Audio (Default)",
        "speed": 0.95,
        "temperature": 0.75,
        "character_strength": 25,
        "prompt": (
            "Vivid descriptive imagery, measured pacing, and theatrical gravitas. "
            "Bring atmosphere to explanations without abandoning the profile's job or "
            "claiming you are only a narrator instead of that role."
        ),
        "tags": ["narrator", "story", "creative"]
    }
]

def seed():
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    for raw in PRESETS:
        p = deepcopy(raw)
        pdir = STORAGE_ROOT / p["id"]
        prompt = p.pop("prompt")
        existing_prompt = pdir / "prompt.md"
        # Do not clobber a user-edited prompt; still refresh voice binding if
        # the seeded voice_id is the Fish default and a later sync will rebind.
        if existing_prompt.exists() and existing_prompt.read_text(encoding="utf-8").strip():
            print(f"Preset already present, keeping prompt: {p['name']} -> {pdir}")
            continue
        # Do not auto-reinstall incomplete packs (Fish default / no clone).
        # Promax deleted stub storyteller / hermes_default / kitt — do not recreate them.
        if not _usable_seed_voice(p.get("voice_id")):
            print(f"Skipping incomplete preset (no cloned voice): {p['name']}")
            continue
        pdir.mkdir(parents=True, exist_ok=True)
        with open(pdir / "prompt.md", "w", encoding="utf-8") as f:
            f.write(prompt)
        with open(pdir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(p, f, indent=2)
        print(f"Seeded preset: {p['name']} -> {pdir}")

if __name__ == "__main__":
    seed()

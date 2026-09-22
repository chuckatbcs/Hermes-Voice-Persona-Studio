"""Seed initial factory presets for PersonaStudio."""
import json
import os
from copy import deepcopy
from pathlib import Path

STORAGE_ROOT = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes") / "personas"

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
        "prompt": "You are Jarvis, a highly capable British butler-style AI assistant. Be precise, calm, formal, and efficiently helpful. Allow dry understated wit. Address the user respectfully. Prefer structured concise answers with clear next actions.",
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
        "prompt": "You are Eric Cartman from South Park. Speak with aggressive defiance, impatient outbursts, and hilarious lack of filter, but still help answer the user's technical questions.",
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
        "prompt": "You are a master dramatic narrator and storyteller. Speak with vivid descriptive imagery, measured pacing, and theatrical gravitas. Bring depth and atmosphere to every explanation.",
        "tags": ["narrator", "story", "creative"]
    }
]

def seed():
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    for raw in PRESETS:
        p = deepcopy(raw)
        pdir = STORAGE_ROOT / p["id"]
        pdir.mkdir(parents=True, exist_ok=True)
        prompt = p.pop("prompt")
        existing_prompt = pdir / "prompt.md"
        # Do not clobber a user-edited prompt; still refresh voice binding if
        # the seeded voice_id is the Fish default and a later sync will rebind.
        if existing_prompt.exists() and existing_prompt.read_text(encoding="utf-8").strip():
            print(f"Preset already present, keeping prompt: {p['name']} -> {pdir}")
            continue
        with open(pdir / "prompt.md", "w", encoding="utf-8") as f:
            f.write(prompt)
        with open(pdir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(p, f, indent=2)
        print(f"Seeded preset: {p['name']} -> {pdir}")

if __name__ == "__main__":
    seed()

"""Storage and bundle management for PersonaStudio."""
from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class PersonaBundle:
    id: str
    name: str
    avatar: str  # Emoji or image path
    system_prompt: str
    provider: str  # "fish_audio" or "voicebox"
    voice_id: str
    voice_name: str
    speed: float = 1.0
    temperature: float = 0.7
    character_strength: str = "soft"
    created_at: float = 0.0
    updated_at: float = 0.0
    tags: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PersonaBundle":
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            avatar=data.get("avatar", "🤖"),
            system_prompt=data.get("system_prompt", ""),
            provider=data.get("provider", "fish_audio"),
            voice_id=data.get("voice_id", "default"),
            voice_name=data.get("voice_name", data.get("voice_id", "Default")),
            speed=float(data.get("speed", 1.0)),
            temperature=float(data.get("temperature", 0.7)),
            character_strength=str(data.get("character_strength") or "soft").strip().lower() or "soft",
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
            tags=data.get("tags") or [],
        )


class PersonaStorage:
    def __init__(self, root_dir: Optional[str] = None):
        if not root_dir:
            root_dir = os.path.expanduser("~/.hermes/personas")
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def list_personas(self) -> List[PersonaBundle]:
        bundles: List[PersonaBundle] = []
        for path in sorted(self.root_dir.iterdir()):
            if path.name.startswith("."):
                continue
            if path.is_dir() and (path / "manifest.json").exists():
                try:
                    with open(path / "manifest.json", "r", encoding="utf-8") as f:
                        data = json.load(f)
                    prompt_file = path / "prompt.md"
                    if prompt_file.exists():
                        with open(prompt_file, "r", encoding="utf-8") as f:
                            data["system_prompt"] = f.read()
                    bundles.append(PersonaBundle.from_dict(data))
                except Exception as e:
                    print(f"[PersonaStorage] Failed to read {path}: {e}")
        return bundles

    def get_persona(self, persona_id: str) -> Optional[PersonaBundle]:
        pdir = self.root_dir / persona_id
        manifest_file = pdir / "manifest.json"
        if not manifest_file.exists():
            return None
        with open(manifest_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        prompt_file = pdir / "prompt.md"
        if prompt_file.exists():
            with open(prompt_file, "r", encoding="utf-8") as f:
                data["system_prompt"] = f.read()
        return PersonaBundle.from_dict(data)

    def save_persona(self, bundle: PersonaBundle, sample_audio: Optional[bytes] = None) -> PersonaBundle:
        pdir = self.root_dir / bundle.id
        pdir.mkdir(parents=True, exist_ok=True)

        bundle.updated_at = time.time()
        if not bundle.created_at:
            bundle.created_at = bundle.updated_at

        data = bundle.to_dict()
        # Save prompt to dedicated markdown file for easy user inspection
        prompt_text = data.pop("system_prompt", "")
        with open(pdir / "prompt.md", "w", encoding="utf-8") as f:
            f.write(prompt_text)

        with open(pdir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        if sample_audio:
            with open(pdir / "reference.wav", "wb") as f:
                f.write(sample_audio)

        bundle.system_prompt = prompt_text
        return bundle

    def delete_persona(self, persona_id: str) -> bool:
        pdir = self.root_dir / persona_id
        if pdir.exists() and pdir.is_dir():
            shutil.rmtree(pdir)
            return True
        return False

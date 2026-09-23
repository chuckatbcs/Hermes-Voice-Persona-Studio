"""Bot profile inspection and voice / persona assignment for Hermes.

Config writes are surgical (Hermes atomic round-trip when importable,
otherwise PyYAML mutate-only + atomic replace). Studio never patches
``~/.hermes/hermes-agent`` source files.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config_io import get_dotted, load_yaml, update_config_keys
from .managed_index import SOURCE_TAG, remember_writes
from .paths import config_path_for_profile, hermes_home, profiles_dir
from .persona_sync import (
    build_style_overlay_prompt,
    character_strength_percent,
    slugify_persona_id,
)

_PLACEHOLDER_VOICE_IDS = frozenset({"", "default", "none", "null", "undefined"})
_VOICEBOX_UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def is_placeholder_voice_id(value: Any) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return not text or text.lower() in _PLACEHOLDER_VOICE_IDS


def is_usable_voicebox_voice_id(value: Any) -> bool:
    """Voicebox command TTS needs a real profile UUID, never ``default``."""
    if is_placeholder_voice_id(value):
        return False
    return bool(_VOICEBOX_UUID.match(str(value).strip()))


def list_bot_profiles() -> List[Dict[str, Any]]:
    """Return all available Hermes bot profiles with their display titles and current voices."""
    profiles: List[Dict[str, Any]] = []
    home = hermes_home()

    def_cfg = home / "config.yaml"
    if def_cfg.exists():
        try:
            c = load_yaml(def_cfg)
            tts = c.get("tts", {}) or {}
            tts_prov = tts.get("provider")
            if (tts_prov or "").strip().lower() == "edge":
                current_voice = (tts.get("edge") or {}).get("voice")
            else:
                prov_cfg = (tts.get("providers", {}) or {}).get(tts_prov or "", {}) or {}
                current_voice = prov_cfg.get("voice")
            profiles.append({
                "id": "default",
                "title": "Default Assistant",
                "provider": tts_prov,
                "voice": current_voice,
            })
        except Exception as e:
            print(f"[Profiles] Error reading default config: {e}")

    named_dir = profiles_dir()
    if named_dir.exists():
        for p in sorted(named_dir.iterdir()):
            if not p.is_dir() or p.name.startswith(".") or p.name == "default":
                continue

            title = p.name
            p_yaml = p / "profile.yaml"
            if p_yaml.exists():
                try:
                    py = load_yaml(p_yaml)
                    meta = (py.get("ui_meta", {}) or {}).get("hermes-bots", {}) or {}
                    title = meta.get("title") or p.name
                except Exception:
                    pass

            tts_prov = None
            current_voice = None
            c_path = p / "config.yaml"
            if c_path.exists():
                try:
                    c = load_yaml(c_path)
                    tts = c.get("tts", {}) or {}
                    tts_prov = tts.get("provider")
                    if (tts_prov or "").strip().lower() == "edge":
                        current_voice = (tts.get("edge") or {}).get("voice")
                    else:
                        prov_cfg = (tts.get("providers", {}) or {}).get(tts_prov or "", {}) or {}
                        current_voice = prov_cfg.get("voice")
                except Exception:
                    pass

            profiles.append({
                "id": p.name,
                "title": title,
                "provider": tts_prov,
                "voice": current_voice,
            })

    return profiles


def _clean_key(name: str) -> str:
    return slugify_persona_id(name)


_DEFAULT_FISH_COMMAND = "voicebox_tts"


def fish_voices_cache_path() -> Path:
    return hermes_home() / "fish_voices.json"


def _upsert_cli_flag(command: str, flag: str, value: str) -> str:
    pattern = rf"{re.escape(flag)}\s+\S+"
    replacement = f"{flag} {value}"
    if re.search(pattern, command):
        return re.sub(pattern, replacement, command, count=1)
    return f"{command.rstrip()} {replacement}".strip()


def _pin_fish_command(cmd: Any, voice_id: str, label: str) -> str:
    """Explicit --fish-voice wins over label cache / stale clones.<label>."""
    text = cmd if isinstance(cmd, str) and cmd.strip() else _DEFAULT_FISH_COMMAND
    text = _upsert_cli_flag(text, "--fish-label", label)
    return _upsert_cli_flag(text, "--fish-voice", voice_id)


def save_cached_voice(label: str, voice_id: str, voice_name: str = "") -> Path:
    """Sync ~/.hermes/fish_voices.json so --fish-label resolves the bound id."""
    try:
        from fish_tts import save_cached_voice as _imported  # type: ignore

        _imported(label, voice_id)
    except Exception:
        pass
    path = fish_voices_cache_path()
    data: Any = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}
    data[label] = voice_id
    voices = data.get("voices")
    if isinstance(voices, dict):
        prev = voices.get(label)
        if isinstance(prev, dict):
            voices[label] = {**prev, "id": voice_id, "voice_id": voice_id, "name": voice_name or label}
        else:
            voices[label] = voice_id
        data["voices"] = voices
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def _tts_updates_for_voice(cfg: Dict[str, Any], provider: str, voice_id: str, voice_name: str) -> Dict[str, Any]:
    target_prov = "fish" if provider in ("fish", "fish_audio") else "voicebox"
    clean_name = _clean_key(voice_name)
    updates: Dict[str, Any] = {"tts.provider": target_prov}

    if target_prov == "fish":
        fish_cfg = get_dotted(cfg, "tts.providers.fish") or {}
        if not isinstance(fish_cfg, dict) or not fish_cfg:
            updates["tts.providers.fish"] = {
                "type": "command",
                "provider_label": "Fish Audio (hosted)",
                "output_format": "wav",
                "timeout": 600,
                "clones": {clean_name: voice_id},
                "voice": clean_name,
                "command": _pin_fish_command("", voice_id, clean_name),
            }
        else:
            updates[f"tts.providers.fish.clones.{clean_name}"] = voice_id
            updates["tts.providers.fish.voice"] = clean_name
            updates["tts.providers.fish.command"] = _pin_fish_command(
                fish_cfg.get("command", ""), voice_id, clean_name
            )
    else:
        if not is_usable_voicebox_voice_id(voice_id):
            raise ValueError(
                f"Refusing to write Voicebox voice id {voice_id!r}; "
                "Voicebox requires a real profile UUID (not 'default')"
            )
        vb_cfg = get_dotted(cfg, "tts.providers.voicebox") or {}
        if not isinstance(vb_cfg, dict) or not vb_cfg:
            updates["tts.providers.voicebox"] = {
                "type": "command",
                "output_format": "wav",
                "timeout": 600,
                "voice": voice_id,
            }
        else:
            updates["tts.providers.voicebox.voice"] = voice_id

    return updates


def assign_voice_to_profile(
    profile_id: str,
    provider: str,
    voice_id: str,
    voice_name: str,
    *,
    cfg_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Assign a voice (Fish Audio or Voicebox) to a specific Hermes profile."""
    path = cfg_path or config_path_for_profile(profile_id)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found for profile '{profile_id}' at {path}")

    cfg = load_yaml(path)
    updates = _tts_updates_for_voice(cfg, provider, voice_id, voice_name)
    remember_writes(profile_id, path, updates.keys())
    strategy = update_config_keys(path, updates)

    target_prov = "fish" if provider in ("fish", "fish_audio") else "voicebox"
    clean_name = _clean_key(voice_name)
    cache_path = None
    if target_prov == "fish" and not is_placeholder_voice_id(voice_id):
        cache_path = save_cached_voice(clean_name, voice_id, voice_name)
    return {
        "ok": True,
        "profile_id": profile_id,
        "provider": target_prov,
        "voice": clean_name if target_prov == "fish" else voice_id,
        "write_strategy": strategy,
        "fish_cache": str(cache_path) if cache_path else None,
    }


def set_profile_persona(
    profile_id: str,
    persona_name: str,
    persona_prompt: str,
    *,
    cfg_path: Optional[Path] = None,
    character_strength: Optional[Any] = None,
) -> Dict[str, Any]:
    """Set the persona for a Hermes profile via display.personality.

    Uses Hermes's built-in personality overlay (same path as /personality).
    Studio-managed entries are stored as dicts so ``render_personality_prompt``
    can read ``system_prompt`` and uninstall --purge can identify them.
    Neutral names (none/default/empty) clear the overlay without deleting
    stored personality definitions. Catalog keys are not themselves active —
    only ``display.personality`` selects them as an ephemeral *style* overlay.
    Session apply does not own user ``agent.system_prompt``.
    """
    path = cfg_path or config_path_for_profile(profile_id)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found for profile '{profile_id}' at {path}")

    clean_name = _clean_key(persona_name)
    percent = 25 if character_strength is None else character_strength_percent(character_strength)
    # Explicit 0 means soul-only: do not inject an overlay even if a name is given.
    neutral = clean_name in ("", "none", "default", "neutral") or (
        character_strength is not None and percent <= 0
    )

    if neutral:
        updates = {"display.personality": ""}
        remember_writes(profile_id, path, updates.keys())
        strategy = update_config_keys(path, updates)
        return {
            "ok": True,
            "profile_id": profile_id,
            "persona": "",
            "write_strategy": strategy,
            "character_strength": 0 if percent <= 0 else percent,
            "message": f"Personality overlay cleared for profile '{profile_id}' — next reply uses stock profile soul",
        }

    personality_value = {
        "system_prompt": build_style_overlay_prompt(
            persona_name, persona_prompt, strength=percent
        ),
        "source": SOURCE_TAG,
        "description": persona_name,
        "character_strength": percent,
    }
    updates = {
        f"agent.personalities.{clean_name}": personality_value,
        "display.personality": clean_name,
    }
    remember_writes(
        profile_id,
        path,
        updates.keys(),
        personality_key=clean_name,
    )
    strategy = update_config_keys(path, updates)
    return {
        "ok": True,
        "profile_id": profile_id,
        "persona": clean_name,
        "write_strategy": strategy,
        "message": (
            f"Speaking style '{persona_name}' set for profile '{profile_id}' — "
            "next reply in this chat picks up the overlay"
        ),
    }

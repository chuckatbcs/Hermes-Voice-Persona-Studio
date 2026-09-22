"""Bot profile inspection and voice / persona assignment for Hermes.

Config writes are surgical (Hermes atomic round-trip when importable,
otherwise PyYAML mutate-only + atomic replace). Studio never patches
``~/.hermes/hermes-agent`` source files.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config_io import get_dotted, load_yaml, update_config_keys
from .managed_index import SOURCE_TAG, remember_writes
from .paths import config_path_for_profile, hermes_home, profiles_dir
from .persona_sync import slugify_persona_id

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
            }
        else:
            updates[f"tts.providers.fish.clones.{clean_name}"] = voice_id
            updates["tts.providers.fish.voice"] = clean_name
            cmd = fish_cfg.get("command", "")
            if isinstance(cmd, str) and "--fish-label" in cmd:
                updates["tts.providers.fish.command"] = re.sub(
                    r"--fish-label\s+\S+", f"--fish-label {clean_name}", cmd
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
    return {
        "ok": True,
        "profile_id": profile_id,
        "provider": target_prov,
        "voice": clean_name if target_prov == "fish" else voice_id,
        "write_strategy": strategy,
    }


def set_profile_persona(
    profile_id: str,
    persona_name: str,
    persona_prompt: str,
    *,
    cfg_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Set the persona for a Hermes profile via display.personality.

    Uses Hermes's built-in personality overlay (same path as /personality).
    Studio-managed entries are stored as dicts so ``render_personality_prompt``
    can read ``system_prompt`` and uninstall --purge can identify them.
    Neutral names (none/default/empty) clear the overlay without deleting
    stored personality definitions.
    """
    path = cfg_path or config_path_for_profile(profile_id)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found for profile '{profile_id}' at {path}")

    clean_name = _clean_key(persona_name)
    neutral = clean_name in ("", "none", "default", "neutral")

    if neutral:
        updates = {"display.personality": ""}
        remember_writes(profile_id, path, updates.keys())
        strategy = update_config_keys(path, updates)
        return {
            "ok": True,
            "profile_id": profile_id,
            "persona": "",
            "write_strategy": strategy,
            "message": f"Personality overlay cleared for profile '{profile_id}' — start a new chat to take effect",
        }

    personality_value = {
        "system_prompt": persona_prompt,
        "source": SOURCE_TAG,
        "description": persona_name,
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
            f"Persona '{persona_name}' set for profile '{profile_id}' — "
            "start a new chat to take effect"
        ),
    }

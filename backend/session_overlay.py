"""Session-scoped speaking-persona overlays on top of profile config.yaml.

Hermes Desktop has no session-scoped personality / TTS API. The only overlay
Hermes honors is ``display.personality`` plus ``tts.*`` in the profile config,
cached when a chat starts. Dropdown apply therefore:

1. Stashes the pre-apply personality + TTS selection.
2. Writes the overlay so *this* chat (refreshed via ``host.newChat``) can speak
   as the chosen persona.
3. Restores the stash on the next user-initiated new session so brand-new chats
   return to stock Hermes and Studio never becomes the implicit default.

This module never patches ``~/.hermes/hermes-agent``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import bot_profiles
from .config_io import get_dotted, load_yaml, snapshot_values, update_config_keys
from .managed_index import SOURCE_TAG
from .paths import config_path_for_profile, session_state_path

STASH_KEYS = (
    "display.personality",
    "tts.provider",
    "tts.providers.fish.voice",
    "tts.providers.fish.command",
    "tts.providers.voicebox.voice",
)


def _empty_state() -> Dict[str, Any]:
    return {"version": 1, "profiles": {}}


def load_session_state(path: Optional[Path] = None) -> Dict[str, Any]:
    target = path or session_state_path()
    if not target.exists():
        return _empty_state()
    try:
        with open(target, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return _empty_state()
        data.setdefault("version", 1)
        data.setdefault("profiles", {})
        return data
    except Exception:
        return _empty_state()


def save_session_state(state: Dict[str, Any], path: Optional[Path] = None) -> None:
    target = path or session_state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")
    tmp.replace(target)


def overlay_status(profile_id: str, *, state_path: Optional[Path] = None) -> Dict[str, Any]:
    state = load_session_state(state_path)
    entry = (state.get("profiles") or {}).get(profile_id) or {}
    return {
        "ok": True,
        "profile_id": profile_id,
        "active": bool(entry.get("active")),
        "applied_persona": entry.get("applied_persona") or "",
        "has_stash": bool(entry.get("stash")),
    }


def _clear_studio_personality_selection(cfg_path: Path) -> bool:
    """Clear a Studio-tagged display.personality without touching TTS.

    Used when a leftover sticky overlay exists from an older apply that never
    wrote a session stash. Mechanic Fish binds must stay put.
    """
    if not cfg_path.exists():
        return False
    cfg = load_yaml(cfg_path)
    selected = get_dotted(cfg, "display.personality")
    if not selected:
        return False
    personality = get_dotted(cfg, f"agent.personalities.{selected}")
    if isinstance(personality, dict) and personality.get("source") == SOURCE_TAG:
        update_config_keys(cfg_path, {"display.personality": ""})
        return True
    return False


def apply_session_overlay(
    profile_id: str,
    *,
    persona_name: str,
    persona_prompt: str,
    provider: Optional[str] = None,
    voice_id: Optional[str] = None,
    voice_name: Optional[str] = None,
    cfg_path: Optional[Path] = None,
    state_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Stash stock settings (once) and apply persona + TTS for this session."""
    path = cfg_path or config_path_for_profile(profile_id)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found for profile '{profile_id}' at {path}")

    state = load_session_state(state_path)
    profiles = state.setdefault("profiles", {})
    entry = profiles.get(profile_id) or {}
    if not entry.get("active") or not isinstance(entry.get("stash"), dict):
        entry = {
            "active": False,
            "applied_persona": "",
            "stash": snapshot_values(path, STASH_KEYS),
        }

    persona_result = bot_profiles.set_profile_persona(
        profile_id,
        persona_name,
        persona_prompt,
        cfg_path=path,
    )
    voice_result = None
    if voice_id and voice_id != "default":
        voice_result = bot_profiles.assign_voice_to_profile(
            profile_id,
            provider or "voicebox",
            voice_id,
            voice_name or voice_id,
            cfg_path=path,
        )

    entry["active"] = True
    entry["applied_persona"] = persona_result.get("persona") or bot_profiles._clean_key(persona_name)
    profiles[profile_id] = entry
    save_session_state(state, state_path)

    return {
        "ok": True,
        "profile_id": profile_id,
        "scope": "session",
        "persona": persona_result.get("persona"),
        "provider": (voice_result or {}).get("provider"),
        "voice": (voice_result or {}).get("voice"),
        "write_strategy": persona_result.get("write_strategy"),
        "message": (
            f"Persona '{persona_name}' applied to this session on '{profile_id}'. "
            "The next new chat returns to stock Hermes."
        ),
    }


def reset_session_overlay(
    profile_id: str,
    *,
    cfg_path: Optional[Path] = None,
    state_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Restore stashed stock Hermes personality + TTS for *profile_id*."""
    path = cfg_path or config_path_for_profile(profile_id)
    state = load_session_state(state_path)
    entry = (state.get("profiles") or {}).get(profile_id) or {}
    restored_keys: List[str] = []
    leftover_cleared = False

    stash = entry.get("stash") if isinstance(entry.get("stash"), dict) else None
    if stash and path.exists():
        updates = {key: stash.get(key) for key in STASH_KEYS}
        update_config_keys(path, updates)
        restored_keys = list(STASH_KEYS)
    elif path.exists():
        leftover_cleared = _clear_studio_personality_selection(path)

    if profile_id in (state.get("profiles") or {}):
        del state["profiles"][profile_id]
        save_session_state(state, state_path)
    elif leftover_cleared:
        save_session_state(state, state_path)

    return {
        "ok": True,
        "profile_id": profile_id,
        "restored": bool(restored_keys),
        "restored_keys": restored_keys,
        "leftover_personality_cleared": leftover_cleared,
        "active": False,
        "message": (
            "Stock Hermes restored for the next session"
            if restored_keys or leftover_cleared
            else "No Studio session overlay was active"
        ),
    }


def reset_all_session_overlays(*, state_path: Optional[Path] = None) -> Dict[str, Any]:
    """Drop every tracked overlay plus leftover Studio personality selections."""
    state = load_session_state(state_path)
    reports: List[Dict[str, Any]] = []
    seen = set()
    for profile_id in list((state.get("profiles") or {}).keys()):
        reports.append(reset_session_overlay(profile_id, state_path=state_path))
        seen.add(profile_id)

    for profile in bot_profiles.list_bot_profiles():
        pid = profile.get("id")
        if not pid or pid in seen:
            continue
        cfg_path = config_path_for_profile(pid)
        if _clear_studio_personality_selection(cfg_path):
            reports.append({
                "ok": True,
                "profile_id": pid,
                "restored": False,
                "restored_keys": [],
                "leftover_personality_cleared": True,
                "active": False,
            })

    return {"ok": True, "profiles": reports}

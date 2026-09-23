"""Session-scoped speaking-style + TTS overlays on top of profile config.yaml.

Hermes Desktop has no session-scoped personality / TTS API. Overlay is
``display.personality`` (ephemeral style) plus ``tts.*``, not a replacement
of the profile's SOUL.md / AGENTS.md identity.

Dropdown apply therefore:

1. Stashes the pre-apply ``display.personality``, user-owned
   ``agent.system_prompt``, and TTS selection.
2. Writes a Studio-managed catalog entry whose ``system_prompt`` is a
   **speaking-style overlay** (mannerisms, not ``You are X`` identity) and
   selects it via ``display.personality``. Binds Fish-prefer TTS. Does **not**
   clobber user ``agent.system_prompt`` with character identity.
3. Restores the stash on the next user-initiated new session. Unusable stash
   (missing, Voicebox ``default``) falls back to Nous stock TTS:
   ``tts.provider: edge`` + ``tts.edge.voice: en-US-AriaNeural``.
   Restores ``agent.system_prompt`` to the stashed user value or ``''``.

This module never patches ``~/.hermes/hermes-agent``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import bot_profiles
from .config_io import get_dotted, load_yaml, snapshot_values, update_config_keys
from .managed_index import SOURCE_TAG, remember_writes
from .paths import config_path_for_profile, session_state_path
from .persona_sync import (
    STYLE_OVERLAY_MARKER,
    build_style_overlay_prompt,
    character_strength_percent,
    is_style_overlay_prompt,
)

STASH_KEYS = (
    "display.personality",
    "agent.system_prompt",
    "tts.provider",
    "tts.edge.voice",
    "tts.providers.fish.voice",
    "tts.providers.fish.command",
    "tts.providers.voicebox.voice",
)

# Nous Hermes clean-install defaults (config_defaults.py / tools/tts_tool.py).
# Voicebox, Fish, Jarvis, and Cartman are optional add-ons, not stock.
STOCK_TTS_PROVIDER = "edge"
STOCK_EDGE_VOICE = "en-US-AriaNeural"


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
        "character_strength": entry.get("character_strength"),
        "provider": entry.get("provider") or "",
        "voice_name": entry.get("voice_name") or "",
        "has_stash": bool(entry.get("stash")),
    }


def stock_edge_updates() -> Dict[str, Any]:
    return {
        "tts.provider": STOCK_TTS_PROVIDER,
        "tts.edge.voice": STOCK_EDGE_VOICE,
    }


def _already_edge_stock(cfg: Dict[str, Any]) -> bool:
    provider = str(get_dotted(cfg, "tts.provider") or "").strip().lower()
    voice = get_dotted(cfg, "tts.edge.voice")
    return provider == "edge" and not bot_profiles.is_placeholder_voice_id(voice)


def _hermes_stock_tts_updates(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """First-run / no-stash stock: Edge AriaNeural. Never Voicebox Jarvis or ``default``."""
    if _already_edge_stock(cfg):
        return {}
    return stock_edge_updates()


def _stash_restore_updates(stash: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Restore pre-apply TTS when usable; otherwise Hermes Edge stock.

    Never writes Voicebox ``voice: default``, a Studio clone id as stock, or
    an invented Jarvis UUID. Promax session 20260922_094441_564b69: a
    placeholder Voicebox id made command TTS 404 and play no audio.

    Always restores ``agent.system_prompt`` (empty if none was stashed).
    Promax mechanic retest: leftover ``You are K.I.T.T....`` in
    ``agent.system_prompt`` made a "default" session stay KITT after
    ``display.personality`` was already empty.
    """
    updates: Dict[str, Any] = {}
    if "display.personality" in stash:
        val = stash.get("display.personality")
        updates["display.personality"] = "" if val is None else val
    else:
        updates["display.personality"] = ""

    stashed_prompt = stash.get("agent.system_prompt") if "agent.system_prompt" in stash else None
    updates["agent.system_prompt"] = "" if stashed_prompt is None else stashed_prompt

    provider = str(stash.get("tts.provider") or "").strip().lower()
    edge_voice = stash.get("tts.edge.voice")
    fish_voice = stash.get("tts.providers.fish.voice")
    fish_cmd = stash.get("tts.providers.fish.command")
    vb_voice = stash.get("tts.providers.voicebox.voice")

    if provider in ("edge",) or (
        not provider and not bot_profiles.is_placeholder_voice_id(edge_voice)
    ):
        updates["tts.provider"] = "edge"
        updates["tts.edge.voice"] = (
            edge_voice
            if not bot_profiles.is_placeholder_voice_id(edge_voice)
            else STOCK_EDGE_VOICE
        )
        return updates

    if provider in ("fish", "fish_audio") and not bot_profiles.is_placeholder_voice_id(fish_voice):
        updates["tts.provider"] = "fish"
        updates["tts.providers.fish.voice"] = fish_voice
        if fish_cmd not in (None, ""):
            updates["tts.providers.fish.command"] = fish_cmd
        return updates

    if provider == "voicebox" and bot_profiles.is_usable_voicebox_voice_id(vb_voice):
        updates["tts.provider"] = "voicebox"
        updates["tts.providers.voicebox.voice"] = vb_voice
        return updates

    # Stash missing, ``default``, empty, or non-UUID Voicebox: Edge stock,
    # unless the live file is already Edge.
    updates.update(_hermes_stock_tts_updates(cfg))
    return updates


def _is_studio_injected_prompt(cfg: Dict[str, Any], prompt: str) -> bool:
    """True when *prompt* is a Studio catalog overlay, not a user-owned soul."""
    text = str(prompt or "").strip()
    if not text:
        return False
    if is_style_overlay_prompt(text) or STYLE_OVERLAY_MARKER.lower() in text.lower():
        return True
    personalities = get_dotted(cfg, "agent.personalities") or {}
    if not isinstance(personalities, dict):
        return False
    for val in personalities.values():
        if not isinstance(val, dict) or val.get("source") != SOURCE_TAG:
            continue
        stored = str(val.get("system_prompt") or "").strip()
        if stored and stored == text:
            return True
    return False


def _clear_display_personality_for_stock(cfg_path: Path) -> bool:
    """Force stock: empty ``display.personality``. Catalog dicts stay put.

    Promax critic: leftover ``display.personality: cartman`` was a Hermes
    catalog name (no ``source: hermes-personastudio``). The old tagged-only
    clear left Cartman style with Edge stock voice. Any selected name is an
    ephemeral overlay — stock means none.
    """
    if not cfg_path.exists():
        return False
    cfg = load_yaml(cfg_path)
    selected = get_dotted(cfg, "display.personality")
    if selected in (None, ""):
        return False
    update_config_keys(cfg_path, {"display.personality": ""})
    return True


def _stock_system_prompt_update() -> Dict[str, Any]:
    return {"agent.system_prompt": ""}


def _clear_studio_injected_system_prompt(cfg_path: Path) -> bool:
    """Clear leftover Studio text from user-owned ``agent.system_prompt``.

    Catalog ``agent.personalities.*`` dicts stay (not active unless selected).
    User-owned prompts that do not match a Studio overlay are left alone.
    """
    if not cfg_path.exists():
        return False
    cfg = load_yaml(cfg_path)
    prompt = str(get_dotted(cfg, "agent.system_prompt") or "").strip()
    if not _is_studio_injected_prompt(cfg, prompt):
        return False
    update_config_keys(cfg_path, _stock_system_prompt_update())
    return True


def apply_session_overlay(
    profile_id: str,
    *,
    persona_name: str,
    persona_prompt: str,
    provider: Optional[str] = None,
    voice_id: Optional[str] = None,
    voice_name: Optional[str] = None,
    character_strength: Optional[Any] = None,
    cfg_path: Optional[Path] = None,
    state_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Stash stock settings (once) and apply style overlay + TTS for this session."""
    path = cfg_path or config_path_for_profile(profile_id)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found for profile '{profile_id}' at {path}")

    state = load_session_state(state_path)
    profiles = state.setdefault("profiles", {})
    entry = profiles.get(profile_id) or {}
    if not entry.get("active") or not isinstance(entry.get("stash"), dict):
        stash = snapshot_values(path, STASH_KEYS)
        cfg_for_stash = load_yaml(path)
        stashed_prompt = str(stash.get("agent.system_prompt") or "")
        if _is_studio_injected_prompt(cfg_for_stash, stashed_prompt):
            stash["agent.system_prompt"] = ""
        entry = {
            "active": False,
            "applied_persona": "",
            "stash": stash,
        }

    strength = character_strength_percent(character_strength)
    style_overlay = build_style_overlay_prompt(
        persona_name, persona_prompt, strength=strength
    )
    if strength <= 0:
        # 0% = no style overlay. Soul/AGENTS.md win. TTS may still bind.
        persona_result = bot_profiles.set_profile_persona(
            profile_id,
            "none",
            "",
            cfg_path=path,
            character_strength=0,
        )
        style_overlay = ""
    else:
        persona_result = bot_profiles.set_profile_persona(
            profile_id,
            persona_name,
            style_overlay,
            cfg_path=path,
            character_strength=strength,
        )
    cfg_live = load_yaml(path)
    live_prompt = str(get_dotted(cfg_live, "agent.system_prompt") or "")
    if _is_studio_injected_prompt(cfg_live, live_prompt):
        remember_writes(profile_id, path, ["agent.system_prompt"])
        update_config_keys(path, _stock_system_prompt_update())
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
    entry["applied_persona"] = bot_profiles._clean_key(persona_name)
    entry["character_strength"] = strength
    entry["provider"] = provider or ""
    entry["voice_name"] = voice_name or ""
    profiles[profile_id] = entry
    save_session_state(state, state_path)

    if strength <= 0:
        message = (
            f"No style overlay at 0% on '{profile_id}' — profile soul only. "
            "New Chat restores stock Hermes."
        )
    elif strength >= 100:
        message = (
            f"Character '{persona_name}' eclipses SOUL on '{profile_id}' for this session. "
            "New Chat restores stock Hermes."
        )
    else:
        message = (
            f"Speaking style '{persona_name}' at {strength}% on '{profile_id}'. "
            "New Chat restores stock Hermes."
        )

    return {
        "ok": True,
        "profile_id": profile_id,
        "scope": "session",
        "persona": entry["applied_persona"],
        "provider": (voice_result or {}).get("provider"),
        "voice": (voice_result or {}).get("voice"),
        "write_strategy": persona_result.get("write_strategy"),
        "style_overlay": style_overlay,
        "character_strength": strength,
        "touched_system_prompt": False,
        "message": message,
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
        cfg = load_yaml(path)
        updates = _stash_restore_updates(stash, cfg)
        if updates:
            update_config_keys(path, updates)
            restored_keys = list(updates.keys())
    elif path.exists():
        leftover_cleared = _clear_display_personality_for_stock(path)
        leftover_cleared = _clear_studio_injected_system_prompt(path) or leftover_cleared
        cfg = load_yaml(path)
        stock = _hermes_stock_tts_updates(cfg)
        if stock:
            update_config_keys(path, stock)
        restored_keys = list(stock.keys())

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
        leftover_cleared = _clear_display_personality_for_stock(cfg_path)
        leftover_cleared = _clear_studio_injected_system_prompt(cfg_path) or leftover_cleared
        placeholder_fix: Dict[str, Any] = {}
        if cfg_path.exists():
            cfg = load_yaml(cfg_path)
            provider = str(get_dotted(cfg, "tts.provider") or "").strip().lower()
            vb_voice = get_dotted(cfg, "tts.providers.voicebox.voice")
            if provider in ("", "voicebox") and not bot_profiles.is_usable_voicebox_voice_id(vb_voice):
                if provider == "voicebox" or bot_profiles.is_placeholder_voice_id(vb_voice):
                    placeholder_fix = _hermes_stock_tts_updates(cfg)
                    if placeholder_fix:
                        update_config_keys(cfg_path, placeholder_fix)
        if leftover_cleared or placeholder_fix:
            reports.append({
                "ok": True,
                "profile_id": pid,
                "restored": bool(placeholder_fix),
                "restored_keys": list(placeholder_fix.keys()),
                "leftover_personality_cleared": leftover_cleared,
                "active": False,
            })

    return {"ok": True, "profiles": reports}

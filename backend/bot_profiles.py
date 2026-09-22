"""Bot profile inspection and voice assignment for Hermes."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml


HERMES_HOME = Path(os.path.expanduser("~/.hermes"))
PROFILES_DIR = HERMES_HOME / "profiles"


def list_bot_profiles() -> List[Dict[str, Any]]:
    """Return all available Hermes bot profiles with their display titles and current voices."""
    profiles: List[Dict[str, Any]] = []

    # 1. Default profile
    def_cfg = HERMES_HOME / "config.yaml"
    if def_cfg.exists():
        try:
            with open(def_cfg, "r", encoding="utf-8") as f:
                c = yaml.safe_load(f) or {}
            tts = c.get("tts", {})
            tts_prov = tts.get("provider", "voicebox")
            prov_cfg = (tts.get("providers", {}) or {}).get(tts_prov, {}) or {}
            profiles.append({
                "id": "default",
                "title": "Default Assistant",
                "provider": tts_prov,
                "voice": prov_cfg.get("voice", "default"),
            })
        except Exception as e:
            print(f"[Profiles] Error reading default config: {e}")

    # 2. Named profiles in ~/.hermes/profiles/
    if PROFILES_DIR.exists():
        for p in sorted(PROFILES_DIR.iterdir()):
            if not p.is_dir() or p.name.startswith(".") or p.name == "default":
                continue

            # Read title from profile.yaml if present
            title = p.name
            p_yaml = p / "profile.yaml"
            if p_yaml.exists():
                try:
                    with open(p_yaml, "r", encoding="utf-8") as f:
                        py = yaml.safe_load(f) or {}
                    meta = (py.get("ui_meta", {}) or {}).get("hermes-bots", {}) or {}
                    title = meta.get("title") or p.name
                except Exception:
                    pass

            # Read current TTS config
            tts_prov = None
            current_voice = None
            c_path = p / "config.yaml"
            if c_path.exists():
                try:
                    with open(c_path, "r", encoding="utf-8") as f:
                        c = yaml.safe_load(f) or {}
                    tts = c.get("tts", {})
                    tts_prov = tts.get("provider")
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


def assign_voice_to_profile(
    profile_id: str,
    provider: str,
    voice_id: str,
    voice_name: str,
) -> Dict[str, Any]:
    """Assign a voice (Fish Audio or Voicebox) to a specific Hermes profile."""
    if profile_id == "default":
        cfg_path = HERMES_HOME / "config.yaml"
    else:
        cfg_path = PROFILES_DIR / profile_id / "config.yaml"

    if not cfg_path.exists():
        raise FileNotFoundError(f"Configuration file not found for profile '{profile_id}' at {cfg_path}")

    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    if "tts" not in cfg:
        cfg["tts"] = {}

    tts = cfg["tts"]
    if "providers" not in tts:
        tts["providers"] = {}

    target_prov = "fish" if provider in ("fish", "fish_audio") else "voicebox"
    tts["provider"] = target_prov

    clean_name = voice_name.lower().replace(" ", "_").replace("-", "_")

    if target_prov == "fish":
        if "fish" not in tts["providers"]:
            tts["providers"]["fish"] = {
                "type": "command",
                "provider_label": "Fish Audio (hosted)",
                "output_format": "wav",
                "timeout": 600,
                "clones": {},
            }
        fish_cfg = tts["providers"]["fish"]
        if "clones" not in fish_cfg or not isinstance(fish_cfg["clones"], dict):
            fish_cfg["clones"] = {}

        fish_cfg["clones"][clean_name] = voice_id
        fish_cfg["voice"] = clean_name
        # Update command template with the label if using the standard wrapper
        cmd = fish_cfg.get("command", "")
        if "--fish-label" in cmd:
            import re
            fish_cfg["command"] = re.sub(r"--fish-label\s+\S+", f"--fish-label {clean_name}", cmd)

    elif target_prov == "voicebox":
        if "voicebox" not in tts["providers"]:
            tts["providers"]["voicebox"] = {
                "type": "command",
                "output_format": "wav",
                "timeout": 600,
            }
        vb_cfg = tts["providers"]["voicebox"]
        vb_cfg["voice"] = voice_id

    # Write back safely
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False)

    return {
        "ok": True,
        "profile_id": profile_id,
        "provider": target_prov,
        "voice": clean_name if target_prov == "fish" else voice_id,
    }


def set_profile_persona(
    profile_id: str,
    persona_name: str,
    persona_prompt: str,
) -> Dict[str, Any]:
    """Set the persona for a Hermes profile via display.personality.
    
    This uses Hermes's built-in personality system — the same path as /personality slash command.
    The persona prompt is stored in agent.personalities.<name> and selected via display.personality.
    """
    if profile_id == "default":
        cfg_path = HERMES_HOME / "config.yaml"
    else:
        cfg_path = PROFILES_DIR / profile_id / "config.yaml"

    if not cfg_path.exists():
        raise FileNotFoundError(f"Configuration file not found for profile '{profile_id}' at {cfg_path}")

    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    # Ensure agent section exists
    if "agent" not in cfg:
        cfg["agent"] = {}
    
    agent = cfg["agent"]
    
    # Ensure personalities section exists
    if "personalities" not in agent or not isinstance(agent["personalities"], dict):
        agent["personalities"] = {}
    
    # Add/update the persona (normalized name)
    clean_name = persona_name.lower().replace(" ", "_").replace("-", "_")
    agent["personalities"][clean_name] = persona_prompt
    
    # Set display.personality to activate it
    if "display" not in cfg:
        cfg["display"] = {}
    cfg["display"]["personality"] = clean_name

    # Write back safely
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False)

    return {
        "ok": True,
        "profile_id": profile_id,
        "persona": clean_name,
        "message": f"Persona '{persona_name}' set for profile '{profile_id}' — restart session to take effect",
    }

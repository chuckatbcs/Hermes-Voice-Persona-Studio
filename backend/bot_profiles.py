"""Bot profile inspection and voice / persona assignment for Hermes.

Config writes are surgical (Hermes atomic round-trip when importable,
otherwise PyYAML mutate-only + atomic replace). Studio never patches
``~/.hermes/hermes-agent`` source files.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

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
# Fish reference ids are 32 hex chars with no separator. Rejecting anything
# else keeps labels and hand-typed placeholders (e.g. "kitt-id") out of the
# cache so they can never be sent upstream and 400.
_FISH_VOICE_ID = re.compile(r"^[0-9a-fA-F]{32}$")


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


def resolve_profile_tts(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Extract configured provider, voice label/id, and resolved voice_id/voice_name from profile config."""
    tts = (cfg.get("tts") or {}) if isinstance(cfg, dict) else {}
    prov_raw = str(tts.get("provider") or "").strip().lower()
    if not prov_raw:
        return {"provider": None, "voice": None, "voice_id": None, "voice_name": None}

    if prov_raw in ("edge", "edgetts"):
        edge_voice = str((tts.get("edge") or {}).get("voice") or "en-US-AriaNeural").strip()
        return {
            "provider": "edge",
            "voice": edge_voice,
            "voice_id": edge_voice,
            "voice_name": edge_voice,
        }

    prov_key = "fish" if prov_raw in ("fish", "fish_audio") else "voicebox"
    prov_cfg = (tts.get("providers", {}) or {}).get(prov_key, {}) or {}
    voice_label = str(prov_cfg.get("voice") or "").strip()

    voice_id = None
    voice_name = voice_label or None

    if prov_key == "voicebox":
        voice_id = voice_label
    elif prov_key == "fish":
        # Check command flag --fish-voice first
        cmd = str(prov_cfg.get("command") or "")
        match_voice = re.search(r"--fish-voice\s+([^\s]+)", cmd)
        if match_voice:
            voice_id = match_voice.group(1).strip()
        # Fall back to clones dict. This map lives in the user's config.yaml,
        # so only obvious placeholders are rejected here — not a strict id
        # format, which would silently break if Fish ever changes its shape.
        if not voice_id:
            clones = prov_cfg.get("clones") or {}
            if isinstance(clones, dict):
                candidate = clones.get(voice_label)
                if not is_placeholder_voice_id(candidate):
                    voice_id = candidate
        # Fall back to ~/.hermes/fish_voices.json, read through the canonical
        # loader. This file is Studio-owned, so it IS held to the real Fish id
        # format: legacy flat-string and nested-dict entries are normalized, and
        # hand-typed placeholders ("kitt-id") are dropped rather than sent
        # upstream to 400.
        if not voice_id:
            voice_id = load_cached_fish_voices().get(voice_label)

    return {
        "provider": prov_key,
        "voice": voice_label or None,
        "voice_id": voice_id or voice_label or None,
        "voice_name": voice_name or voice_label or None,
    }


def list_bot_profiles() -> List[Dict[str, Any]]:
    """Return all available Hermes bot profiles with their display titles and current voices."""
    profiles: List[Dict[str, Any]] = []
    home = hermes_home()

    def_cfg = home / "config.yaml"
    if def_cfg.exists():
        try:
            c = load_yaml(def_cfg)
            resolved = resolve_profile_tts(c)
            profiles.append({
                "id": "default",
                "title": "Default Assistant",
                "provider": resolved["provider"],
                "voice": resolved["voice"],
                "voice_id": resolved["voice_id"],
                "voice_name": resolved["voice_name"],
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

            resolved = {"provider": None, "voice": None, "voice_id": None, "voice_name": None}
            c_path = p / "config.yaml"
            if c_path.exists():
                try:
                    c = load_yaml(c_path)
                    resolved = resolve_profile_tts(c)
                except Exception:
                    pass

            profiles.append({
                "id": p.name,
                "title": title,
                "provider": resolved["provider"],
                "voice": resolved["voice"],
                "voice_id": resolved["voice_id"],
                "voice_name": resolved["voice_name"],
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


def _coerce_cached_voice_id(value: Any) -> Optional[str]:
    """Canonical voice id from any historical cache shape.

    Studio used to write flat strings *and* nested dicts into the same
    ``fish_voices.json``, so readers had to branch on three shapes. Fish
    ``default`` clones additionally hold non-hex placeholder ids like
    ``kitt-id`` which 400 the API. Normalize to one shape and reject
    placeholders so a stale label can never be sent upstream.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, dict):
        for key in ("voice_id", "id"):
            raw = value.get(key)
            if isinstance(raw, str) and raw.strip():
                text = raw.strip()
                break
        else:
            return None
    else:
        return None
    if not text or text.lower() in _PLACEHOLDER_VOICE_IDS:
        return None
    # Fish reference ids are 32 hex chars. Anything else is a label or a
    # placeholder that was pasted in by mistake (e.g. "kitt-id").
    if not _FISH_VOICE_ID.match(text):
        return None
    return text


def repair_cached_fish_voices(
    voices: Optional[Iterable[Any]] = None,
) -> Dict[str, Any]:
    """Replace placeholder cache ids with the real clone id, when one exists.

    ``hermes_kitt`` was cached as the literal string ``"kitt-id"`` — a
    placeholder, not a Fish reference id. Migration alone would DROP that
    label, silently losing a working clone, so try to rebind it first against
    the live provider catalog by name.

    Returns ``{repaired: {label: id}, dropped: [label]}``. A placeholder with
    no live twin stays in ``dropped`` — an unrepairable label must not keep
    pointing at an id that will 400.
    """
    catalog = list(voices) if voices is not None else []
    path = fish_voices_cache_path()
    report: Dict[str, Any] = {"ok": True, "repaired": {}, "dropped": []}
    if not path.exists() or not catalog:
        return report
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return report
    if not isinstance(raw, dict):
        return report

    by_name: Dict[str, str] = {}
    for info in catalog:
        vid = _coerce_cached_voice_id(getattr(info, "id", None))
        name = str(getattr(info, "name", "") or "")
        if vid and name:
            by_name.setdefault(_clean_key(name), vid)

    for label in list(raw.keys()):
        if label == "voices":
            continue
        if _coerce_cached_voice_id(raw[label]) is not None:
            continue  # already a real id
        candidate = (
            by_name.get(_clean_key(label))
            or by_name.get(_clean_key(str(label).replace("hermes_", "", 1)))
        )
        if candidate:
            prior = raw[label] if isinstance(raw[label], dict) else {}
            raw[label] = {**prior, "voice_id": candidate}
            report["repaired"][label] = candidate
        else:
            report["dropped"].append(str(label))
    if not report["repaired"]:
        return report

    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".fish_voices_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(raw, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return report


def preview_cached_fish_drops() -> List[str]:
    """Labels the canonical migration would drop, without writing anything.

    A dropped label had a placeholder id (e.g. the literal ``kitt-id``), so
    leaving it in place means TTS sends a value Fish will 400 on.
    """
    path = fish_voices_cache_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, dict):
        return []
    dropped: List[str] = []
    sources = ([raw.get("voices")] if isinstance(raw.get("voices"), dict) else []) + [
        {k: v for k, v in raw.items() if k != "voices"}
    ]
    for source in sources:
        for label, value in (source or {}).items():
            if label and _coerce_cached_voice_id(value) is None and label not in dropped:
                dropped.append(str(label))
    return sorted(dropped)


def migrate_cached_fish_voices(*, cache_path: Optional[Path] = None) -> Dict[str, Any]:
    """Rewrite the Fish label cache into the one canonical shape.

    Repairs the three-shapes-at-once file in place: flat-string values become
    ``{voice_id: ...}``, the legacy nested ``voices`` map is folded up, and any
    label whose value is a placeholder (e.g. the literal ``kitt-id``) is
    dropped rather than left to 400 Fish on the next TTS call. Existing
    metadata (``title``, ``source``) is preserved.

    Returns the before/after label counts and what was removed.
    """
    path = cache_path or fish_voices_cache_path()
    report: Dict[str, Any] = {
        "ok": True,
        "path": str(path),
        "changed": False,
        "before": 0,
        "after": 0,
        "dropped": [],
        "retyped": [],
    }
    if not path.exists():
        return report
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return report
    if not isinstance(raw, dict):
        return report

    report["before"] = len([k for k in raw if k != "voices"])
    canonical: Dict[str, Any] = {}
    nested = raw.get("voices")
    sources = ([nested] if isinstance(nested, dict) else []) + [
        {k: v for k, v in raw.items() if k != "voices"}
    ]
    for source in sources:
        for label, value in (source or {}).items():
            if not label:
                continue
            vid = _coerce_cached_voice_id(value)
            if vid is None:
                if label not in report["dropped"]:
                    report["dropped"].append(str(label))
                continue
            if isinstance(value, str) and str(label) not in report["retyped"]:
                report["retyped"].append(str(label))
            # Top-level (later) sources win; metadata is merged, not clobbered.
            existing = canonical.get(label)
            prior: Dict[str, Any] = existing if isinstance(existing, dict) else {}
            canonical[label] = {**prior, "voice_id": vid}

    report["after"] = len(canonical)
    if canonical == raw:
        return report

    report["changed"] = True
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".fish_voices_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(canonical, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return report


def load_cached_fish_voices() -> Dict[str, str]:
    """Read the Fish label cache into one canonical ``{label: voice_id}`` map."""
    path = fish_voices_cache_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out: Dict[str, str] = {}
    # A nested "voices" map is a legacy Studio shape; fold it in first so the
    # top-level (canonical) entries win on conflict.
    nested = data.get("voices")
    if isinstance(nested, dict):
        for label, raw in nested.items():
            vid = _coerce_cached_voice_id(raw)
            if label and vid:
                out[str(label)] = vid
    for label, raw in data.items():
        if label == "voices":
            continue
        vid = _coerce_cached_voice_id(raw)
        if label and vid:
            out[str(label)] = vid
    return out


def save_cached_voice(label: str, voice_id: str, voice_name: str = "") -> Optional[Path]:
    """Sync ~/.hermes/fish_voices.json so --fish-label resolves the bound id.

    Writes ONE canonical shape (flat ``{label: {voice_id, ...}}`` matching
    ``fish_tts.save_cached_voice``) as a single atomic full-file replace, so a
    concurrent reader can never observe a half-written cache and a stale
    label can never resurrect a deleted model.
    """
    clean_label = _clean_key(label)
    vid = _coerce_cached_voice_id(voice_id)
    path = fish_voices_cache_path()
    if not clean_label or vid is None:
        return None

    # Delegate to fish_tts so we share its path resolution and shape, then
    # rewrite the whole file canonically in one atomic replace.
    try:
        from fish_tts import save_cached_voice as _imported  # type: ignore

        meta = {"title": voice_name} if voice_name else None
        _imported(clean_label, vid, meta)
    except Exception:
        store: Dict[str, Any] = {}
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    store = existing
            except Exception:
                store = {}
        store[clean_label] = {
            "voice_id": vid,
            **({"title": voice_name} if voice_name else {}),
            "source": SOURCE_TAG,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".fish_voices_", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(store, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
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

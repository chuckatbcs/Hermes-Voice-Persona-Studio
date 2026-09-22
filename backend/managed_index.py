"""Tracks PersonaStudio writes so ``install.py --uninstall --purge`` can revert them.

Never deletes a whole ``config.yaml``. The index lives at
``~/.hermes/personas/.studio-managed.json`` (outside hermes-agent).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .config_io import snapshot_values, update_config_keys
from .paths import config_path_for_profile, managed_index_path

SOURCE_TAG = "hermes-personastudio"


def _empty_index() -> Dict[str, Any]:
    return {"version": 1, "profiles": {}}


def load_index(path: Optional[Path] = None) -> Dict[str, Any]:
    target = path or managed_index_path()
    if not target.exists():
        return _empty_index()
    try:
        with open(target, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return _empty_index()
        data.setdefault("version", 1)
        data.setdefault("profiles", {})
        return data
    except Exception:
        return _empty_index()


def save_index(index: Dict[str, Any], path: Optional[Path] = None) -> None:
    target = path or managed_index_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(index, handle, indent=2, sort_keys=True)
        handle.write("\n")
    tmp.replace(target)


def _profile_entry(index: Dict[str, Any], profile_id: str) -> Dict[str, Any]:
    profiles = index.setdefault("profiles", {})
    entry = profiles.setdefault(profile_id, {})
    entry.setdefault("personality_keys", [])
    entry.setdefault("tts_keys", [])
    entry.setdefault("previous", {})
    return entry


def remember_writes(
    profile_id: str,
    cfg_path: Path,
    keys: Iterable[str],
    *,
    personality_key: Optional[str] = None,
    index_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Record keys we are about to write, snapshotting prior values once."""
    key_list = [k for k in keys if k]
    index = load_index(index_path)
    entry = _profile_entry(index, profile_id)
    previous = entry["previous"]
    snaps = snapshot_values(cfg_path, key_list) if cfg_path.exists() else {}
    for key in key_list:
        if key not in previous:
            previous[key] = snaps.get(key)
        if key.startswith("agent.personalities.") or key.startswith("display.personality"):
            continue
        if key not in entry["tts_keys"]:
            entry["tts_keys"].append(key)
    if personality_key:
        if personality_key not in entry["personality_keys"]:
            entry["personality_keys"].append(personality_key)
    save_index(index, index_path)
    return index


def revert_profile_entry(profile_id: str, entry: Dict[str, Any], cfg_path: Path) -> List[str]:
    """Restore snapshotted values (or delete keys whose previous value was None)."""
    restored: List[str] = []
    if not cfg_path.exists():
        return restored
    previous = entry.get("previous") or {}
    updates: Dict[str, Any] = {}
    for key, old in previous.items():
        updates[key] = old
        restored.append(key)
    # If a Studio personality is still selected, clear the overlay.
    personality_keys = entry.get("personality_keys") or []
    if personality_keys:
        # Display personality is restored via previous snapshot when we wrote it.
        # Drop Studio-tagged personality definitions we created even if the
        # snapshot missed them (first-run create).
        for name in personality_keys:
            dotted = f"agent.personalities.{name}"
            if dotted not in updates:
                updates[dotted] = None
                restored.append(dotted)
    if updates:
        update_config_keys(cfg_path, updates)
    return restored


def purge_tracked_config(*, index_path: Optional[Path] = None) -> Dict[str, Any]:
    """Revert Studio-tracked keys in every recorded profile config. Never deletes the file."""
    index = load_index(index_path)
    report: Dict[str, Any] = {"profiles": {}, "ok": True}
    for profile_id, entry in (index.get("profiles") or {}).items():
        cfg_path = config_path_for_profile(profile_id)
        restored = revert_profile_entry(profile_id, entry, cfg_path)
        report["profiles"][profile_id] = {
            "config": str(cfg_path),
            "restored_keys": restored,
            "existed": cfg_path.exists(),
        }
    # Drop the index after a successful revert so a second purge is a no-op.
    target = index_path or managed_index_path()
    if target.exists():
        try:
            target.unlink()
        except OSError:
            report["ok"] = False
    return report

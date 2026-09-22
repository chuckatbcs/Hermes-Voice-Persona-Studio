"""Surgical Hermes config.yaml updates.

Prefer Nous Hermes ``atomic_roundtrip_yaml_update`` when the user's
``~/.hermes/hermes-agent`` checkout is importable. That path preserves
comments, key order, quoting, and Unicode.

Otherwise fall back to a PyYAML load → mutate dotted keys only → atomic
replace dump. Residual risk of the fallback is documented in
``docs/AGENT_REVIEW.md``: comments and original scalar quoting can be lost
because PyYAML re-serializes the whole document. Unrelated mapping keys
and their values are still preserved.

This module never rewrites ``~/.hermes/hermes-agent`` source.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

import yaml

STRATEGY_HERMES_ATOMIC = "hermes-atomic"
STRATEGY_PYYAML_SURGICAL = "pyyaml-surgical"

_HERMES_AGENT_CANDIDATES = (
    Path(os.path.expanduser("~/.hermes/hermes-agent")),
    Path(os.environ.get("HERMES_AGENT_ROOT") or ""),
)


def _hermes_agent_roots() -> Iterable[Path]:
    seen = set()
    for candidate in _HERMES_AGENT_CANDIDATES:
        if not candidate or not str(candidate).strip():
            continue
        resolved = candidate.resolve() if candidate.exists() else candidate
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        yield candidate


def _try_import_hermes_atomic():
    """Return atomic_roundtrip_yaml_update or None. Never raises to callers."""
    for root in _hermes_agent_roots():
        if not (root / "utils.py").is_file():
            continue
        inserted = str(root) not in sys.path
        if inserted:
            sys.path.insert(0, str(root))
        try:
            existing = sys.modules.get("utils")
            if existing is not None:
                existing_file = str(getattr(existing, "__file__", "") or "")
                if existing_file and not existing_file.startswith(str(root)):
                    if inserted:
                        try:
                            sys.path.remove(str(root))
                        except ValueError:
                            pass
                    continue
            from utils import atomic_roundtrip_yaml_update  # type: ignore

            if not callable(atomic_roundtrip_yaml_update):
                raise TypeError("atomic_roundtrip_yaml_update is not callable")
            return atomic_roundtrip_yaml_update
        except Exception:
            if inserted:
                try:
                    sys.path.remove(str(root))
                except ValueError:
                    pass
    return None


def _split_dotted(key_path: str) -> Tuple[str, ...]:
    # Escape-aware split so ``tts.providers.fish.clones.a.b`` stays dotted segments.
    parts: list[str] = []
    buf = []
    escaped = False
    for ch in key_path:
        if escaped:
            buf.append(ch)
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == ".":
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    parts.append("".join(buf))
    return tuple(p for p in parts if p)


def get_dotted(data: Any, key_path: str, default: Any = None) -> Any:
    node = data
    for seg in _split_dotted(key_path):
        if not isinstance(node, dict) or seg not in node:
            return default
        node = node[seg]
    return node


def set_dotted(data: Dict[str, Any], key_path: str, value: Any) -> None:
    segs = _split_dotted(key_path)
    if not segs:
        raise ValueError("empty key path")
    node: Dict[str, Any] = data
    for seg in segs[:-1]:
        nxt = node.get(seg)
        if not isinstance(nxt, dict):
            nxt = {}
            node[seg] = nxt
        node = nxt
    leaf = segs[-1]
    if value is None:
        node.pop(leaf, None)
    else:
        node[leaf] = value


def _atomic_yaml_dump(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = None
    if path.exists():
        mode = path.stat().st_mode
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.stem}_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.safe_dump(
                data,
                handle,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        if mode is not None:
            try:
                os.chmod(path, mode)
            except OSError:
                pass
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML root at {path} is not a mapping")
    return data


def update_config_keys(path: Path, updates: Dict[str, Any]) -> str:
    """Apply dotted-key updates. ``None`` deletes a key.

    Returns the strategy used: ``hermes-atomic`` or ``pyyaml-surgical``.
    """
    if not updates:
        return STRATEGY_PYYAML_SURGICAL

    hermes_update = _try_import_hermes_atomic()
    if hermes_update is not None:
        try:
            for key, value in updates.items():
                hermes_update(path, key, value)
            return STRATEGY_HERMES_ATOMIC
        except Exception:
            # Fall through to PyYAML so a Hermes import that later fails
            # (ruamel missing, deleted profile, etc.) still lands the write.
            pass

    cfg = load_yaml(path)
    for key, value in updates.items():
        set_dotted(cfg, key, value)
    _atomic_yaml_dump(path, cfg)
    return STRATEGY_PYYAML_SURGICAL


def snapshot_values(path: Path, keys: Iterable[str]) -> Dict[str, Any]:
    cfg = load_yaml(path)
    return {key: get_dotted(cfg, key) for key in keys}

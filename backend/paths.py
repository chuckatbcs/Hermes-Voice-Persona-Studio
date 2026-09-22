"""Resolves Hermes home and PersonaStudio sidecar paths.

All writes stay outside ``~/.hermes/hermes-agent`` so Nous checkouts remain clean.
Tests inject ``HERMES_HOME`` to keep the suite offline.
"""
from __future__ import annotations

import os
from pathlib import Path


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes"))


def personas_root() -> Path:
    return hermes_home() / "personas"


def profiles_dir() -> Path:
    return hermes_home() / "profiles"


def managed_index_path() -> Path:
    return personas_root() / ".studio-managed.json"


def session_state_path() -> Path:
    return personas_root() / ".studio-session.json"


def config_path_for_profile(profile_id: str) -> Path:
    if profile_id == "default":
        return hermes_home() / "config.yaml"
    return profiles_dir() / profile_id / "config.yaml"

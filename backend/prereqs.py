"""
Automated Voicebox & TTS Model Provisioning for PersonaStudio.
Ensures local GPU models (Kokoro, Chatterbox Turbo, Qwen) and demo voices
are automatically discovered, downloaded, and registered upon install.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

VOICEBOX_BASE_URL = "http://127.0.0.1:17493"
DEFAULT_ENGINES = ["kokoro", "chatterbox_turbo", "qwen"]


def is_voicebox_healthy(base_url: str = VOICEBOX_BASE_URL) -> bool:
    try:
        req = urllib.request.Request(f"{base_url.rstrip('/')}/health")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.status == 200
    except Exception:
        return False


def get_models_status(base_url: str = VOICEBOX_BASE_URL) -> List[Dict]:
    try:
        req = urllib.request.Request(f"{base_url.rstrip('/')}/models/status")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode())
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("models") or data.get("items") or []
    except Exception as e:
        print(f"[Prereqs] Warning: could not fetch /models/status: {e}")
    return []


def ensure_local_models(base_url: str = VOICEBOX_BASE_URL) -> List[str]:
    """Verify and trigger downloads for default models if missing."""
    if not is_voicebox_healthy(base_url):
        return []

    models = get_models_status(base_url)
    downloaded_names = {
        m.get("model_name") or m.get("name")
        for m in models
        if m.get("downloaded") or m.get("ready")
    }

    triggered: List[str] = []
    # Identify available models to download if needed
    for m in models:
        name = m.get("model_name") or m.get("name")
        engine = m.get("engine") or ""
        if (engine in DEFAULT_ENGINES or name in DEFAULT_ENGINES) and name not in downloaded_names:
            print(f"[Prereqs] Triggering download for model: {name} ({engine})...")
            try:
                post_req = urllib.request.Request(
                    f"{base_url.rstrip('/')}/models/download",
                    data=json.dumps({"model_name": name}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(post_req, timeout=10.0) as resp:
                    if resp.status in (200, 201, 202):
                        triggered.append(name)
            except Exception as e:
                print(f"[Prereqs] Could not trigger download for {name}: {e}")

    return triggered


def ensure_sample_voices(base_url: str = VOICEBOX_BASE_URL) -> bool:
    """Ensure at least one local default voice exists so synthesis works out-of-the-box."""
    if not is_voicebox_healthy(base_url):
        return False

    try:
        req = urllib.request.Request(f"{base_url.rstrip('/')}/profiles")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            profiles = json.loads(resp.read().decode())
            if len(profiles) > 0:
                return True  # Already has local profiles
    except Exception:
        return False

    # Create a default high-quality preset profile (Kokoro / Qwen)
    default_profile = {
        "name": "Hermes Default",
        "language": "en",
        "voice_type": "preset",
        "preset_engine": "kokoro",
        "preset_voice_id": "am_adam",
        "default_engine": "kokoro",
        "personality": "You are a helpful, clear AI assistant.",
    }
    try:
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/profiles",
            data=json.dumps(default_profile).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            if resp.status in (200, 201):
                print("[Prereqs] Created initial default local voice profile.")
                return True
    except Exception as e:
        print(f"[Prereqs] Failed to create default profile: {e}")

    return False

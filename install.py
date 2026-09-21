#!/usr/bin/env python3
"""Hermes PersonaStudio — Non-Destructive Installer & Manager."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN_SRC = Path(__file__).parent / "desktop" / "plugin.js"
HERMES_DESKTOP_PLUGINS = Path(os.path.expanduser("~/.hermes/desktop-plugins/hermes-personastudio"))
COMPANION_SERVER_PY = Path(__file__).parent / "server.py"


def install():
    print("=" * 60)
    print("  Installing Hermes PersonaStudio (MVP)")
    print("=" * 60)

    # 1. Check Python dependencies
    print("[1/5] Checking environment dependencies...")
    try:
        import fastapi
        import uvicorn
        import requests
        print("  ✓ FastAPI, Uvicorn, and Requests available.")
    except ImportError as e:
        print(f"  ✗ Missing dependency: {e}. Please run: pip install fastapi uvicorn requests")
        return 1

    # 2. Check local Voicebox & Model Provisioning
    print("[2/5] Checking local GPU Voicebox models & default voices...")
    try:
        from backend.prereqs import is_voicebox_healthy, ensure_local_models, ensure_sample_voices
        if is_voicebox_healthy():
            print("  ✓ Local GPU Voicebox is running on http://127.0.0.1:17493.")
            triggered = ensure_local_models()
            if triggered:
                print(f"  ✓ Download queued for missing engine models: {', '.join(triggered)}")
            else:
                print("  ✓ Required TTS models verified.")
            ensure_sample_voices()
        else:
            print("  ℹ Voicebox is not active locally — cloud Fish Audio will serve as the primary provider.")
    except Exception as e:
        print(f"  ℹ Model provision note: {e}")

    # 3. Seed factory presets
    print("[3/5] Seeding factory presets (~/.hermes/personas/)...")
    seed_script = Path(__file__).parent / "seed_presets.py"
    if seed_script.exists():
        subprocess.run([sys.executable, str(seed_script)], check=True)

    # 4. Deploy desktop plugin and companion server
    print(f"[4/5] Deploying plugin and companion backend to {HERMES_DESKTOP_PLUGINS}...")
    HERMES_DESKTOP_PLUGINS.mkdir(parents=True, exist_ok=True)
    
    # Copy backend, server.py, and desktop
    for item in ["desktop", "backend", "server.py"]:
        src = Path(__file__).parent / item
        dst = HERMES_DESKTOP_PLUGINS / item
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        elif src.is_file():
            shutil.copy2(src, dst)
            
    # Hermes Desktop searches directly for plugin.js at the root of the plugin directory
    shutil.copy2(PLUGIN_SRC, HERMES_DESKTOP_PLUGINS / "plugin.js")
    print(f"  ✓ Deployed plugin and backend to {HERMES_DESKTOP_PLUGINS}")

    # 5. Check/Start background companion service
    print("[5/5] Starting PersonaStudio companion service on port 17495...")
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:17495/api/studio/status", timeout=1) as resp:
            if resp.status == 200:
                print("  ✓ Companion service is already running on http://127.0.0.1:17495.")
    except Exception:
        # Start in background
        proc = subprocess.Popen(
            [sys.executable, str(COMPANION_SERVER_PY)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        print(f"  ✓ Launched background companion daemon (PID: {proc.pid}) on port 17495.")

    print("\n" + "=" * 60)
    print("  Installation Complete! 🎉")
    print("  1. Launch or reload Hermes Desktop.")
    print("  2. Click '🎭 Personas' or '🎙️ Studio' in the titlebar.")
    print("  3. Create clones, tune sliders, live audition, and switch!")
    print("=" * 60)
    return 0


def uninstall():
    print("=" * 60)
    print("  Uninstalling Hermes PersonaStudio")
    print("=" * 60)

    if HERMES_DESKTOP_PLUGINS.exists():
        shutil.rmtree(HERMES_DESKTOP_PLUGINS)
        print(f"  ✓ Removed desktop plugin from {HERMES_DESKTOP_PLUGINS}")

    # Kill running server on port 17495
    try:
        cmd = "lsof -ti:17495 | xargs -r kill -9"
        subprocess.run(cmd, shell=True)
        print("  ✓ Stopped companion server daemon.")
    except Exception:
        pass

    print("\nPersonaStudio uninstalled cleanly. Hermes core remains untouched.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Hermes PersonaStudio Installer")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall PersonaStudio completely")
    args = parser.parse_args()

    if args.uninstall:
        return uninstall()
    return install()


if __name__ == "__main__":
    sys.exit(main())

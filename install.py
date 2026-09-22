#!/usr/bin/env python3
"""Hermes PersonaStudio — Non-Destructive Installer & Manager."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERMES_HOME = Path(os.path.expanduser("~/.hermes"))
HERMES_DESKTOP_PLUGINS = HERMES_HOME / "desktop-plugins" / "hermes-personastudio"
COMPANION_SERVER_PY = Path(__file__).parent / "server.py"
USER_SYSTEMD_DIR = Path(os.path.expanduser("~/.config/systemd/user"))
SYSTEMD_UNIT_NAME = "hermes-personastudio.service"
SYSTEMD_MARKER = "# Managed-by: hermes-personastudio-install"
COMPANION_PORT = 17495


def _systemd_unit_path() -> Path:
    return USER_SYSTEMD_DIR / SYSTEMD_UNIT_NAME


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, **kwargs)


def _systemctl_user(*args: str) -> None:
    try:
        _run(["systemctl", "--user", *args], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        pass


def _unit_is_ours(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return SYSTEMD_MARKER in text or "Hermes PersonaStudio companion" in text


def write_systemd_unit(exec_python: str, server_path: Path, working_dir: Path) -> Path:
    USER_SYSTEMD_DIR.mkdir(parents=True, exist_ok=True)
    unit = f"""{SYSTEMD_MARKER}
[Unit]
Description=Hermes PersonaStudio companion
After=network.target

[Service]
Type=simple
WorkingDirectory={working_dir}
Environment=PYTHONPATH={working_dir}
ExecStart={exec_python} {server_path}
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
"""
    path = _systemd_unit_path()
    path.write_text(unit, encoding="utf-8")
    _systemctl_user("daemon-reload")
    _systemctl_user("enable", "--now", SYSTEMD_UNIT_NAME)
    return path


def stop_companion_systemd() -> None:
    _systemctl_user("stop", SYSTEMD_UNIT_NAME)
    _systemctl_user("disable", SYSTEMD_UNIT_NAME)


def remove_companion_systemd_unit() -> bool:
    path = _systemd_unit_path()
    if not path.exists():
        return False
    if not _unit_is_ours(path):
        print(f"  ℹ Left systemd unit in place (not Studio-managed): {path}")
        return False
    try:
        path.unlink()
        _systemctl_user("daemon-reload")
        print(f"  ✓ Removed systemd user unit {path}")
        return True
    except OSError as exc:
        print(f"  ℹ Could not remove systemd unit: {exc}")
        return False


def kill_companion_port() -> None:
    try:
        cmd = f"lsof -ti:{COMPANION_PORT} | xargs -r kill -9"
        _run(cmd, shell=True)
        print("  ✓ Stopped companion server daemon.")
    except Exception:
        pass


def remove_stray_plugin_py(plugin_dir: Path) -> None:
    stray = plugin_dir / "plugin.py"
    if stray.exists() or stray.is_symlink():
        stray.unlink()
        print(f"  ✓ Removed stray misnamed {stray}")


def deploy_plugin(src_root: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for item in ["desktop", "backend", "server.py"]:
        src = src_root / item
        dst = dest / item
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        elif src.is_file():
            shutil.copy2(src, dst)
    plugin_js = src_root / "desktop" / "plugin.js"
    shutil.copy2(plugin_js, dest / "plugin.js")
    remove_stray_plugin_py(dest)
    # Never copy a misnamed plugin.py even if one exists in src.
    leftover = dest / "plugin.py"
    if leftover.exists():
        leftover.unlink()


def sync_voices_from_install() -> None:
    repo_root = Path(__file__).parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from backend.api import PROVIDERS, storage
    from backend.persona_sync import collect_provider_voices, sync_personas_from_voices

    voices = collect_provider_voices(PROVIDERS)
    result = sync_personas_from_voices(storage, voices)
    print(
        f"  ✓ Sync-from-voices: created={len(result['created'])} "
        f"updated={len(result['updated'])} skipped={len(result['skipped'])}"
    )


def install(sync_voices: bool = True, systemd: bool = False) -> int:
    print("=" * 60)
    print("  Installing Hermes PersonaStudio (MVP)")
    print("=" * 60)

    # 1. Check Python dependencies
    print("[1/6] Checking environment dependencies...")
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
        import requests  # noqa: F401
        import yaml  # noqa: F401
        print("  ✓ FastAPI, Uvicorn, Requests, and PyYAML available.")
    except ImportError as e:
        print(f"  ✗ Missing dependency: {e}. Please run: pip install -r requirements.txt")
        return 1

    # 2. Check local Voicebox & Model Provisioning
    print("[2/6] Checking local GPU Voicebox models & default voices...")
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
    print("[3/6] Seeding factory presets (~/.hermes/personas/)...")
    seed_script = Path(__file__).parent / "seed_presets.py"
    if seed_script.exists():
        subprocess.run([sys.executable, str(seed_script)], check=True)

    # 4. Deploy desktop plugin and companion server
    print(f"[4/6] Deploying plugin and companion backend to {HERMES_DESKTOP_PLUGINS}...")
    deploy_plugin(Path(__file__).parent, HERMES_DESKTOP_PLUGINS)
    print(f"  ✓ Deployed plugin.js (not plugin.py) and backend to {HERMES_DESKTOP_PLUGINS}")

    # 5. Reconcile existing Voicebox/Fish clones into speaking personas
    print("[5/6] Syncing persona bundles from existing clones...")
    if sync_voices:
        try:
            sync_voices_from_install()
        except Exception as e:
            print(f"  ℹ Sync-from-voices skipped: {e}")
    else:
        print("  ℹ Skipped (--no-sync-voices). Run later: python3 install.py --sync-voices")

    # 6. Check/Start background companion service
    print("[6/6] Starting PersonaStudio companion service on port 17495...")
    if systemd:
        try:
            unit = write_systemd_unit(sys.executable, HERMES_DESKTOP_PLUGINS / "server.py", HERMES_DESKTOP_PLUGINS)
            print(f"  ✓ Installed and started systemd user unit: {unit}")
        except Exception as e:
            print(f"  ℹ systemd helper failed ({e}); falling back to a background process.")
            systemd = False
    if not systemd:
        try:
            import urllib.request
            with urllib.request.urlopen("http://127.0.0.1:17495/api/studio/status", timeout=1) as resp:
                if resp.status == 200:
                    print("  ✓ Companion service is already running on http://127.0.0.1:17495.")
        except Exception:
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
    print("  3. Picking a persona OR a clone applies LLM system text + bound TTS voice.")
    print("=" * 60)
    return 0


def uninstall(purge: bool = False) -> int:
    print("=" * 60)
    print("  Uninstalling Hermes PersonaStudio")
    print("=" * 60)

    print("[1/4] Stopping companion systemd unit (if present)...")
    stop_companion_systemd()
    remove_companion_systemd_unit()

    print("[2/4] Removing desktop plugin...")
    if HERMES_DESKTOP_PLUGINS.exists():
        shutil.rmtree(HERMES_DESKTOP_PLUGINS)
        print(f"  ✓ Removed desktop plugin from {HERMES_DESKTOP_PLUGINS}")
    else:
        print("  ℹ Plugin directory already absent.")

    print("[3/4] Stopping companion process on port 17495...")
    kill_companion_port()

    if purge:
        print("[4/4] --purge: reverting Studio-tracked config keys and removing personas/...")
        try:
            repo_root = Path(__file__).parent
            if str(repo_root) not in sys.path:
                sys.path.insert(0, str(repo_root))
            from backend.managed_index import purge_tracked_config

            report = purge_tracked_config()
            for profile_id, info in (report.get("profiles") or {}).items():
                keys = info.get("restored_keys") or []
                print(f"  ✓ Reverted {len(keys)} tracked key(s) on profile '{profile_id}' ({info.get('config')})")
            print("  ✓ Never deleted any config.yaml file.")
        except Exception as e:
            print(f"  ℹ Config revert note: {e}")

        personas = HERMES_HOME / "personas"
        if personas.exists():
            shutil.rmtree(personas)
            print(f"  ✓ Removed {personas}")
        else:
            print("  ℹ personas/ already absent.")
    else:
        print("[4/4] Keeping ~/.hermes/personas/ and Hermes config.yaml (pass --purge to revert Studio keys).")

    print("\nPersonaStudio uninstalled. Hermes core and ~/.hermes/hermes-agent remain untouched.")
    if not purge:
        print("Tracked personality/TTS keys were left in place. Use --purge to revert them.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Hermes PersonaStudio Installer")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall PersonaStudio plugin + companion")
    parser.add_argument(
        "--purge",
        action="store_true",
        help="With --uninstall: also remove ~/.hermes/personas/ and revert Studio-tracked config keys (never deletes config.yaml)",
    )
    parser.add_argument(
        "--sync-voices",
        action="store_true",
        help="Only reconcile existing TTS clones into ~/.hermes/personas/ bundles (idempotent)",
    )
    parser.add_argument(
        "--no-sync-voices",
        action="store_true",
        help="Skip clone→persona reconciliation during install",
    )
    parser.add_argument(
        "--systemd",
        action="store_true",
        help="Install and start a systemd --user unit for the companion daemon",
    )
    args = parser.parse_args()

    if args.purge and not args.uninstall:
        parser.error("--purge requires --uninstall")

    if args.sync_voices and not args.uninstall:
        # Standalone reconciliation path (also used after clones already exist).
        print("Syncing speaking personas from existing TTS clones...")
        try:
            seed_script = Path(__file__).parent / "seed_presets.py"
            if seed_script.exists():
                subprocess.run([sys.executable, str(seed_script)], check=False)
            sync_voices_from_install()
            return 0
        except Exception as e:
            print(f"Sync failed: {e}")
            return 1

    if args.uninstall:
        return uninstall(purge=args.purge)
    return install(sync_voices=not args.no_sync_voices, systemd=args.systemd)


if __name__ == "__main__":
    sys.exit(main())

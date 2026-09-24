#!/usr/bin/env python3
"""Hermes PersonaStudio — Non-Destructive Installer & Manager.

One entry point for Linux and Windows. Linux can persist the companion with
systemd --user. Windows registers a per-user Startup launcher that starts the
installed plugin server (not a source checkout path).
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from backend.paths import hermes_home
from install_platform import (
    COMPANION_PORT,
    MANAGED_MARKER,
    check_prereqs,
    companion_state_from,
    configure_stdio,
    detect_os,
    install_windows_startup,
    print_prereqs,
    remove_windows_startup,
    say,
    windows_startup_folder,
)

SYSTEMD_MARKER = MANAGED_MARKER
SYSTEMD_UNIT_NAME = "hermes-personastudio.service"
USER_SYSTEMD_DIR = Path(os.path.expanduser("~/.config/systemd/user"))
REPO_ROOT = Path(__file__).parent


def plugin_dest() -> Path:
    return hermes_home() / "desktop-plugins" / "hermes-personastudio"


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
        say("info", f"Left systemd unit in place (not Studio-managed): {path}")
        return False
    try:
        path.unlink()
        _systemctl_user("daemon-reload")
        say("ok", f"Removed systemd user unit {path}")
        return True
    except OSError as exc:
        say("info", f"Could not remove systemd unit: {exc}")
        return False


def kill_companion_port() -> None:
    """Stop whatever is listening on the companion port. OS-aware."""
    os_kind = detect_os()
    if os_kind == "windows":
        script = (
            f"$conns = Get-NetTCPConnection -LocalPort {COMPANION_PORT} -State Listen "
            "-ErrorAction SilentlyContinue; "
            "if (-not $conns) { exit 3 }; "
            "$conns | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
        )
        try:
            result = _run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            say("info", "powershell.exe not found; companion process was not stopped.")
            return
        if result.returncode == 0:
            say("ok", f"Stopped listener on port {COMPANION_PORT}.")
        else:
            say("info", f"No listener stopped on port {COMPANION_PORT}.")
        return

    try:
        result = _run(
            ["lsof", "-ti", f":{COMPANION_PORT}"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        say("info", "lsof is not installed; companion process was not stopped.")
        return
    pids = [part for part in (result.stdout or "").split() if part.isdigit()]
    if not pids:
        say("info", f"No listener found on port {COMPANION_PORT}.")
        return
    for pid in pids:
        try:
            os.kill(int(pid), signal.SIGKILL)
        except OSError:
            continue
    say("ok", f"Stopped companion server daemon on port {COMPANION_PORT}.")


def remove_stray_plugin_py(plugin_dir: Path) -> None:
    stray = plugin_dir / "plugin.py"
    if stray.exists() or stray.is_symlink():
        stray.unlink()
        say("ok", f"Removed stray misnamed {stray}")


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
    leftover = dest / "plugin.py"
    if leftover.exists():
        leftover.unlink()


def sync_voices_from_install() -> None:
    repo_root = REPO_ROOT
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from backend.api import PROVIDERS, storage
    from backend.persona_sync import collect_provider_voices, sync_personas_from_voices

    voices = collect_provider_voices(PROVIDERS)
    result = sync_personas_from_voices(storage, voices)
    say(
        "ok",
        "Sync-from-voices: "
        f"created={len(result['created'])} "
        f"updated={len(result['updated'])} skipped={len(result['skipped'])}",
    )


def _launch_background(server_path: Path, working_dir: Path) -> subprocess.Popen:
    kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
        "cwd": str(working_dir),
    }
    if detect_os() == "windows":
        flags = int(getattr(subprocess, "DETACHED_PROCESS", 0x00000008))
        flags |= int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
        kwargs["creationflags"] = flags
        kwargs["close_fds"] = True
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen([sys.executable, str(server_path)], **kwargs)


def _print_plan(os_kind: str, dest: Path, *, systemd: bool, startup: Path | None) -> None:
    server = dest / "server.py"
    say("info", f"OS: {os_kind}")
    say("info", f"Plugin directory: {dest}")
    say("info", f"Companion server: {server} on port {COMPANION_PORT}")
    if os_kind == "windows":
        say("info", f"Startup launcher: {startup / 'Hermes_PersonaStudio_Companion.vbs' if startup else 'Startup folder'}")
        say("info", f"Starter script: {hermes_home() / 'scripts' / 'start_personastudio_companion.ps1'}")
    elif systemd:
        say("info", f"systemd --user unit: {_systemd_unit_path()}")
    else:
        say("info", "Linux persistence: background process only (pass --systemd for a user unit)")


def install(
    sync_voices: bool = True,
    systemd: bool = False,
    dry_run: bool = False,
    platform_name: str | None = None,
    startup_dir: Path | None = None,
    prereq_kwargs: dict | None = None,
) -> int:
    configure_stdio()
    os_kind = detect_os(platform_name) if platform_name is not None else detect_os()
    print("=" * 60)
    print("  Installing Hermes PersonaStudio (MVP)")
    print("=" * 60)

    if os_kind == "unsupported":
        found = platform_name or sys.platform
        say("fail", f"Unsupported operating system: {found}. PersonaStudio install supports Windows and Linux.")
        return 2

    if systemd and os_kind != "linux":
        say("warn", "--systemd is Linux-only. Windows registers a Startup-folder launcher instead.")
        systemd = False

    home = hermes_home()
    dest = plugin_dest()
    print("[1/7] Checking prerequisites (Python, packages, Hermes home, optional providers)...")
    overrides = dict(prereq_kwargs or {})
    overrides.setdefault("touch_home", not dry_run)
    report = check_prereqs(home, **overrides)
    print_prereqs(report)
    if report.hard_failed():
        say("fail", "Prerequisite checks failed. Nothing was deployed.")
        return 1

    startup = None
    if os_kind == "windows":
        try:
            startup = windows_startup_folder(startup_dir)
        except OSError as exc:
            say("fail", str(exc))
            return 1

    if dry_run:
        print("[2/7] Dry run — planned actions:")
        _print_plan(os_kind, dest, systemd=systemd, startup=startup)
        say("info", "Dry run: no files copied and no process started.")
        return 0

    print("[2/7] Checking local GPU Voicebox models and default voices...")
    try:
        from backend.prereqs import ensure_local_models, ensure_sample_voices, is_voicebox_healthy

        if is_voicebox_healthy():
            say("ok", "Local GPU Voicebox is running on http://127.0.0.1:17493.")
            triggered = ensure_local_models()
            if triggered:
                say("ok", "Download queued for missing engine models: " + ", ".join(triggered))
            else:
                say("ok", "Required TTS models verified.")
            ensure_sample_voices()
        else:
            say("info", "Voicebox is not active locally. Cloud Fish Audio can serve as the primary provider.")
    except Exception as exc:
        say("info", f"Model provision note: {exc}")

    print("[3/7] Seeding factory presets (~/.hermes/personas/)...")
    seed_script = REPO_ROOT / "seed_presets.py"
    if seed_script.exists():
        subprocess.run([sys.executable, str(seed_script)], check=True)

    print(f"[4/7] Deploying plugin and companion backend to {dest}...")
    deploy_plugin(REPO_ROOT, dest)
    say("ok", f"Deployed plugin.js (not plugin.py) and backend to {dest}")

    print("[5/7] Syncing persona bundles from existing clones...")
    if sync_voices:
        try:
            sync_voices_from_install()
        except Exception as exc:
            say("info", f"Sync-from-voices skipped: {exc}")
    else:
        say("info", "Skipped (--no-sync-voices). Run later: python3 install.py --sync-voices")

    print(f"[6/7] Starting PersonaStudio companion service on port {COMPANION_PORT}...")
    server_path = dest / "server.py"
    companion_state = companion_state_from(report)
    started_by_systemd = False
    if os_kind == "linux" and systemd:
        try:
            unit = write_systemd_unit(sys.executable, server_path, dest)
            say("ok", f"Installed and started systemd user unit: {unit}")
            started_by_systemd = True
        except Exception as exc:
            say("info", f"systemd helper failed ({exc}); falling back to a background process.")
    if not started_by_systemd:
        if companion_state == "up":
            say("ok", f"Companion service is already running on http://127.0.0.1:{COMPANION_PORT}.")
        elif companion_state == "occupied":
            say("warn", f"Port {COMPANION_PORT} is occupied by another process. Companion was not started.")
        else:
            try:
                proc = _launch_background(server_path, dest)
                say("ok", f"Launched background companion (PID: {proc.pid}) on port {COMPANION_PORT}.")
            except OSError as exc:
                say("fail", f"Could not start companion: {exc}")
                return 1

    print("[7/7] Registering reboot persistence...")
    if os_kind == "windows":
        if startup is None:
            say("fail", "Windows Startup folder was not resolved.")
            return 1
        try:
            written = install_windows_startup(home, sys.executable, startup)
        except OSError as exc:
            say("fail", f"Could not register Windows startup: {exc}")
            return 1
        for path in written:
            say("ok", f"Wrote {path}")
    elif started_by_systemd:
        say("ok", "Reboot persistence is the systemd --user unit.")
    else:
        say("info", "No reboot persistence requested. Pass --systemd on Linux to install a user unit.")

    print("\n" + "=" * 60)
    print("  Installation complete.")
    print("  1. Launch or reload Hermes Desktop.")
    print("  2. Open Personas or Studio in the titlebar.")
    print("  3. Picking a complete persona pack applies speaking style + cloned TTS.")
    print("=" * 60)
    return 0


def uninstall(
    purge: bool = False,
    platform_name: str | None = None,
    startup_dir: Path | None = None,
    stop_process: bool = True,
) -> int:
    configure_stdio()
    os_kind = detect_os(platform_name) if platform_name is not None else detect_os()
    print("=" * 60)
    print("  Uninstalling Hermes PersonaStudio")
    print("=" * 60)

    if os_kind == "unsupported":
        found = platform_name or sys.platform
        say("fail", f"Unsupported operating system: {found}. Uninstall supports Windows and Linux.")
        return 2

    print("[1/4] Stopping companion persistence...")
    if os_kind == "linux":
        stop_companion_systemd()
        remove_companion_systemd_unit()
    else:
        try:
            startup = windows_startup_folder(startup_dir)
        except OSError as exc:
            say("fail", str(exc))
            return 1
        removed = remove_windows_startup(hermes_home(), startup)
        if removed:
            for path in removed:
                say("ok", f"Removed Windows startup artifact {path}")
        else:
            say("info", "No Studio-managed Windows startup files were present.")

    print("[2/4] Removing desktop plugin...")
    dest = plugin_dest()
    if dest.exists():
        shutil.rmtree(dest)
        say("ok", f"Removed desktop plugin from {dest}")
    else:
        say("info", "Plugin directory already absent.")

    print(f"[3/4] Stopping companion process on port {COMPANION_PORT}...")
    if stop_process:
        kill_companion_port()
    else:
        say("info", "Skipped stopping the companion process.")

    if purge:
        print("[4/4] --purge: reverting Studio-tracked config keys and removing personas/...")
        try:
            repo_root = REPO_ROOT
            if str(repo_root) not in sys.path:
                sys.path.insert(0, str(repo_root))
            from backend.managed_index import purge_tracked_config

            report = purge_tracked_config()
            for profile_id, info in (report.get("profiles") or {}).items():
                keys = info.get("restored_keys") or []
                say("ok", f"Reverted {len(keys)} tracked key(s) on profile '{profile_id}' ({info.get('config')})")
            say("ok", "Never deleted any config.yaml file.")
        except Exception as exc:
            say("info", f"Config revert note: {exc}")

        personas = hermes_home() / "personas"
        if personas.exists():
            shutil.rmtree(personas)
            say("ok", f"Removed {personas}")
        else:
            say("info", "personas/ already absent.")
    else:
        print("[4/4] Keeping ~/.hermes/personas/ and Hermes config.yaml (pass --purge to revert Studio keys).")

    print("\nPersonaStudio uninstalled. Hermes core and ~/.hermes/hermes-agent remain untouched.")
    if not purge:
        print("Tracked personality/TTS keys were left in place. Use --purge to revert them.")
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
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
        help="Skip clone-to-persona reconciliation during install",
    )
    parser.add_argument(
        "--systemd",
        action="store_true",
        help="Linux only: install and start a systemd --user unit for the companion daemon",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect the OS, run prerequisite checks, and print the install plan without copying files or starting processes",
    )
    args = parser.parse_args(argv)

    if args.purge and not args.uninstall:
        parser.error("--purge requires --uninstall")
    if args.dry_run and args.uninstall:
        parser.error("--dry-run cannot be combined with --uninstall")

    if args.sync_voices and not args.uninstall:
        print("Syncing speaking personas from existing TTS clones...")
        try:
            seed_script = REPO_ROOT / "seed_presets.py"
            if seed_script.exists():
                subprocess.run([sys.executable, str(seed_script)], check=False)
            sync_voices_from_install()
            return 0
        except Exception as exc:
            say("fail", f"Sync failed: {exc}")
            return 1

    if args.uninstall:
        return uninstall(purge=args.purge)
    return install(sync_voices=not args.no_sync_voices, systemd=args.systemd, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())

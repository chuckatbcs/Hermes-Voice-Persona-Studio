"""OS helpers for the PersonaStudio installer.

``install.py`` is the only entry point. This module detects Windows vs Linux,
runs prerequisite checks, and renders the Windows Startup launcher. It does
not import FastAPI or start services.
"""
from __future__ import annotations

import importlib.util
import os
import socket
import sys
from dataclasses import dataclass, field
from pathlib import Path

COMPANION_PORT = 17495
VOICEBOX_PORT = 17493
VOICEBOX_URL = "http://127.0.0.1:17493"
MIN_PYTHON = (3, 10)
MANAGED_MARKER = "# Managed-by: hermes-personastudio-install"
STARTUP_VBS_NAME = "Hermes_PersonaStudio_Companion.vbs"
STARTUP_PS1_NAME = "start_personastudio_companion.ps1"
REQUIRED_MODULES = (
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    ("requests", "requests"),
    ("pyyaml", "yaml"),
)


@dataclass
class Check:
    name: str
    status: str  # ok, warn, fail, info
    detail: str


@dataclass
class PrereqReport:
    checks: list[Check] = field(default_factory=list)

    def hard_failed(self) -> bool:
        return any(item.status == "fail" for item in self.checks)


def detect_os(platform_name: str | None = None) -> str:
    """Return ``windows``, ``linux``, or ``unsupported``."""
    plat = (platform_name if platform_name is not None else sys.platform).lower()
    if plat in {"windows", "win32", "cygwin"} or plat.startswith("win"):
        return "windows"
    if plat in {"linux"} or plat.startswith("linux"):
        return "linux"
    return "unsupported"


def configure_stdio() -> None:
    """Prefer UTF-8 on consoles that default to cp1252. Messages stay ASCII."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            continue


def say(status: str, message: str) -> None:
    labels = {"ok": "[ok]", "warn": "[warn]", "fail": "[fail]", "info": "[info]"}
    print(f"  {labels.get(status, '[info]')} {message}")


def missing_required_modules() -> list[str]:
    missing: list[str] = []
    for dist_name, module_name in REQUIRED_MODULES:
        if importlib.util.find_spec(module_name) is None:
            missing.append(dist_name)
    return missing


def tcp_open(port: int, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            return sock.connect_ex((host, port)) == 0
    except OSError:
        return False


def probe_companion(port: int = COMPANION_PORT) -> str:
    """Return ``down``, ``up``, or ``occupied``."""
    if not tcp_open(port):
        return "down"
    try:
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/studio/status", timeout=1) as resp:
            if getattr(resp, "status", 0) == 200:
                return "up"
    except Exception:
        return "occupied"
    return "occupied"


def fish_key_present(home: Path) -> bool:
    """True when a Fish key is configured. Never returns the key itself."""
    if (os.environ.get("FISH_KEY") or os.environ.get("FISH_API_KEY") or "").strip():
        return True
    key_file = home / "fish_key.txt"
    if key_file.is_file():
        try:
            if key_file.read_text(encoding="utf-8", errors="replace").strip():
                return True
        except OSError:
            pass
    cfg_path = home / "config.yaml"
    if not cfg_path.is_file():
        return False
    try:
        import yaml
    except ImportError:
        return False
    try:
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return False
    if not isinstance(cfg, dict):
        return False
    tts = cfg.get("tts") or {}
    if not isinstance(tts, dict):
        return False
    providers = tts.get("providers") or {}
    if not isinstance(providers, dict):
        return False
    fish = providers.get("fish") or {}
    if not isinstance(fish, dict):
        return False
    return bool(str(fish.get("api_key") or "").strip())


def check_write_access(home: Path, *, touch: bool) -> tuple[bool, str]:
    """Confirm Hermes home can be written. ``touch`` may create the directory."""
    try:
        if home.exists():
            if not home.is_dir():
                return False, f"{home} exists but is not a directory"
            probe = home / ".studio-install-probe"
            probe.write_text("ok", encoding="ascii")
            probe.unlink()
            return True, str(home)
        parent = home
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        if not parent.exists() or not os.access(parent, os.W_OK):
            return False, f"cannot write under {parent}"
        if not touch:
            return True, f"{home} (parent {parent} is writable)"
        home.mkdir(parents=True, exist_ok=True)
        probe = home / ".studio-install-probe"
        probe.write_text("ok", encoding="ascii")
        probe.unlink()
        return True, str(home)
    except OSError as exc:
        return False, str(exc)


def check_prereqs(
    home: Path,
    *,
    touch_home: bool = False,
    python_version: tuple[int, int] | None = None,
    missing_modules: list[str] | None = None,
    voicebox_up: bool | None = None,
    fish_present: bool | None = None,
    companion_state: str | None = None,
) -> PrereqReport:
    report = PrereqReport()
    version = python_version if python_version is not None else sys.version_info[:2]
    if version < MIN_PYTHON:
        report.checks.append(
            Check(
                "python",
                "fail",
                f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required; found {version[0]}.{version[1]}",
            )
        )
    else:
        report.checks.append(Check("python", "ok", f"Python {version[0]}.{version[1]}"))

    missing = missing_required_modules() if missing_modules is None else list(missing_modules)
    if missing:
        report.checks.append(
            Check(
                "packages",
                "fail",
                "missing " + ", ".join(missing) + " — run: pip install -r requirements.txt",
            )
        )
    else:
        report.checks.append(Check("packages", "ok", "fastapi, uvicorn, requests, pyyaml"))

    writable, detail = check_write_access(home, touch=touch_home)
    report.checks.append(Check("hermes-home", "ok" if writable else "fail", detail))

    if voicebox_up is None:
        try:
            from backend.prereqs import is_voicebox_healthy

            voicebox_up = is_voicebox_healthy()
        except Exception:
            voicebox_up = False
    if voicebox_up:
        report.checks.append(Check("voicebox", "ok", f"optional Voicebox is up on {VOICEBOX_URL}"))
    else:
        report.checks.append(
            Check(
                "voicebox",
                "warn",
                f"optional Voicebox is not responding on {VOICEBOX_URL}; local GPU TTS stays unavailable",
            )
        )

    present = fish_key_present(home) if fish_present is None else fish_present
    if present:
        report.checks.append(Check("fish-key", "ok", "Fish API key is configured (value not shown)"))
    else:
        report.checks.append(
            Check(
                "fish-key",
                "warn",
                "optional Fish API key not found "
                "(FISH_KEY, FISH_API_KEY, fish_key.txt, or config.yaml tts.providers.fish.api_key)",
            )
        )

    state = probe_companion() if companion_state is None else companion_state
    if state == "down":
        report.checks.append(Check("companion-port", "ok", f"port {COMPANION_PORT} is free"))
    elif state == "up":
        report.checks.append(
            Check(
                "companion-port",
                "info",
                f"companion already responding on http://127.0.0.1:{COMPANION_PORT}",
            )
        )
    else:
        report.checks.append(
            Check(
                "companion-port",
                "warn",
                f"port {COMPANION_PORT} is in use but /api/studio/status did not respond",
            )
        )
    return report


def print_prereqs(report: PrereqReport) -> None:
    for item in report.checks:
        say(item.status, f"{item.name}: {item.detail}")


def windows_startup_folder(override: Path | None = None) -> Path:
    if override is not None:
        return override
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise OSError("APPDATA is not set; cannot locate the per-user Startup folder")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def ps_single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def render_windows_ps1(python_exe: str) -> str:
    quoted = ps_single_quote(python_exe)
    return f"""{MANAGED_MARKER}
# Starts the installed PersonaStudio companion. No source-checkout path.
$ErrorActionPreference = 'Stop'
$port = {COMPANION_PORT}
try {{
    $listening = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($listening) {{ exit 0 }}
}} catch {{}}
$plugin = Join-Path $env:USERPROFILE '.hermes\\desktop-plugins\\hermes-personastudio'
$server = Join-Path $plugin 'server.py'
if (-not (Test-Path -LiteralPath $server)) {{ exit 1 }}
$python = {quoted}
if (-not (Test-Path -LiteralPath $python)) {{
    $python = $null
    foreach ($name in @('py', 'python')) {{
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) {{ $python = $cmd.Source; break }}
    }}
}}
if (-not $python) {{
    $candidates = @(
        (Join-Path $env:LocalAppData 'Programs\\Python\\Python313\\python.exe'),
        (Join-Path $env:LocalAppData 'Programs\\Python\\Python312\\python.exe'),
        (Join-Path $env:LocalAppData 'Programs\\Python\\Python311\\python.exe'),
        (Join-Path $env:LocalAppData 'Programs\\Python\\Python310\\python.exe'),
        'C:\\Program Files\\Python313\\python.exe',
        'C:\\Program Files\\Python312\\python.exe',
        'C:\\Program Files\\Python311\\python.exe',
        'C:\\Program Files\\Python310\\python.exe'
    )
    foreach ($candidate in $candidates) {{
        if (Test-Path -LiteralPath $candidate) {{ $python = $candidate; break }}
    }}
}}
if (-not $python) {{ exit 1 }}
Start-Process -FilePath $python -ArgumentList @($server) -WorkingDirectory $plugin -WindowStyle Hidden
"""


def render_windows_vbs() -> str:
    """Hidden Startup launcher. Resolves the installed PS1 via %USERPROFILE%."""
    ps1_expr = (
        'ps1 = sh.ExpandEnvironmentStrings("%USERPROFILE%") & "\\.hermes\\scripts\\'
        + STARTUP_PS1_NAME
        + '"'
    )
    command_expr = (
        'command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps1 & """"'
    )
    return "\n".join(
        [
            f"' {MANAGED_MARKER}",
            "Option Explicit",
            "Dim sh, ps1, command",
            'Set sh = CreateObject("WScript.Shell")',
            ps1_expr,
            command_expr,
            "sh.Run command, 0, False",
            "",
        ]
    )


def companion_state_from(report: PrereqReport) -> str:
    """Map the companion-port check to ``down``, ``up``, or ``occupied``."""
    for item in report.checks:
        if item.name != "companion-port":
            continue
        if item.status == "info":
            return "up"
        if item.status == "warn":
            return "occupied"
        return "down"
    return "down"


def script_dir(home: Path) -> Path:
    return home / "scripts"


def windows_artifact_paths(home: Path, startup: Path) -> list[Path]:
    scripts = script_dir(home)
    return [
        scripts / STARTUP_PS1_NAME,
        scripts / STARTUP_VBS_NAME,
        startup / STARTUP_VBS_NAME,
    ]


def is_managed_text(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return MANAGED_MARKER in text


def install_windows_startup(home: Path, python_exe: str, startup: Path) -> list[Path]:
    scripts = script_dir(home)
    scripts.mkdir(parents=True, exist_ok=True)
    startup.mkdir(parents=True, exist_ok=True)
    written = [
        scripts / STARTUP_PS1_NAME,
        scripts / STARTUP_VBS_NAME,
        startup / STARTUP_VBS_NAME,
    ]
    written[0].write_text(render_windows_ps1(python_exe), encoding="utf-8")
    vbs = render_windows_vbs()
    written[1].write_text(vbs, encoding="utf-8")
    written[2].write_text(vbs, encoding="utf-8")
    return written


def remove_windows_startup(home: Path, startup: Path) -> list[Path]:
    """Remove Studio-managed Startup files only. Leave unrelated scripts alone."""
    removed: list[Path] = []
    for path in windows_artifact_paths(home, startup):
        if not path.exists():
            continue
        if not is_managed_text(path):
            continue
        path.unlink()
        removed.append(path)
    scripts = script_dir(home)
    try:
        if scripts.is_dir() and not any(scripts.iterdir()):
            scripts.rmdir()
    except OSError:
        pass
    return removed

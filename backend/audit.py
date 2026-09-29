"""Persona pack audit: report drift instead of silently serving a wrong voice.

Three classes of problem the Studio UI could not previously see:

- **manifest drift** — a pack whose id no longer matches what the session
  state or the profile config refers to (O-1)
- **dead voice** — a pack bound to a voice that is no longer in the provider
  catalog, so apply falls back to something else (O-4)
- **shared fallback id** — a pack whose Voicebox id is also pinned as some
  profile's ``tts.providers.voicebox.voice``, so when Fish fails that profile
  speaks as this pack (O-4)
- **strength disagreement** — manifest vs the applied profile config (O-5)

Everything here is read-only.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from . import bot_profiles, persona_sync
from .config_io import get_dotted, load_yaml
from .pack_ids import reconcile_applied_persona
from .paths import config_path_for_profile
from .persona_sync import overlay_strength_percent

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _profile_voicebox_fallbacks() -> Dict[str, List[str]]:
    """Map Voicebox voice id -> profile ids that pin it as their voice."""
    out: Dict[str, List[str]] = {}
    for profile in bot_profiles.list_bot_profiles():
        pid = profile.get("id")
        if not pid:
            continue
        cfg_path = config_path_for_profile(pid)
        if not cfg_path.exists():
            continue
        try:
            cfg = load_yaml(cfg_path)
        except Exception:
            continue
        vid = get_dotted(cfg, "tts.providers.voicebox.voice")
        if isinstance(vid, str) and vid.strip() and not bot_profiles.is_placeholder_voice_id(vid):
            out.setdefault(vid.strip(), []).append(pid)
    return out


def audit_personas(
    bundles: Sequence[Any],
    voices: Iterable[Any],
    *,
    session_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return ``{ok, findings, summary}`` for every pack in *bundles*."""
    catalog = [persona_sync._voice_as_info(v) for v in voices]
    by_id: Dict[str, Any] = {}
    for info in catalog:
        if info.id:
            by_id.setdefault(info.id, info)
    known_ids = [b.id for b in bundles if getattr(b, "id", None)]
    fallbacks = _profile_voicebox_fallbacks()
    findings: List[Dict[str, Any]] = []

    def _add(severity: str, code: str, message: str, **extra: Any) -> None:
        findings.append(
            {"severity": severity, "code": code, "message": message, **extra}
        )

    for bundle in bundles:
        bid = getattr(bundle, "id", "")
        vid = getattr(bundle, "voice_id", "")
        provider = getattr(bundle, "provider", "")

        # --- dead voice -------------------------------------------------
        if vid and not persona_sync.is_placeholder_voice_id(vid):
            if vid not in by_id:
                twins = persona_sync.find_name_matching_clones(
                    [bundle.name, bid, getattr(bundle, "voice_name", "")],
                    catalog,
                    fish_only=persona_sync.is_fish_provider(provider),
                )
                if twins:
                    _add(
                        "medium",
                        "voice-rebound",
                        f"Pack '{bid}' is bound to {vid}, which is gone from the "
                        f"{provider} catalog; '{twins[0].name}' ({twins[0].id}) can serve it.",
                        persona_id=bid,
                        missing_voice_id=vid,
                        suggested_voice_id=twins[0].id,
                    )
                else:
                    _add(
                        "high",
                        "voice-missing",
                        f"Pack '{bid}' is bound to {vid}, which no longer exists in "
                        f"the {provider} catalog and has no name twin.",
                        persona_id=bid,
                        missing_voice_id=vid,
                    )

        # --- shared Voicebox fallback -----------------------------------
        if not persona_sync.is_fish_provider(provider) and vid in fallbacks:
            _add(
                "medium",
                "shared-fallback-voice",
                f"Pack '{bid}' shares Voicebox voice {vid} with profile(s) "
                f"{', '.join(sorted(fallbacks[vid]))}; if Fish fails, that profile "
                f"speaks as '{getattr(bundle, 'name', bid)}'.",
                persona_id=bid,
                voice_id=vid,
                profiles=sorted(fallbacks[vid]),
            )

        # --- strength disagreement (O-5) ---------------------------------
        manifest_strength = persona_sync.character_strength_percent(
            getattr(bundle, "character_strength", None)
        )
        prompt_strength = overlay_strength_percent(getattr(bundle, "system_prompt", ""))
        if prompt_strength is not None and prompt_strength != manifest_strength:
            _add(
                "low",
                "strength-mismatch",
                f"Pack '{bid}' manifest says {manifest_strength}% but its prompt text "
                f"embeds {prompt_strength}%.",
                persona_id=bid,
                manifest_strength=manifest_strength,
                prompt_strength=prompt_strength,
            )

    # --- session overlay drift (O-1) ---------------------------------------
    for profile_id, entry in ((session_state or {}).get("profiles") or {}).items():
        if not isinstance(entry, dict) or not entry.get("active"):
            continue
        applied = entry.get("applied_persona") or ""
        if not applied:
            continue
        resolved = reconcile_applied_persona(applied, known_ids)
        if resolved is None:
            _add(
                "high",
                "overlay-orphan",
                f"Profile '{profile_id}' has an active overlay for '{applied}', which is "
                f"not a persona pack; the titlebar cannot show what is applied.",
                profile_id=profile_id,
                applied_persona=applied,
            )
        elif resolved != applied:
            _add(
                "medium",
                "overlay-id-drift",
                f"Profile '{profile_id}' applied '{applied}' but the pack id is "
                f"'{resolved}'; run reconcile to repair it.",
                profile_id=profile_id,
                applied_persona=applied,
                pack_id=resolved,
            )

    # --- untracked clone: a real voice with no pack at all -------------------
    bound = {getattr(b, "voice_id", "") for b in bundles}
    for info in catalog:
        if info.voice_type not in ("cloned", "custom"):
            continue
        if info.id in bound:
            continue
        if any(
            persona_sync.names_match(info.name, getattr(b, "name", "")) for b in bundles
        ):
            continue
        _add(
            "low",
            "voice-without-pack",
            f"{info.provider} clone '{info.name}' ({info.id}) has no persona pack.",
            voice_id=info.id,
            voice_name=info.name,
        )

    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9), f["code"]))
    summary: Dict[str, int] = {}
    for f in findings:
        summary[f["severity"]] = summary.get(f["severity"], 0) + 1
    return {
        "ok": True,
        "pack_count": len(bundles),
        "voice_count": len(catalog),
        "summary": summary,
        "findings": findings,
    }

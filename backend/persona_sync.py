"""Create and reconcile speaking-persona bundles from TTS voices.

A speaking persona is display name + LLM system prompt + bound TTS voice.
Clones that exist only as Voicebox/Fish voices get a matching bundle under
``~/.hermes/personas/`` so the Desktop titlebar can apply both text and voice.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .providers.base import VoiceInfo
from .storage import PersonaBundle, PersonaStorage

GENERIC_DESCRIPTION_PREFIXES = (
    "fish audio clone",
    "[voicebox sample persona",
    "cloned via hermes personastudio",
    "re-sampled voice reference",
)

STOP_TOKENS = frozenset({"the", "a", "an", "of", "and", "my", "voice", "clone", "hermes"})

FISH_PROVIDERS = frozenset({"fish", "fish_audio"})
PREFERRED_TTS_PROVIDER = "fish_audio"


def slugify_persona_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return slug or "persona"


def normalize_voice_slug(name: str) -> str:
    """Slug used for TTS matching. Strips a leading ``hermes_`` Fish-list prefix."""
    slug = slugify_persona_id(name)
    while slug.startswith("hermes_"):
        slug = slug[len("hermes_") :].lstrip("_")
    return slug or slugify_persona_id(name)


def name_tokens(name: str) -> set:
    tokens = set(normalize_voice_slug(name).split("_"))
    return {t for t in tokens if t and t not in STOP_TOKENS}


def is_fish_provider(provider: Optional[str]) -> bool:
    return (provider or "").strip().lower() in FISH_PROVIDERS


def provider_display_name(provider: Optional[str]) -> str:
    return "Fish" if is_fish_provider(provider) else "Voicebox"


def provider_rank(provider: Optional[str]) -> int:
    """Higher rank wins when reconciling Fish vs Voicebox onto one bundle."""
    if is_fish_provider(provider):
        return 2
    if (provider or "").strip().lower() == "voicebox":
        return 1
    return 0


def names_match(left: str, right: str) -> bool:
    return name_match_score(left, right) > 0


def name_match_score(needle: str, haystack: str) -> int:
    """Higher is a better TTS twin. 0 means no usable match.

    Exact slug (after stripping a Fish ``Hermes `` prefix) wins. Equal token
    sets beat subsets, so ``Eric Cartman`` prefers ``Hermes eric_cartman``
    over the shorter ``Hermes cartman`` twin.
    """
    if not needle or not haystack:
        return 0
    ns, hs = normalize_voice_slug(needle), normalize_voice_slug(haystack)
    if not ns or not hs:
        return 0
    if ns == hs:
        return 1000
    nt, ht = name_tokens(needle), name_tokens(haystack)
    if not nt or not ht:
        return 0
    if nt == ht:
        return 900
    if nt < ht:
        return 400 + 20 * len(nt) + 5 * len(ht)
    if ht < nt:
        return 200 + 20 * len(ht)
    inter = nt & ht
    if inter:
        return 50 + 10 * len(inter)
    return 0


def is_generic_voice_description(description: Optional[str]) -> bool:
    text = (description or "").strip()
    if not text:
        return True
    lowered = text.lower()
    if any(lowered.startswith(prefix) for prefix in GENERIC_DESCRIPTION_PREFIXES):
        return True
    return False


STYLE_OVERLAY_MARKER = "SPEAKING STYLE OVERLAY"
CHARACTER_ECLIPSE_MARKER = "CHARACTER IDENTITY"

# Legacy Soft/Medium/Strong labels migrate to these percents.
STRENGTH_LEGACY_PERCENT = {"soft": 25, "medium": 55, "strong": 85}
DEFAULT_CHARACTER_STRENGTH_PERCENT = 25

_PLACEHOLDER_VOICE_IDS = frozenset({"", "default", "none", "null", "undefined", "system"})
_STUB_PROMPT_EXACT = frozenset({"todo", "placeholder", "tbd", "stub"})
_STUB_PROMPT_PREFIXES = (
    "distinctive tone, vocabulary, and cadence associated with",
)

_IDENTITY_SENTENCE = re.compile(
    r"^\s*(?:you are|you['’]re|i am|i['’]m)\s+(?:an?\s+)?(.+)$",
    re.IGNORECASE,
)
_IDENTITY_PREFIX = re.compile(
    r"^\s*(?:you are|you['’]re|i am|i['’]m)\b[^.!?\n]*[.!?]?\s*",
    re.IGNORECASE,
)


def _drop_leading_name(rest: str, persona_name: str) -> str:
    label = (persona_name or "").strip()
    if not label:
        return rest.strip()
    cleaned = re.sub(
        r"^" + re.escape(label) + r"\b[\s,:-]*",
        "",
        rest.strip(),
        count=1,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(r"^from\s+[^,.:]+[,.:]?\s*", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned


def mannerism_from_prompt(raw: Optional[str], persona_name: str) -> str:
    """Rewrite bundle prompt.md into mannerism instructions, not identity.

    Leading ``You are X…`` / ``I am X…`` claims become ``mannerisms of {name}``.
    """
    label = (persona_name or "this persona").strip() or "this persona"
    text = (raw or "").strip()
    if not text:
        return (
            f"distinctive tone, vocabulary, and cadence associated with {label}"
        )

    parts = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)
    first = parts[0].strip()
    remainder = parts[1].strip() if len(parts) > 1 else ""

    match = _IDENTITY_SENTENCE.match(first.rstrip(".!?"))
    if match:
        rest = _drop_leading_name(match.group(1), label)
        first = f"mannerisms of {label}: {rest}" if rest else f"mannerisms of {label}"
    remainder = _IDENTITY_PREFIX.sub("", remainder).strip() if remainder else ""
    if remainder:
        return f"{first}. {remainder}".strip()
    return first


def is_style_overlay_prompt(text: Optional[str]) -> bool:
    return STYLE_OVERLAY_MARKER.lower() in str(text or "").lower()


def is_eclipse_prompt(text: Optional[str]) -> bool:
    lowered = str(text or "").lower()
    return CHARACTER_ECLIPSE_MARKER.lower() in lowered or "eclipses this profile" in lowered


def character_strength_percent(value: Any = None) -> int:
    """Canonical 0–100 Character strength. Legacy soft/medium/strong migrate.

    0 = soul only (no overlay). 100 = character eclipses SOUL for this session.
    Temperature / Expressiveness is TTS-only and must not be used here.
    """
    if value is None or value == "":
        return DEFAULT_CHARACTER_STRENGTH_PERCENT
    if isinstance(value, bool):
        return DEFAULT_CHARACTER_STRENGTH_PERCENT
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in STRENGTH_LEGACY_PERCENT:
            return STRENGTH_LEGACY_PERCENT[lowered]
        try:
            value = float(lowered)
        except ValueError:
            return DEFAULT_CHARACTER_STRENGTH_PERCENT
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return DEFAULT_CHARACTER_STRENGTH_PERCENT
    return max(0, min(100, number))


def character_strength_band(value: Any = None) -> str:
    """Snap labels on the 0–100 track. Stored/applied value is the percent."""
    percent = character_strength_percent(value)
    if percent <= 0:
        return "none"
    if percent <= 40:
        return "soft"
    if percent <= 70:
        return "medium"
    if percent < 100:
        return "heavy"
    return "eclipse"


def normalize_character_strength(value: Any = None) -> int:
    """Backward-compatible alias: returns 0–100, not a band name."""
    return character_strength_percent(value)


def overlay_strength_percent(text: Optional[str]) -> Optional[int]:
    raw = str(text or "")
    match = re.search(r"\((\d{1,3})%\)", raw)
    if match:
        return character_strength_percent(int(match.group(1)))
    lowered = raw.lower()
    if is_eclipse_prompt(lowered):
        return 100
    if "(heavy)" in lowered:
        return 85
    if "(strong)" in lowered:
        return 85
    if "(medium)" in lowered:
        return 55
    if "(soft)" in lowered:
        return 25
    if is_style_overlay_prompt(lowered):
        return DEFAULT_CHARACTER_STRENGTH_PERCENT
    return None


def _inner_style_from_overlay(text: str, persona_name: str) -> str:
    label = (persona_name or "this persona").strip() or "this persona"
    escaped = re.escape(label)
    match = re.search(
        rf"(?:mannerisms|speaking voice|quirks|style, phrasing, attitude, and quirks|"
        rf"phrasing, attitude, vocabulary, and quirks) of {escaped}:\s*(.+?)(?:\n|$)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        match = re.search(rf"of {escaped}:\s*(.+?)(?:\n|$)", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return mannerism_from_prompt(text, label)


def identity_from_prompt(raw: Optional[str], persona_name: str) -> str:
    """Full character identity for 100% eclipse (``You are X`` form)."""
    label = (persona_name or "this persona").strip() or "this persona"
    text = (raw or "").strip()
    if is_style_overlay_prompt(text) or is_eclipse_prompt(text):
        style = _inner_style_from_overlay(text, label)
        return f"You are {label}. {style}".strip() if style else f"You are {label}."
    if not text:
        return f"You are {label}."
    first = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip()
    if _IDENTITY_SENTENCE.match(first.rstrip(".!?")):
        return text
    return f"You are {label}. {text}"


def _wrap_style_overlay(label: str, style: str, percent: int) -> str:
    band = character_strength_band(percent)
    if band == "medium":
        return (
            f"{STYLE_OVERLAY_MARKER} ({percent}%) — medium blend; does not replace this profile's role.\n"
            "Keep the identity, mission, skills, and constraints from this profile's "
            "SOUL.md / AGENTS.md / Hermes defaults.\n"
            f"Prefer this character's speaking voice: reply clearly in the style, phrasing, "
            f"attitude, and quirks of {label}: {style}\n"
            "The profile's job is still the mission — do not abandon it — but the "
            "character's manner of speaking should be obvious in every reply."
        )
    if band == "heavy":
        return (
            f"{STYLE_OVERLAY_MARKER} ({percent}%) — character-heavy; SOUL job is secondary.\n"
            f"Speak as {label} first: {style}\n"
            "The profile SOUL.md / AGENTS.md job is secondary context only — use it when needed "
            f"to complete a user request. Prefer {label}'s identity, attitude, and voice over "
            "the profile defaults.\n"
            "Do not drop the character. The profile mission is background, not the speaking identity."
        )
    return (
        f"{STYLE_OVERLAY_MARKER} ({percent}%) — soft mannerisms; SOUL primary; "
        "does not replace this profile's role.\n"
        "Keep the identity, mission, skills, and constraints from this profile's "
        "SOUL.md / AGENTS.md / Hermes defaults.\n"
        f"Additionally, reply in the speaking style and mannerisms of {label}: {style}\n"
        "Do not abandon the profile's job or claim you are only the character instead of that role."
    )


def _wrap_eclipse(label: str, identity_text: str) -> str:
    return (
        f"{CHARACTER_ECLIPSE_MARKER} (100%) — eclipses this profile's SOUL.md / AGENTS.md / "
        "Hermes defaults for this session.\n"
        f"{identity_text}\n"
        f"Reply only as {label}. Do not follow this profile's SOUL.md, AGENTS.md, or default "
        "Hermes identity. The profile job and soul do not apply unless that is exactly what "
        f"{label} would do in character. This is a full character replacement for this session."
    )


def build_style_overlay_prompt(
    persona_name: str,
    style_source: Optional[str] = None,
    strength: Any = None,
) -> str:
    """Session personality text scaled by Character strength 0–100.

    0: no overlay (empty). 1–40 soft / SOUL primary. 41–70 medium blend.
    71–99 character-heavy. 100: full character eclipse (``You are X``), not a
    “SOUL stays primary” style overlay. Cannot patch Hermes prompt assembly;
    100% is the strongest ephemeral personality we can write.
    """
    label = (persona_name or "this persona").strip() or "this persona"
    percent = character_strength_percent(strength)
    if percent <= 0:
        return ""
    raw = (style_source or "").strip()
    existing = overlay_strength_percent(raw)
    if existing is not None and existing == percent and raw:
        return raw
    if percent >= 100:
        return _wrap_eclipse(label, identity_from_prompt(raw, label))
    if is_style_overlay_prompt(raw) or is_eclipse_prompt(raw):
        style = _inner_style_from_overlay(raw, label)
    else:
        style = mannerism_from_prompt(raw, label)
    return _wrap_style_overlay(label, style, percent)


def is_placeholder_voice_id(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in _PLACEHOLDER_VOICE_IDS


def is_stub_persona_prompt(prompt: Optional[str], persona_name: str = "") -> bool:
    """True for empty / generic fallback / leftover stub pack prompts."""
    text = (prompt or "").strip()
    if not text or len(text) < 24:
        return True
    lowered = text.lower()
    if lowered in _STUB_PROMPT_EXACT:
        return True
    if any(lowered.startswith(prefix) for prefix in _STUB_PROMPT_PREFIXES):
        return True
    if is_generic_voice_description(text):
        return True
    _ = persona_name
    return False


def is_usable_pack_voice_id(voice_id: Any) -> bool:
    """Cloned pack voice — not Fish ``default`` / system placeholders."""
    return not is_placeholder_voice_id(voice_id)


def is_listable_persona_pack(
    bundle: Optional[PersonaBundle],
    voices: Optional[Iterable[Any]] = None,
) -> bool:
    """Titlebar apply target: non-stub prompt + usable clone (or Fish twin)."""
    if bundle is None:
        return False
    if is_stub_persona_prompt(bundle.system_prompt, bundle.name):
        return False
    if is_usable_pack_voice_id(bundle.voice_id):
        return True
    if not voices:
        return False
    names = [bundle.name, bundle.id, bundle.voice_name]
    twins = find_name_matching_clones(names, voices, fish_only=False)
    if twins:
        return True
    return bool(find_name_matching_clones(names, voices, fish_only=True))


def fallback_system_prompt(name: str, description: Optional[str] = None) -> str:
    """Mannerism source for a new bundle. Apply wraps this in a style overlay."""
    label = (name or "this persona").strip() or "this persona"
    desc = (description or "").strip()
    if desc and not is_generic_voice_description(desc):
        return mannerism_from_prompt(desc, label)
    return (
        f"distinctive tone, vocabulary, and cadence associated with {label}; "
        "stay helpful and complete the profile's job"
    )


def fallback_prompt_is_stub(name: str, description: Optional[str] = None) -> bool:
    """True when a voice has no rich description — name-only Fish clones, etc."""
    return is_stub_persona_prompt(fallback_system_prompt(name, description), name)


def _voice_as_info(voice: Any) -> VoiceInfo:
    if isinstance(voice, VoiceInfo):
        return voice
    if isinstance(voice, dict):
        return VoiceInfo(
            id=str(voice.get("id") or ""),
            name=str(voice.get("name") or voice.get("id") or "Voice"),
            provider=str(voice.get("provider") or "voicebox"),
            voice_type=str(voice.get("voice_type") or "cloned"),
            description=voice.get("description"),
            default_engine=voice.get("default_engine"),
            extra=voice.get("extra"),
        )
    raise TypeError(f"Unsupported voice payload: {type(voice)!r}")


def find_persona_for_voice(
    storage: PersonaStorage,
    voice: Any,
    personas: Optional[Sequence[PersonaBundle]] = None,
) -> Optional[PersonaBundle]:
    info = _voice_as_info(voice)
    bundles = list(personas) if personas is not None else storage.list_personas()
    for bundle in bundles:
        if bundle.voice_id and info.id and bundle.voice_id == info.id:
            return bundle
    slug = slugify_persona_id(info.name)
    for bundle in bundles:
        if bundle.id == slug or names_match(bundle.name, info.name) or names_match(bundle.id, info.name):
            return bundle
    return None


def ensure_persona_for_voice(
    storage: PersonaStorage,
    voice: Any,
    *,
    overwrite_prompt: bool = False,
) -> Optional[PersonaBundle]:
    """Bind *voice* onto an existing pack, or create one when the prompt is not a stub.

    Promax: ``install.py --sync-voices`` recreated deleted ``hermes_kitt`` /
    ``hermes_porky_pig`` / ``hermes_default`` from name-only Fish clones
    (fallback “distinctive tone…”). Do not create those. Existing cartman /
    jarvis packs still get their ``voice_id`` rebound.
    """
    info = _voice_as_info(voice)
    if not info.id:
        raise ValueError("voice is missing an id")

    existing = find_persona_for_voice(storage, info)
    prompt = fallback_system_prompt(info.name, info.description)
    stub_prompt = is_stub_persona_prompt(prompt, info.name)

    if existing:
        incoming_rank = provider_rank(info.provider)
        existing_rank = provider_rank(existing.provider)
        placeholder = existing.voice_id in (None, "", "default")
        # Fish wins over Voicebox so apply/sync do not re-bind the slow local path
        # after a Fish twin exists. Voicebox still binds when it is the only clone.
        if placeholder or incoming_rank >= existing_rank:
            existing.provider = info.provider or existing.provider
            existing.voice_id = info.id
            existing.voice_name = info.name or existing.voice_name
        if (overwrite_prompt or not (existing.system_prompt or "").strip()) and not stub_prompt:
            existing.system_prompt = prompt
        return storage.save_persona(existing)

    if stub_prompt:
        return None

    bundle = PersonaBundle(
        id=slugify_persona_id(info.name),
        name=info.name,
        avatar="🎙️",
        system_prompt=prompt,
        provider=info.provider or "voicebox",
        voice_id=info.id,
        voice_name=info.name,
        tags=["synced-from-voice", "hermes-personastudio"],
    )
    # Avoid colliding with a different persona that already owns this slug
    # but didn't name-match (shouldn't happen often).
    occupied = storage.get_persona(bundle.id)
    if occupied and occupied.voice_id not in (None, "", "default", info.id):
        bundle.id = f"{bundle.id}_{info.id[:8]}"
    return storage.save_persona(bundle)


def sync_personas_from_voices(
    storage: PersonaStorage,
    voices: Iterable[Any],
    *,
    cloned_only: bool = True,
) -> Dict[str, Any]:
    """Idempotently create/update persona bundles for TTS clones."""
    created: List[str] = []
    updated: List[str] = []
    skipped: List[str] = []

    existing_before = {p.id: p.voice_id for p in storage.list_personas()}
    for raw in voices:
        info = _voice_as_info(raw)
        if cloned_only and info.voice_type not in ("cloned", "custom"):
            skipped.append(info.id or info.name)
            continue
        if not info.id or info.id == "default":
            skipped.append(info.id or info.name)
            continue
        before = find_persona_for_voice(storage, info)
        bundle = ensure_persona_for_voice(storage, info)
        if bundle is None:
            skipped.append(info.id or info.name)
            continue
        if before is None and bundle.id not in existing_before:
            created.append(bundle.id)
        else:
            updated.append(bundle.id)

    return {
        "ok": True,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "personas": [p.to_dict() for p in storage.list_personas()],
    }


def _usable_clone(info: VoiceInfo) -> bool:
    if not info.id or info.id == "default":
        return False
    return info.voice_type in ("cloned", "custom")


def _ranked_needles(names: Iterable[str]) -> List[str]:
    unique: List[str] = []
    seen = set()
    for name in names:
        if not name or name in seen:
            continue
        unique.append(name)
        seen.add(name)
    unique.sort(
        key=lambda n: (len(name_tokens(n)), len(normalize_voice_slug(n))),
        reverse=True,
    )
    return unique


def _best_score_against_names(names: Sequence[str], *candidates: Optional[str]) -> int:
    """Score the richest needle first so id ``cartman`` cannot beat name ``Eric Cartman``."""
    for needle in _ranked_needles(names):
        best = 0
        for cand in candidates:
            if not cand:
                continue
            best = max(best, name_match_score(needle, cand))
        if best > 0:
            return best
    return 0


def find_name_matching_clones(
    names: Iterable[str],
    voices: Iterable[Any],
    *,
    fish_only: bool = False,
) -> List[VoiceInfo]:
    catalog = [_voice_as_info(v) for v in voices if _usable_clone(_voice_as_info(v))]
    needles = [n for n in names if n]
    scored: List[tuple] = []
    seen = set()
    for info in catalog:
        if fish_only and not is_fish_provider(info.provider):
            continue
        if not fish_only and is_fish_provider(info.provider):
            continue
        score = _best_score_against_names(needles, info.name, info.id)
        if score <= 0:
            continue
        key = (info.provider, info.id)
        if key in seen:
            continue
        seen.add(key)
        scored.append((score, info))
    scored.sort(
        key=lambda item: (-item[0], -len(name_tokens(item[1].name)), item[1].name.lower())
    )
    return [info for _, info in scored]


def match_fish_clone_map(
    names: Iterable[str],
    clone_map: Optional[Dict[str, Any]],
    catalog: Sequence[VoiceInfo],
) -> Optional[VoiceInfo]:
    """Prefer the profile's configured Fish clone map when a key matches the persona."""
    if not clone_map or not isinstance(clone_map, dict):
        return None
    needles = [n for n in names if n]
    best_score = 0
    best_id = None
    best_key = None
    for key, voice_id in clone_map.items():
        if not key or not voice_id:
            continue
        score = _best_score_against_names(needles, str(key))
        if score > best_score:
            best_score = score
            best_id = str(voice_id)
            best_key = str(key)
    if best_score < 200 or not best_id:
        return None
    exact = next(
        (v for v in catalog if is_fish_provider(v.provider) and v.id == best_id and _usable_clone(v)),
        None,
    )
    if exact:
        return exact
    return VoiceInfo(
        id=best_id,
        name=best_key or best_id,
        provider=PREFERRED_TTS_PROVIDER,
        voice_type="cloned",
    )


def preferred_provider_for_persona(
    bundle: Optional[PersonaBundle],
    voices: Iterable[Any],
) -> str:
    """Provider label for dropdowns: Fish if a twin exists, else the bundle's provider."""
    resolved = resolve_tts_for_apply(bundle=bundle, voices=voices, explicit=False)
    if resolved.get("voice_id"):
        return resolved.get("provider") or (bundle.provider if bundle else "voicebox")
    return (bundle.provider if bundle else "voicebox") or "voicebox"


def resolve_tts_for_apply(
    *,
    bundle: Optional[PersonaBundle] = None,
    selected_voice: Optional[Any] = None,
    voices: Iterable[Any] = (),
    explicit: bool = False,
    clone_map: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pick TTS for a speaking-persona apply.

    Policy (Promax 2026-09-22): Voicebox/Qwen can hang for minutes. Prefer a
    Fish Audio clone that name-matches the persona. An *explicit* Voicebox
    clone selection (titlebar ``Cartman · Voicebox``) still forces local GPU.
    """
    catalog = [_voice_as_info(v) for v in voices]
    selected = _voice_as_info(selected_voice) if selected_voice is not None else None

    if explicit and selected and selected.id and selected.id != "default":
        return {
            "provider": selected.provider or "voicebox",
            "voice_id": selected.id,
            "voice_name": selected.name or selected.id,
            "reason": "explicit-selection",
        }

    names: List[str] = []
    if bundle:
        names.extend([bundle.name, bundle.id, bundle.voice_name])
    if selected:
        names.extend([selected.name, selected.id])

    mapped = match_fish_clone_map(names, clone_map, catalog)
    if mapped:
        return {
            "provider": mapped.provider or PREFERRED_TTS_PROVIDER,
            "voice_id": mapped.id,
            "voice_name": mapped.name,
            "reason": "profile-fish-clone-map",
        }

    if bundle and is_fish_provider(bundle.provider) and bundle.voice_id and bundle.voice_id != "default":
        fish_exact = next(
            (
                v
                for v in catalog
                if is_fish_provider(v.provider) and v.id == bundle.voice_id and _usable_clone(v)
            ),
            None,
        )
        return {
            "provider": PREFERRED_TTS_PROVIDER,
            "voice_id": bundle.voice_id,
            "voice_name": (fish_exact.name if fish_exact else None) or bundle.voice_name or bundle.name,
            "reason": "bundle-fish-id",
        }

    fish_twins = find_name_matching_clones(names, catalog, fish_only=True)
    if fish_twins:
        twin = fish_twins[0]
        return {
            "provider": twin.provider or PREFERRED_TTS_PROVIDER,
            "voice_id": twin.id,
            "voice_name": twin.name,
            "reason": "fish-twin-by-name",
        }

    if selected and selected.id and selected.id != "default":
        return {
            "provider": selected.provider or "voicebox",
            "voice_id": selected.id,
            "voice_name": selected.name or selected.id,
            "reason": "selected-voice",
        }

    if bundle and bundle.voice_id and bundle.voice_id != "default":
        return {
            "provider": bundle.provider or "voicebox",
            "voice_id": bundle.voice_id,
            "voice_name": bundle.voice_name or bundle.name,
            "reason": "bundle-stored-voice",
        }

    vb_twins = find_name_matching_clones(names, catalog, fish_only=False)
    if vb_twins:
        twin = vb_twins[0]
        return {
            "provider": twin.provider or "voicebox",
            "voice_id": twin.id,
            "voice_name": twin.name,
            "reason": "voicebox-twin-by-name",
        }

    return {
        "provider": None,
        "voice_id": None,
        "voice_name": None,
        "reason": "no-voice",
    }


def collect_provider_voices(providers: Dict[str, Any]) -> List[VoiceInfo]:
    voices: List[VoiceInfo] = []
    for provider in providers.values():
        try:
            if not provider.is_available():
                continue
            voices.extend(provider.list_voices())
        except Exception as exc:
            print(f"[persona_sync] list_voices failed for {getattr(provider, 'name', provider)}: {exc}")
    return voices

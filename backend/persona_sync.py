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

STOP_TOKENS = frozenset({"the", "a", "an", "of", "and", "my", "voice", "clone"})

FISH_PROVIDERS = frozenset({"fish", "fish_audio"})
PREFERRED_TTS_PROVIDER = "fish_audio"


def slugify_persona_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return slug or "persona"


def name_tokens(name: str) -> set:
    tokens = set(slugify_persona_id(name).split("_"))
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
    if not left or not right:
        return False
    a, b = slugify_persona_id(left), slugify_persona_id(right)
    if a == b:
        return True
    ta, tb = name_tokens(left), name_tokens(right)
    return bool(ta and tb and (ta & tb))


def is_generic_voice_description(description: Optional[str]) -> bool:
    text = (description or "").strip()
    if not text:
        return True
    lowered = text.lower()
    if any(lowered.startswith(prefix) for prefix in GENERIC_DESCRIPTION_PREFIXES):
        return True
    return False


def fallback_system_prompt(name: str, description: Optional[str] = None) -> str:
    label = (name or "this persona").strip() or "this persona"
    desc = (description or "").strip()
    if desc and not is_generic_voice_description(desc):
        if "you are" in desc.lower() or len(desc) >= 40:
            return desc
        return (
            f"You are {label}. {desc} Stay in character while remaining helpful "
            "and answering the user's questions."
        )
    return (
        f"You are {label}. Stay in character while remaining helpful and answering "
        "the user's questions."
    )


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
) -> PersonaBundle:
    """Create or update a persona bundle bound to *voice*. Idempotent."""
    info = _voice_as_info(voice)
    if not info.id:
        raise ValueError("voice is missing an id")

    existing = find_persona_for_voice(storage, info)
    prompt = fallback_system_prompt(info.name, info.description)

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
        if overwrite_prompt or not (existing.system_prompt or "").strip():
            existing.system_prompt = prompt
        return storage.save_persona(existing)

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


def find_name_matching_clones(
    names: Iterable[str],
    voices: Iterable[Any],
    *,
    fish_only: bool = False,
) -> List[VoiceInfo]:
    catalog = [_voice_as_info(v) for v in voices if _usable_clone(_voice_as_info(v))]
    needles = [n for n in names if n]
    hits: List[VoiceInfo] = []
    seen = set()
    for info in catalog:
        if fish_only and not is_fish_provider(info.provider):
            continue
        if not fish_only and is_fish_provider(info.provider):
            continue
        if any(names_match(needle, info.name) or names_match(needle, info.id) for needle in needles):
            key = (info.provider, info.id)
            if key not in seen:
                seen.add(key)
                hits.append(info)
    hits.sort(
        key=lambda v: (
            0 if any(slugify_persona_id(n) == slugify_persona_id(v.name) for n in needles) else 1,
            v.name.lower(),
        )
    )
    return hits


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

"""FastAPI router and backend service for PersonaStudio."""
from __future__ import annotations

import base64
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .providers.base import BaseTTSProvider, VoiceInfo
from .providers.fish_audio import FishAudioProvider
from .providers.voicebox import VoiceboxProvider
from .storage import PersonaBundle, PersonaStorage
from . import bot_profiles
from . import persona_sync
from . import session_overlay
from .config_io import get_dotted, load_yaml
from .paths import config_path_for_profile

router = APIRouter(prefix="/api/studio", tags=["PersonaStudio"])
storage = PersonaStorage()

fish_provider = FishAudioProvider()
voicebox_provider = VoiceboxProvider()

PROVIDERS: Dict[str, BaseTTSProvider] = {
    "fish_audio": fish_provider,
    "voicebox": voicebox_provider,
}

def _normalize_pack_engine(engine: Optional[str]) -> Optional[str]:
    text = str(engine or "").strip()
    return text or None


def _sync_voicebox_engine(provider: str, voice_id: str, engine: Optional[str]) -> None:
    """Best-effort: write pack engine onto the Voicebox profile default_engine."""
    if not engine:
        return
    if str(provider or "").strip().lower() not in ("voicebox", "vb"):
        return
    vid = str(voice_id or "").strip()
    if not vid or vid in ("default", "none", "null"):
        return
    try:
        voicebox_provider.update_default_engine(vid, engine)
    except Exception as e:
        print(f"[PersonaStudio] Voicebox engine sync skipped: {e}")




class AuditionRequest(BaseModel):
    text: str
    provider: str = "voicebox"
    voice_id: Optional[str] = "default"
    speed: float = 1.0
    temperature: float = 0.7
    engine: Optional[str] = None


class SpeakProfileRequest(BaseModel):
    text: str
    profile_id: str
    speed: float = 1.0
    temperature: float = 0.7


class CreatePersonaRequest(BaseModel):
    id: Optional[str] = None
    name: str
    avatar: str = "🤖"
    system_prompt: str = ""
    provider: str = "voicebox"
    voice_id: str
    voice_name: str
    speed: float = 1.0
    temperature: float = 0.7
    character_strength: Optional[Any] = 25
    engine: Optional[str] = None
    tags: Optional[List[str]] = None


class UpdatePersonaRequest(BaseModel):
    name: Optional[str] = None
    avatar: Optional[str] = None
    system_prompt: Optional[str] = None
    provider: Optional[str] = None
    voice_id: Optional[str] = None
    voice_name: Optional[str] = None
    speed: Optional[float] = None
    temperature: Optional[float] = None
    character_strength: Optional[Any] = None
    engine: Optional[str] = None
    tags: Optional[List[str]] = None


class AssignVoiceRequest(BaseModel):
    provider: str
    voice_id: str
    voice_name: str


class SetPersonaRequest(BaseModel):
    persona_name: str
    persona_prompt: str


class ResolveTtsRequest(BaseModel):
    persona_id: Optional[str] = None
    voice_id: Optional[str] = None
    provider: Optional[str] = None
    explicit: bool = False
    profile_id: Optional[str] = None


class SessionApplyRequest(BaseModel):
    persona_name: str
    persona_prompt: str
    provider: Optional[str] = None
    voice_id: Optional[str] = None
    voice_name: Optional[str] = None
    persona_id: Optional[str] = None
    character_strength: Optional[Any] = None


@router.get("/status")
def get_status() -> Dict[str, Any]:
    return {
        "ok": True,
        "providers": {
            "fish_audio": {"available": fish_provider.is_available(), "has_key": bool(fish_provider._api_key)},
            "voicebox": {"available": voicebox_provider.is_available(), "url": voicebox_provider._base_url},
        },
    }


@router.get("/models")
def list_clone_models(provider: str = "voicebox") -> List[Dict[str, Any]]:
    """Return available engines/models for cloning and synthesis."""
    if provider == "voicebox":
        return [
            {"id": "luxtts", "name": "LuxTTS (Fast, CPU/GPU-friendly ~1.2s, High Quality)", "recommended": True},
            {"id": "qwen_fast", "name": "Qwen 3 (0.6B - ⚡ Instant ~0.4s Lag, Low VRAM, Local GPU)", "recommended": False},
            {"id": "qwen", "name": "Qwen 3 (1.7B Standard, Deep Expressiveness, Local GPU)", "recommended": False},
            {"id": "chatterbox_turbo", "name": "Chatterbox Turbo (High Emotion, Tag-Aware, Local GPU)", "recommended": False},
            {"id": "chatterbox", "name": "Chatterbox Standard (Deep Neural Voice, Local GPU)", "recommended": False},
            {"id": "kokoro", "name": "Kokoro (Ultra-Fast Preset Only, Low VRAM)", "recommended": False},
        ]
    elif provider == "fish_audio":
        return [
            {"id": "s2.1-pro-free", "name": "Fish Audio S2.1 Pro (Free Tier, Zero-Shot)", "recommended": True},
            {"id": "s1", "name": "Fish Audio Speech S1 (High Accuracy)", "recommended": False},
            {"id": "speech-1.5", "name": "Fish Audio Speech 1.5", "recommended": False},
        ]
    return []


@router.delete("/voices/{provider}/{voice_id}")
def delete_voice(provider: str, voice_id: str) -> Dict[str, Any]:
    prov = PROVIDERS.get(provider)
    if not prov:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}'")
    if not prov.is_available():
        raise HTTPException(status_code=503, detail=f"Provider '{provider}' is not available")

    ok = prov.delete_voice(voice_id)
    if not ok:
        raise HTTPException(status_code=400, detail=f"Failed to delete voice '{voice_id}' from {provider}")
    return {"ok": True, "deleted": voice_id}


@router.post("/voices/{provider}/{voice_id}/resample")
async def resample_voice(
    provider: str,
    voice_id: str,
    reference_text: Optional[str] = Form(None),
    file: UploadFile = File(...),
) -> Dict[str, Any]:
    prov = PROVIDERS.get(provider)
    if not prov:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}'")
    if not prov.is_available():
        raise HTTPException(status_code=503, detail=f"Provider '{provider}' is not available")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty audio sample")

    ok = prov.resample_voice(
        voice_id=voice_id,
        audio_bytes=content,
        filename=file.filename or "sample.wav",
        reference_text=reference_text,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=f"Failed to re-sample voice '{voice_id}'")
    return {"ok": True, "resampled": voice_id}


@router.get("/voices")
def list_voices(provider: Optional[str] = None) -> List[Dict[str, Any]]:
    """List voices. Omit provider to return Fish + Voicebox together."""
    out: List[Dict[str, Any]] = []
    target_providers = [PROVIDERS[provider]] if provider and provider in PROVIDERS else PROVIDERS.values()

    for p in target_providers:
        if p.is_available():
            for v in p.list_voices():
                out.append(v.to_dict())
    return out


@router.post("/audition")
def audition_voice(req: AuditionRequest) -> Dict[str, Any]:
    prov = PROVIDERS.get(req.provider)
    if not prov:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{req.provider}'")
    if not prov.is_available():
        raise HTTPException(status_code=503, detail=f"Provider '{req.provider}' is not available or unconfigured")

    try:
        audio_bytes = prov.synthesize(
            text=req.text,
            voice_id=req.voice_id,
            speed=req.speed,
            temperature=req.temperature,
            engine=req.engine,
        )
        b64 = base64.b64encode(audio_bytes).decode("ascii")
        return {"ok": True, "audio_base64": b64, "format": "audio/wav"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/speak-profile")
def speak_for_profile(req: SpeakProfileRequest) -> Dict[str, Any]:
    """Synthesize speech using a bot profile's assigned voice identity."""
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty text to speak")

    pid = str(req.profile_id or "default").strip()
    path = config_path_for_profile(pid)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Profile '{pid}' config not found")

    cfg = load_yaml(path)
    tts_res = bot_profiles.resolve_profile_tts(cfg)
    prov_name = tts_res.get("provider") or "voicebox"
    voice_id = tts_res.get("voice_id") or tts_res.get("voice") or "default"

    # Map provider key
    prov_key = "fish_audio" if prov_name in ("fish", "fish_audio") else "voicebox"
    prov = PROVIDERS.get(prov_key)
    if not prov:
        raise HTTPException(status_code=400, detail=f"Provider '{prov_name}' not supported")
    if not prov.is_available():
        raise HTTPException(status_code=503, detail=f"Provider '{prov_name}' is not available or unconfigured")

    try:
        audio_bytes = prov.synthesize(
            text=text,
            voice_id=voice_id,
            speed=req.speed,
            temperature=req.temperature,
        )
        b64 = base64.b64encode(audio_bytes).decode("ascii")
        return {
            "ok": True,
            "profile_id": pid,
            "provider": prov_key,
            "voice_id": voice_id,
            "voice_name": tts_res.get("voice_name") or voice_id,
            "audio_base64": b64,
            "format": "audio/wav",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/clone")
async def clone_voice(
    name: str = Form(...),
    provider: str = Form("voicebox"),
    engine: Optional[str] = Form("chatterbox_turbo"),
    description: Optional[str] = Form(None),
    reference_text: Optional[str] = Form(None),
    file: UploadFile = File(...),
) -> Dict[str, Any]:
    prov = PROVIDERS.get(provider)
    if not prov:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}'")
    if not prov.is_available():
        raise HTTPException(status_code=503, detail=f"Provider '{provider}' is not available or unconfigured")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty audio sample")

    try:
        vinfo = prov.clone_voice(
            name=name,
            audio_bytes=content,
            filename=file.filename or "sample.wav",
            description=description,
            engine=engine,
            reference_text=reference_text,
        )
        persona = persona_sync.ensure_persona_for_voice(storage, vinfo)
        return {
            "ok": True,
            "voice": vinfo.to_dict(),
            "persona": persona.to_dict() if persona else None,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/personas")
def list_personas(listable: bool = False) -> List[Dict[str, Any]]:
    voices = persona_sync.collect_provider_voices(PROVIDERS) if listable else ()
    out: List[Dict[str, Any]] = []
    for bundle in storage.list_personas():
        data = bundle.to_dict()
        data["character_strength"] = persona_sync.character_strength_percent(
            bundle.character_strength
        )
        data["listable"] = persona_sync.is_listable_persona_pack(bundle, voices or None)
        if listable and not data["listable"]:
            continue
        out.append(data)
    return out


@router.post("/sync-from-voices")
def sync_from_voices() -> Dict[str, Any]:
    """Idempotently create/update persona bundles for existing TTS clones."""
    voices = persona_sync.collect_provider_voices(PROVIDERS)
    return persona_sync.sync_personas_from_voices(storage, voices)


def _fish_clone_map_for_profile(profile_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not profile_id:
        return None
    path = config_path_for_profile(profile_id)
    if not path.exists():
        return None
    try:
        clones = get_dotted(load_yaml(path), "tts.providers.fish.clones")
    except Exception:
        return None
    return clones if isinstance(clones, dict) else None


@router.post("/resolve-tts")
def resolve_tts(req: ResolveTtsRequest) -> Dict[str, Any]:
    """Prefer a Fish clone twin unless the caller explicitly selected Voicebox."""
    voices = persona_sync.collect_provider_voices(PROVIDERS)
    bundle = storage.get_persona(req.persona_id) if req.persona_id else None
    selected = None
    if req.voice_id:
        for info in voices:
            if info.id == req.voice_id and (
                not req.provider or info.provider == req.provider or (
                    persona_sync.is_fish_provider(req.provider) and persona_sync.is_fish_provider(info.provider)
                )
            ):
                selected = info
                break
        if selected is None:
            selected = VoiceInfo(
                id=req.voice_id,
                name=req.voice_id,
                provider=req.provider or "voicebox",
                voice_type="cloned",
            )
    result = persona_sync.resolve_tts_for_apply(
        bundle=bundle,
        selected_voice=selected,
        voices=voices,
        explicit=req.explicit,
        clone_map=_fish_clone_map_for_profile(req.profile_id),
    )
    return {"ok": True, **result}


@router.post("/personas")
def save_persona(req: CreatePersonaRequest) -> Dict[str, Any]:
    pid = req.id or persona_sync.slugify_persona_id(req.name)
    prompt = (req.system_prompt or "").strip() or persona_sync.fallback_system_prompt(req.name)
    engine = _normalize_pack_engine(req.engine)
    bundle = PersonaBundle(
        id=pid,
        name=req.name,
        avatar=req.avatar,
        system_prompt=prompt,
        provider=req.provider,
        voice_id=req.voice_id,
        voice_name=req.voice_name,
        speed=req.speed,
        temperature=req.temperature,
        character_strength=persona_sync.character_strength_percent(req.character_strength),
        engine=engine,
        tags=req.tags or [],
    )
    saved = storage.save_persona(bundle)
    _sync_voicebox_engine(saved.provider, saved.voice_id, saved.engine)
    data = saved.to_dict()
    return {"ok": True, "created": True, "persona": data}


@router.put("/personas/{persona_id}")
def update_persona(persona_id: str, req: UpdatePersonaRequest) -> Dict[str, Any]:
    """Update an existing pack in place (Character strength, prompt, voice)."""
    existing = storage.get_persona(persona_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Persona '{persona_id}' not found")
    if req.name is not None and str(req.name).strip():
        existing.name = str(req.name).strip()
    if req.avatar is not None:
        existing.avatar = req.avatar or existing.avatar
    if req.system_prompt is not None:
        existing.system_prompt = req.system_prompt
    if req.provider is not None:
        existing.provider = req.provider
    if req.voice_id is not None:
        existing.voice_id = req.voice_id
    if req.voice_name is not None:
        existing.voice_name = req.voice_name
    if req.speed is not None:
        existing.speed = float(req.speed)
    if req.temperature is not None:
        existing.temperature = float(req.temperature)
    if req.character_strength is not None:
        existing.character_strength = persona_sync.character_strength_percent(req.character_strength)
    if req.engine is not None:
        existing.engine = _normalize_pack_engine(req.engine)
    if req.tags is not None:
        existing.tags = req.tags
    saved = storage.save_persona(existing)
    _sync_voicebox_engine(saved.provider, saved.voice_id, saved.engine)
    data = saved.to_dict()
    data["character_strength"] = persona_sync.character_strength_percent(saved.character_strength)
    return {"ok": True, "updated": True, "persona": data}


@router.delete("/personas/{persona_id}")
def delete_persona(persona_id: str) -> Dict[str, Any]:
    deleted = storage.delete_persona(persona_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Persona not found")
    return {"ok": True}


@router.get("/profiles")
def get_bot_profiles() -> List[Dict[str, Any]]:
    return bot_profiles.list_bot_profiles()


@router.post("/profiles/{profile_id}/assign-voice")
def assign_bot_voice(profile_id: str, req: AssignVoiceRequest) -> Dict[str, Any]:
    try:
        return bot_profiles.assign_voice_to_profile(
            profile_id=profile_id,
            provider=req.provider,
            voice_id=req.voice_id,
            voice_name=req.voice_name,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/profiles/{profile_id}/set-persona")
def set_bot_persona(profile_id: str, req: SetPersonaRequest) -> Dict[str, Any]:
    try:
        return bot_profiles.set_profile_persona(
            profile_id=profile_id,
            persona_name=req.persona_name,
            persona_prompt=req.persona_prompt,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/state")
def get_session_overlay_state(profile_id: Optional[str] = None) -> Dict[str, Any]:
    if profile_id:
        return session_overlay.overlay_status(profile_id)
    return session_overlay.load_session_state()


@router.post("/session/reset-all")
def reset_all_session_overlays() -> Dict[str, Any]:
    """Clear leftover Studio overlays on plugin startup. Does not auto-apply anything."""
    try:
        return session_overlay.reset_all_session_overlays()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/profiles/{profile_id}/session/apply")
def apply_session_overlay(profile_id: str, req: SessionApplyRequest) -> Dict[str, Any]:
    """Apply persona + voice for this chat session; stash stock Hermes for the next new chat."""
    try:
        strength = req.character_strength
        if strength in (None, "") and req.persona_id:
            bundle = storage.get_persona(req.persona_id)
            if bundle is not None:
                strength = bundle.character_strength
        return session_overlay.apply_session_overlay(
            profile_id,
            persona_name=req.persona_name,
            persona_prompt=req.persona_prompt,
            provider=req.provider,
            voice_id=req.voice_id,
            voice_name=req.voice_name,
            character_strength=strength,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/profiles/{profile_id}/session/reset")
def reset_session_overlay(profile_id: str) -> Dict[str, Any]:
    """Restore stashed stock Hermes personality + TTS for the next session."""
    try:
        return session_overlay.reset_session_overlay(profile_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

"""Base interface for PersonaStudio TTS providers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


@dataclass
class VoiceInfo:
    id: str
    name: str
    provider: str
    voice_type: str  # "cloned", "preset", "system"
    language: str = "en"
    description: Optional[str] = None
    sample_url: Optional[str] = None
    default_engine: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BaseTTSProvider(ABC):
    """Abstract base provider for voice synthesis and cloning."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g. 'fish_audio', 'voicebox')."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider is configured and reachable."""
        pass

    @abstractmethod
    def list_voices(self) -> List[VoiceInfo]:
        """Return available voices from this provider."""
        pass

    @abstractmethod
    def synthesize(
        self,
        text: str,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        temperature: float = 0.7,
        out_path: Optional[str] = None,
        **kwargs: Any,
    ) -> bytes:
        """Synthesize text and return raw audio bytes (wav/mp3)."""
        pass

    @abstractmethod
    def clone_voice(
        self,
        name: str,
        audio_bytes: bytes,
        filename: str = "sample.wav",
        description: Optional[str] = None,
        **kwargs: Any,
    ) -> VoiceInfo:
        """Create a new zero-shot or trained clone and return its VoiceInfo."""
        pass

    def delete_voice(self, voice_id: str) -> bool:
        """Delete a voice profile/model from this provider."""
        return False

    def resample_voice(
        self,
        voice_id: str,
        audio_bytes: bytes,
        filename: str = "sample.wav",
        reference_text: Optional[str] = None,
        **kwargs: Any,
    ) -> bool:
        """Update/re-sample an existing voice with newer reference audio."""
        return False

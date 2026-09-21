"""Fish Audio cloud API provider for PersonaStudio."""
from __future__ import annotations

import os
import time
import requests
from typing import Any, Dict, List, Optional
from .base import BaseTTSProvider, VoiceInfo

API_BASE = "https://api.fish.audio"
DEFAULT_MODEL = "s2.1-pro-free"


class FishAudioProvider(BaseTTSProvider):
    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or self._detect_api_key()

    @property
    def name(self) -> str:
        return "fish_audio"

    def _detect_api_key(self) -> Optional[str]:
        # Check env vars
        key = os.environ.get("FISH_KEY") or os.environ.get("FISH_API_KEY")
        if key:
            return key.strip()

        # Check ~/.hermes/fish_key.txt
        root = os.path.expanduser("~/.hermes")
        key_file = os.path.join(root, "fish_key.txt")
        if os.path.isfile(key_file):
            try:
                with open(key_file, "r", encoding="utf-8") as f:
                    val = f.read().strip()
                if val:
                    return val
            except Exception:
                pass

        # Check ~/.hermes/config.yaml
        cfg_path = os.path.join(root, "config.yaml")
        if os.path.isfile(cfg_path):
            try:
                import yaml
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                tts = cfg.get("tts") or {}
                fish = (tts.get("providers") or {}).get("fish") or {}
                val = fish.get("api_key")
                if val:
                    return str(val).strip()
            except Exception:
                pass

        return None

    def set_api_key(self, key: str) -> None:
        self._api_key = key.strip() if key else None

    def is_available(self) -> bool:
        return bool(self._api_key)

    def list_voices(self) -> List[VoiceInfo]:
        if not self._api_key:
            return []

        voices: List[VoiceInfo] = []
        try:
            headers = {"Authorization": f"Bearer {self._api_key}"}
            # 1. Fetch user's own custom cloned models using self=true
            resp = requests.get(f"{API_BASE}/model?self=true&page_size=100", headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items") if isinstance(data, dict) else (data if isinstance(data, list) else [])
                # Sort newest first
                items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
                for item in items:
                    v_id = item.get("_id") or item.get("id")
                    title = item.get("title") or item.get("name") or v_id
                    state = item.get("state", "trained")
                    vis = item.get("visibility", "private")
                    desc = f"Fish Audio Clone ({state}, {vis})"
                    voices.append(
                        VoiceInfo(
                            id=v_id,
                            name=f"{title}",
                            provider=self.name,
                            voice_type="cloned",
                            description=desc,
                            extra={
                                "visibility": vis,
                                "train_mode": item.get("train_mode"),
                                "state": state,
                                "created_at": item.get("created_at"),
                            },
                        )
                    )
        except Exception as e:
            print(f"[FishAudioProvider] list_voices warning: {e}")

        # Always include Fish default voice at the top
        voices.insert(
            0,
            VoiceInfo(
                id="default",
                name="Fish Audio (Default Voice)",
                provider=self.name,
                voice_type="system",
                description="Fish Audio default standard speaker",
            ),
        )
        return voices

    def synthesize(
        self,
        text: str,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        temperature: float = 0.7,
        out_path: Optional[str] = None,
        **kwargs: Any,
    ) -> bytes:
        if not self._api_key:
            raise RuntimeError("Fish Audio API key missing.")
        if not text or not text.strip():
            raise ValueError("Empty text for synthesis.")

        selected_model = kwargs.get("engine") or kwargs.get("model") or DEFAULT_MODEL
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "model": selected_model,
        }
        payload: Dict[str, Any] = {
            "text": text,
            "format": kwargs.get("audio_format", "wav"),
            "sample_rate": kwargs.get("sample_rate", 44100),
            "latency": kwargs.get("latency", "normal"),
        }
        if voice_id and voice_id != "default":
            payload["reference_id"] = voice_id

        resp = requests.post(f"{API_BASE}/v1/tts", headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        audio = resp.content

        if not audio or (audio[:4] == b"{" and b"message" in audio[:200]):
            raise RuntimeError(f"Fish TTS returned invalid audio payload: {audio[:200]!r}")

        if out_path:
            os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
            with open(out_path, "wb") as f:
                f.write(audio)

        return audio

    def clone_voice(
        self,
        name: str,
        audio_bytes: bytes,
        filename: str = "sample.wav",
        description: Optional[str] = None,
        **kwargs: Any,
    ) -> VoiceInfo:
        if not self._api_key:
            raise RuntimeError("Fish Audio API key missing.")
        if not audio_bytes:
            raise ValueError("Empty audio sample provided for cloning.")

        url = f"{API_BASE}/model"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        train_mode = kwargs.get("train_mode", "fast")
        visibility = kwargs.get("visibility", "private")

        files = {"voices": (filename, audio_bytes, "audio/wav")}
        data = {
            "type": "tts",
            "title": name,
            "description": description or f"Cloned via Hermes PersonaStudio",
            "visibility": visibility,
            "train_mode": train_mode,
            "enhance_audio_quality": "true",
            "generate_sample": "false",
        }

        resp = requests.post(url, headers=headers, files=files, data=data, timeout=180)
        resp.raise_for_status()
        res_json = resp.json()
        vid = res_json.get("_id") or res_json.get("id")
        if not vid:
            raise RuntimeError(f"Fish Audio voice cloning returned no model ID: {res_json}")

        return VoiceInfo(
            id=vid,
            name=name,
            provider=self.name,
            voice_type="cloned",
            description=description or "Cloned via Hermes PersonaStudio",
            extra={"train_mode": train_mode, "visibility": visibility},
        )

    def delete_voice(self, voice_id: str) -> bool:
        if not self._api_key or not voice_id or voice_id == "default":
            return False
        url = f"{API_BASE}/model/{voice_id}"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        resp = requests.delete(url, headers=headers, timeout=10)
        return resp.status_code in [200, 204]

    def resample_voice(
        self,
        voice_id: str,
        audio_bytes: bytes,
        filename: str = "sample.wav",
        reference_text: Optional[str] = None,
        **kwargs: Any,
    ) -> bool:
        if not self._api_key or not voice_id or not audio_bytes:
            return False
        headers = {"Authorization": f"Bearer {self._api_key}"}
        resp = requests.get(f"{API_BASE}/model/{voice_id}", headers=headers, timeout=10)
        title = "Updated Voice"
        if resp.status_code == 200:
            title = resp.json().get("title", "Updated Voice")
        new_voice = self.clone_voice(
            name=f"{title}",
            audio_bytes=audio_bytes,
            filename=filename,
            description="Re-sampled voice reference",
        )
        return bool(new_voice and new_voice.id)

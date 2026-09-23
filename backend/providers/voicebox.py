"""Local GPU Voicebox provider for PersonaStudio."""
from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.error
import requests
from typing import Any, Dict, List, Optional
from .base import BaseTTSProvider, VoiceInfo

DEFAULT_VOICEBOX_URL = "http://127.0.0.1:17493"


def _touch_tts_activity() -> None:
    """Stamp activity file so Voicebox GPU lifecycle daemon preserves warm VRAM models."""
    try:
        hermes_home = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
        os.makedirs(hermes_home, exist_ok=True)
        path = os.path.join(hermes_home, "voicebox_tts_activity")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f'{{"touched_at": {time.time()}, "pid": {os.getpid()}}}\n')
    except Exception:
        pass


class VoiceboxProvider(BaseTTSProvider):
    def __init__(self, base_url: str = DEFAULT_VOICEBOX_URL):
        self._base_url = base_url.rstrip("/")

    @property
    def name(self) -> str:
        return "voicebox"

    def is_available(self) -> bool:
        try:
            r = requests.get(f"{self._base_url}/health", timeout=1.5)
            return r.status_code == 200
        except Exception:
            return False

    def list_voices(self) -> List[VoiceInfo]:
        voices: List[VoiceInfo] = []
        try:
            r = requests.get(f"{self._base_url}/profiles", timeout=3.0)
            if r.status_code == 200:
                profiles = r.json()
                for p in profiles:
                    voices.append(
                        VoiceInfo(
                            id=p["id"],
                            name=p.get("name") or p["id"],
                            provider=self.name,
                            voice_type=p.get("voice_type", "cloned"),
                            language=p.get("language", "en"),
                            description=p.get("personality"),
                            default_engine=p.get("default_engine"),
                            extra={"sample_count": p.get("sample_count", 0), "engine": p.get("default_engine")},
                        )
                    )
        except Exception as e:
            print(f"[VoiceboxProvider] list_voices warning: {e}")
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
        if not text or not text.strip():
            raise ValueError("Empty text for synthesis.")

        # 1. Fetch profile to discover engine
        engine = kwargs.get("engine")
        if not engine and voice_id:
            try:
                prof_resp = requests.get(f"{self._base_url}/profiles/{voice_id}", timeout=2.0)
                if prof_resp.status_code == 200:
                    prof_data = prof_resp.json()
                    engine = prof_data.get("default_engine") or prof_data.get("preset_engine")
            except Exception:
                pass

        payload: Dict[str, Any] = {
            "profile_id": voice_id,
            "text": text,
            "language": kwargs.get("language", "en"),
        }
        model_size = kwargs.get("model_size")
        if engine == "qwen_fast":
            engine = "qwen"
            model_size = "0.6B"
        elif engine == "qwen" and not model_size:
            model_size = "0.6B"

        if engine:
            payload["engine"] = engine
        if model_size:
            payload["model_size"] = model_size

        # Try /generate/stream first
        audio_bytes = b""
        stream_url = f"{self._base_url}/generate/stream"
        req = urllib.request.Request(
            stream_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

        _touch_tts_activity()
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                audio_bytes = r.read()
            _touch_tts_activity()
        except Exception as stream_err:
            # Fallback to async job API (/generate -> /history/{id} -> /audio/{id})
            post_resp = requests.post(f"{self._base_url}/generate", json=payload, timeout=10)
            post_resp.raise_for_status()
            gen_data = post_resp.json()
            gen_id = gen_data["id"]

            deadline = time.time() + 45.0
            while time.time() < deadline:
                h_resp = requests.get(f"{self._base_url}/history/{gen_id}", timeout=5)
                if h_resp.status_code == 200:
                    h_data = h_resp.json()
                    status = h_data.get("status")
                    if status == "completed":
                        a_resp = requests.get(f"{self._base_url}/audio/{gen_id}", timeout=10)
                        a_resp.raise_for_status()
                        audio_bytes = a_resp.content
                        break
                    elif status == "failed":
                        raise RuntimeError(h_data.get("error") or "Voicebox generation failed")
                time.sleep(0.5)

        if not audio_bytes:
            raise RuntimeError("Voicebox generation returned no audio bytes.")

        if out_path:
            os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
            with open(out_path, "wb") as f:
                f.write(audio_bytes)

        return audio_bytes

    def clone_voice(
        self,
        name: str,
        audio_bytes: bytes,
        filename: str = "sample.wav",
        description: Optional[str] = None,
        **kwargs: Any,
    ) -> VoiceInfo:
        # 1. Create profile
        engine = kwargs.get("engine", "qwen")
        if engine == "qwen_fast":
            engine = "qwen"
        p_data = {
            "name": name,
            "personality": description or "",
            "default_engine": engine,
        }
        create_resp = requests.post(f"{self._base_url}/profiles", json=p_data, timeout=5)
        create_resp.raise_for_status()
        profile = create_resp.json()
        pid = profile["id"]

        # 2. Upload audio sample to /profiles/{pid}/samples
        files = {"file": (filename, audio_bytes, "audio/wav")}
        data = {"reference_text": kwargs.get("reference_text") or "Reference voice sample audio."}
        try:
            sample_resp = requests.post(f"{self._base_url}/profiles/{pid}/samples", files=files, data=data, timeout=30)
            sample_resp.raise_for_status()
            _touch_tts_activity()
        except Exception as e:
            # Clean up the empty profile on error
            try:
                requests.delete(f"{self._base_url}/profiles/{pid}", timeout=5)
            except Exception:
                pass
            raise e

        return VoiceInfo(
            id=pid,
            name=name,
            provider=self.name,
            voice_type="cloned",
            description=description,
            default_engine=p_data["default_engine"],
        )

    def update_default_engine(self, voice_id: str, engine: str) -> bool:
        """Persist synthesis engine on the Voicebox profile (PUT /profiles/{id}).

        Runtime Hermes TTS reads profile ``default_engine``; Studio Save must
        update it or the UI model choice is audition-only.
        """
        if not voice_id or voice_id == "default" or not engine:
            return False
        stored = engine
        if stored == "qwen_fast":
            # Match clone_voice: Voicebox stores qwen + model_size for the fast path.
            stored = "qwen"
        try:
            resp = requests.put(
                f"{self._base_url}/profiles/{voice_id}",
                json={"default_engine": stored, "preset_engine": stored},
                timeout=5,
            )
            if resp.status_code in (200, 204):
                return True
            # Some builds require name; merge with existing profile.
            if resp.status_code in (400, 422):
                prof = requests.get(f"{self._base_url}/profiles/{voice_id}", timeout=2.0)
                if prof.status_code == 200:
                    body = dict(prof.json() or {})
                    body["default_engine"] = stored
                    body["preset_engine"] = stored
                    resp2 = requests.put(
                        f"{self._base_url}/profiles/{voice_id}",
                        json=body,
                        timeout=5,
                    )
                    return resp2.status_code in (200, 204)
            print(f"[VoiceboxProvider] update_default_engine HTTP {resp.status_code}: {resp.text[:200]}")
            return False
        except Exception as e:
            print(f"[VoiceboxProvider] update_default_engine warning: {e}")
            return False

    def delete_voice(self, voice_id: str) -> bool:
        if not voice_id or voice_id == "default":
            return False
        resp = requests.delete(f"{self._base_url}/profiles/{voice_id}", timeout=10)
        return resp.status_code in [200, 204]

    def resample_voice(
        self,
        voice_id: str,
        audio_bytes: bytes,
        filename: str = "sample.wav",
        reference_text: Optional[str] = None,
        **kwargs: Any,
    ) -> bool:
        if not voice_id or not audio_bytes:
            return False
        files = {"file": (filename, audio_bytes, "audio/wav")}
        data = {"reference_text": reference_text or "Updated reference voice sample audio."}
        resp = requests.post(f"{self._base_url}/profiles/{voice_id}/samples", files=files, data=data, timeout=30)
        return resp.status_code in [200, 201]

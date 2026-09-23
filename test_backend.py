import json
import os
import tempfile
import unittest
from pathlib import Path

import yaml

from backend.storage import PersonaStorage, PersonaBundle
from backend.providers.base import VoiceInfo
from backend.providers.fish_audio import FishAudioProvider
from backend.providers.voicebox import VoiceboxProvider
from backend import bot_profiles
from backend import persona_sync
from backend import config_io
from backend import managed_index
import install as install_mod


class IsolatedHermesHomeTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.home = Path(self.temp_dir) / "hermes"
        self.home.mkdir()
        self._old_home = os.environ.get("HERMES_HOME")
        os.environ["HERMES_HOME"] = str(self.home)

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = self._old_home
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)


class TestPersonaStorage(IsolatedHermesHomeTest):
    def test_storage_roundtrip(self):
        storage = PersonaStorage(root_dir=str(self.home / "personas"))
        bundle = PersonaBundle(
            id="test_persona",
            name="Test Persona",
            avatar="🧪",
            system_prompt="You are a test assistant.",
            provider="fish_audio",
            voice_id="default",
            voice_name="Default Voice",
        )
        storage.save_persona(bundle)
        loaded = storage.get_persona("test_persona")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.name, "Test Persona")
        self.assertEqual(loaded.system_prompt, "You are a test assistant.")
        self.assertEqual(len(storage.list_personas()), 1)

    def test_storage_migrates_legacy_character_strength(self):
        storage = PersonaStorage(root_dir=str(self.home / "personas"))
        bundle = PersonaBundle(
            id="cartman",
            name="Eric Cartman",
            avatar="🧢",
            system_prompt="Aggressive impatient South Park snark while doing the job.",
            provider="voicebox",
            voice_id="c9da87b0-19be-49c4-ab44-01cb7943f5c4",
            voice_name="Cartman",
            character_strength="strong",
        )
        storage.save_persona(bundle)
        loaded = storage.get_persona("cartman")
        self.assertEqual(loaded.character_strength, 85)
        self.assertEqual(
            PersonaBundle.from_dict({"id": "x", "name": "X", "avatar": "🤖",
                                     "system_prompt": "enough text for a real prompt here",
                                     "provider": "fish_audio", "voice_id": "v",
                                     "voice_name": "V", "character_strength": "medium"}).character_strength,
            55,
        )

    def test_put_updates_existing_pack_character_strength(self):
        storage = PersonaStorage(root_dir=str(self.home / "personas"))
        storage.save_persona(
            PersonaBundle(
                id="cartman",
                name="Eric Cartman",
                avatar="🧢",
                system_prompt="Aggressive impatient South Park snark while doing the job.",
                provider="voicebox",
                voice_id="c9da87b0-19be-49c4-ab44-01cb7943f5c4",
                voice_name="Cartman",
                character_strength=25,
            )
        )
        existing = storage.get_persona("cartman")
        existing.character_strength = persona_sync.character_strength_percent(100)
        saved = storage.save_persona(existing)
        self.assertEqual(saved.character_strength, 100)
        loaded = storage.get_persona("cartman")
        self.assertEqual(loaded.character_strength, 100)
        self.assertEqual(loaded.name, "Eric Cartman")
        self.assertEqual(loaded.system_prompt, "Aggressive impatient South Park snark while doing the job.")
        api_src = Path(__file__).resolve().parent.joinpath("backend", "api.py").read_text(encoding="utf-8")
        self.assertIn('@router.put("/personas/{persona_id}")', api_src)
        self.assertIn("def update_persona(", api_src)
        self.assertIn('status_code=404, detail=f"Persona \'{persona_id}\' not found"', api_src)
        self.assertIn('"updated": True', api_src)

    def test_storage_persists_engine_on_pack(self):
        """Voice model (Synthesis engine) must survive Save → reload."""
        from backend.storage import normalize_pack_engine

        storage = PersonaStorage(root_dir=str(self.home / "personas"))
        storage.save_persona(
            PersonaBundle(
                id="amanda",
                name="Amanda",
                avatar="🎙️",
                system_prompt="Warm supportive conversational manner while doing the job.",
                provider="voicebox",
                voice_id="33d87aca-4281-479a-a320-623633377589",
                voice_name="Amanda",
                character_strength=25,
                engine="chatterbox_turbo",
            )
        )
        loaded = storage.get_persona("amanda")
        self.assertEqual(loaded.engine, "chatterbox_turbo")
        raw = (self.home / "personas" / "amanda" / "manifest.json").read_text(encoding="utf-8")
        self.assertIn("chatterbox_turbo", raw)
        loaded.engine = "chatterbox"
        storage.save_persona(loaded)
        again = storage.get_persona("amanda")
        self.assertEqual(again.engine, "chatterbox")

        missing = PersonaBundle.from_dict(
            {
                "id": "legacy",
                "name": "Legacy",
                "avatar": "🤖",
                "system_prompt": "enough text for a real prompt here",
                "provider": "voicebox",
                "voice_id": "v",
                "voice_name": "V",
            }
        )
        self.assertIsNone(missing.engine)
        self.assertIsNone(normalize_pack_engine(""))
        self.assertIsNone(normalize_pack_engine("   "))
        self.assertEqual(normalize_pack_engine("  qwen_fast  "), "qwen_fast")

    def test_api_create_update_persists_engine_and_syncs_voicebox_only(self):
        from unittest.mock import patch

        from backend import api
        from backend.api import CreatePersonaRequest, UpdatePersonaRequest

        prompt = "Warm supportive conversational manner while doing the job."
        created = PersonaBundle(
            id="amanda",
            name="Amanda",
            avatar="🎙️",
            system_prompt=prompt,
            provider="voicebox",
            voice_id="voice-1",
            voice_name="Amanda",
            engine="chatterbox_turbo",
        )
        with patch.object(api, "storage") as storage, patch.object(api, "voicebox_provider") as vb:
            storage.save_persona.return_value = created
            result = api.save_persona(
                CreatePersonaRequest(
                    name="Amanda",
                    avatar="🎙️",
                    system_prompt=prompt,
                    provider="voicebox",
                    voice_id="voice-1",
                    voice_name="Amanda",
                    engine="chatterbox_turbo",
                )
            )
            self.assertTrue(result["created"])
            self.assertEqual(result["persona"]["engine"], "chatterbox_turbo")
            self.assertEqual(storage.save_persona.call_args.args[0].engine, "chatterbox_turbo")
            vb.update_default_engine.assert_called_once_with("voice-1", "chatterbox_turbo")

            storage.get_persona.return_value = created
            storage.save_persona.return_value = PersonaBundle(
                id="amanda",
                name="Amanda",
                avatar="🎙️",
                system_prompt=prompt,
                provider="voicebox",
                voice_id="voice-1",
                voice_name="Amanda",
                engine="chatterbox",
            )
            vb.reset_mock()
            updated = api.update_persona("amanda", UpdatePersonaRequest(engine="chatterbox"))
            self.assertTrue(updated["updated"])
            self.assertEqual(updated["persona"]["engine"], "chatterbox")
            vb.update_default_engine.assert_called_once_with("voice-1", "chatterbox")

            fish = PersonaBundle(
                id="amanda",
                name="Amanda",
                avatar="🎙️",
                system_prompt=prompt,
                provider="fish_audio",
                voice_id="fish-1",
                voice_name="Amanda",
                engine="s2.1-pro-free",
            )
            storage.get_persona.return_value = fish
            storage.save_persona.return_value = fish
            vb.reset_mock()
            api.update_persona("amanda", UpdatePersonaRequest(engine="s2.1-pro-free"))
            vb.update_default_engine.assert_not_called()

        api_src = Path(__file__).resolve().parent.joinpath("backend", "api.py").read_text(encoding="utf-8")
        self.assertIn("engine: Optional[str] = None", api_src)
        self.assertIn("existing.engine = normalize_pack_engine(req.engine)", api_src)
        self.assertIn("engine=engine", api_src)
        self.assertIn("_sync_voicebox_engine(saved.provider, saved.voice_id, saved.engine)", api_src)
        self.assertIn('not in ("voicebox", "vb")', api_src)

    def test_storage_skips_dotfiles(self):
        root = self.home / "personas"
        storage = PersonaStorage(root_dir=str(root))
        (root / ".studio-managed.json").write_text("{}", encoding="utf-8")
        hidden = root / ".hidden"
        hidden.mkdir()
        (hidden / "manifest.json").write_text("{}", encoding="utf-8")
        self.assertEqual(storage.list_personas(), [])


class TestProvidersOffline(unittest.TestCase):
    def test_fish_audio_provider_name(self):
        provider = FishAudioProvider()
        self.assertEqual(provider.name, "fish_audio")

    def test_voicebox_provider_name(self):
        provider = VoiceboxProvider()
        self.assertEqual(provider.name, "voicebox")

    def test_voicebox_update_default_engine_puts_profile(self):
        from unittest.mock import MagicMock, patch

        provider = VoiceboxProvider(base_url="http://voicebox.test")
        with patch("backend.providers.voicebox.requests.put") as put, patch(
            "backend.providers.voicebox.requests.get"
        ) as get:
            ok = MagicMock(status_code=200, text="")
            put.return_value = ok
            self.assertTrue(provider.update_default_engine("voice-1", "chatterbox_turbo"))
            put.assert_called_once_with(
                "http://voicebox.test/profiles/voice-1",
                json={"default_engine": "chatterbox_turbo", "preset_engine": "chatterbox_turbo"},
                timeout=5,
            )
            get.assert_not_called()

            put.reset_mock()
            put.return_value = ok
            self.assertTrue(provider.update_default_engine("voice-1", "qwen_fast"))
            self.assertEqual(put.call_args.kwargs["json"]["default_engine"], "qwen")

            put.reset_mock()
            get.reset_mock()
            rejected = MagicMock(status_code=422, text="name required")
            put.side_effect = [rejected, ok]
            get.return_value = MagicMock(status_code=200)
            get.return_value.json.return_value = {"id": "voice-1", "name": "Amanda"}
            self.assertTrue(provider.update_default_engine("voice-1", "chatterbox"))
            self.assertEqual(get.call_count, 1)
            self.assertEqual(put.call_count, 2)
            self.assertEqual(put.call_args.kwargs["json"]["name"], "Amanda")
            self.assertEqual(put.call_args.kwargs["json"]["default_engine"], "chatterbox")

            self.assertFalse(provider.update_default_engine("default", "chatterbox"))
            self.assertFalse(provider.update_default_engine("voice-1", ""))


class TestPersonaSync(IsolatedHermesHomeTest):
    def test_fallback_prompt_uses_description(self):
        prompt = persona_sync.fallback_system_prompt(
            "Jarvis", "You are Jarvis, a butler."
        )
        self.assertIn("Jarvis", prompt)
        self.assertNotRegex(prompt, r"(?i)^you are\b")
        self.assertIn("mannerisms", prompt.lower())

    def test_fallback_prompt_ignores_fish_metadata(self):
        prompt = persona_sync.fallback_system_prompt(
            "Voldemort", "Fish Audio Clone (trained, private)"
        )
        self.assertNotRegex(prompt, r"(?i)^you are voldemort")
        self.assertIn("Voldemort", prompt)
        self.assertIn("profile's job", prompt)

    def test_style_overlay_preserves_role_language(self):
        overlay = persona_sync.build_style_overlay_prompt(
            "Eric Cartman",
            "You are Eric Cartman from South Park. Speak with aggressive snark.",
        )
        self.assertIn(persona_sync.STYLE_OVERLAY_MARKER, overlay)
        self.assertIn("SOUL.md", overlay)
        self.assertIn("AGENTS.md", overlay)
        self.assertIn("does not replace this profile's role", overlay)
        self.assertIn("Do not abandon the profile's job", overlay)
        self.assertIn("Eric Cartman", overlay)
        self.assertIn("snark", overlay.lower())
        self.assertNotRegex(overlay, r"(?i)^you are eric cartman")
        self.assertNotEqual(overlay.strip(), "You are Eric Cartman.")
        already = persona_sync.build_style_overlay_prompt("Eric Cartman", overlay)
        self.assertEqual(already, overlay)

    def test_character_strength_percent_scale(self):
        source = "Aggressive, impatient South Park snark. Still do the profile job."
        zero = persona_sync.build_style_overlay_prompt("Eric Cartman", source, strength=0)
        soft = persona_sync.build_style_overlay_prompt("Eric Cartman", source, strength=25)
        medium = persona_sync.build_style_overlay_prompt("Eric Cartman", source, strength=55)
        heavy = persona_sync.build_style_overlay_prompt("Eric Cartman", source, strength=85)
        eclipse = persona_sync.build_style_overlay_prompt("Eric Cartman", source, strength=100)
        self.assertEqual(zero, "")
        self.assertEqual(persona_sync.character_strength_percent("soft"), 25)
        self.assertEqual(persona_sync.character_strength_percent("medium"), 55)
        self.assertEqual(persona_sync.character_strength_percent("strong"), 85)
        self.assertEqual(persona_sync.character_strength_band(0), "none")
        self.assertEqual(persona_sync.character_strength_band(25), "soft")
        self.assertEqual(persona_sync.character_strength_band(55), "medium")
        self.assertEqual(persona_sync.character_strength_band(85), "heavy")
        self.assertEqual(persona_sync.character_strength_band(100), "eclipse")
        self.assertNotEqual(soft, medium)
        self.assertNotEqual(medium, heavy)
        self.assertIn("Additionally, reply in the speaking style", soft)
        self.assertIn("does not replace this profile's role", soft)
        self.assertIn("Prefer this character's speaking voice", medium)
        self.assertIn("character-heavy", heavy)
        self.assertIn("secondary", heavy.lower())
        self.assertNotIn(persona_sync.STYLE_OVERLAY_MARKER, eclipse)
        self.assertIn(persona_sync.CHARACTER_ECLIPSE_MARKER, eclipse)
        self.assertIn("You are Eric Cartman", eclipse)
        self.assertIn("eclipses this profile", eclipse.lower())
        self.assertIn("NAME LOCK", eclipse)
        self.assertIn("answer only as Eric Cartman", eclipse)
        self.assertIn("Never claim to be the Hermes profile name, Critic, Mechanic, Magellan", eclipse)
        self.assertIn("this block wins", eclipse)
        self.assertIn("ignored for identity", eclipse)
        self.assertIn("ANTI-LEAK", eclipse)
        self.assertTrue(eclipse.rstrip().endswith("You are Eric Cartman. Your name is Eric Cartman."))
        self.assertNotIn("unless that is exactly what", eclipse)
        self.assertNotIn("does not replace this profile's role", eclipse)
        self.assertNotIn("SOUL stays primary", eclipse)
        self.assertNotIn("Keep the identity, mission", eclipse)
        for overlay in (soft, medium, heavy):
            self.assertIn("SOUL.md", overlay)
            self.assertIn("snark", overlay.lower())
            self.assertNotRegex(overlay, r"(?i)^you are eric cartman")
        rebuilt = persona_sync.build_style_overlay_prompt("Eric Cartman", soft, strength=100)
        self.assertIn("You are Eric Cartman", rebuilt)
        self.assertIn("snark", rebuilt.lower())

    def test_listable_pack_requires_prompt_and_cloned_voice(self):
        complete = PersonaBundle(
            id="cartman",
            name="Eric Cartman",
            avatar="🧢",
            system_prompt="Aggressive impatient South Park snark while doing the job.",
            provider="voicebox",
            voice_id="c9da87b0-19be-49c4-ab44-01cb7943f5c4",
            voice_name="Cartman",
        )
        stub = PersonaBundle(
            id="storyteller",
            name="The Storyteller",
            avatar="🎙️",
            system_prompt="distinctive tone, vocabulary, and cadence associated with The Storyteller; stay helpful and complete the profile's job",
            provider="fish_audio",
            voice_id="default",
            voice_name="Fish Audio (Default)",
        )
        no_voice = PersonaBundle(
            id="kitt",
            name="KITT",
            avatar="🚗",
            system_prompt="Clipped loyal Knight Rider cadence while doing the profile job.",
            provider="fish_audio",
            voice_id="default",
            voice_name="Fish Audio (Default)",
        )
        self.assertTrue(persona_sync.is_listable_persona_pack(complete))
        self.assertFalse(persona_sync.is_listable_persona_pack(stub))
        self.assertFalse(persona_sync.is_listable_persona_pack(no_voice))
        voices = [
            VoiceInfo(id="fish-kitt", name="Hermes kitt", provider="fish_audio", voice_type="cloned"),
        ]
        self.assertTrue(persona_sync.is_listable_persona_pack(no_voice, voices))

    def test_mannerism_from_prompt_strips_you_are_identity(self):
        style = persona_sync.mannerism_from_prompt(
            "You are K.I.T.T. from Knight Rider. Be clipped and loyal.",
            "K.I.T.T.",
        )
        self.assertNotRegex(style, r"(?i)^you are\b")
        self.assertIn("clipped", style.lower())

    def test_sync_from_voices_creates_missing_personas(self):
        storage = PersonaStorage(root_dir=str(self.home / "personas"))
        voices = [
            VoiceInfo(
                id="voice-jarvis-1",
                name="Jarvis",
                provider="voicebox",
                voice_type="cloned",
                description="You are Jarvis, a highly capable British butler.",
            ),
            VoiceInfo(
                id="voice-cartman-1",
                name="Cartman",
                provider="voicebox",
                voice_type="cloned",
                description="",
            ),
        ]
        result = persona_sync.sync_personas_from_voices(storage, voices)
        self.assertTrue(result["ok"])
        self.assertEqual(result["created"], ["jarvis"])
        self.assertIn("voice-cartman-1", result["skipped"])
        jarvis = storage.get_persona("jarvis")
        self.assertEqual(jarvis.voice_id, "voice-jarvis-1")
        self.assertIn("butler", jarvis.system_prompt.lower())
        self.assertIsNone(storage.get_persona("cartman"))

    def test_sync_from_voices_is_idempotent(self):
        storage = PersonaStorage(root_dir=str(self.home / "personas"))
        voices = [
            VoiceInfo(
                id="voice-jarvis-1",
                name="Jarvis",
                provider="voicebox",
                voice_type="cloned",
                description="You are Jarvis, a highly capable British butler.",
            )
        ]
        first = persona_sync.sync_personas_from_voices(storage, voices)
        second = persona_sync.sync_personas_from_voices(storage, voices)
        self.assertEqual(first["created"], ["jarvis"])
        self.assertEqual(second["created"], [])
        self.assertEqual(second["updated"], ["jarvis"])
        self.assertEqual(len(storage.list_personas()), 1)

    def test_sync_rebinds_seeded_default_voice_on_name_match(self):
        storage = PersonaStorage(root_dir=str(self.home / "personas"))
        seeded = PersonaBundle(
            id="jarvis",
            name="Jarvis (Tech Butler)",
            avatar="🤖",
            system_prompt="You are Jarvis, keep this custom prompt.",
            provider="fish_audio",
            voice_id="default",
            voice_name="Fish Audio (Default)",
        )
        storage.save_persona(seeded)
        voices = [
            VoiceInfo(
                id="real-jarvis-clone",
                name="Jarvis",
                provider="voicebox",
                voice_type="cloned",
                description="ignored because prompt already exists",
            )
        ]
        persona_sync.sync_personas_from_voices(storage, voices)
        loaded = storage.get_persona("jarvis")
        self.assertEqual(loaded.voice_id, "real-jarvis-clone")
        self.assertEqual(loaded.provider, "voicebox")
        self.assertEqual(loaded.system_prompt, "You are Jarvis, keep this custom prompt.")

    def test_sync_does_not_recreate_stub_fish_name_clones(self):
        """Name-only Fish clones must not recreate deleted hermes_* stub packs."""
        storage = PersonaStorage(root_dir=str(self.home / "personas"))
        storage.save_persona(
            PersonaBundle(
                id="cartman",
                name="Eric Cartman",
                avatar="🧢",
                system_prompt="Aggressive impatient South Park snark while doing the job.",
                provider="voicebox",
                voice_id="old-cartman",
                voice_name="Cartman",
            )
        )
        storage.save_persona(
            PersonaBundle(
                id="jarvis",
                name="Jarvis (Tech Butler)",
                avatar="🤖",
                system_prompt="Precise calm British butler manner while doing the profile job.",
                provider="fish_audio",
                voice_id="default",
                voice_name="Fish Audio (Default)",
            )
        )
        voices = [
            VoiceInfo(id="fish-kitt", name="Hermes kitt", provider="fish_audio", voice_type="cloned"),
            VoiceInfo(id="fish-porky", name="Hermes porky pig", provider="fish_audio", voice_type="cloned"),
            VoiceInfo(id="fish-default", name="Hermes default", provider="fish_audio", voice_type="cloned"),
            VoiceInfo(id="fish-cartman", name="Hermes eric_cartman", provider="fish_audio", voice_type="cloned"),
            VoiceInfo(id="fish-jarvis", name="Hermes jarvis", provider="fish_audio", voice_type="cloned"),
            VoiceInfo(
                id="vb-voldemort",
                name="Voldemort",
                provider="voicebox",
                voice_type="cloned",
                description="Cold, precise, aristocratic hiss. Complete the profile job without claiming you are only Voldemort.",
            ),
        ]
        result = persona_sync.sync_personas_from_voices(storage, voices)
        ids = {p.id for p in storage.list_personas()}
        self.assertNotIn("hermes_kitt", ids)
        self.assertNotIn("kitt", ids)
        self.assertNotIn("hermes_porky_pig", ids)
        self.assertNotIn("porky_pig", ids)
        self.assertNotIn("hermes_default", ids)
        self.assertIn("fish-kitt", result["skipped"])
        self.assertIn("fish-porky", result["skipped"])
        self.assertIn("fish-default", result["skipped"])
        self.assertEqual(storage.get_persona("cartman").voice_id, "fish-cartman")
        self.assertEqual(storage.get_persona("jarvis").voice_id, "fish-jarvis")
        self.assertIn("voldemort", result["created"])
        self.assertIn("aristocratic", storage.get_persona("voldemort").system_prompt.lower())
        self.assertIsNone(persona_sync.ensure_persona_for_voice(
            storage,
            VoiceInfo(id="fish-kitt", name="Hermes kitt", provider="fish_audio", voice_type="cloned"),
        ))

    def test_sync_skips_preset_and_default_voices(self):
        storage = PersonaStorage(root_dir=str(self.home / "personas"))
        voices = [
            VoiceInfo(id="default", name="Fish Default", provider="fish_audio", voice_type="system"),
            VoiceInfo(id="am_adam", name="Adam", provider="voicebox", voice_type="preset"),
        ]
        result = persona_sync.sync_personas_from_voices(storage, voices)
        self.assertEqual(result["created"], [])
        self.assertEqual(storage.list_personas(), [])

    def test_ensure_persona_for_voice_updates_same_slug(self):
        storage = PersonaStorage(root_dir=str(self.home / "personas"))
        storage.save_persona(
            PersonaBundle(
                id="storyteller",
                name="The Storyteller",
                avatar="🎙️",
                system_prompt="Vivid theatrical narrator cadence while doing the profile job.",
                provider="voicebox",
                voice_id="abc",
                voice_name="Storyteller",
            )
        )
        voice2 = VoiceInfo(id="def", name="The Storyteller", provider="voicebox", voice_type="cloned")
        second = persona_sync.ensure_persona_for_voice(storage, voice2)
        self.assertIsNotNone(second)
        self.assertEqual(second.id, "storyteller")
        self.assertEqual(second.voice_id, "def")
        self.assertEqual(len(storage.list_personas()), 1)

    def test_sync_does_not_downgrade_fish_binding_to_voicebox(self):
        storage = PersonaStorage(root_dir=str(self.home / "personas"))
        storage.save_persona(
            PersonaBundle(
                id="cartman",
                name="Eric Cartman",
                avatar="🧢",
                system_prompt="Aggressive impatient South Park snark while doing the job.",
                provider="fish_audio",
                voice_id="fish-cartman",
                voice_name="Cartman",
            )
        )
        voices = [
            VoiceInfo(id="fish-cartman", name="Cartman", provider="fish_audio", voice_type="cloned"),
            VoiceInfo(id="vb-cartman", name="Cartman", provider="voicebox", voice_type="cloned"),
        ]
        persona_sync.sync_personas_from_voices(storage, voices)
        loaded = storage.get_persona("cartman")
        self.assertEqual(loaded.provider, "fish_audio")
        self.assertEqual(loaded.voice_id, "fish-cartman")

    def test_sync_upgrades_voicebox_bundle_when_fish_twin_appears(self):
        storage = PersonaStorage(root_dir=str(self.home / "personas"))
        storage.save_persona(
            PersonaBundle(
                id="kitt",
                name="KITT",
                avatar="🚗",
                system_prompt="Clipped loyal Knight Rider cadence while doing the profile job.",
                provider="voicebox",
                voice_id="vb-kitt",
                voice_name="KITT",
            )
        )
        persona_sync.ensure_persona_for_voice(
            storage,
            VoiceInfo(id="fish-kitt", name="kitt", provider="fish_audio", voice_type="cloned"),
        )
        loaded = storage.get_persona("kitt")
        self.assertEqual(loaded.provider, "fish_audio")
        self.assertEqual(loaded.voice_id, "fish-kitt")

    def test_resolve_prefers_fish_twin_for_voicebox_stored_persona(self):
        bundle = PersonaBundle(
            id="cartman",
            name="Eric Cartman",
            avatar="🧢",
            system_prompt="Respect my authoritah.",
            provider="voicebox",
            voice_id="vb-cartman-uuid",
            voice_name="Cartman",
        )
        voices = [
            VoiceInfo(id="vb-cartman-uuid", name="Cartman", provider="voicebox", voice_type="cloned"),
            VoiceInfo(id="fish-cartman-id", name="Cartman", provider="fish_audio", voice_type="cloned"),
        ]
        resolved = persona_sync.resolve_tts_for_apply(bundle=bundle, voices=voices, explicit=False)
        self.assertEqual(resolved["provider"], "fish_audio")
        self.assertEqual(resolved["voice_id"], "fish-cartman-id")
        self.assertEqual(resolved["reason"], "fish-twin-by-name")

    def test_resolve_explicit_voicebox_selection_is_honored(self):
        bundle = PersonaBundle(
            id="cartman",
            name="Eric Cartman",
            avatar="🧢",
            system_prompt="Respect my authoritah.",
            provider="voicebox",
            voice_id="vb-cartman-uuid",
            voice_name="Cartman",
        )
        selected = VoiceInfo(id="vb-cartman-uuid", name="Cartman", provider="voicebox", voice_type="cloned")
        voices = [
            selected,
            VoiceInfo(id="fish-cartman-id", name="Cartman", provider="fish_audio", voice_type="cloned"),
        ]
        resolved = persona_sync.resolve_tts_for_apply(
            bundle=bundle,
            selected_voice=selected,
            voices=voices,
            explicit=True,
        )
        self.assertEqual(resolved["provider"], "voicebox")
        self.assertEqual(resolved["voice_id"], "vb-cartman-uuid")
        self.assertEqual(resolved["reason"], "explicit-selection")

    def test_resolve_kitt_name_match_to_fish(self):
        bundle = PersonaBundle(
            id="kitt",
            name="KITT",
            avatar="🚗",
            system_prompt="You are KITT.",
            provider="voicebox",
            voice_id="vb-kitt",
            voice_name="KITT",
        )
        voices = [
            VoiceInfo(id="vb-kitt", name="KITT", provider="voicebox", voice_type="cloned"),
            VoiceInfo(id="fish-kitt", name="kitt", provider="fish_audio", voice_type="cloned"),
        ]
        resolved = persona_sync.resolve_tts_for_apply(bundle=bundle, voices=voices)
        self.assertEqual(resolved["voice_id"], "fish-kitt")
        self.assertTrue(persona_sync.is_fish_provider(resolved["provider"]))

    def test_resolve_falls_back_to_voicebox_without_fish_twin(self):
        bundle = PersonaBundle(
            id="voldemort",
            name="Voldemort",
            avatar="🐍",
            system_prompt="You are Voldemort.",
            provider="voicebox",
            voice_id="vb-voldy",
            voice_name="Voldemort",
        )
        voices = [
            VoiceInfo(id="vb-voldy", name="Voldemort", provider="voicebox", voice_type="cloned"),
        ]
        resolved = persona_sync.resolve_tts_for_apply(bundle=bundle, voices=voices)
        self.assertEqual(resolved["provider"], "voicebox")
        self.assertEqual(resolved["voice_id"], "vb-voldy")
        self.assertEqual(resolved["reason"], "bundle-stored-voice")

    def test_resolve_ignores_fish_system_default(self):
        bundle = PersonaBundle(
            id="jarvis",
            name="Jarvis (Tech Butler)",
            avatar="🤖",
            system_prompt="You are Jarvis.",
            provider="fish_audio",
            voice_id="default",
            voice_name="Fish Audio (Default)",
        )
        voices = [
            VoiceInfo(id="default", name="Fish Audio (Default Voice)", provider="fish_audio", voice_type="system"),
            VoiceInfo(id="fish-jarvis", name="Jarvis", provider="fish_audio", voice_type="cloned"),
        ]
        resolved = persona_sync.resolve_tts_for_apply(bundle=bundle, voices=voices)
        self.assertEqual(resolved["voice_id"], "fish-jarvis")
        self.assertEqual(resolved["reason"], "fish-twin-by-name")

    def test_resolve_hermes_prefixed_fish_names(self):
        voices = [
            VoiceInfo(id="fish-jarvis", name="Hermes jarvis", provider="fish_audio", voice_type="cloned"),
            VoiceInfo(id="fish-kitt", name="Hermes kitt", provider="fish_audio", voice_type="cloned"),
            VoiceInfo(id="fish-cartman", name="Hermes cartman", provider="fish_audio", voice_type="cloned"),
            VoiceInfo(id="fish-eric", name="Hermes eric_cartman", provider="fish_audio", voice_type="cloned"),
        ]
        jarvis = PersonaBundle(
            id="jarvis",
            name="Jarvis (Tech Butler)",
            avatar="🤖",
            system_prompt="You are Jarvis.",
            provider="voicebox",
            voice_id="vb-jarvis",
            voice_name="Jarvis",
        )
        kitt = PersonaBundle(
            id="kitt",
            name="KITT",
            avatar="🚗",
            system_prompt="You are KITT.",
            provider="voicebox",
            voice_id="vb-kitt",
            voice_name="KITT",
        )
        cartman = PersonaBundle(
            id="cartman",
            name="Eric Cartman",
            avatar="🧢",
            system_prompt="Respect my authoritah.",
            provider="voicebox",
            voice_id="vb-cartman",
            voice_name="Cartman",
        )
        self.assertEqual(
            persona_sync.resolve_tts_for_apply(bundle=jarvis, voices=voices)["voice_id"],
            "fish-jarvis",
        )
        self.assertEqual(
            persona_sync.resolve_tts_for_apply(bundle=kitt, voices=voices)["voice_id"],
            "fish-kitt",
        )
        cartman_r = persona_sync.resolve_tts_for_apply(bundle=cartman, voices=voices)
        self.assertEqual(cartman_r["voice_id"], "fish-eric")
        self.assertEqual(cartman_r["voice_name"], "Hermes eric_cartman")

    def test_resolve_prefers_profile_clone_map_key(self):
        bundle = PersonaBundle(
            id="cartman",
            name="Eric Cartman",
            avatar="🧢",
            system_prompt="Respect my authoritah.",
            provider="voicebox",
            voice_id="vb-cartman",
            voice_name="Cartman",
        )
        voices = [
            VoiceInfo(id="id-cartman", name="Hermes cartman", provider="fish_audio", voice_type="cloned"),
            VoiceInfo(id="id-eric", name="Hermes eric_cartman", provider="fish_audio", voice_type="cloned"),
        ]
        resolved = persona_sync.resolve_tts_for_apply(
            bundle=bundle,
            voices=voices,
            clone_map={"eric_cartman": "id-eric", "cartman": "id-cartman"},
        )
        self.assertEqual(resolved["voice_id"], "id-eric")
        self.assertEqual(resolved["reason"], "profile-fish-clone-map")


class TestSurgicalConfigWrites(IsolatedHermesHomeTest):
    def _write_config(self, extra: str = "") -> Path:
        cfg = self.home / "config.yaml"
        cfg.write_text(
            "model: keep-me\n"
            "tools:\n"
            "  enabled: true\n"
            "tts:\n"
            "  provider: fish\n"
            "  providers:\n"
            "    fish:\n"
            "      voice: old_voice\n"
            "      clones:\n"
            "        old_voice: old-id\n"
            "agent:\n"
            "  max_turns: 12\n"
            "display:\n"
            "  personality: helpful\n"
            + extra,
            encoding="utf-8",
        )
        return cfg

    def test_set_profile_persona_writes_dict_and_keeps_unrelated_keys(self):
        cfg = self._write_config()
        result = bot_profiles.set_profile_persona(
            "default",
            "Jarvis (Tech Butler)",
            "You are Jarvis.",
            cfg_path=cfg,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["persona"], "jarvis_tech_butler")
        data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        self.assertEqual(data["model"], "keep-me")
        self.assertEqual(data["tools"]["enabled"], True)
        self.assertEqual(data["agent"]["max_turns"], 12)
        persona = data["agent"]["personalities"]["jarvis_tech_butler"]
        self.assertIn("SPEAKING STYLE OVERLAY", persona["system_prompt"])
        self.assertNotEqual(persona["system_prompt"].strip(), "You are Jarvis.")
        self.assertEqual(persona["source"], "hermes-personastudio")
        self.assertEqual(data["display"]["personality"], "jarvis_tech_butler")

    def test_clear_persona_writes_empty_display_personality(self):
        cfg = self._write_config()
        bot_profiles.set_profile_persona("default", "none", "", cfg_path=cfg)
        data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        self.assertEqual(data["display"]["personality"], "")
        self.assertEqual(data["model"], "keep-me")

    def test_assign_voice_surgical_keeps_unrelated_and_sets_voicebox(self):
        cfg = self._write_config()
        result = bot_profiles.assign_voice_to_profile(
            "default",
            "voicebox",
            "c9da87b0-19be-49c4-ab44-01cb7943f5c4",
            "Cartman",
            cfg_path=cfg,
        )
        self.assertTrue(result["ok"])
        data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        self.assertEqual(data["model"], "keep-me")
        self.assertEqual(data["tts"]["provider"], "voicebox")
        self.assertEqual(data["tts"]["providers"]["voicebox"]["voice"], "c9da87b0-19be-49c4-ab44-01cb7943f5c4")
        self.assertEqual(data["tts"]["providers"]["fish"]["voice"], "old_voice")
        self.assertEqual(data["agent"]["max_turns"], 12)

    def test_assign_fish_voice_pins_fish_voice_id_over_stale_label(self):
        stale = "7121ed18a81b450d8e54e5638190eb26"
        live = "a3767161e96c4b7caa61b605bc6b015a"
        cfg = self.home / "config.yaml"
        cfg.write_text(
            "model: keep-me\n"
            "tts:\n"
            "  provider: fish\n"
            "  providers:\n"
            "    fish:\n"
            "      voice: vincent_price\n"
            "      command: voicebox_tts --fish-label vincent_price\n"
            "      clones:\n"
            f"        vincent_price: {stale}\n"
            "display:\n"
            "  personality: helpful\n",
            encoding="utf-8",
        )
        result = bot_profiles.assign_voice_to_profile(
            "default",
            "fish_audio",
            live,
            "Vincent Price",
            cfg_path=cfg,
        )
        self.assertTrue(result["ok"])
        data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        command = data["tts"]["providers"]["fish"]["command"]
        self.assertIn("--fish-voice " + live, command)
        self.assertIn("--fish-label vincent_price", command)
        self.assertNotIn(stale, command)
        self.assertEqual(data["tts"]["providers"]["fish"]["clones"]["vincent_price"], live)
        self.assertEqual(data["tts"]["providers"]["fish"]["voice"], "vincent_price")
        cache = json.loads((self.home / "fish_voices.json").read_text(encoding="utf-8"))
        self.assertEqual(cache["vincent_price"], live)

    def test_update_config_keys_preserves_sibling_keys(self):
        cfg = self._write_config()
        strategy = config_io.update_config_keys(cfg, {"display.personality": "jarvis"})
        self.assertIn(strategy, (config_io.STRATEGY_PYYAML_SURGICAL, config_io.STRATEGY_HERMES_ATOMIC))
        data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        self.assertEqual(data["display"]["personality"], "jarvis")
        self.assertEqual(data["model"], "keep-me")

    def test_managed_index_purge_restores_previous_values(self):
        cfg = self._write_config()
        bot_profiles.set_profile_persona("default", "Jarvis", "You are Jarvis.", cfg_path=cfg)
        bot_profiles.assign_voice_to_profile(
            "default", "voicebox", "c9da87b0-19be-49c4-ab44-01cb7943f5c4", "Jarvis", cfg_path=cfg
        )
        index_path = self.home / "personas" / ".studio-managed.json"
        self.assertTrue(index_path.exists())
        report = managed_index.purge_tracked_config(index_path=index_path)
        self.assertTrue(report["ok"])
        data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        self.assertEqual(data["display"]["personality"], "helpful")
        self.assertEqual(data["tts"]["provider"], "fish")
        self.assertNotIn("jarvis", (data.get("agent") or {}).get("personalities") or {})
        self.assertTrue(cfg.exists())
        self.assertFalse(index_path.exists())

    def test_list_bot_profiles_uses_hermes_home(self):
        self._write_config()
        profiles = bot_profiles.list_bot_profiles()
        self.assertTrue(any(p["id"] == "default" for p in profiles))


class TestSessionOverlay(IsolatedHermesHomeTest):
    def _write_config(self) -> Path:
        cfg = self.home / "config.yaml"
        cfg.write_text(
            "model: keep-me\n"
            "tts:\n"
            "  provider: fish\n"
            "  providers:\n"
            "    fish:\n"
            "      voice: mechanic_default\n"
            "      clones:\n"
            "        mechanic_default: old-id\n"
            "        eric_cartman: cartman-id\n"
            "display:\n"
            "  personality: ''\n",
            encoding="utf-8",
        )
        return cfg

    def test_apply_stashes_and_reset_restores_stock(self):
        from backend import session_overlay

        cfg = self._write_config()
        apply = session_overlay.apply_session_overlay(
            "default",
            persona_name="Eric Cartman",
            persona_prompt="You are Eric Cartman.",
            provider="fish_audio",
            voice_id="cartman-id",
            voice_name="Hermes eric_cartman",
            cfg_path=cfg,
        )
        self.assertTrue(apply["ok"])
        self.assertEqual(apply["scope"], "session")
        after = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        self.assertEqual(after["display"]["personality"], "eric_cartman")
        self.assertNotEqual((after.get("agent") or {}).get("system_prompt") or "", "You are Eric Cartman.")
        catalog = ((after.get("agent") or {}).get("personalities") or {}).get("eric_cartman") or {}
        self.assertEqual(catalog.get("source"), "hermes-personastudio")
        self.assertIn("SPEAKING STYLE OVERLAY", catalog.get("system_prompt") or "")
        self.assertIn("SOUL.md", catalog.get("system_prompt") or "")
        self.assertNotEqual((catalog.get("system_prompt") or "").strip(), "You are Eric Cartman.")
        self.assertEqual(after["tts"]["provider"], "fish")
        self.assertEqual(after["tts"]["providers"]["fish"]["voice"], "hermes_eric_cartman")
        self.assertTrue(session_overlay.overlay_status("default")["active"])

        reset = session_overlay.reset_session_overlay("default", cfg_path=cfg)
        self.assertTrue(reset["restored"])
        restored = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        self.assertEqual(restored["display"]["personality"], "")
        self.assertEqual(restored["agent"]["system_prompt"], "")
        self.assertEqual(restored["tts"]["provider"], "fish")
        self.assertEqual(restored["tts"]["providers"]["fish"]["voice"], "mechanic_default")
        self.assertEqual(restored["model"], "keep-me")
        self.assertFalse(session_overlay.overlay_status("default")["active"])
        # Catalog entry is not itself active
        kitt_or_cartman = ((restored.get("agent") or {}).get("personalities") or {}).get("eric_cartman")
        self.assertIsInstance(kitt_or_cartman, dict)

    def test_second_apply_does_not_overwrite_stash(self):
        from backend import session_overlay

        cfg = self._write_config()
        session_overlay.apply_session_overlay(
            "default",
            persona_name="Eric Cartman",
            persona_prompt="You are Eric Cartman.",
            provider="fish_audio",
            voice_id="cartman-id",
            voice_name="Hermes eric_cartman",
            cfg_path=cfg,
        )
        session_overlay.apply_session_overlay(
            "default",
            persona_name="Jarvis",
            persona_prompt="You are Jarvis.",
            provider="fish_audio",
            voice_id="jarvis-id",
            voice_name="Hermes jarvis",
            cfg_path=cfg,
        )
        session_overlay.reset_session_overlay("default", cfg_path=cfg)
        restored = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        self.assertEqual(restored["display"]["personality"], "")
        self.assertEqual(restored["tts"]["providers"]["fish"]["voice"], "mechanic_default")

    def test_reset_without_stash_uses_edge_stock_not_studio_clone(self):
        from backend import session_overlay

        cfg = self._write_config()
        bot_profiles.set_profile_persona(
            "default", "Eric Cartman", "You are Eric Cartman.", cfg_path=cfg
        )
        bot_profiles.assign_voice_to_profile(
            "default", "fish_audio", "cartman-id", "Hermes eric_cartman", cfg_path=cfg
        )
        reset = session_overlay.reset_session_overlay("default", cfg_path=cfg)
        self.assertTrue(reset["leftover_personality_cleared"] or reset["restored"])
        data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        self.assertEqual(data["display"]["personality"], "")
        self.assertEqual(data["tts"]["provider"], "edge")
        self.assertEqual(data["tts"]["edge"]["voice"], "en-US-AriaNeural")
        fish_voice = ((data.get("tts") or {}).get("providers") or {}).get("fish") or {}
        self.assertNotEqual(data["tts"]["provider"], "voicebox")
        self.assertNotEqual(fish_voice.get("voice"), "default")

    def test_reset_all_clears_active_overlay(self):
        from backend import session_overlay

        cfg = self._write_config()
        session_overlay.apply_session_overlay(
            "default",
            persona_name="KITT",
            persona_prompt="You are KITT.",
            provider="fish_audio",
            voice_id="kitt-id",
            voice_name="Hermes kitt",
            cfg_path=cfg,
        )
        report = session_overlay.reset_all_session_overlays()
        self.assertTrue(report["ok"])
        data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        self.assertEqual(data["display"]["personality"], "")
        self.assertEqual(data["tts"]["providers"]["fish"]["voice"], "mechanic_default")
        self.assertEqual((data.get("agent") or {}).get("system_prompt") or "", "")

    def test_reset_does_not_write_voicebox_default(self):
        from backend import session_overlay

        cfg = self._write_config()
        session_overlay.apply_session_overlay(
            "default",
            persona_name="Eric Cartman",
            persona_prompt="You are Eric Cartman.",
            provider="fish_audio",
            voice_id="cartman-id",
            voice_name="Hermes eric_cartman",
            cfg_path=cfg,
        )
        state = session_overlay.load_session_state()
        state["profiles"]["default"]["stash"] = {
            "display.personality": "",
            "tts.provider": "voicebox",
            "tts.providers.voicebox.voice": "default",
            "tts.providers.fish.voice": None,
            "tts.edge.voice": None,
        }
        session_overlay.save_session_state(state)
        session_overlay.reset_session_overlay("default", cfg_path=cfg)
        data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        vb = ((data.get("tts") or {}).get("providers") or {}).get("voicebox") or {}
        self.assertNotEqual(vb.get("voice"), "default")
        self.assertEqual(data["tts"]["provider"], "edge")
        self.assertEqual(data["tts"]["edge"]["voice"], "en-US-AriaNeural")

    def test_edge_stash_restores_aria_not_jarvis(self):
        from backend import session_overlay

        cfg = self.home / "config.yaml"
        cfg.write_text(
            "tts:\n"
            "  provider: edge\n"
            "  edge:\n"
            "    voice: en-US-AriaNeural\n"
            "display:\n"
            "  personality: ''\n",
            encoding="utf-8",
        )
        session_overlay.apply_session_overlay(
            "default",
            persona_name="Jarvis",
            persona_prompt="You are Jarvis.",
            provider="voicebox",
            voice_id="f2cb3bdc-de82-4d31-9a82-b2b637800a31",
            voice_name="Jarvis",
            cfg_path=cfg,
        )
        after = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        self.assertEqual(after["tts"]["provider"], "voicebox")
        session_overlay.reset_session_overlay("default", cfg_path=cfg)
        restored = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        self.assertEqual(restored["display"]["personality"], "")
        self.assertEqual(restored["tts"]["provider"], "edge")
        self.assertEqual(restored["tts"]["edge"]["voice"], "en-US-AriaNeural")
        vb = ((restored.get("tts") or {}).get("providers") or {}).get("voicebox") or {}
        self.assertNotEqual(vb.get("voice"), "default")

    def test_assign_voicebox_rejects_default_id(self):
        cfg = self._write_config()
        with self.assertRaises(ValueError):
            bot_profiles.assign_voice_to_profile(
                "default", "voicebox", "default", "Default", cfg_path=cfg
            )

    def test_reset_restores_stashed_system_prompt_or_empty(self):
        from backend import session_overlay

        cfg = self.home / "config.yaml"
        cfg.write_text(
            "agent:\n"
            "  system_prompt: You are a custom mechanic helper.\n"
            "tts:\n"
            "  provider: edge\n"
            "  edge:\n"
            "    voice: en-US-AriaNeural\n"
            "display:\n"
            "  personality: ''\n",
            encoding="utf-8",
        )
        session_overlay.apply_session_overlay(
            "default",
            persona_name="KITT",
            persona_prompt="You are K.I.T.T. from Knight Rider.",
            provider="fish_audio",
            voice_id="kitt-id",
            voice_name="Hermes kitt",
            cfg_path=cfg,
        )
        after = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        self.assertNotEqual(after["agent"]["system_prompt"], "You are K.I.T.T. from Knight Rider.")
        self.assertEqual(after["agent"]["system_prompt"], "You are a custom mechanic helper.")
        self.assertEqual(after["display"]["personality"], "kitt")
        catalog = after["agent"]["personalities"]["kitt"]
        self.assertIn("SPEAKING STYLE OVERLAY", catalog["system_prompt"])
        self.assertNotIn("You are K.I.T.T. from Knight Rider.", catalog["system_prompt"].split("\n")[0])
        session_overlay.reset_session_overlay("default", cfg_path=cfg)
        restored = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        self.assertEqual(restored["display"]["personality"], "")
        self.assertEqual(restored["agent"]["system_prompt"], "You are a custom mechanic helper.")
        self.assertEqual(restored["agent"]["personalities"]["kitt"]["source"], "hermes-personastudio")

    def test_leftover_kitt_system_prompt_cleared_without_stash(self):
        from backend import session_overlay

        cfg = self.home / "config.yaml"
        cfg.write_text(
            "agent:\n"
            "  system_prompt: You are K.I.T.T. from Knight Rider...\n"
            "  personalities:\n"
            "    kitt:\n"
            "      system_prompt: You are K.I.T.T. from Knight Rider...\n"
            "      source: hermes-personastudio\n"
            "tts:\n"
            "  provider: edge\n"
            "  edge:\n"
            "    voice: en-US-AriaNeural\n"
            "display:\n"
            "  personality: ''\n",
            encoding="utf-8",
        )
        session_overlay.reset_session_overlay("default", cfg_path=cfg)
        data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        self.assertEqual(data["display"]["personality"], "")
        self.assertEqual(data["agent"]["system_prompt"], "")
        self.assertEqual(data["agent"]["personalities"]["kitt"]["source"], "hermes-personastudio")
        self.assertEqual(data["tts"]["provider"], "edge")

    def test_apply_mechanic_does_not_write_magellan_tts_or_personality(self):
        from backend import session_overlay

        mechanic = self.home / "profiles" / "mechanic" / "config.yaml"
        magellan = self.home / "profiles" / "magellan" / "config.yaml"
        mechanic.parent.mkdir(parents=True)
        magellan.parent.mkdir(parents=True)
        mechanic.write_text(
            "tts:\n"
            "  provider: edge\n"
            "  edge:\n"
            "    voice: en-US-AriaNeural\n"
            "display:\n"
            "  personality: ''\n",
            encoding="utf-8",
        )
        magellan.write_text(
            "tts:\n"
            "  provider: voicebox\n"
            "  providers:\n"
            "    voicebox:\n"
            "      voice: c9da87b0-19be-49c4-ab44-01cb7943f5c4\n"
            "display:\n"
            "  personality: ''\n"
            "agent:\n"
            "  system_prompt: leftover flirty text\n",
            encoding="utf-8",
        )
        apply = session_overlay.apply_session_overlay(
            "mechanic",
            persona_name="Eric Cartman",
            persona_prompt="You are Eric Cartman.",
            provider="fish_audio",
            voice_id="cartman-id",
            voice_name="Hermes eric_cartman",
            cfg_path=mechanic,
        )
        self.assertTrue(apply["ok"])
        after_m = yaml.safe_load(mechanic.read_text(encoding="utf-8"))
        after_g = yaml.safe_load(magellan.read_text(encoding="utf-8"))
        self.assertEqual(after_m["display"]["personality"], "eric_cartman")
        self.assertIn("SPEAKING STYLE OVERLAY", after_m["agent"]["personalities"]["eric_cartman"]["system_prompt"])
        self.assertEqual(after_g["display"]["personality"], "")
        self.assertEqual(after_g["tts"]["provider"], "voicebox")
        self.assertEqual(
            after_g["tts"]["providers"]["voicebox"]["voice"],
            "c9da87b0-19be-49c4-ab44-01cb7943f5c4",
        )
        self.assertEqual(after_g["agent"]["system_prompt"], "leftover flirty text")
        self.assertTrue(session_overlay.overlay_status("mechanic")["active"])
        self.assertFalse(session_overlay.overlay_status("magellan")["active"])

        reset_g = session_overlay.reset_session_overlay("magellan", cfg_path=magellan)
        self.assertTrue(reset_g["ok"])
        after_g2 = yaml.safe_load(magellan.read_text(encoding="utf-8"))
        after_m2 = yaml.safe_load(mechanic.read_text(encoding="utf-8"))
        self.assertEqual(after_g2["tts"]["provider"], "edge")
        self.assertEqual(after_g2["tts"]["edge"]["voice"], "en-US-AriaNeural")
        self.assertEqual(after_m2["display"]["personality"], "eric_cartman")
        self.assertTrue(session_overlay.overlay_status("mechanic")["active"])
        self.assertFalse(session_overlay.overlay_status("magellan")["active"])

    def test_reset_clears_untagged_cartman_personality_leftover(self):
        """Critic: display.personality cartman (no SOURCE_TAG) survived tagged-only clear."""
        from backend import session_overlay

        critic = self.home / "profiles" / "critic" / "config.yaml"
        mechanic = self.home / "profiles" / "mechanic" / "config.yaml"
        critic.parent.mkdir(parents=True)
        mechanic.parent.mkdir(parents=True)
        critic.write_text(
            "agent:\n"
            "  system_prompt: You are K.I.T.T. leftover\n"
            "  personalities:\n"
            "    cartman:\n"
            "      system_prompt: Speak like Cartman.\n"
            "tts:\n"
            "  provider: edge\n"
            "  edge:\n"
            "    voice: en-US-AriaNeural\n"
            "display:\n"
            "  personality: cartman\n",
            encoding="utf-8",
        )
        mechanic.write_text(
            "tts:\n"
            "  provider: edge\n"
            "  edge:\n"
            "    voice: en-US-AriaNeural\n"
            "display:\n"
            "  personality: ''\n",
            encoding="utf-8",
        )
        session_overlay.apply_session_overlay(
            "mechanic",
            persona_name="Eric Cartman",
            persona_prompt="You are Eric Cartman.",
            provider="fish_audio",
            voice_id="cartman-id",
            voice_name="Hermes eric_cartman",
            cfg_path=mechanic,
        )
        reset = session_overlay.reset_session_overlay("critic", cfg_path=critic)
        self.assertTrue(reset["leftover_personality_cleared"])
        critic_after = yaml.safe_load(critic.read_text(encoding="utf-8"))
        mechanic_after = yaml.safe_load(mechanic.read_text(encoding="utf-8"))
        self.assertEqual(critic_after["display"]["personality"], "")
        self.assertEqual(critic_after["tts"]["provider"], "edge")
        self.assertEqual(critic_after["tts"]["edge"]["voice"], "en-US-AriaNeural")
        self.assertEqual(
            critic_after["agent"]["personalities"]["cartman"]["system_prompt"],
            "Speak like Cartman.",
        )
        self.assertEqual(critic_after["agent"]["system_prompt"], "You are K.I.T.T. leftover")
        self.assertEqual(mechanic_after["display"]["personality"], "eric_cartman")
        self.assertTrue(session_overlay.overlay_status("mechanic")["active"])
        self.assertFalse(session_overlay.overlay_status("critic")["active"])

    def test_reset_all_clears_untagged_personality_without_session_entry(self):
        from backend import session_overlay

        critic = self.home / "profiles" / "critic" / "config.yaml"
        critic.parent.mkdir(parents=True)
        critic.write_text(
            "tts:\n"
            "  provider: edge\n"
            "  edge:\n"
            "    voice: en-US-AriaNeural\n"
            "display:\n"
            "  personality: cartman\n",
            encoding="utf-8",
        )
        report = session_overlay.reset_all_session_overlays()
        self.assertTrue(report["ok"])
        after = yaml.safe_load(critic.read_text(encoding="utf-8"))
        self.assertEqual(after["display"]["personality"], "")
        self.assertEqual(after["tts"]["provider"], "edge")
        self.assertTrue(
            any(p.get("profile_id") == "critic" and p.get("leftover_personality_cleared") for p in report["profiles"])
        )

    def test_apply_zero_skips_style_overlay(self):
        from backend import session_overlay

        cfg = self._write_config()
        apply = session_overlay.apply_session_overlay(
            "default",
            persona_name="Eric Cartman",
            persona_prompt="You are Eric Cartman. Speak with aggressive snark.",
            provider="fish_audio",
            voice_id="cartman-id",
            voice_name="Hermes eric_cartman",
            character_strength=0,
            cfg_path=cfg,
        )
        self.assertEqual(apply["character_strength"], 0)
        self.assertEqual(apply["style_overlay"], "")
        after = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        self.assertEqual(after["display"]["personality"], "")
        self.assertEqual(after["tts"]["provider"], "fish")
        self.assertNotIn("You are Eric Cartman", (after.get("agent") or {}).get("system_prompt") or "")

    def test_apply_hundred_eclipses_soul(self):
        from backend import session_overlay

        cfg = self._write_config()
        apply = session_overlay.apply_session_overlay(
            "default",
            persona_name="Eric Cartman",
            persona_prompt="You are Eric Cartman. Speak with aggressive snark.",
            provider="fish_audio",
            voice_id="cartman-id",
            voice_name="Hermes eric_cartman",
            character_strength=100,
            cfg_path=cfg,
        )
        self.assertEqual(apply["character_strength"], 100)
        self.assertIn("You are Eric Cartman", apply["style_overlay"])
        self.assertIn("eclipses this profile", apply["style_overlay"].lower())
        self.assertIn("NAME LOCK", apply["style_overlay"])
        self.assertIn("this block wins", apply["style_overlay"])
        self.assertTrue(apply["style_overlay"].rstrip().endswith("You are Eric Cartman. Your name is Eric Cartman."))
        self.assertNotIn("unless that is exactly what", apply["style_overlay"])
        self.assertNotIn("does not replace this profile's role", apply["style_overlay"])
        self.assertNotIn(persona_sync.STYLE_OVERLAY_MARKER, apply["style_overlay"])
        after = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        overlay = after["agent"]["personalities"]["eric_cartman"]["system_prompt"]
        self.assertIn("You are Eric Cartman", overlay)
        self.assertEqual(after["display"]["personality"], "eric_cartman")
        self.assertEqual(after["agent"]["personalities"]["eric_cartman"]["character_strength"], 100)
        self.assertNotEqual((after.get("agent") or {}).get("system_prompt") or "", overlay)
        status = session_overlay.overlay_status("default")
        self.assertTrue(status["active"])
        self.assertEqual(status["applied_persona"], "eric_cartman")
        self.assertEqual(status["character_strength"], 100)
        self.assertEqual(status["provider"], "fish_audio")
        self.assertEqual(status["voice_name"], "Hermes eric_cartman")

    def test_apply_mid_character_strength_writes_blend_overlay(self):
        from backend import session_overlay

        cfg = self._write_config()
        apply = session_overlay.apply_session_overlay(
            "default",
            persona_name="Eric Cartman",
            persona_prompt="You are Eric Cartman. Speak with aggressive snark.",
            provider="fish_audio",
            voice_id="cartman-id",
            voice_name="Hermes eric_cartman",
            character_strength=85,
            cfg_path=cfg,
        )
        self.assertEqual(apply["character_strength"], 85)
        self.assertIn("character-heavy", apply["style_overlay"])
        after = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        overlay = after["agent"]["personalities"]["eric_cartman"]["system_prompt"]
        self.assertIn("character-heavy", overlay)
        self.assertEqual(after["agent"]["personalities"]["eric_cartman"]["character_strength"], 85)
        self.assertNotEqual((after.get("agent") or {}).get("system_prompt") or "", overlay)

    def test_apply_does_not_write_bare_you_are_cartman_identity(self):
        from backend import session_overlay

        cfg = self._write_config()
        apply = session_overlay.apply_session_overlay(
            "default",
            persona_name="Eric Cartman",
            persona_prompt="You are Eric Cartman.",
            provider="fish_audio",
            voice_id="cartman-id",
            voice_name="Hermes eric_cartman",
            cfg_path=cfg,
        )
        after = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        self.assertFalse(apply.get("touched_system_prompt"))
        self.assertNotEqual((after.get("agent") or {}).get("system_prompt"), "You are Eric Cartman.")
        catalog = after["agent"]["personalities"]["eric_cartman"]["system_prompt"]
        self.assertIn("SPEAKING STYLE OVERLAY", catalog)
        self.assertIn("SOUL.md", catalog)
        self.assertIn("profile's job", catalog.lower())
        self.assertNotEqual(catalog.strip(), "You are Eric Cartman.")
        self.assertNotRegex(catalog, r"(?im)^you are eric cartman\.?$")

    def test_reset_clears_style_overlay_selection(self):
        from backend import session_overlay

        cfg = self._write_config()
        session_overlay.apply_session_overlay(
            "default",
            persona_name="Jarvis",
            persona_prompt="You are Jarvis.",
            provider="fish_audio",
            voice_id="jarvis-id",
            voice_name="Hermes jarvis",
            cfg_path=cfg,
        )
        after = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        self.assertEqual(after["display"]["personality"], "jarvis")
        self.assertIn("SPEAKING STYLE OVERLAY", after["agent"]["personalities"]["jarvis"]["system_prompt"])
        session_overlay.reset_session_overlay("default", cfg_path=cfg)
        restored = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        self.assertEqual(restored["display"]["personality"], "")
        self.assertEqual((restored.get("agent") or {}).get("system_prompt") or "", "")
        self.assertFalse(session_overlay.overlay_status("default")["active"])


class TestPluginSessionWatchRace(unittest.TestCase):
    """Promax double-blank race: first-prompt focusedSessionId churn is not New Chat."""

    @classmethod
    def setUpClass(cls):
        cls.plugin_path = Path(__file__).resolve().parent / "desktop" / "plugin.js"
        cls.src = cls.plugin_path.read_text(encoding="utf-8")
        start = cls.src.index("// SESSION_WATCH_BEGIN")
        end = cls.src.index("// SESSION_WATCH_END")
        cls.helpers = cls.src[start:end]

    def _run_js(self, body: str):
        import json
        import subprocess
        import tempfile

        script = (
            self.helpers
            + "\n"
            + body
            + "\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
            handle.write(script)
            path = handle.name
        try:
            result = subprocess.run(
                ["node", path],
                capture_output=True,
                text=True,
                check=False,
            )
        finally:
            Path(path).unlink(missing_ok=True)
        self.assertEqual(
            result.returncode,
            0,
            msg=f"node failed: {result.stderr or result.stdout}",
        )
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_apply_gate_is_several_seconds(self):
        import re

        match = re.search(r"const APPLY_GATE_MS = (\d+)", self.src)
        self.assertIsNotNone(match)
        self.assertGreaterEqual(int(match.group(1)), 5000)

    def test_watcher_does_not_call_newchat_after_user_new_chat(self):
        start = self.src.index("const onSessionChange = async () => {")
        end = self.src.index("return subscribeFocusedSession(onSessionChange);")
        watcher = self.src[start:end]
        self.assertIn("decideSessionWatchTick", watcher)
        self.assertIn("reset-stock", watcher)
        self.assertNotIn("startNewChat", watcher)
        self.assertIn("Do not call host.newChat again", watcher)

    def test_old_focused_session_id_churn_trigger_is_gone(self):
        start = self.src.index("const onSessionChange = async () => {")
        end = self.src.index("return subscribeFocusedSession(onSessionChange);")
        watcher = self.src[start:end]
        self.assertNotIn("sid === overlay.sessionId", watcher)
        self.assertNotIn("if (!sid || sid === overlay.sessionId) return;", watcher)
        self.assertNotIn("setTimeout(() => { overlayRef.current.applyInProgress = false; }, 500)", self.src)

    def test_first_prompt_persist_does_not_reset(self):
        data = self._run_js(
            """
            const overlay = { active: true, sessionId: 'ephemeral-1', storedId: null, applyInProgress: false };
            const decision = decideSessionWatchTick(overlay, 'persisted-uuid-2', 'stored-abc');
            console.log(JSON.stringify({
              action: decision.action,
              callNewChat: decision.callNewChat,
              userNewChat: isUserNewChatTransition(overlay.storedId, 'stored-abc')
            }));
            """
        )
        self.assertEqual(data["action"], "track")
        self.assertFalse(data["callNewChat"])
        self.assertFalse(data["userNewChat"])

    def test_session_id_string_churn_alone_does_not_reset(self):
        data = self._run_js(
            """
            const overlay = { active: true, sessionId: 'ephemeral-1', storedId: null, applyInProgress: false };
            const decision = decideSessionWatchTick(overlay, 'ephemeral-renumbered', null);
            console.log(JSON.stringify(decision));
            """
        )
        self.assertEqual(data["action"], "track")
        self.assertFalse(data["callNewChat"])

    def test_user_new_chat_resets_without_newchat(self):
        data = self._run_js(
            """
            const overlay = { active: true, sessionId: 'sess-2', storedId: 'stored-abc', applyInProgress: false };
            const decision = decideSessionWatchTick(overlay, 'ephemeral-blank', null);
            console.log(JSON.stringify(decision));
            """
        )
        self.assertEqual(data["action"], "reset-stock")
        self.assertFalse(data["callNewChat"])
        self.assertEqual(data["overlayPatch"]["active"], False)
        self.assertIsNone(data["overlayPatch"]["storedId"])

    def test_empty_string_stored_id_is_user_new_chat(self):
        data = self._run_js(
            """
            const overlay = { active: true, sessionId: 'sess-2', storedId: 'stored-abc', applyInProgress: false };
            const decision = decideSessionWatchTick(overlay, 'ephemeral-blank', '');
            console.log(JSON.stringify({
              action: decision.action,
              callNewChat: decision.callNewChat,
              isTransition: isUserNewChatTransition('stored-abc', '')
            }));
            """
        )
        self.assertTrue(data["isTransition"])
        self.assertEqual(data["action"], "reset-stock")
        self.assertFalse(data["callNewChat"])

    def test_apply_gate_swallows_newchat_stored_transition(self):
        data = self._run_js(
            """
            const overlay = { active: true, sessionId: 'old', storedId: 'stored-abc', applyInProgress: true };
            const decision = decideSessionWatchTick(overlay, 'ephemeral-blank', null);
            console.log(JSON.stringify(decision));
            """
        )
        self.assertEqual(data["action"], "gate-refresh")
        self.assertFalse(data["callNewChat"])
        self.assertIsNone(data["overlayPatch"]["storedId"])
        self.assertEqual(data["overlayPatch"]["sessionId"], "ephemeral-blank")

    def test_apply_and_standard_clear_do_not_call_newchat(self):
        start = self.src.index("const onSelectPersona = async (id) => {")
        end = self.src.index("const listablePersonas")
        select = self.src[start:end]
        apply_fn = self.src[
            self.src.index("// STUDIO_APPLY_BEGIN") : self.src.index("// STUDIO_APPLY_END")
        ]
        self.assertNotIn("startNewChat", select)
        self.assertNotIn("shouldReloadSessionAfterApply", self.src)
        self.assertNotIn("host.newChat", select)
        self.assertNotIn("host.newChat", apply_fn)
        self.assertNotIn("startNewChat", self.src)
        self.assertIn("focusedSessionProfile", self.src)
        self.assertIn("persona-select-${profileId}", self.src)
        self.assertIn("syncTitlebarToFocusedProfile", self.src)
        self.assertIn("applySpeakingBundleToProfile", select)
        self.assertIn("character_strength", apply_fn)
        self.assertIn("refreshLiveSessionPersonality", apply_fn)
        self.assertIn("Live session refreshed", apply_fn)
        self.assertIn("config only", apply_fn)
        self.assertIn("config.set", self.src)
        self.assertIn("requestProfile", self.src)
        self.assertIn("profileRoutes", self.src)
        self.assertIn("host.request", self.src)
        self.assertIn("bare profile string rejected", self.src)
        self.assertNotIn("🎙️ CLONES", self.src)
        self.assertIn("complete packs", self.src)
        self.assertIn("Character strength (LLM) — 0% = profile soul only", self.src)
        self.assertIn("Temperature / Expressiveness (TTS only)", self.src)
        self.assertIn("Target profile", self.src)
        self.assertIn("Choose persona", self.src)
        self.assertIn("Character strength", self.src)
        self.assertIn("Apply to this chat", self.src)
        self.assertIn("Current applied state", self.src)
        self.assertIn("Fish Audio (cloud)", self.src)
        self.assertIn("Voicebox (local GPU)", self.src)
        self.assertIn("handleApplyToChat", self.src)
        self.assertIn("applyPackToForm", self.src)
        self.assertIn("hydrateFormFromPack", self.src)
        start = self.src.index("const persistStudioPack = async () => {")
        end = self.src.index("const handleSavePersona = async () => {")
        save = self.src[start:end]
        self.assertIn("personaSaveRequest", save)
        self.assertIn("plan.method", save)
        self.assertIn("engine: selectedModel", save)
        self.assertIn("selectedModel: selectedModel", save)
        self.assertIn("setSelectedModel((prev) => {", self.src)
        self.assertIn("mList.some((m) => m.id === prev)", self.src)
        self.assertIn("pack.engine || pack.default_engine", self.src)
        self.assertIn("match.default_engine", self.src)
        self.assertIn("Synthesis engine (saved with pack)", self.src)
        self.assertNotIn("onOpenChange(false)", save)
        self.assertNotIn("Please enter a name for the Persona.", save.split("plan.error")[0])
        self.assertNotIn("host.toast", self.src)
        handle_save = self.src[
            self.src.index("const handleSavePersona = async () => {") : self.src.index("const handleApplyToChat")
        ]
        self.assertIn("notifyHost", handle_save)
        self.assertIn("host.notify", self.src)

    def test_profile_switch_to_other_bot_is_not_user_new_chat(self):
        data = self._run_js(
            """
            const overlay = { active: true, sessionId: 'm1', storedId: 'stored-m', profileId: 'mechanic', applyInProgress: false };
            const decision = decideSessionWatchTick(overlay, 'g1', 'stored-g', 'magellan');
            console.log(JSON.stringify(decision));
            """
        )
        self.assertEqual(data["action"], "profile-switch")
        self.assertFalse(data["callNewChat"])

    def test_profile_switch_without_own_overlay_is_stock_ui(self):
        data = self._run_js(
            """
            const overlay = { active: true, profileId: 'mechanic', applyInProgress: false };
            const stock = decideProfileSwitchTick(overlay, 'magellan', { active: false, applied_persona: '' });
            const own = decideProfileSwitchTick(overlay, 'magellan', { active: true, applied_persona: 'jarvis' });
            const sel = selectionForAppliedPersona('eric_cartman', [{ id: 'eric_cartman', name: 'Eric Cartman' }]);
            console.log(JSON.stringify({ stock, own, sel }));
            """
        )
        self.assertEqual(data["stock"]["action"], "stock")
        self.assertTrue(data["stock"]["resetNewProfile"])
        self.assertEqual(data["stock"]["selection"], "default")
        self.assertEqual(data["own"]["action"], "restore-own")
        self.assertFalse(data["own"]["resetNewProfile"])
        self.assertEqual(data["own"]["selection"], "jarvis")
        self.assertEqual(data["sel"], "persona:eric_cartman")

    def test_titlebar_lists_only_complete_packs(self):
        helpers = self.src[self.src.index("function isGenericVoiceDescription") :]
        helpers = helpers[: helpers.index("// TITLEBAR_PACK_END") + len("// TITLEBAR_PACK_END")]
        data = self._run_js_helpers(
            helpers,
            """
            const complete = {
              id: 'cartman',
              name: 'Eric Cartman',
              system_prompt: 'Aggressive impatient South Park snark while doing the job.',
              voice_id: 'c9da87b0-19be-49c4-ab44-01cb7943f5c4'
            };
            const stub = {
              id: 'storyteller',
              name: 'The Storyteller',
              system_prompt: 'distinctive tone, vocabulary, and cadence associated with The Storyteller; stay helpful',
              voice_id: 'default'
            };
            const orphanVoice = { id: 'porky-id', name: 'Porky Pig', provider: 'fish_audio', voice_type: 'cloned' };
            console.log(JSON.stringify({
              complete: isListablePersonaPack(complete, [orphanVoice]),
              stub: isListablePersonaPack(stub, [orphanVoice]),
              strength: characterStrengthPercent(80)
            }));
            """,
        )
        self.assertTrue(data["complete"])
        self.assertFalse(data["stub"])
        self.assertEqual(data["strength"], 80)

    def test_studio_hydrate_and_save_update_plan(self):
        helpers = self.src[self.src.index("function isGenericVoiceDescription") :]
        helpers = helpers[: helpers.index("// STUDIO_FORM_END") + len("// STUDIO_FORM_END")]
        data = self._run_js_helpers(
            helpers,
            """
            const pack = {
              id: 'cartman',
              name: 'Eric Cartman',
              avatar: '🧢',
              system_prompt: 'Aggressive impatient South Park snark.',
              provider: 'voicebox',
              voice_id: 'c9da87b0-19be-49c4-ab44-01cb7943f5c4',
              speed: 1.05,
              temperature: 0.8,
              character_strength: 25,
              engine: 'chatterbox_turbo'
            };
            const hydrated = hydrateFormFromPack(pack);
            const unnamed = personaSaveRequest({
              editingId: 'cartman',
              name: '',
              selectedPack: pack,
              avatar: '🧢',
              systemPrompt: pack.system_prompt,
              provider: 'voicebox',
              selectedVoice: pack.voice_id,
              voiceName: 'Cartman',
              speed: 1.05,
              temperature: 0.8,
              characterStrength: 100,
              engine: 'chatterbox',
              selectedModel: 'chatterbox'
            });
            const created = personaSaveRequest({
              editingId: '',
              name: 'New Pal',
              selectedPack: null,
              avatar: '🤖',
              systemPrompt: 'hello',
              provider: 'fish_audio',
              selectedVoice: 'abc',
              voiceName: 'abc',
              speed: 1,
              temperature: 0.7,
              characterStrength: 40,
              selectedModel: 's2.1-pro-free'
            });
            const fromVoiceDefault = hydrateFormFromPack({
              ...pack,
              engine: '',
              default_engine: 'qwen'
            });
            const missing = personaSaveRequest({
              editingId: '',
              name: '',
              selectedPack: null,
              avatar: '🤖',
              systemPrompt: '',
              provider: 'voicebox',
              selectedVoice: '',
              speed: 1,
              temperature: 0.7,
              characterStrength: 25
            });
            const calls = [];
            const notified = notifyHost('success', 'Persona Updated', 'Eric Cartman — Character strength 100%', {
              notify: (payload) => calls.push(payload)
            });
            const noApi = notifyHost('info', 'Title', 'Message', {});
            const stock = formatStudioLiveStatus({ active: false, applied_persona: '', profile_id: 'mechanic' });
            const live = formatStudioLiveStatus({
              active: true,
              applied_persona: 'eric_cartman',
              profile_id: 'mechanic',
              provider: 'fish_audio',
              voice_name: 'Hermes eric_cartman',
              character_strength: 100
            });
            console.log(JSON.stringify({ hydrated, unnamed, created, missing, fromVoiceDefault, notified, calls, noApi, stock, live }));
            """,
        )
        self.assertEqual(data["hydrated"]["name"], "Eric Cartman")
        self.assertEqual(data["hydrated"]["characterStrength"], 25)
        self.assertEqual(data["hydrated"]["selectedVoice"], "c9da87b0-19be-49c4-ab44-01cb7943f5c4")
        self.assertEqual(data["hydrated"]["engine"], "chatterbox_turbo")
        self.assertEqual(data["fromVoiceDefault"]["engine"], "qwen")
        self.assertEqual(data["unnamed"]["method"], "PUT")
        self.assertEqual(data["unnamed"]["url"], "/personas/cartman")
        self.assertEqual(data["unnamed"]["body"]["name"], "Eric Cartman")
        self.assertEqual(data["unnamed"]["body"]["character_strength"], 100)
        self.assertEqual(data["unnamed"]["body"]["engine"], "chatterbox")
        self.assertEqual(data["created"]["method"], "POST")
        self.assertEqual(data["created"]["url"], "/personas")
        self.assertEqual(data["created"]["body"]["engine"], "s2.1-pro-free")
        self.assertIn("error", data["missing"])
        self.assertTrue(data["notified"])
        self.assertEqual(data["calls"][0]["kind"], "success")
        self.assertEqual(data["calls"][0]["title"], "Persona Updated")
        self.assertIn("100%", data["calls"][0]["message"])
        self.assertFalse(data["noApi"])
        self.assertEqual(data["stock"]["headline"], 'Stock Hermes on "mechanic"')
        self.assertIn("Live: eric_cartman · Fish", data["live"]["headline"])
        self.assertIn("100%", data["live"]["detail"])

    def test_live_session_personality_refresh_plan(self):
        slug = self.src[self.src.index("function slugifyName") : self.src.index("function nameTokens")]
        helpers = self.src[self.src.index("// LIVE_SESSION_REFRESH_BEGIN") : self.src.index("// LIVE_SESSION_REFRESH_END") + len("// LIVE_SESSION_REFRESH_END")]
        data = self._run_js_helpers(
            slug + "\n" + helpers,
            """
            const routes = [
              { connectionId: 'conn-mechanic', mode: 'remote', profile: 'mechanic', targetProfile: 'mechanic' },
              { connectionId: 'conn-critic', mode: 'local', profile: 'critic', targetProfile: 'critic' },
              { connectionId: 'conn-mechanic-2', mode: 'local', profile: 'mechanic', targetProfile: 'mechanic' }
            ];
            const ownerState = {
              focusedSessionId: 'sess-runtime-1',
              focusedSessionOwner: { connectionId: 'conn-mechanic', profile: 'mechanic' },
              focusedSessionProfile: 'default'
            };
            const criticState = {
              focusedSessionId: 'sess-runtime-1',
              focusedSessionOwner: { profile: 'critic' }
            };
            const route = resolveFocusedProfileRouteFromList(routes, ownerState, 'mechanic');
            const unique = resolveFocusedProfileRouteFromList(routes, criticState, 'critic');
            const synthesized = resolveFocusedProfileRouteFromList(
              [],
              { focusedSessionOwner: { connectionId: 'conn-9', profile: 'mechanic' } },
              'mechanic'
            );
            const ambiguous = resolveFocusedProfileRouteFromList(
              routes,
              { focusedSessionOwner: { profile: 'mechanic' } },
              'mechanic'
            );
            const hostApi = { requestProfile: () => {}, request: () => {} };
            const sameGatewayState = { ...ownerState, profile: 'Mechanic' };
            const apply = refreshLiveSessionPersonalityPlan('eric_cartman', hostApi, sameGatewayState, 'default', route, routes);
            const fromName = refreshLiveSessionPersonalityPlan('Eric Cartman', hostApi, sameGatewayState, 'default', route, routes);
            const cleared = refreshLiveSessionPersonalityPlan('none', hostApi, sameGatewayState, 'default', route, routes);
            const fallbackRequest = refreshLiveSessionPersonalityPlan(
              'eric_cartman',
              { request: () => {} },
              { activeSessionId: 'sess-active-2', focusedSessionProfile: 'mechanic', profile: 'mechanic' },
              'default',
              null,
              routes
            );
            const mismatched = refreshLiveSessionPersonalityPlan(
              'eric_cartman',
              hostApi,
              { focusedSessionId: 'sess-3', focusedSessionOwner: { connectionId: 'conn-mechanic', profile: 'mechanic' }, profile: 'critic' },
              'default',
              route,
              routes
            );
            const wrongGateway = refreshLiveSessionPersonalityPlan(
              'eric_cartman',
              { request: () => {}, requestProfile: () => {} },
              { focusedSessionId: 'sess-3', focusedSessionProfile: 'mechanic', profile: 'default' },
              'default',
              null,
              routes
            );
            const activeFromProfileAtom = resolveActiveGatewayProfile({ profile: 'Mechanic' }, routes);
            const draft = refreshLiveSessionPersonalityPlan('eric_cartman', hostApi, {}, 'critic', route, routes);
            const noRpc = refreshLiveSessionPersonalityPlan('eric_cartman', {}, ownerState, 'critic', route, routes);
            const liveOk = interpretLiveSessionRefreshResult({ ok: true, info: { applied: true } });
            const bareSuccess = interpretLiveSessionRefreshResult({ ok: true });
            const historyOnly = interpretLiveSessionRefreshResult({ ok: true, history_reset: true });
            const bareRoute = isFullProfileRoute('mechanic');
            const fullOk = isFullProfileRoute(route);
            console.log(JSON.stringify({
              route, unique, synthesized, ambiguous,
              apply, fromName, cleared, fallbackRequest, mismatched, wrongGateway, draft, noRpc,
              liveOk, bareSuccess, historyOnly, bareRoute, fullOk, activeFromProfileAtom
            }));
            """,
        )
        self.assertEqual(data["route"]["connectionId"], "conn-mechanic")
        self.assertEqual(data["route"]["profile"], "mechanic")
        self.assertEqual(data["unique"]["connectionId"], "conn-critic")
        self.assertEqual(data["synthesized"]["connectionId"], "conn-9")
        self.assertEqual(data["synthesized"]["mode"], "local")
        self.assertIsNone(data["ambiguous"])
        self.assertTrue(data["apply"]["attempted"])
        self.assertEqual(data["apply"]["via"], "request")
        self.assertEqual(data["apply"]["route"]["connectionId"], "conn-mechanic")
        self.assertEqual(data["apply"]["payload"]["method"], "config.set")
        self.assertEqual(data["apply"]["payload"]["params"]["key"], "personality")
        self.assertEqual(data["apply"]["payload"]["params"]["value"], "eric_cartman")
        self.assertEqual(data["apply"]["payload"]["params"]["session_id"], "sess-runtime-1")
        self.assertEqual(data["fromName"]["payload"]["params"]["value"], "eric_cartman")
        self.assertEqual(data["cleared"]["payload"]["params"]["value"], "none")
        self.assertEqual(data["fallbackRequest"]["via"], "request")
        self.assertEqual(data["fallbackRequest"]["payload"]["params"]["session_id"], "sess-active-2")
        self.assertEqual(data["mismatched"]["via"], "requestProfile")
        self.assertEqual(data["mismatched"]["route"]["connectionId"], "conn-mechanic")
        self.assertEqual(data["wrongGateway"]["skipped"], "no-route")
        self.assertEqual(data["activeFromProfileAtom"], "Mechanic")
        self.assertFalse(data["wrongGateway"]["ok"])
        self.assertEqual(data["draft"]["skipped"], "no-session")
        self.assertFalse(data["draft"]["ok"])
        self.assertFalse(data["draft"]["attempted"])
        self.assertEqual(data["noRpc"]["skipped"], "no-request")
        self.assertFalse(data["noRpc"]["ok"])
        self.assertTrue(data["liveOk"]["ok"])
        self.assertFalse(data["bareSuccess"]["ok"])
        self.assertFalse(data["historyOnly"]["ok"])
        self.assertIn("history_reset", data["historyOnly"]["error"])
        self.assertFalse(data["bareRoute"])
        self.assertTrue(data["fullOk"])

    def _run_js_helpers(self, helpers: str, body: str):
        import json
        import subprocess
        import tempfile

        script = helpers + "\n" + body + "\n"
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
            handle.write(script)
            path = handle.name
        try:
            result = subprocess.run(["node", path], capture_output=True, text=True, check=False)
        finally:
            Path(path).unlink(missing_ok=True)
        self.assertEqual(result.returncode, 0, msg=f"node failed: {result.stderr or result.stdout}")
        return json.loads(result.stdout.strip().splitlines()[-1])


class TestInstallHygiene(IsolatedHermesHomeTest):
    def test_deploy_plugin_copies_js_and_removes_plugin_py(self):
        src = Path(self.temp_dir) / "src"
        desktop = src / "desktop"
        backend = src / "backend"
        desktop.mkdir(parents=True)
        backend.mkdir()
        (desktop / "plugin.js").write_text("export default {}\n", encoding="utf-8")
        (src / "server.py").write_text("# server\n", encoding="utf-8")
        dest = Path(self.temp_dir) / "plugin"
        dest.mkdir()
        (dest / "plugin.py").write_text("this should not remain\n", encoding="utf-8")
        install_mod.deploy_plugin(src, dest)
        self.assertTrue((dest / "plugin.js").exists())
        self.assertFalse((dest / "plugin.py").exists())
        self.assertIn("export default", (dest / "plugin.js").read_text(encoding="utf-8"))

    def test_unit_is_ours_detects_marker(self):
        path = Path(self.temp_dir) / "hermes-personastudio.service"
        path.write_text(install_mod.SYSTEMD_MARKER + "\n[Service]\n", encoding="utf-8")
        self.assertTrue(install_mod._unit_is_ours(path))
        other = Path(self.temp_dir) / "other.service"
        other.write_text("[Service]\nExecStart=/bin/true\n", encoding="utf-8")
        self.assertFalse(install_mod._unit_is_ours(other))


class TestSeedPresets(IsolatedHermesHomeTest):
    def test_seed_writes_under_hermes_home(self):
        import seed_presets

        seed_presets.STORAGE_ROOT = self.home / "personas"
        seed_presets.seed()
        self.assertFalse((self.home / "personas" / "storyteller" / "prompt.md").exists())
        self.assertFalse((self.home / "personas" / "jarvis" / "prompt.md").exists())
        cartman_path = self.home / "personas" / "cartman" / "prompt.md"
        self.assertTrue(cartman_path.exists())
        cartman = cartman_path.read_text(encoding="utf-8")
        seed_presets.seed()
        self.assertEqual(cartman, cartman_path.read_text(encoding="utf-8"))
        self.assertNotRegex(cartman, r"(?i)^you are eric cartman")
        self.assertIn("PC repair", cartman)
        self.assertIn("role", cartman.lower())
        jarvis_dir = self.home / "personas" / "jarvis"
        jarvis_dir.mkdir(parents=True)
        (jarvis_dir / "prompt.md").write_text("Existing Jarvis mannerisms.\n", encoding="utf-8")
        seed_presets.seed()
        self.assertEqual(
            (jarvis_dir / "prompt.md").read_text(encoding="utf-8"),
            "Existing Jarvis mannerisms.\n",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

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


class TestPersonaSync(IsolatedHermesHomeTest):
    def test_fallback_prompt_uses_description(self):
        prompt = persona_sync.fallback_system_prompt(
            "Jarvis", "You are Jarvis, a butler."
        )
        self.assertIn("Jarvis", prompt)
        self.assertTrue(prompt.startswith("You are Jarvis"))

    def test_fallback_prompt_ignores_fish_metadata(self):
        prompt = persona_sync.fallback_system_prompt(
            "Voldemort", "Fish Audio Clone (trained, private)"
        )
        self.assertEqual(
            prompt,
            "You are Voldemort. Stay in character while remaining helpful and answering the user's questions.",
        )

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
        self.assertEqual(sorted(result["created"]), ["cartman", "jarvis"])
        jarvis = storage.get_persona("jarvis")
        self.assertEqual(jarvis.voice_id, "voice-jarvis-1")
        self.assertIn("butler", jarvis.system_prompt.lower())
        cartman = storage.get_persona("cartman")
        self.assertEqual(cartman.voice_id, "voice-cartman-1")
        self.assertIn("You are Cartman", cartman.system_prompt)

    def test_sync_from_voices_is_idempotent(self):
        storage = PersonaStorage(root_dir=str(self.home / "personas"))
        voices = [
            VoiceInfo(
                id="voice-jarvis-1",
                name="Jarvis",
                provider="voicebox",
                voice_type="cloned",
                description="You are Jarvis.",
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
        voice = VoiceInfo(id="abc", name="Storyteller", provider="voicebox", voice_type="cloned")
        first = persona_sync.ensure_persona_for_voice(storage, voice)
        voice2 = VoiceInfo(id="def", name="The Storyteller", provider="voicebox", voice_type="cloned")
        second = persona_sync.ensure_persona_for_voice(storage, voice2)
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.voice_id, "def")
        self.assertEqual(len(storage.list_personas()), 1)

    def test_sync_does_not_downgrade_fish_binding_to_voicebox(self):
        storage = PersonaStorage(root_dir=str(self.home / "personas"))
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
        persona_sync.ensure_persona_for_voice(
            storage,
            VoiceInfo(id="vb-kitt", name="KITT", provider="voicebox", voice_type="cloned"),
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
        self.assertEqual(persona["system_prompt"], "You are Jarvis.")
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
            "clone-uuid",
            "Cartman",
            cfg_path=cfg,
        )
        self.assertTrue(result["ok"])
        data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        self.assertEqual(data["model"], "keep-me")
        self.assertEqual(data["tts"]["provider"], "voicebox")
        self.assertEqual(data["tts"]["providers"]["voicebox"]["voice"], "clone-uuid")
        self.assertEqual(data["tts"]["providers"]["fish"]["voice"], "old_voice")
        self.assertEqual(data["agent"]["max_turns"], 12)

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
            "default", "voicebox", "clone-uuid", "Jarvis", cfg_path=cfg
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
        self.assertTrue((self.home / "personas" / "jarvis" / "prompt.md").exists())
        prompt = (self.home / "personas" / "jarvis" / "prompt.md").read_text(encoding="utf-8")
        seed_presets.seed()
        prompt_again = (self.home / "personas" / "jarvis" / "prompt.md").read_text(encoding="utf-8")
        self.assertEqual(prompt, prompt_again)


if __name__ == "__main__":
    unittest.main(verbosity=2)

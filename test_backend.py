import unittest
import tempfile
import shutil
from pathlib import Path

from backend.storage import PersonaStorage, PersonaBundle
from backend.providers.fish_audio import FishAudioProvider
from backend.providers.voicebox import VoiceboxProvider
from backend import bot_profiles


class TestPersonaStudioBackend(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_storage(self):
        storage = PersonaStorage(root_dir=self.temp_dir)
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

    def test_fish_audio_provider(self):
        provider = FishAudioProvider()
        self.assertEqual(provider.name, "fish_audio")
        if provider.is_available():
            voices = provider.list_voices()
            self.assertGreater(len(voices), 0)

    def test_voicebox_provider(self):
        provider = VoiceboxProvider()
        self.assertEqual(provider.name, "voicebox")
        if provider.is_available():
            voices = provider.list_voices()
            self.assertGreater(len(voices), 0)

    def test_bot_profiles(self):
        profiles = bot_profiles.list_bot_profiles()
        self.assertIsInstance(profiles, list)
        self.assertGreater(len(profiles), 0)
        self.assertTrue(any(p["id"] == "default" for p in profiles))


if __name__ == "__main__":
    unittest.main(verbosity=2)

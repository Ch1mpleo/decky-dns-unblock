import json
import os
import tempfile
import unittest

from dns_unblock import providers
from dns_unblock.settings import Settings


class ProviderTests(unittest.TestCase):
    def test_split_servers(self):
        self.assertEqual(
            providers.split_servers(["1.1.1.1", " 2606:4700:4700::1111 ", "1.1.1.1"]),
            (["1.1.1.1"], ["2606:4700:4700::1111"]),
        )

    def test_rejects_bad_servers(self):
        for bad in (["nope"], ["127.0.0.1"], ["0.0.0.0"], []):
            with self.assertRaises(ValueError):
                providers.split_servers(bad)

    def test_plain_servers(self):
        self.assertEqual(providers.plain_servers("quad9", []), (["9.9.9.9", "149.112.112.112"], ["2620:fe::fe", "2620:fe::9"]))
        self.assertEqual(providers.plain_servers("custom", ["192.168.1.53"]), (["192.168.1.53"], []))


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "sub", "settings.json")

    def tearDown(self):
        self.dir.cleanup()

    def write(self, data):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(data if isinstance(data, str) else json.dumps(data))

    def test_defaults_when_missing_or_corrupt(self):
        self.assertEqual(Settings(self.path).to_dict()["provider"], "cloudflare")
        self.write("{not json")
        self.assertFalse(Settings(self.path).enabled)

    def test_round_trip(self):
        s = Settings(self.path)
        s.enabled = True
        s.set_mode("plain")
        s.set_provider("custom", ["9.9.9.9", ""])
        s.save()
        self.assertEqual(Settings(self.path).to_dict(), {
            "enabled": True, "mode": "plain", "provider": "custom", "custom_servers": ["9.9.9.9"],
        })

    def test_invalid_values_fall_back(self):
        self.write({"enabled": "yes", "mode": "turbo", "provider": "custom", "custom_servers": ["bad"]})
        s = Settings(self.path)
        self.assertEqual((s.enabled, s.mode, s.provider), (False, "auto", "cloudflare"))

    def test_setters_validate(self):
        s = Settings(self.path)
        with self.assertRaises(ValueError):
            s.set_mode("turbo")
        with self.assertRaises(ValueError):
            s.set_provider("opendns")
        with self.assertRaises(ValueError):
            s.set_provider("custom", ["not-an-ip"])
        self.assertEqual(s.provider, "cloudflare")


if __name__ == "__main__":
    unittest.main()
